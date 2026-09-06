# data/data_feed.py
"""
交易账单解析层 (Bill Parsing Layer)。

【v1.2 重构要点】
1. 完整读取 CFMMC 交割单的三个关键页签：
     - 成交明细 : 逐笔成交流水（含成交价 / 成交时间 / 成交额）
     - 持仓明细 : 月末未平持仓快照（含买入价 / 卖出价 / 实际成交日期）
     - 结算月报 : 资金勾稽区（上月结存 / 客户权益 / 当月盈亏 / 当月手续费）
2. FIFO 配对升级：携带开仓价、开仓时刻、合约乘数，并按"理论盈亏加权"分配平仓盈亏。
3. 跨月真缝合：多文件合并后按全局时间排序再跑一次 FIFO，
   结果**与导入顺序完全无关**（分月导入 ≡ 一次性导入）。
4. 月末未平持仓腿持久化返回，交由调用方写入 open_legs 表，
   使下一次导入能够无缝延续上一次的仓位。

【纯粹性约束】本模块是纯函数层：**不碰数据库、不碰 UI**。
历史持仓腿由调用方以 initial_legs 传入，新持仓腿以返回值交回，
保证解析器可以被单独测试，也便于将来接入其他数据源。
"""
import hashlib
import logging
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.preferences import TIME_SOURCE_DATE_ONLY, TIME_SOURCE_STATEMENT
from models.trade import TradeRecord

logger = logging.getLogger(__name__)

# CFMMC 交割单中用于判定"开仓/平仓"与"买/卖"的合法取值
BUY, SELL = '买', '卖'
OPEN, CLOSE = 'OPEN', 'CLOSE'

# 结算单中的关键工作表名
TRADE_SHEET = '成交明细'
POSITION_SHEET = '持仓明细'
REPORT_SHEET = '客户交易结算月报'
DEFAULT_ACCOUNT = "CFMMC真实账户"

# 通用"无数据"占位符（交割单用 '--' 表示不适用，如开仓行的平仓盈亏）
NULL_TOKENS = {'', '-', '--', '---', 'nan', 'nat', 'none', 'null'}

# 成交明细的列名别名表（兼容不同期货公司的导出差异）
TRADE_ALIASES = {
    'trade_date': ('交易日期', '成交日期', '日期'),
    'symbol':     ('合约', '品种', '合约代码', '品种合约'),
    'trade_id':   ('成交序号', '成交编号', '流水号', '成交流水号'),
    'fill_time':  ('成交时间', '时间'),
    'bs':         ('买/卖', '买卖', '买卖标志'),
    'hedge':      ('投机（一般）/套保/套利', '投机套保套利', '投保标志'),
    'price':      ('成交价', '成交价格', '价格'),
    'lots':       ('手数', '成交手数', '成交量', '成交数量'),
    'amount':     ('成交额', '成交金额'),
    'oc':         ('开/平', '开平', '开平标志'),
    'commission': ('手续费', '佣金'),
    'close_pnl':  ('平仓盈亏',),
}

# 持仓明细的列名别名表
POSITION_ALIASES = {
    'symbol':     ('合约', '品种合约', '品种'),
    'trade_id':   ('成交序号', '流水号'),
    'buy_lots':   ('买持仓', '买入持仓'),
    'buy_price':  ('买入价', '买价'),
    'sell_lots':  ('卖持仓', '卖出持仓'),
    'sell_price': ('卖出价', '卖价'),
    'open_date':  ('实际成交日期', '成交日期'),
}

# 结算月报资金区的标签映射（左块与右块布局混排，靠标签名定位数值）
REPORT_LABELS = {
    '上月结存':     'prev_balance',
    '当月存取合计': 'month_deposit',
    '当月盈亏':     'month_pnl',
    '当月手续费':   'month_fee',
    '当月结存':     'equity',
    '客户权益':     'equity',
}

# 表头行定位关键词（各页签标题行）
HEADER_KEYWORDS = {
    TRADE_SHEET:    ('交易日期', '成交日期'),
    POSITION_SHEET: ('买持仓', '卖持仓'),
}


# ==========================================
# 基础清洗工具 (Pure Helpers)
# ==========================================
def clean_str(s):
    """强力清洗字符串中的所有空白字符（包括前后空格、制表符等）"""
    if pd.isna(s): return ""
    return re.sub(r'\s+', '', str(s))


def _to_float(value, default=0.0):
    """安全转浮点数，遇到 '1,234.5'、'--'、空值或脏数据一律回落到默认值"""
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    try:
        text = str(value).replace(',', '').strip()
        if text.lower() in NULL_TOKENS:
            return default
        result = pd.to_numeric(text, errors='coerce')
        return default if pd.isna(result) else float(result)
    except Exception:
        return default


