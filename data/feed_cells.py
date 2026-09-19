# data/feed_cells.py
"""交割单解析的**单元格 / 工作表工具层**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。

【职责】只有"把脏 Excel 单元格变成干净标量"这一层，不含任何业务语义：
  · 基础清洗与安全转换（`clean_str` / `_to_float` / `_to_int` / `_to_time_str` / `_to_date`）；
  · 合约乘数反推（`_infer_multiplier`：成交额 ÷ 价 ÷ 手，只在接近正整数时采信）；
  · 工作表定位与结构化（`_locate_header_row` / `_build_dataframe` / `_drop_summary_rows`
    / `_resolve_columns` / `_read_sheet`）；
  · 账户名容错提取（`_extract_account_name`）；
  · 列名别名表与页签名常量（各期货公司导出差异的**统一映射处**）。

【纯粹性约束】与 `data_feed.py` 同源：**不碰数据库、不碰 UI、不联网**。
  `data_feed.py` 从这里 import 这些工具，`legacy` 的 `from data.data_feed import ...`
  由 `data_feed.py` 再导出兜底，外部调用口径零改动。
"""
import logging
import re

import pandas as pd

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
    if pd.isna(s):
        return ""
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
