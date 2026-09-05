# core/backtest.py
"""
单股事件模式回测引擎 (A股仅做多 LONG)。

执行约定 (与产品决策一致)：
- 信号语义 = 事件：买入条件、卖出条件各自独立；仅在“由假变真”那一根 K 线触发。
- 下单时机：信号产生于收盘后 (用当日收盘数据评估)，于**次日开盘**成交；
  若卖出信号出现在最后一根K线且次日不存在，则当日收盘强平 (杜绝悬空持仓)。
- 成本：佣金率 (双边, 默认万3)，结果以「单股单位」归一化净值。
- 同一时间只允许一个持仓 (信号期内重复买入信号忽略)。

注意：该引擎当前只服务 A 股做多策略；做空/期货在远期设计中另行支持。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd

from core.formula import FormulaEngine

# 默认回测数据起点：更早行情对量化回测参考意义有限 (产品决策)
DEFAULT_START_DATE = "2018-01-01"

# 默认双边佣金率 (万3)
DEFAULT_COMMISSION_RATE = 0.0003


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
    ) -> BacktestResult:
        # ---- 数据准备 ----
        data = df.copy()
        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date').reset_index(drop=True)
        for col in ('open', 'high', 'low', 'close', 'volume'):
            if col in data.columns:
                data[col] = pd.to_numeric(data[col], errors='coerce')
        data = data.dropna(subset=['close', 'open'])

        # 默认数据窗: 2018-01-01 起 (回测意义窗)，终点不设上限
        start_ts = pd.Timestamp(start_date or DEFAULT_START_DATE)
        data = data[data['date'] >= start_ts]
        if end_date:
            data = data[data['date'] <= pd.Timestamp(end_date)]
        if data.empty:
            return BacktestResult(symbol, buy_expression, sell_expression,
                                  str(start_ts.date()), str(end_date or ""), params=params,
                                  commission_rate=commission_rate)

        # ---- 信号求值 (事件判定由引擎完成) ----
        buy_signal = FormulaEngine.signal(buy_expression, data, params).to_numpy()
        sell_signal = FormulaEngine.signal(sell_expression, data, params).to_numpy()

        return self._run_on_signals(
            data=data, buy_signal=buy_signal, sell_signal=sell_signal,
            symbol=symbol, buy_expression=buy_expression, sell_expression=sell_expression,
            start_date=str(start_ts.date()), end_date=str(end_date or data['date'].max().date()),
            params=params or {}, commission_rate=commission_rate,
        )

    # 独立为纯函数便于单测
    @staticmethod
    def _run_on_signals(data, buy_signal, sell_signal, symbol, buy_expression, sell_expression,
                        start_date, end_date, params, commission_rate) -> BacktestResult:
        dates = data['date'].tolist()
        opens = data['open'].to_numpy()
        closes = data['close'].to_numpy()
        n = len(data)

        trades: list[BacktestTrade] = []
        equity_curve = []
        equity = 1.0          # 归一化净值 (初始=1 股成本基准)
        in_market = False
        entry_price = 0.0
        entry_date = None
        entry_bar = -1

        for i in range(n):
            # 1) 处理上一根K线触发的“次日开盘进场”
            if not in_market and entry_bar == i:
                entry_price = float(opens[i])
                entry_date = dates[i]
                in_market = True

            # 2) 在场内时检查今日卖出信号(收盘评估)，次日开盘离场
            if in_market and i + 1 < n and bool(sell_signal[i]):
                exit_price = float(opens[i + 1])
                exit_date = dates[i + 1]
                commission = (entry_price + exit_price) * commission_rate
                pnl = exit_price - entry_price - commission
                ret = pnl / entry_price if entry_price else 0.0
                trades.append(BacktestTrade(
                    entry_date=entry_date, exit_date=exit_date,
                    entry_price=entry_price, exit_price=exit_price,
                    commission=commission, pnl=pnl, return_pct=ret))
                equity *= (1.0 + ret)
                in_market = False
                entry_bar = -1

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
            exit_date = dates[-1]
            commission = (entry_price + exit_price) * commission_rate
            pnl = exit_price - entry_price - commission
            ret = pnl / entry_price if entry_price else 0.0
            trades.append(BacktestTrade(
                entry_date=entry_date, exit_date=exit_date,
                entry_price=entry_price, exit_price=exit_price,
                commission=commission, pnl=pnl, return_pct=ret))
            equity *= (1.0 + ret)

        equity_df = pd.DataFrame(equity_curve, columns=['date', 'equity', 'in_market'])
        return BacktestResult(
            symbol=symbol, buy_expression=buy_expression, sell_expression=sell_expression,
            start_date=start_date, end_date=end_date,
            trades=trades, equity=equity_df, params=params, commission_rate=commission_rate,
        )