def _to_int(value, default=0) -> int:
    return int(_to_float(value, default))


def _to_time_str(value) -> str:
    """
    把交割单的「成交时间」统一成 'HH:MM:SS'。

    实测该列在 Excel 中以字符串 '10:34:51' 形式存在，
    但不同期货公司可能导出为 datetime.time 或空值，这里做统一归一化。
    无法识别时返回空串（代表"没有可用的时分信息"），绝不返回假造的 00:00:00。
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.lower() in NULL_TOKENS:
        return ""
    match = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$', text)
    if not match:
        return ""
    hour, minute, second = match.group(1), match.group(2), match.group(3) or '00'
    if int(hour) > 23 or int(minute) > 59 or int(second) > 59:
        return ""
    return f"{int(hour):02d}:{minute}:{second}"


def _to_date(value, default=None):
    """解析交易日期；失败时返回默认值（默认 None，由调用方决定兜底策略）"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = clean_str(value).split(' ')[0]
    if not text or text.lower() in NULL_TOKENS:
        return default
    try:
        parsed = pd.to_datetime(text)
        return None if pd.isna(parsed) else parsed.to_pydatetime()
    except Exception:
        return default


def _infer_multiplier(price, lots, amount) -> float:
    """
    由「成交额 = 成交价 × 手数 × 合约乘数」反推合约乘数。

    实测精度：IF2506 → 300.0000，IM2506 → 200.0000，完全吻合。
    只在结果非常接近正整数时采信（防止脏数据污染），否则返回 0.0 表示未知。
    """
    if not price or not lots or not amount:
        return 0.0
    try:
        raw = float(amount) / (float(price) * float(lots))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    if pd.isna(raw) or raw <= 0:
        return 0.0
    nearest = round(raw)
    # 容忍浮点误差，但不接受任意小数（那说明数据本身有问题）
    return float(nearest) if abs(raw - nearest) < 0.01 else 0.0


# ==========================================
# 工作表读取与结构化 (Sheet Readers)
# ==========================================
def _locate_header_row(df_raw: pd.DataFrame, keywords) -> int:
    """在原始无表头数据中定位真正的表头行"""
    for idx, row in df_raw.iterrows():
        if any(k in str(row.values) for k in keywords):
            return idx
    return -1


