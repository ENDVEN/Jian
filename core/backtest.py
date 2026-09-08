# core/backtest.py
"""
单股事件模式回测引擎 (A股仅做多 LONG)。

执行约定 (与产品决策一致)：
- 信号语义 = 条件成立即触发：买入条件、卖出条件各自独立布尔信号序列；
  成交时机：信号于收盘后判定，于**次日开盘**成交。
- 若卖出信号出现在最后一根K线且次日不存在，则当日收盘强平 (杜绝悬空持仓)。
- 成本：佣金率 (双边, 默认万3)，结果以「单股单位」归一化净值。
- 同一时间只允许一个持仓 (信号期内重复买入信号忽略)。

【阶段B 风控离场器】硬性保护规则 (可选, 默认全关)：
- 与"信号"正交：信号是主观决策、收盘确认、次日执行；风控是预设保护单、
  **当日盘中触发即离场**，谁先到谁执行，且硬规则优先于信号。
- stop_loss / take_profit / trailing 基于当日 low/high 触发：
  - 触发价 = 预设线价；若当日开盘已跳空越过触发线，则按开盘价成交 (不占未来便宜)。
  - trailing 峰值取"进场以来最高 high"，回撤线 = 峰值 × (1 - trail%)；
  - 同根多线下沿(止损/移动止盈)同时触及 → 取更高线价成交 (先触达的那条)。
- max_bars (最长持仓 N 根) 属管理型规则：第 N 根收盘仍持仓则**当日收盘价强平**。
- 每笔成交记录 exit_reason，供 UI 区分离场来源 (signal / stop_loss / take_profit /
  trailing / max_bars / force_close)。

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

# 风控离场原因 (UI 展示与存档用，勿改字符串)
REASON_SIGNAL = "signal"
REASON_STOP_LOSS = "stop_loss"
REASON_TAKE_PROFIT = "take_profit"
REASON_TRAILING = "trailing"
REASON_MAX_BARS = "max_bars"
REASON_FORCE_CLOSE = "force_close"


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
            return BacktestResult(symbol, buy_expression, sell_expression,
                                  str(start_ts.date()), str(end_date or ""), params=params,
                                  commission_rate=commission_rate, risk=normalize_risk(risk))

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
        )

    # 独立为纯函数便于单测；risk 应为已归一化 dict (由 run()/调用方负责)
    @staticmethod
    def _run_on_signals(data, buy_signal, sell_signal, symbol, buy_expression, sell_expression,
                        start_date, end_date, params, commission_rate, risk=None) -> BacktestResult:
        risk = risk or {}
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

        trades: list[BacktestTrade] = []
        equity_curve = []
        equity = 1.0          # 归一化净值 (初始=1 股成本基准)
        in_market = False
        entry_price = 0.0
        entry_date = None
        entry_bar = -1
        entry_idx = -1
        peak_high = 0.0       # 进场以来最高 high (移动止盈基准)
        bars_held = 0         # 已持仓根数 (含当根)

        def settle(reason: str, exit_price: float, exit_bar: int):
            """把已决定的一笔离场落账 (闭包复用循环状态)"""
            nonlocal equity, in_market, entry_bar, entry_idx, peak_high, bars_held
            commission = (entry_price + exit_price) * commission_rate
            pnl = exit_price - entry_price - commission
            ret = pnl / entry_price if entry_price else 0.0
            trades.append(BacktestTrade(
                entry_date=entry_date, exit_date=dates[exit_bar],
                entry_price=entry_price, exit_price=exit_price,
                commission=commission, pnl=pnl, return_pct=ret,
                exit_reason=reason))
            equity *= (1.0 + ret)
            in_market = False
            entry_bar = -1
            entry_idx = -1
            peak_high = 0.0
            bars_held = 0

        for i in range(n):
            # 1) 处理上一根K线触发的“次日开盘进场”
            if not in_market and entry_bar == i:
                entry_price = float(opens[i])
                entry_date = dates[i]
                entry_idx = i
                bars_held = 1
                peak_high = float(highs[i]) if has_trail else 0.0
                in_market = True

            # 2) 在场内：先跑硬性风控 (盘中触发，硬规则优先于信号)
            if in_market:
                if i > entry_idx:
                    bars_held += 1

                # 2a) 下沿保护：止损线 / 移动止盈线 (取实际触发中更高的一条先成交)
                line_stop = entry_price * (1.0 - stop_frac) if has_stop else None
                line_trail = (peak_high * (1.0 - trail_frac)
                              if has_trail and peak_high > 0 else None)
                hit_line = None
                hit_reason = None
                for line, reason in ((line_trail, REASON_TRAILING),
                                     (line_stop, REASON_STOP_LOSS)):
                    if line is not None and lows[i] <= line:
                        if hit_line is None or line > hit_line:
                            hit_line = line
                            hit_reason = reason
                if hit_line is not None:
                    # 跳空低开越过线 -> 按开盘价成交；盘中触及 -> 按线价成交
                    settle(hit_reason, float(min(opens[i], hit_line)), i)
                else:
                    # 2b) 上沿止盈
                    if has_take:
                        line_take = entry_price * (1.0 + take_frac)
                        if highs[i] >= line_take:
                            settle(REASON_TAKE_PROFIT,
                                   float(max(opens[i], line_take)), i)
                    # 2c) 超时强平 (第 max_bars 根收盘仍持仓)
                    if in_market and max_bars > 0 and bars_held >= max_bars:
                        settle(REASON_MAX_BARS, float(closes[i]), i)
                    # 2d) 移动止盈峰值滚动更新 (触发判断用“昨日以前峰值”，避免当日新高自触发)
                    if in_market and has_trail:
                        peak_high = max(peak_high, float(highs[i]))

                # 2e) 信号离场 (收盘评估，次日开盘成交)；硬规则未触发时才考虑
                if in_market and i + 1 < n and bool(sell_signal[i]):
                    settle(REASON_SIGNAL, float(opens[i + 1]), i + 1)

            # 3) 不在场时：今日收盘出现买入信号 -> 次日开盘进场
            if not in_market and i + 1 < n and bool(buy_signal[i]):
                entry_bar = i + 1

            # 4) 净值打点：在场内按当日收盘做未实现市值标记，否则取已实现净值
            if in_market:
                mark_equity = equity * (closes[i] / entry_price if entry_price else 1.0)
            else:
                mark_equity = equity
            equity_curve.append((dates[i], float(mark_equity), bool(in_market)))

        # 收盘仍持仓 -> 以最后收盘价强平 (杜绝悬空)
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
            risk=risk,
        )
