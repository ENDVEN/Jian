# data/feed_fifo.py
"""交割单解析的**数据模型 + FIFO 配对引擎**（1.25 自 `data/data_feed.py` 拆出 · §9-L）。

【职责】
  · 三个纯数据结构：`Fill`（逐笔成交，FIFO 最小单位）/ `OpenLeg`（未平开仓腿）
    / `MonthlySummary`（结算月报资金勾稽快照）；
  · 持仓腿确定性主键 `_make_leg_id` 与开仓时刻合成 `_compose_entry_time`；
  · `_allocate_pnl`：把一笔平仓盈亏分配到各切片，保证**总额守恒**（v1.2.1 修正）；
  · `_run_fifo`：全局有序的 FIFO 配对，产出闭环 `TradeRecord` + 剩余持仓腿 + 统计。

【纯粹性约束】同 `data_feed.py`：**不碰数据库、不碰 UI**（历史腿由调用方传入、
  新腿以返回值交回）。迁移时**逐字保留**原算法与注释（§9-L 纯重构红线）。
"""
import hashlib
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from core.preferences import TIME_SOURCE_DATE_ONLY, TIME_SOURCE_STATEMENT
from data.feed_cells import BUY, OPEN, SELL
from models.trade import TradeRecord


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