def _build_dataframe(df_raw: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    """
    【性能要点】整个文件只读一次 Excel。
    用定位到的表头行手动重建 DataFrame，避免二次 IO 解析同一张表。
    """
    raw_header = df_raw.iloc[header_idx].tolist()

    columns, seen = [], {}
    for i, cell in enumerate(raw_header):
        name = clean_str(cell) or f"__unnamed_{i}"
        # 同名列去重，防止后续 row.get() 取到 DataFrame 而非标量
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        columns.append(name)

    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = columns
    return df.reset_index(drop=True)


def _drop_summary_rows(df: pd.DataFrame) -> pd.DataFrame:
    """剔除末尾的「合计」行与全空行"""
    if df.empty:
        return df
    first_col = df.columns[0]
    mask = df[first_col].notna() & (~df[first_col].astype(str).str.contains('合计', na=False))
    return df[mask].reset_index(drop=True)


def _resolve_columns(df: pd.DataFrame, aliases: dict) -> dict:
    """把标准字段别名映射到 DataFrame 中真实存在的列名"""
    cleaned = {clean_str(c): c for c in df.columns}
    resolved = {}
    for key, names in aliases.items():
        for name in names:
            target = cleaned.get(clean_str(name))
            if target is not None:
                resolved[key] = target
                break
    return resolved


def _read_sheet(xls: pd.ExcelFile, sheet_name: str, keywords) -> pd.DataFrame:
    """读取指定页签并定位表头；页签不存在或找不到表头时返回空 DataFrame"""
    if sheet_name not in xls.sheet_names:
        return pd.DataFrame()
    df_raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    header_idx = _locate_header_row(df_raw, keywords)
    if header_idx == -1:
        return pd.DataFrame()
    return _drop_summary_rows(_build_dataframe(df_raw, header_idx))


def _extract_account_name(xls: pd.ExcelFile, fallback: str) -> str:
    """从结算月报页签中容错提取客户名称，失败时回落到默认账户名"""
    try:
        if REPORT_SHEET not in xls.sheet_names:
            return fallback
        df_info = pd.read_excel(xls, sheet_name=REPORT_SHEET, header=None)
        for _, row in df_info.iterrows():
            if '客户名称' in str(row.values):
                for cell in row.values[1:]:
                    if pd.notna(cell) and str(cell).strip():
                        return str(cell).strip()
                break
    except Exception as e:
        logger.debug(f"未能从结算月报提取客户名称，使用默认账户: {e}")
    return fallback


# ==========================================
# 逐笔成交 (Fill) 与持仓腿 (OpenLeg)
# ==========================================
@dataclass
class Fill:
    """一条标准化后的成交（逐笔），FIFO 配对的最小单位。"""
    account: str
    symbol: str
    trade_id: str
    bs: str                  # BUY / SELL
    oc: str                  # OPEN / CLOSE
    trade_date: datetime
    fill_time: str           # 'HH:MM:SS'，空串表示无时分信息
    price: float
    lots: int
    amount: float
    commission: float
    close_pnl: float
    multiplier: float
    source_file: str = ""


@dataclass
class OpenLeg:
    """一条未平仓的开仓腿，参与 FIFO 队列。lots 会在配对过程中递减。"""
    leg_id: str
    symbol: str
    direction: str           # LONG / SHORT
    open_date: str
    open_time: str
    price: float
    lots: int
    commission: float
    multiplier: float
    source_month: str = ""


@dataclass
class MonthlySummary:
    """结算月报的资金勾稽快照，用于月度对账与漏月检测。"""
    account: str
    month: str               # 'YYYY-MM'，空串表示尚无法确定
    prev_balance: float
    equity: float
    month_pnl: float
    month_fee: float
    month_deposit: float
    source_file: str


def _make_leg_id(account: str, symbol: str, trade_id: str) -> str:
    """持仓腿的确定性主键，支持重复导入时安全覆盖"""
    return hashlib.md5(f"{account}_{symbol}_{trade_id}".encode('utf-8')).hexdigest()


def _compose_entry_time(open_date: str, open_time: str):
    """
    合成开仓腿的真实成交时刻 (完整 datetime)。

    成交明细每一行都真实携带"交易日期 + 成交时间"，
    因此合成出的开仓时刻是原始数据，绝非虚构。
    信息不全时返回 None（孤儿单），由上层如实显示为待补录。
    """
    if not open_date:
        return None
    try:
        text = f"{open_date} {open_time}".strip() if open_time else open_date
        parsed = pd.to_datetime(text)
        return None if pd.isna(parsed) else parsed.to_pydatetime()
    except Exception:
        return None


def _parse_fills(xls: pd.ExcelFile, account: str, source_file: str) -> tuple[list[Fill], dict]:
    """解析成交明细页签，返回 (逐笔列表, 统计信息)"""
    df = _read_sheet(xls, TRADE_SHEET, HEADER_KEYWORDS[TRADE_SHEET])
    if df.empty:
        return [], {'rows': 0, 'skipped': 0}

    cols = _resolve_columns(df, TRADE_ALIASES)
    if 'symbol' not in cols or 'bs' not in cols:
        logger.warning(f"{source_file}: 成交明细缺少「合约」或「买/卖」列，已跳过该文件")
        return [], {'rows': len(df), 'skipped': len(df)}

    fills, skipped = [], 0
    for _, row in df.iterrows():
        symbol = clean_str(row.get(cols['symbol'], ''))
        bs = clean_str(row.get(cols.get('bs', ''), ''))
        oc_raw = clean_str(row.get(cols.get('oc', ''), ''))

        if bs not in (BUY, SELL) or not symbol:
            skipped += 1
            continue

        # 开/平 归一化：平今 / 平昨 都归入 CLOSE
        if '开' in oc_raw:
            oc = OPEN
        elif '平' in oc_raw:
            oc = CLOSE
        else:
            skipped += 1
            continue

        trade_date = _to_date(row.get(cols.get('trade_date', ''), None))
        if trade_date is None:
            skipped += 1
            continue

        lots = _to_int(row.get(cols.get('lots', ''), 0))
        if lots <= 0:
            skipped += 1
            continue

        price = _to_float(row.get(cols.get('price', ''), 0.0))
        amount = _to_float(row.get(cols.get('amount', ''), 0.0))
        raw_id = clean_str(row.get(cols.get('trade_id', ''), ''))
        trade_id = raw_id or f"C_{uuid.uuid4().hex[:8]}"

        fills.append(Fill(
            account=account,
            symbol=symbol,
            trade_id=trade_id,
            bs=bs,
            oc=oc,
            trade_date=trade_date,
            fill_time=_to_time_str(row.get(cols.get('fill_time', ''), '')),
            price=price,
            lots=lots,
            amount=amount,
            commission=_to_float(row.get(cols.get('commission', ''), 0.0)),
            close_pnl=_to_float(row.get(cols.get('close_pnl', ''), 0.0)),
            multiplier=_infer_multiplier(price, lots, amount),
            source_file=source_file,
        ))

    return fills, {'rows': len(df), 'skipped': skipped}


def _parse_positions(xls: pd.ExcelFile, account: str, source_month: str) -> list[OpenLeg]:
    """
    解析持仓明细页签 —— 这是消灭跨月孤儿单的关键数据源。

    CFMMC 每月交割单都附带一份**月末未平持仓快照**，直接提供了
    「买入价 / 卖出价 / 实际成交日期」，正是下个月延续仓位所需的全部信息。
    """
    df = _read_sheet(xls, POSITION_SHEET, HEADER_KEYWORDS[POSITION_SHEET])
    if df.empty:
        return []

    cols = _resolve_columns(df, POSITION_ALIASES)
    if 'symbol' not in cols:
        return []

    legs = []
    for _, row in df.iterrows():
        symbol = clean_str(row.get(cols['symbol'], ''))
        if not symbol:
            continue

        buy_lots = _to_int(row.get(cols.get('buy_lots', ''), 0))
        sell_lots = _to_int(row.get(cols.get('sell_lots', ''), 0))
        buy_price = _to_float(row.get(cols.get('buy_price', ''), 0.0))
        sell_price = _to_float(row.get(cols.get('sell_price', ''), 0.0))
        open_date = clean_str(row.get(cols.get('open_date', ''), ''))
        raw_id = clean_str(row.get(cols.get('trade_id', ''), '')) or f"P_{uuid.uuid4().hex[:8]}"

        # 同一行可能同时存在买卖双向持仓（锁仓），需拆成两条腿
        if buy_lots > 0:
            legs.append(OpenLeg(
                leg_id=_make_leg_id(account, symbol, f"{raw_id}_B"),
                symbol=symbol, direction='LONG',
                open_date=open_date, open_time='',
                price=buy_price, lots=buy_lots,
                commission=0.0, multiplier=0.0, source_month=source_month,
            ))
        if sell_lots > 0:
            legs.append(OpenLeg(
                leg_id=_make_leg_id(account, symbol, f"{raw_id}_S"),
                symbol=symbol, direction='SHORT',
                open_date=open_date, open_time='',
                price=sell_price, lots=sell_lots,
                commission=0.0, multiplier=0.0, source_month=source_month,
            ))

    return legs


def _scan_labeled_values(df: pd.DataFrame, label_map: dict) -> dict:
    """
    扫描二维表，找出「标签 → 数值」映射。

    结算月报的资金区采用左右双块布局（左块 标签在第0列、右块 标签在第5列），
    与其硬编码列号，不如直接扫描：命中标签后取该行右侧第一个可解析的数值。
    """
    found = {}
    for _, row in df.iterrows():
        values = row.tolist()
        for i, cell in enumerate(values):
            key = label_map.get(clean_str(cell))
            if not key or key in found:
                continue
            for candidate in values[i + 1:]:
                # 用 None 作为默认值以区分"解析失败"与"数值就是 0"
                num = _to_float(candidate, default=None)
                if num is not None:
                    found[key] = num
                    break
    return found


def _parse_monthly_report(xls: pd.ExcelFile, account: str,
                          source_file: str) -> MonthlySummary:
    """解析结算月报的资金勾稽区；任何字段缺失都回落到 0.0，绝不抛异常"""
    blank = MonthlySummary(account, "", 0.0, 0.0, 0.0, 0.0, 0.0, source_file)
    try:
        if REPORT_SHEET not in xls.sheet_names:
            return blank
        df = pd.read_excel(xls, sheet_name=REPORT_SHEET, header=None)
        values = _scan_labeled_values(df, REPORT_LABELS)
        return MonthlySummary(
            account=account,
            month="",  # 月份由 _infer_months 依据成交日期 / 资金链推断
            prev_balance=values.get('prev_balance', 0.0),
            equity=values.get('equity', 0.0),
            month_pnl=values.get('month_pnl', 0.0),
            month_fee=values.get('month_fee', 0.0),
            month_deposit=values.get('month_deposit', 0.0),
            source_file=source_file,
        )
    except Exception as e:
        logger.warning(f"{source_file}: 结算月报解析失败 ({e})，月度对账将跳过该文件")
        return blank


# ==========================================
# FIFO 配对引擎 (Matching Engine)
# ==========================================
def _allocate_pnl(fill: Fill, slices: list, direction: str) -> list[float]:
    """
    把一笔平仓的实际平仓盈亏分配到每个切片，保证 Σ切片 = 整笔平仓盈亏（总额守恒）。

    【v1.2.1 修正】旧算法在"孤儿与匹配切片混合"时会整体退化为按手数均分，导致
    「有开仓价的切片」分到的盈亏与其"点数×乘数×手数"完全对不上——
    例：平 3 手 @6000，其中 1 手匹配开仓 @5900（价差 100 点 × 200 = 2 万），
    另 2 手为孤儿，整笔平仓盈亏 3 万。按手数均分会给匹配片 1 万、孤儿片 2 万，
    用户核对点数时会看到"点数明明很大、盈亏却对不上"。

    【分配策略】(逐笔对冲语义)
      - 开仓价已知的切片：按理论盈亏 (点数 × 乘数 × 手数) 各取各的 —— 天然自洽
      - 孤儿切片（开仓价缺失）：承接「整笔盈亏 − 已知片理论盈亏合计」的余额，
        这正是孤儿仓在交易所逐笔对冲下的真实盈亏
    当一笔平仓全部为已知片时，按各片理论盈亏的比例分摊整笔盈亏（同样自洽）。
    """
    amounts = []
    orphan_lots: list[int] = []      # 孤儿切片的手数（用于按手数分摊余额）
    for leg, lots in slices:
        if leg is not None and leg.price and fill.price:
            diff = fill.price - leg.price
            if direction == 'SHORT':
                diff = -diff
            amounts.append(diff * lots * (fill.multiplier or 1.0))
        else:
            amounts.append(None)
            orphan_lots.append(lots)

    total_pnl = fill.close_pnl
    known = [a for a in amounts if a is not None]

    if not orphan_lots:
        # 全部已知：按 |理论盈亏| 的比例分摊（Σ = total_pnl 恒成立）
        denom = sum(abs(a) for a in known)
        if denom <= 0:
            equal = total_pnl / len(slices)
            return [equal] * len(slices)
        return [total_pnl * (abs(a) / denom) for a in amounts]

    # 存在孤儿片：已知片拿理论值，孤儿片按各自手数比例承接余额。
    # 按手数而非等分，能保证多个孤儿切片之间也与"点数×乘数×手数"的自洽方向一致。
    known_sum = sum(known)
    balance = total_pnl - known_sum
    orphan_total = sum(orphan_lots) or 1
    j = 0
    for i, amount in enumerate(amounts):
        if amount is None:
            amounts[i] = balance * orphan_lots[j] / orphan_total
            j += 1
    return amounts


def _run_fifo(fills: list[Fill], initial_legs: list[OpenLeg],
              source_month: str = "") -> tuple[list[TradeRecord], list[OpenLeg], dict]:
    """
    执行 FIFO 配对，返回 (闭环交易列表, 剩余未平持仓腿, 统计信息)。

    【全局有序】调用方必须保证 fills 已按 (日期, 时刻, 成交序号) 排序，
    这样"先导入 8 月再导入 7 月"与"按序导入"会得到完全一致的结果。
    """
    # 历史持仓腿按开仓时间排序后置于队列最前，保证 FIFO 语义正确
    positions: dict[tuple[str, str], list[OpenLeg]] = {}
    for leg in sorted(initial_legs, key=lambda x: (x.open_date or '', x.open_time or '')):
        if leg.lots > 0:
            positions.setdefault((leg.symbol, leg.direction), []).append(leg)

    trades: list[TradeRecord] = []
    stats = {'orphan_closes': 0, 'missing_price': 0, 'missing_multiplier': 0}

    for fill in fills:
        if fill.oc == OPEN:
            direction = 'LONG' if fill.bs == BUY else 'SHORT'
            positions.setdefault((fill.symbol, direction), []).append(OpenLeg(
                leg_id=_make_leg_id(fill.account, fill.symbol, fill.trade_id),
                symbol=fill.symbol, direction=direction,
                open_date=fill.trade_date.strftime('%Y-%m-%d'),
                open_time=fill.fill_time,
                price=fill.price, lots=fill.lots,
                commission=fill.commission,
                multiplier=fill.multiplier,
                source_month=source_month,
            ))
            if not fill.price:
                stats['missing_price'] += 1
            if not fill.multiplier:
                stats['missing_multiplier'] += 1
            continue

        # 平仓：买平 = 平掉空单，卖平 = 平掉多单
        direction = 'LONG' if fill.bs == SELL else 'SHORT'
        queue = positions.get((fill.symbol, direction), [])

        # ---- 切片：按 FIFO 顺序啃掉队列 ----
        slices: list[tuple[OpenLeg | None, int]] = []
        remaining = fill.lots
        while remaining > 0 and queue:
            leg = queue[0]
            matched = min(remaining, leg.lots)
            slices.append((leg, matched))
            remaining -= matched
            leg.lots -= matched
            if leg.lots <= 0:
                queue.pop(0)

        # 【过月持仓】本批数据内找不到对应开仓 → 标记为孤儿单，
        # 盈亏数字依然来自交割单本身（完全准确），只是开仓侧信息缺失。
        if remaining > 0:
            slices.append((None, remaining))
            stats['orphan_closes'] += 1

        pnl_amounts = _allocate_pnl(fill, slices, direction)
        total_lots = fill.lots or 1
        slice_count = len(slices)

        for idx, ((leg, matched), net_pnl) in enumerate(zip(slices, pnl_amounts)):
            # 开仓手续费按手数摊薄；平仓手续费按手数比例分摊（总额守恒）
            open_comm = 0.0
            if leg is not None and leg.lots + matched > 0:
                original_lots = leg.lots + matched  # 还原该腿被啃之前的原始手数
                open_comm = leg.commission * (matched / original_lots)
            close_comm = fill.commission * (matched / total_lots)

            # 【时间双轨制】成交时刻完整保留（真实数据），
            # 是否展示由用户的"时间精度"偏好决定，切换零成本。
            time_source = TIME_SOURCE_STATEMENT if (fill.fill_time or (leg and leg.open_time)) \
                else TIME_SOURCE_DATE_ONLY

            trades.append(TradeRecord(
                trade_id=fill.trade_id,
                account=fill.account,
                symbol=fill.symbol,
                direction=direction,
                trade_time=fill.trade_date,          # 主锚点：永远是纯日期
                lots=matched,
                net_profit=net_pnl,
                commission=open_comm + close_comm,
                entry_price=(leg.price if (leg and leg.price) else None),
                exit_price=(fill.price or None),
                # 开仓腿真实成交时刻：由开仓日期 + 开仓时分合成（孤儿单为 None）
                entry_time=(_compose_entry_time(leg.open_date, leg.open_time) if leg else None),
                entry_fill_time=(leg.open_time if leg else ""),
                exit_fill_time=fill.fill_time,
                time_source=time_source,
                multiplier=(fill.multiplier or (leg.multiplier if leg else 0.0)),
                is_orphan=0 if leg is not None else 1,
                slice_index=idx,
                slice_total=slice_count,
            ))

    remaining_legs = [
        leg for queue in positions.values() for leg in queue if leg.lots > 0
    ]
    return trades, remaining_legs, stats


# ==========================================
# 月份推断 (Month Inference)
# ==========================================
def _infer_months(per_file: list[dict]) -> list[dict]:
    """
    推断每个文件实际所属的月份。

    【为什么不能信表头的「交易月份」】实测 2025-07 的样例文件里该字段写成了
    `2025-09`，与文件名和真实数据都不符。因此一律以**成交明细里的交易日期众数**
    为准；没有成交的月份（如空仓的 6 月）交给 _link_months_by_balance 用资金链反推。
    """
    for item in per_file:
        dates = [f.trade_date for f in item['fills'] if f.trade_date]
        if dates:
            counter = {}
            for d in dates:
                key = d.strftime('%Y-%m')
                counter[key] = counter.get(key, 0) + 1
            item['month'] = max(counter, key=counter.get)
        else:
            item['month'] = ""
        item['summary'].month = item['month']
    return per_file


def _link_months_by_balance(per_file: list[dict]) -> list[dict]:
    """
    用资金链为"无成交的月份"补出月份归属。

    恒等式（实测四个月全部精确成立）：
        客户权益 = 上月结存 + 当月存取合计 + 当月盈亏 - 当月手续费
    链条关系：第 N 月的「上月结存」 == 第 N-1 月的「客户权益」。
    因此即便某月零成交，也能靠它在链条中的位置锁定月份。
    """
    known = {f['month']: f for f in per_file if f['month']}
    for item in per_file:
        if item['month']:
            continue
        summary = item['summary']
        if not summary.prev_balance:
            continue
        # 找到"客户权益 == 本文件上月结存"的那个月，本文件即排在它之后
        for month, anchor in known.items():
            if anchor['summary'].equity and abs(anchor['summary'].equity - summary.prev_balance) < 0.01:
                year, mon = (int(x) for x in month.split('-'))
                mon += 1
                if mon > 12:
                    year, mon = year + 1, 1
                item['month'] = f"{year:04d}-{mon:02d}"
                item['summary'].month = item['month']
                break
    return per_file


# ==========================================
# 多文件合并解析 (Main Entry)
# ==========================================
def parse_cfmmc_files(file_paths, initial_legs: list[OpenLeg] = None) -> dict:
    """
    合并解析多个 CFMMC 交割单（跨月真缝合）。

    :param file_paths: 交割单路径列表（顺序无关）
    :param initial_legs: 上次导入遗留的未平持仓腿，由调用方从 open_legs 表载入
    :return: {
        'trades':    list[TradeRecord],
        'open_legs': list[dict]   本次导入结束后的最新未平持仓（交给调用方持久化），
        'coverage':  list[dict]   月度资金勾稽记录（用于漏月检测），
        'report':    dict         导入质量报告（用于 UI 反馈）
    }
    """
    initial_legs = list(initial_legs or [])

    all_fills: list[Fill] = []
    per_file: list[dict] = []
    accounts: set[str] = set()
    total_rows = skipped_rows = 0

    for path in file_paths:
        name = str(path).rsplit('\\', 1)[-1].rsplit('/', 1)[-1]
        xls = pd.ExcelFile(path)
        try:
            account = _extract_account_name(xls, fallback=DEFAULT_ACCOUNT)
            accounts.add(account)
            fills, fstats = _parse_fills(xls, account, name)
            summary = _parse_monthly_report(xls, account, name)
            positions = _parse_positions(xls, account, "")
            total_rows += fstats['rows']
            skipped_rows += fstats['skipped']
            all_fills.extend(fills)
            per_file.append({
                'account': account, 'fills': fills, 'summary': summary,
                'positions': positions, 'source_file': name, 'month': "",
            })
        except Exception as e:
            logger.error(f"解析交割单 {name} 失败: {e}")
            raise ValueError(f"无法解析文件「{name}」：{e}")
        finally:
            # 【资源安全】ExcelFile 持有文件句柄，不关闭会在 Windows 下锁死源文件
            xls.close()

    if not per_file:
        return {'trades': [], 'open_legs': [], 'coverage': [], 'report': {}}

    _infer_months(per_file)
    _link_months_by_balance(per_file)

    # 把持仓明细页签解析出的月末持仓并入"待延续腿"（它能提供最准确的开仓价）
    carried: list[OpenLeg] = list(initial_legs)
    for item in per_file:
        for leg in item['positions']:
            leg.source_month = item['month']
            carried.append(leg)

    # 【顺序无关的关键】按 (日期, 时刻, 成交序号) 全局排序后只跑一次 FIFO
    all_fills.sort(key=lambda f: (
        f.trade_date or datetime.min,
        f.fill_time or '99:99:99',
        f.trade_id,
    ))

    source_month = min((i['month'] for i in per_file if i['month']), default="")
    trades, remaining, fifo_stats = _run_fifo(all_fills, carried, source_month)

    open_legs_payload = []
    for leg in remaining:
        account = next((f.account for f in all_fills if f.symbol == leg.symbol), DEFAULT_ACCOUNT)
        open_legs_payload.append({
            'leg_id': leg.leg_id, 'account': account, 'symbol': leg.symbol,
            'direction': leg.direction, 'open_date': leg.open_date,
            'open_time': leg.open_time, 'price': leg.price, 'lots': leg.lots,
            'commission': leg.commission, 'multiplier': leg.multiplier,
            'source_month': leg.source_month or source_month,
        })

    coverage = [
        {
            'account': item['summary'].account,
            'month': item['month'],
            'prev_balance': item['summary'].prev_balance,
            'equity': item['summary'].equity,
            'month_pnl': item['summary'].month_pnl,
            'month_fee': item['summary'].month_fee,
            'month_deposit': item['summary'].month_deposit,
            'has_trades': bool(item['fills']),
            'source_file': item['source_file'],
        }
        for item in per_file if item['month']
    ]

    return {
        'trades': trades,
        'open_legs': open_legs_payload,
        'coverage': coverage,
        'report': {
            'files': len(per_file),
            'total_rows': total_rows,
            'skipped_rows': skipped_rows,
            'parsed_fills': len(all_fills),
            'closed_trades': len(trades),
            'orphan_closes': fifo_stats['orphan_closes'],
            'open_legs': len(open_legs_payload),
            'missing_price': fifo_stats['missing_price'],
            'missing_multiplier': fifo_stats['missing_multiplier'],
            'accounts': sorted(accounts),
            'months': sorted(i['month'] for i in per_file if i['month']),
        },
    }


def legs_from_payload(payload: list[dict]) -> list[OpenLeg]:
    """
    把持久化在 open_legs 表中的持仓腿还原为 OpenLeg 对象，供下一次导入延续。

    解析器本身不碰数据库（保持纯函数），这个转换函数让调用方
    无需了解 OpenLeg 的内部结构即可完成"读取 → 延续"的闭环。
    """
    return [
        OpenLeg(
            leg_id=row['leg_id'],
            symbol=row['symbol'],
            direction=row['direction'],
            open_date=row.get('open_date', ''),
            open_time=row.get('open_time', ''),
            price=row.get('price'),
            lots=row.get('lots', 0),
            commission=row.get('commission', 0.0),
            multiplier=row.get('multiplier', 0.0),
            source_month=row.get('source_month', ''),
        )
        for row in payload
    ]


# ==========================================
# 漏月检测 (Coverage Gap Detection)
# ==========================================
def _prev_month(month: str) -> str:
    """返回上一个月的 'YYYY-MM' 表示"""
    year, mon = (int(x) for x in month.split('-'))
    mon -= 1
    if mon == 0:
        year, mon = year - 1, 12
    return f"{year:04d}-{mon:02d}"


def detect_coverage_gaps(coverage: list[dict], known_gaps: set = None) -> list[dict]:
    """
    纯函数：依据「上月结存 ↔ 客户权益」资金链，检测导入月份是否存在断层。

    【为什么不用表头的交易月份字段】实测该字段不可信（2025-07 的文件里写 2025-09），
    但资金链是硬的：第 N 月的「上月结存」必然等于第 N-1 月的「客户权益」。
    链条一旦接不上，就说明中间漏了至少一个月。

    【防误报】已导入月份中**最早**的那一个，其"上月"本就不在导入范围内，
    属于正常情况，不判为断层（否则每个月都会误报一次）。

    :param coverage: 本次解析产出的月度记录
    :param known_gaps: 用户已确认"有意跳过"的 (account, month) 集合
    :return: 断层描述列表 [{'account', 'month', 'missing_month', 'prev_balance', ...}]
    """
    known_gaps = known_gaps or set()
    gaps = []
    by_account: dict[str, list[dict]] = {}
    for item in coverage:
        by_account.setdefault(item['account'], []).append(item)

    for account, items in by_account.items():
        items = sorted(items, key=lambda x: x['month'])
        if not items:
            continue
        earliest_month = items[0]['month']
        imported = {i['month'] for i in items}
        # 已导入月份的"期末权益"集合，作为链条的合法衔接点
        equities = [i['equity'] for i in items if i.get('equity')]

        for item in items:
            prev = item.get('prev_balance')
            month = item['month']
            if not prev or (account, month) in known_gaps:
                continue
            if month == earliest_month:
                continue  # 最早月份的上月本就不在范围内，属正常情况

            linked = any(abs(prev - eq) < 0.01 for eq in equities)
            if not linked and equities:
                missing = _prev_month(month)
                gaps.append({
                    'account': account,
                    'month': month,
                    'missing_month': missing if missing not in imported else '',
                    'prev_balance': prev,
                    'available_equities': equities,
                })
    return gaps


# ==========================================
# 解析器抽象层 (Extension Boundary)
# ==========================================
class BaseTradeParser(ABC):
    """
    交易账单解析器抽象基类。

    【扩展点】未来接入新的券商 / 期货公司账单，只需：
      1. 继承本类并实现 parse()
      2. 声明 name 与 supported_extensions
      3. 登记进 PARSER_REGISTRY
    UI 层通过 get_parser(name) 取用，完全无需改动。
    """
    name = "未命名解析器"
    supported_extensions: tuple = ()

    @abstractmethod
    def parse(self, file_path) -> list[TradeRecord]:
        """解析账单文件，返回已配对闭环的交易记录列表"""

    @classmethod
    def supports(cls, file_path) -> bool:
        """按扩展名粗筛，用于导入向导自动推荐解析器"""
        return str(file_path).lower().endswith(cls.supported_extensions)


class CFMMCTradeParser(BaseTradeParser):
    """中国期货市场监控中心 (CFMMC) 结算单解析器"""
    name = "CFMMC 期货结算单"
    supported_extensions = ('.xls', '.xlsx')

    def parse(self, file_path) -> list[TradeRecord]:
        """单文件解析（内部委托给多文件入口，保证逻辑只有一份）"""
        return parse_cfmmc_files([file_path])['trades']

    def parse_many(self, file_paths, initial_legs=None) -> dict:
        """多文件合并解析，返回完整的解析结果包（含持仓腿与月度覆盖）"""
        return parse_cfmmc_files(file_paths, initial_legs)


# 解析器注册表：名称 -> 解析器类 (新增账单格式时在此登记)
PARSER_REGISTRY: dict[str, type[BaseTradeParser]] = {
    parser.name: parser for parser in (CFMMCTradeParser,)
}


def get_parser(name: str) -> BaseTradeParser:
    """按名称实例化解析器，未注册时给出明确的可选清单"""
    if name not in PARSER_REGISTRY:
        raise ValueError(f"未注册的解析器 '{name}'，当前可用: {list(PARSER_REGISTRY)}")
    return PARSER_REGISTRY[name]()


def parse_cfmmc_excel(file_path) -> list[TradeRecord]:
    """解析 CFMMC 格式 Excel (向后兼容门面，UI 层已有调用)"""
    return CFMMCTradeParser().parse(file_path)
