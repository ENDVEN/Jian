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

【v1.25 拆分（§9-L）】本文件曾 800+ 行，现按"职责"拆成 5 个纯函数模块：
    · `data/feed_cells.py`  —— 单元格 / 工作表工具层（清洗·转换·列名别名·页签读取）
    · `data/feed_fifo.py`   —— 数据模型（Fill/OpenLeg/MonthlySummary）+ FIFO 配对引擎
    · `data/feed_report.py` —— 结算月报页签解析（资金勾稽）
    · `data/feed_months.py` —— 月份推断 + 资金链对账（漏月检测用）
    · **本文件**            —— 成交/持仓页签解析 + 多文件编排 + 解析器注册表 + 兼容再导出
  ⚠ 迁移**逐字保留**原算法与注释；本文件把搬迁出去的公共名**再导出**，
    于是 `from data.data_feed import parse_cfmmc_files` 等既有调用口径零改动。

【纯粹性约束】本层是纯函数层：**不碰数据库、不碰 UI**。
历史持仓腿由调用方以 initial_legs 传入，新持仓腿以返回值交回，
保证解析器可以被单独测试，也便于将来接入其他数据源。
"""
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

# ---- 工具层（再导出，兼容旧 import 路径）----
from data.feed_cells import (BUY, CLOSE, DEFAULT_ACCOUNT, HEADER_KEYWORDS,  # noqa: F401
                             NULL_TOKENS, OPEN, POSITION_ALIASES,
                             POSITION_SHEET, REPORT_LABELS, REPORT_SHEET, SELL,
                             TRADE_ALIASES, TRADE_SHEET, _build_dataframe,
                             _drop_summary_rows, _extract_account_name,
                             _infer_multiplier, _locate_header_row,
                             _read_sheet, _resolve_columns, _to_date, _to_float,
                             _to_int, _to_time_str, clean_str)
# ---- 模型 + FIFO 引擎（再导出）----
from data.feed_fifo import (Fill, MonthlySummary, OpenLeg,  # noqa: F401
                            _allocate_pnl, _compose_entry_time, _make_leg_id,
                            _run_fifo)
# ---- 结算月报解析（再导出）----
from data.feed_months import (_infer_months,  # noqa: F401
                              _link_months_by_balance, _prev_month)
from data.feed_report import (_parse_monthly_report,  # noqa: F401
                              _scan_labeled_values)
from models.trade import TradeRecord

logger = logging.getLogger(__name__)


# ==========================================
# 三页签解析 (Page Parsers)
# ==========================================
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
    """解析 CFMMC 格式 Excel (向后兼容门面)

    NOTE(v5.7)：本门面及上方的 BaseTradeParser / CFMMCTradeParser / PARSER_REGISTRY /
    get_parser 目前**全仓无外部调用**，是为"未来接入其它期货公司账单格式"预留的扩展点。
    真实对外 API 只有 parse_cfmmc_files / legs_from_payload / detect_coverage_gaps 三个
    （均被 core/engine.py 调用）。
    """
    return parse_cfmmc_files([file_path])['trades']
