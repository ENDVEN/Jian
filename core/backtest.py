# core/backtest.py
"""
单股事件模式回测引擎 (A股仅做多 LONG)。

执行约定 (与产品决策一致)：
- 信号语义 = 条件成立即触发：买入条件、卖出条件各自独立布尔信号序列；
  信号**于该根 K 线收盘后判定**，成交时点由**成交时点模型**决定 (v6.17 新增)：
  · `next_open` (默认)：次日开盘价成交 (与旧版逐位一致)；
  · `close`：当日收盘价成交 (语义 = 尾盘看盘下单)；
  · `trigger`：次日挂**条件单** —— 买入需突破 `high[信号日] + tick×0.01`、
    卖出需跌破 `low[信号日] − tick×0.01` 才成交；**未触达则本次信号作废**。
- 成本：佣金率 (双边, 默认万3)，结果以「单股单位」归一化净值。
- 同一时间只允许一个持仓 (信号期内重复买入信号忽略)。

【v6.17 · §7-B5 核心铁律 T+1】：出场 K 线必须**严格晚于**入场 K 线。
- ⇒ **入场根之后必须至少还有一根 K 线**，否则本次买入信号作废 (避免"买完当天强平"的假交易)；
- ⇒ 止损 / 止盈 / 移动止盈若在**进场当根**触发，**当日不得成交**，
  顺延到"最早可卖根"按**该根开盘价**成交 (跳空低开就承受跳空 —— 真实优先，绝不用线价美化)；
- ⇒ `max_bars` 属"收盘评估型"：T+1 下自然顺延到次根收盘 (N=1 ⇒ 次日收盘离场)；
- ⇒ `close` 档入场时，当根的卖出信号不评估 (同一时刻既买又卖自相矛盾)；
- ⇒ **同根不重建仓**：若本次建仓的**成交根**正好是刚发生过离场的那一根，则不建仓 ——
  否则同一根同时命中买卖条件会退化成"卖出后原价立刻买回"(白付两次佣金、持仓其实没变)；
  持续为真的条件 (如 `C > MA(C,20)` 同时出现在买卖两侧) 会因此**每根空转并严重低估结果**。
  ⚠ 判据是"**成交根**重合"而非"评估根"重合：离场之后下一根的合法再入场照常允许。
- 背景：修复前 `stop_loss`/`take_profit`/`max_bars` 均可在买入当天离场，
  按 A股 T+1 属违规且**低估风险** (带止损的策略回撤比真实好看)。详见 §7-B5-B 的 F3。
- 若卖出/风控信号出现在最后一根 K 线且无可执行根，则按最后收盘价强平 (杜绝悬空持仓)。

【阶段B 风控离场器】硬性保护规则 (可选, 默认全关)：
- 与"信号"正交：信号是主观决策、收盘确认、按成交时点模型执行；
  风控是预设保护单、**盘中触发即离场**，谁先到谁执行，且硬规则优先于信号。
- stop_loss / take_profit / trailing 基于当日 low/high 触发 (受 T+1 闸门约束)：
  - 触发价 = 预设线价；若当日开盘已跳空越过触发线，则按开盘价成交 (不占未来便宜)。
  - trailing 峰值取"进场以来最高 high"，回撤线 = 峰值 × (1 - trail%)；
  - 同根多线下沿 (止损 / 移动止盈 / 触发式卖单) 同时触及 → 取更高线价成交 (先触达的那条)。
- max_bars (最长持仓 N 根) 属管理型规则：第 N 根收盘仍持仓则**当日收盘价强平**。
- 每笔成交记录 exit_reason，供 UI 区分离场来源 (signal / stop_loss / take_profit /
  trailing / max_bars / force_close)；被 T+1 顺延的成交另记 `deferred_t1=True`。

注意：该引擎当前只服务 A 股做多策略；做空/期货在远期设计中另行支持。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd

from core.formula import FormulaEngine

# 默认回测数据起点：更早行情对量化回测参考意义有限 (产品决策)
# v5.6：下沿由 2018 放宽到 2016（用户要求更长样本窗）；
#       必须与 ui/views/backtest.py 的「全部(2016起)」预设 + 起始日期 minimumDate 保持一致。
DEFAULT_START_DATE = "2016-01-01"

# 默认双边佣金率 (万3)
DEFAULT_COMMISSION_RATE = 0.0003

# ---- 成交时点模型 (v6.17 · §7-B5 C1) ----
FILL_NEXT_OPEN = "next_open"   # 信号日收盘成立 → 次日开盘成交 (默认，与旧版逐位一致)
FILL_CLOSE = "close"           # 信号日收盘成立 → 当日收盘成交 (语义 = 尾盘下单)
FILL_TRIGGER = "trigger"       # 挂条件单：次日触达触发价才成交，未触达则本次信号作废

FILL_MODE_LABELS = {
    FILL_NEXT_OPEN: "次日开盘价成交（默认 · 最保守）",
    FILL_CLOSE: "当日收盘价成交（尾盘下单）",
    FILL_TRIGGER: "价格冲破 / 跌破才成交",
}

# 【用户指引 · v6.17】每一档的"一句话解释"，**面向完全不懂行的用户**：
# 只讲"什么时候、按什么价、会发生什么"，不出现 跳 / 当根 / K 线 / 条件单 等术语。
# ⚠ 这份文案是 UI 行内说明与「三档怎么选」教学弹窗的**唯一来源**，禁止在页面里另写一份。
FILL_MODE_ONELINERS = {
    FILL_NEXT_OPEN: "信号出现后的下一个交易日一开盘，就按开盘价买卖。最保守，"
                    "但如果第二天大幅跳空高开，你只能在高位买进。",
    FILL_CLOSE: "信号出现当天收盘，就按收盘价买卖。相当于你每天尾盘盯盘下单，"
                "不再白等一整天。",
    FILL_TRIGGER: "先挂单等价格到点：冲破信号日最高价 +{offset:.2f} 元才买入、"
                  "跌破最低价 −{offset:.2f} 元才卖出；一整天没碰到，就不买也不卖。",
}

# A股最小价格变动：1 跳 = 0.01 元。触发价 = 信号根 high/low ∓ tick × TICK_SIZE。
# ⚠「跳」是交易所术语：**只在 tooltip 里当补充说明出现，绝不作为界面上的唯一说明**。
TICK_SIZE = 0.01
DEFAULT_TRIGGER_TICK = 1

# T+1 说明（导出/报告与 UI tooltip 共用同一份文案，勿在别处另写）
T1_SUMMARY = "T+1 约束：已启用（出场 K 线必须晚于入场 K 线）"


def normalize_fill(fill_mode: str | None, trigger_tick=None) -> dict:
    """成交时点模型参数归一化；非法值一律回落默认 (next_open / tick=1)。幂等，可重复调用。"""
    mode = str(fill_mode or FILL_NEXT_OPEN).strip().lower()
    if mode not in FILL_MODE_LABELS:
        mode = FILL_NEXT_OPEN
    try:
        tick = int(trigger_tick)
    except (TypeError, ValueError):
        tick = DEFAULT_TRIGGER_TICK
    if tick < 0:
        tick = DEFAULT_TRIGGER_TICK
    return {"fill_mode": mode, "trigger_tick": tick}


def tick_to_yuan(tick) -> float:
    """跳数 → 元（UI 用「元」跟用户说话，内部仍以整数跳为准，避免浮点漂移）。"""
    return normalize_fill(FILL_TRIGGER, tick)["trigger_tick"] * TICK_SIZE


def yuan_to_tick(yuan) -> int:
    """元 → 跳数；至少 1 跳（0.01 元），非法值回落默认。"""
    try:
        ticks = int(round(float(yuan) / TICK_SIZE))
    except (TypeError, ValueError):
        return DEFAULT_TRIGGER_TICK
    return max(1, ticks) if ticks > 0 else DEFAULT_TRIGGER_TICK


def fill_mode_oneliner(fill_mode: str | None, trigger_tick=None) -> str:
    """单档成交时点的**一句话用户说明**（含具体数字，用户不必理解"跳"）。

    教学弹窗与页面行内说明共用这一份，禁止在 UI 里另写。
    """
    conf = normalize_fill(fill_mode, trigger_tick)
    template = FILL_MODE_ONELINERS.get(conf["fill_mode"], FILL_MODE_ONELINERS[FILL_NEXT_OPEN])
    return template.format(offset=tick_to_yuan(conf["trigger_tick"]))


def fill_summary(fill_mode: str | None, trigger_tick=None) -> str:
    """成交时点模型 → 一行留档文案（CSV 表头 / PNG 报告图 / 明细回执）。

    与 `risk_summary` 同源纪律：**禁止任何 UI 文件再各写一份**（§9-O7 同类教训）。
    ⚠ 与 `fill_mode_oneliner` 的分工：这里要"可复现"（写清具体价差），
    那里要"看得懂"（讲清会发生什么）。
    """
    conf = normalize_fill(fill_mode, trigger_tick)
    if conf["fill_mode"] == FILL_CLOSE:
        return "成交时点：当日收盘价（尾盘下单）"
    if conf["fill_mode"] == FILL_TRIGGER:
        return ("成交时点：价格冲破/跌破才成交"
                f"（信号日最高价 +{tick_to_yuan(conf['trigger_tick']):.2f} 元买入 / "
                f"最低价 −{tick_to_yuan(conf['trigger_tick']):.2f} 元卖出，未到点则该次信号作废）")
    return "成交时点：次日开盘价（最保守）"

# 风控离场原因 (UI 展示与存档用，勿改字符串)
REASON_SIGNAL = "signal"
REASON_STOP_LOSS = "stop_loss"
REASON_TAKE_PROFIT = "take_profit"
REASON_TRAILING = "trailing"
REASON_MAX_BARS = "max_bars"
REASON_FORCE_CLOSE = "force_close"

# 离场原因 -> 中文标签 / 配色（v5.15：从 UI 层上收到 core，供 明细表/CSV/PNG报告图 同源使用，
# 禁止任何 UI 文件再各自定义一份 —— §9-O7 同类教训）
EXIT_REASON_LABELS = {
    REASON_SIGNAL: "卖出信号",
    REASON_STOP_LOSS: "固定止损",
    REASON_TAKE_PROFIT: "固定止盈",
    REASON_TRAILING: "移动止盈",
    REASON_MAX_BARS: "超时强平",
    REASON_FORCE_CLOSE: "收盘强平",
}
EXIT_REASON_COLORS = {
    REASON_SIGNAL: "#1976D2",       # 蓝：主观卖出
    REASON_STOP_LOSS: "#F44336",    # 红：亏损离场
    REASON_TAKE_PROFIT: "#4CAF50",  # 绿：止盈离场
    REASON_TRAILING: "#2E7D32",     # 深绿：保盈离场
    REASON_MAX_BARS: "#FB8C00",     # 橙：管理型超时
    REASON_FORCE_CLOSE: "#9AA3B2",  # 灰：期末强平
}


def risk_summary(risk: dict | None) -> str:
    """风控参数 → 人话一句话（CSV 表头 / PNG 报告共用同一来源，勿在 UI 再写一份）。

    输入与 UI 一致：百分比为"8 表示 8%"，max_bars 为根数；全关/空返回「全部关闭」。
    """
    risk = risk or {}

    def num(key: str) -> float:
        try:
            return float(risk.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    parts = []
    max_bars = int(num("max_bars"))
    if max_bars:
        parts.append(f"最长持仓 {max_bars} 根")
    for label, key in (("固定止损", "stop_loss_pct"), ("固定止盈", "take_profit_pct"),
                       ("移动止盈回撤", "trailing_pct")):
        value = num(key)
        if value:
            parts.append(f"{label} {value:g}%")
    return "；".join(parts) if parts else "全部关闭"


def normalize_risk(risk: dict | None) -> dict:
    """把 UI/外部传入的风控参数归一为引擎内部小数口径，非法值一律回落 0 (关闭)。

    接受键: max_bars / stop_loss_pct / take_profit_pct / trailing_pct (百分比)。
    """
    risk = risk or {}
    try:
        max_bars = max(0, int(risk.get("max_bars", 0) or 0))
    except (TypeError, ValueError):
        max_bars = 0
    frac = {}
    for key in ("stop_loss_pct", "take_profit_pct", "trailing_pct"):
        try:
            val = float(risk.get(key, 0) or 0)
        except (TypeError, ValueError):
            val = 0.0
        frac[key] = max(0.0, val) / 100.0
    return {
        "max_bars": max_bars,
        "stop_loss_pct": frac["stop_loss_pct"],
        "take_profit_pct": frac["take_profit_pct"],
        "trailing_pct": frac["trailing_pct"],
    }


@dataclass
class BacktestTrade:
    """一笔完成的回合交易 (单位为“一股”)"""
    entry_date: object
    exit_date: object
    entry_price: float
    exit_price: float
    shares: float = 1.0
    commission: float = 0.0
    pnl: float = 0.0          # 价差净收益 (含成本)
    return_pct: float = 0.0   # 单笔收益率 (净值变动因子)
    exit_reason: str = REASON_SIGNAL  # 离场来源 (阶段B)
    deferred_t1: bool = False  # 是否因 T+1 被顺延到"最早可卖根"成交 (v6.17 · §7-B5)

    @property
    def days_held(self):
        try:
            return (self.exit_date - self.entry_date).days
        except TypeError:
            return None


@dataclass
class BacktestResult:
    """一次单股回测的完整结果"""
    symbol: str
    buy_expression: str
    sell_expression: str
    start_date: str
    end_date: str
    trades: list[BacktestTrade] = field(default_factory=list)
    equity: pd.DataFrame = field(default_factory=pd.DataFrame)  # date / equity / in_market
    params: dict = field(default_factory=dict)
    commission_rate: float = DEFAULT_COMMISSION_RATE
    risk: dict = field(default_factory=dict)  # 本次实际生效的风控参数 (阶段B)
    fill_mode: str = FILL_NEXT_OPEN           # 本次实际生效的成交时点模型 (v6.17 · §7-B5)
    trigger_tick: int = DEFAULT_TRIGGER_TICK  # 触发式委托的跳数 (1 跳 = TICK_SIZE = 0.01 元)

    # ---------- 汇总指标 ----------
    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_count(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def cumulative_return(self) -> float:
        if self.equity.empty:
            return 0.0
        return float(self.equity['equity'].iloc[-1] - 1.0)

    def summary(self) -> dict:
        wins = self.win_count
        total = self.total_trades
        return {
            "total_trades": total,
            "win_trades": wins,
            "loss_trades": total - wins,
            "win_rate": wins / total if total else 0.0,
            "cumulative_return": self.cumulative_return,
            "avg_return_pct": float(np.mean([t.return_pct for t in self.trades])) if total else 0.0,
            "best_return_pct": float(max((t.return_pct for t in self.trades), default=0.0)),
            "worst_return_pct": float(min((t.return_pct for t in self.trades), default=0.0)),
        }


class BacktestEngine:
    """事件模式回测引擎 (无 UI / 无网络，纯计算)"""

    def run(
        self,
        df: pd.DataFrame,
        buy_expression: str,
        sell_expression: str,
        symbol: str = "",
        params: dict = None,
        start_date: str = DEFAULT_START_DATE,
        end_date: str = None,
        commission_rate: float = DEFAULT_COMMISSION_RATE,
        risk: dict = None,
        fill_mode: str = FILL_NEXT_OPEN,
        trigger_tick: int = DEFAULT_TRIGGER_TICK,
    ) -> BacktestResult:
        # ---- 数据准备 ----
        data = df.copy()
        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date').reset_index(drop=True)
        for col in ('open', 'high', 'low', 'close', 'volume'):
            if col in data.columns:
                data[col] = pd.to_numeric(data[col], errors='coerce')
        data = data.dropna(subset=['close', 'open'])

        # 默认数据窗: 2016-01-01 起 (回测意义窗)，终点不设上限
        start_ts = pd.Timestamp(start_date or DEFAULT_START_DATE)
        data = data[data['date'] >= start_ts]
        if end_date:
            data = data[data['date'] <= pd.Timestamp(end_date)]
        if data.empty:
            fill_conf = normalize_fill(fill_mode, trigger_tick)
            return BacktestResult(symbol, buy_expression, sell_expression,
                                  str(start_ts.date()), str(end_date or ""), params=params,
                                  commission_rate=commission_rate, risk=normalize_risk(risk),
                                  fill_mode=fill_conf["fill_mode"],
                                  trigger_tick=fill_conf["trigger_tick"])

        # ---- 信号求值 (信号为布尔序列，事件性由表达式规则如 CROSS 决定) ----
        buy_signal = FormulaEngine.signal(buy_expression, data, params).to_numpy()
        sell_signal = FormulaEngine.signal(sell_expression, data, params).to_numpy()

        # 归一化只在 run() 做一次；_run_on_signals 收到的是已归一化小数口径
        risk_norm = normalize_risk(risk)
        return self._run_on_signals(
            data=data, buy_signal=buy_signal, sell_signal=sell_signal,
            symbol=symbol, buy_expression=buy_expression, sell_expression=sell_expression,
            start_date=str(start_ts.date()), end_date=str(end_date or data['date'].max().date()),
            params=params or {}, commission_rate=commission_rate, risk=risk_norm,
            fill_mode=fill_mode, trigger_tick=trigger_tick,
        )

    # 独立为纯函数便于单测；risk 应为已归一化 dict (由 run()/调用方负责)；
    # fill_mode / trigger_tick 在此再归一化一次 (幂等)，便于直接单测本函数。
    @staticmethod
    def _run_on_signals(data, buy_signal, sell_signal, symbol, buy_expression, sell_expression,
                        start_date, end_date, params, commission_rate, risk=None,
                        fill_mode=FILL_NEXT_OPEN,
                        trigger_tick=DEFAULT_TRIGGER_TICK) -> BacktestResult:
        risk = risk or {}
        conf = normalize_fill(fill_mode, trigger_tick)
        fill_mode = conf["fill_mode"]
        trigger_offset = conf["trigger_tick"] * TICK_SIZE

        dates = data['date'].tolist()
        opens = data['open'].to_numpy(dtype=float)
        highs = data['high'].to_numpy(dtype=float) if 'high' in data.columns else opens
        lows = data['low'].to_numpy(dtype=float) if 'low' in data.columns else opens
        closes = data['close'].to_numpy(dtype=float)
        n = len(data)

        max_bars = risk.get("max_bars", 0)
        stop_frac = risk.get("stop_loss_pct", 0.0)
        take_frac = risk.get("take_profit_pct", 0.0)
        trail_frac = risk.get("trailing_pct", 0.0)
        has_stop = stop_frac > 0
        has_take = take_frac > 0
        has_trail = trail_frac > 0

        # T+1 铁律 (§7-B5 C2)：出场根必须严格晚于入场根 ⇒ 可入场的最晚一根 = n-2
        # （入场后至少还留一根可卖；否则本次买入信号作废，避免"买完当天强平"的假交易）
        last_entry_bar = n - 2

        trades: list[BacktestTrade] = []
        equity_curve = []
        equity = 1.0          # 归一化净值 (初始=1 股成本基准)
        in_market = False
        entry_price = 0.0
        entry_date = None
        entry_idx = -1
        peak_high = 0.0        # 进场以来最高 high (移动止盈基准)
        bars_held = 0          # 已持仓根数 (含当根)
        entry_plan = None      # 挂单入场 {bar, kind, trigger}
        deferred_reason = None  # 进场当根被 T+1 拦下的价格型离场（次根开盘执行）
        pending_exit = None    # 触发式卖单 {bar, trigger}；未触达即作废
        last_exit_bar = -1     # 最近一次"离场成交根"（用于"同根不重建仓"，见下）

        def settle(reason: str, exit_price: float, exit_bar: int, deferred_t1: bool = False):
            """把已决定的一笔离场落账 (闭包复用循环状态)"""
            nonlocal equity, in_market, entry_idx, peak_high, bars_held
            nonlocal deferred_reason, pending_exit, last_exit_bar
            commission = (entry_price + exit_price) * commission_rate
            pnl = exit_price - entry_price - commission
            ret = pnl / entry_price if entry_price else 0.0
            trades.append(BacktestTrade(
                entry_date=entry_date, exit_date=dates[exit_bar],
                entry_price=entry_price, exit_price=exit_price,
                commission=commission, pnl=pnl, return_pct=ret,
                exit_reason=reason, deferred_t1=deferred_t1))
            equity *= (1.0 + ret)
            in_market = False
            entry_idx = -1
            peak_high = 0.0
            bars_held = 0
            deferred_reason = None
            pending_exit = None
            last_exit_bar = exit_bar      # "同根不重建仓"的判据基准

        def lower_bound_hit(i):
            """当根"下沿型"触发：止损线 / 移动止盈线 / 触发式卖单 —— 同根取更高线先成交。"""
            best_line = None
            best_reason = None
            candidates = []
            if has_trail and peak_high > 0:
                candidates.append((peak_high * (1.0 - trail_frac), REASON_TRAILING))
            if has_stop:
                candidates.append((entry_price * (1.0 - stop_frac), REASON_STOP_LOSS))
            if pending_exit is not None and pending_exit['bar'] == i:
                candidates.append((pending_exit['trigger'], REASON_SIGNAL))
            for line, reason in candidates:
                if lows[i] <= line and (best_line is None or line > best_line):
                    best_line, best_reason = line, reason
            return best_line, best_reason

        def signal_exit(i):
            """信号离场：按成交时点模型决定何时/以何价成交（T+1 由调用处保证）。"""
            nonlocal pending_exit
            if fill_mode == FILL_CLOSE:
                settle(REASON_SIGNAL, float(closes[i]), i)          # 当根收盘成交
            elif i + 1 < n:
                if fill_mode == FILL_NEXT_OPEN:
                    settle(REASON_SIGNAL, float(opens[i + 1]), i + 1)   # 次日开盘成交
                else:
                    # 触发式卖单：次日跌破 信号根低点 − tick 才卖；未跌破 ⇒ 本次信号作废
                    pending_exit = {'bar': i + 1,
                                    'trigger': float(lows[i]) - trigger_offset}

        for i in range(n):
            # ---- 1) 挂单入场（next_open / trigger 两档在此成交）----
            #     "同根不重建仓"：本根刚成交过离场 ⇒ 不允许在此建仓（防"卖出后原价买回"空转）
            if (not in_market and entry_plan is not None and entry_plan['bar'] == i
                    and i != last_exit_bar):
                plan, entry_plan = entry_plan, None
                price = None
                if plan['kind'] == 'open':
                    price = float(opens[i])
                else:
                    # trigger：开盘已越过 → 按开盘价；盘中触达 → 按触发价；未触达 → 本次信号作废
                    if float(opens[i]) >= plan['trigger']:
                        price = float(opens[i])
                    elif float(highs[i]) >= plan['trigger']:
                        price = float(plan['trigger'])
                if price is not None:
                    entry_price = price
                    entry_date = dates[i]
                    entry_idx = i
                    bars_held = 1
                    peak_high = float(highs[i]) if has_trail else 0.0
                    in_market = True

            # ---- 2) 在场内：离场判定（T+1 闸门：出场根必须 > 入场根）----
            if in_market:
                if i > entry_idx:
                    bars_held += 1

                if deferred_reason is not None:
                    # 进场当根被 T+1 拦下的价格型离场：在"最早可卖根"按开盘价成交。
                    # 跳空低开就承受跳空 —— 这是真实成交价，绝不用触发线价美化。
                    settle(deferred_reason, float(opens[i]), i, deferred_t1=True)
                else:
                    hit_line, hit_reason = lower_bound_hit(i)
                    if hit_reason is not None:
                        if i > entry_idx:
                            # 跳空越过线 → 按开盘价成交；盘中触及 → 按线价成交
                            settle(hit_reason, float(min(opens[i], hit_line)), i)
                        else:
                            # 进场当根：T+1 禁止当日卖出 ⇒ 只登记，顺延到最早可卖根
                            deferred_reason = hit_reason
                    else:
                        # 2b) 上沿止盈
                        if has_take:
                            line_take = entry_price * (1.0 + take_frac)
                            if highs[i] >= line_take:
                                if i > entry_idx:
                                    settle(REASON_TAKE_PROFIT,
                                           float(max(opens[i], line_take)), i)
                                else:
                                    deferred_reason = REASON_TAKE_PROFIT
                        # 2c) 超时强平 (第 max_bars 根收盘仍持仓)
                        #     收盘评估型规则：T+1 下自然顺延到次根收盘 (N=1 ⇒ 次日收盘离场)
                        if in_market and max_bars > 0 and bars_held >= max_bars and i > entry_idx:
                            settle(REASON_MAX_BARS, float(closes[i]), i)
                        # 2d) 移动止盈峰值滚动更新 (触发判断用“昨日以前峰值”，避免当日新高自触发)
                        if in_market and has_trail:
                            peak_high = max(peak_high, float(highs[i]))
                        # 2e) 信号离场 (硬规则未触发时才考虑)
                        #     close 档在入场当根不评估（同一时刻既买又卖自相矛盾）；
                        #     next_open / trigger 档的成交落在下一根，天然满足 T+1。
                        if in_market and bool(sell_signal[i]):
                            if not (fill_mode == FILL_CLOSE and i == entry_idx):
                                signal_exit(i)

            # ---- 3) 过期挂单清理（防御性兜底；正常路径不会命中）----
            if entry_plan is not None and entry_plan['bar'] <= i:
                entry_plan = None
            if pending_exit is not None and pending_exit['bar'] <= i:
                pending_exit = None      # 触发式卖单未触达 ⇒ 本次卖出信号作废

            # ---- 4) 收盘后：按成交时点模型建仓 ----
            #     "同根不重建仓"（v6.17 用户拍板）：判据是"**成交根**重合"，不是"评估根"重合 ——
            #     只要本次建仓的**成交根**正好是刚发生过离场的那一根，就不建仓。
            #     否则"同一根 K 线同时命中买卖条件"会退化成"卖出后立刻在同一价格买回"：
            #     白付两次佣金而持仓毫无变化；若条件持续为真（如 C>MA(C,20) 两侧都成立），
            #     就会**每根空转**并把结果严重低估。
            #     ⚠ 只拦"同一成交根"：离场之后下一根的合法再入场照常允许。
            if not in_market and bool(buy_signal[i]) and i <= last_entry_bar:
                if fill_mode == FILL_CLOSE:
                    # 当日收盘成交：信号与成交同一根；放在第 2 步之后，当根的盘中波动不予评估
                    if i != last_exit_bar:
                        entry_price = float(closes[i])
                        entry_date = dates[i]
                        entry_idx = i
                        bars_held = 1
                        peak_high = float(highs[i]) if has_trail else 0.0
                        in_market = True
                elif i + 1 != last_exit_bar:
                    entry_plan = {
                        'bar': i + 1,
                        'kind': 'open' if fill_mode == FILL_NEXT_OPEN else 'trigger',
                        'trigger': float(highs[i]) + trigger_offset,
                    }

            # ---- 5) 净值打点：在场内按当日收盘做未实现市值标记，否则取已实现净值 ----
            if in_market:
                mark_equity = equity * (closes[i] / entry_price if entry_price else 1.0)
            else:
                mark_equity = equity
            equity_curve.append((dates[i], float(mark_equity), bool(in_market)))

        # 收盘仍持仓 -> 以最后收盘价强平 (杜绝悬空)
        # T+1 下这是安全的：入场根被 last_entry_bar 限制在 n-2 之前，末根必晚于入场根。
        if in_market:
            exit_price = float(closes[-1])
            commission = (entry_price + exit_price) * commission_rate
            pnl = exit_price - entry_price - commission
            ret = pnl / entry_price if entry_price else 0.0
            trades.append(BacktestTrade(
                entry_date=entry_date, exit_date=dates[-1],
                entry_price=entry_price, exit_price=exit_price,
                commission=commission, pnl=pnl, return_pct=ret,
                exit_reason=REASON_FORCE_CLOSE))
            equity *= (1.0 + ret)

        equity_df = pd.DataFrame(equity_curve, columns=['date', 'equity', 'in_market'])
        return BacktestResult(
            symbol=symbol, buy_expression=buy_expression, sell_expression=sell_expression,
            start_date=start_date, end_date=end_date,
            trades=trades, equity=equity_df, params=params, commission_rate=commission_rate,
            risk=risk, fill_mode=fill_mode, trigger_tick=conf["trigger_tick"],
        )
