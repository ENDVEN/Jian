# core/portfolio_stats.py
"""🧺 组合的**统计内核**（★1.85 / §7-B17 **P1**）—— 纯计算，零 Qt、零 IO。

【它算什么】
  · `nav_series`：把 N 只票的**日收益**按权重合成一条组合净值（基期 = 1.0000）；
  · `holdings_rows`：持仓表的四列（权重 / 成本 / 最新 / 盈亏）；
  · `max_drawdown` / `annualized`：净值曲线上的两个标准数。

【三条口径（用户 2026-10-26 拍板，写死在这里，UI 不许另算）】
  ① **再平衡 = 买入持有 or 按月**；"按月" = **每月最后一个交易日**收盘把权重拉回目标；
  ② **现金不参与再平衡**（固定占比，收益恒 0）—— 用户原话："有时持有现金跑赢所有组合"；
  ③ **成本价 = 组合基期那天的收盘价**（相当于按目标权重"模拟买入"），
     所以"盈亏" = 最新/成本 − 1，含义是**区间涨跌**，不是券商的持仓成本（那是账本，不是这里）。

【为什么"停牌/缺数据"要 ffill 而不是丢日期】
  组合净值必须**逐日可比**；某只票当天没成交（停牌）⇒ 价格沿用上一日（收益 0），这才是真实组合的行为。
  但**整只票没有任何数据**时**不许**当 0 收益：`holdings_rows` 会标 `data_ok=False`，界面写"数据不足"（§10-4）。
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 244      # 与 `core.sweep_stats` 同一个年化口径


def _frame_returns(df) -> pd.Series:
    """`DataFrame(date, close)` → `Series(index=日期字符串, 日收益)`（首日 0）。"""
    if df is None or len(df) == 0 or "close" not in getattr(df, "columns", ()):
        return pd.Series(dtype=float)
    d = pd.DataFrame({"date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
                      "close": pd.to_numeric(df["close"], errors="coerce")})
    d = d.dropna(subset=["close"]).drop_duplicates(subset=["date"], keep="last")
    if d.empty:
        return pd.Series(dtype=float)
    s = d.set_index("date")["close"].astype(float)
    return s.pct_change().fillna(0.0)


def build_returns(frames: dict) -> tuple:
    """多只票 → `(交易日列表, {symbol: 日收益 Series})`。

    · 交易日 = 各票日期的**并集**（组合要逐日可比）；
    · 单票缺失日 ⇒ 价格 ffill（收益 0，= 停牌）；
    · 返回的 Series 已按交易日列表对齐（长度一致，便于矩阵运算）。
    """
    rets = {str(k): _frame_returns(v) for k, v in (frames or {}).items()}
    rets = {k: v for k, v in rets.items() if len(v)}
    if not rets:
        return [], {}
    days = sorted(set().union(*(set(v.index) for v in rets.values())))
    aligned = {}
    for k, v in rets.items():
        # 先按并集 reindex（缺失 = NaN ⇒ 停牌 ⇒ 用 0 收益），再 ffill 兜住"中间空档"
        aligned[k] = v.reindex(days).fillna(0.0)
        aligned[k] = aligned[k].fillna(0.0)
    return days, aligned


def _month_end_mask(days) -> np.ndarray:
    """标记"每月最后一个交易日"（`days` 必须是升序 `YYYY-MM-DD`）。"""
    if not days:
        return np.zeros(0, dtype=bool)
    months = np.array([str(d)[:7] for d in days])
    mask = np.zeros(len(days), dtype=bool)
    mask[-1] = True
    mask[:-1] = months[:-1] != months[1:]
    return mask


def nav_series(days, returns: dict, weights: dict, cash: float = 0.0,
               rebalance: str = "monthly") -> pd.Series:
    """按权重合成净值（基期 1.0000）。

    :param weights: `{symbol: 权重百分数}`（合计应与 `100 - cash` 一致；这里**会归一**，不静默取整）
    :param rebalance: `'buy_hold'`（权重自由漂移）或 `'monthly'`（每月末拉回目标）
    """
    days = list(days or ())
    syms = [s for s in (weights or {}) if s in (returns or {})]
    if not days or not syms:
        return pd.Series(dtype=float)
    w = np.array([max(0.0, float(weights[s])) for s in syms], dtype=float)
    tot = w.sum()
    if tot <= 0:
        return pd.Series(dtype=float)
    w = w / tot * (1.0 - float(cash or 0.0) / 100.0)      # 归一（现金占比固定，收益 0）
    R = np.vstack([np.asarray(returns[s], dtype=float) for s in syms])   # (n_sym, n_day)
    n = len(days)
    vals = w.copy()                       # 当前"每只票的价值"（总净值 = sum + cash）
    cash_v = float(cash or 0.0) / 100.0
    out = np.empty(n, dtype=float)
    resets = _month_end_mask(days) if str(rebalance) == "monthly" else np.zeros(n, dtype=bool)
    for i in range(n):
        if i > 0:
            vals = vals * (1.0 + R[:, i])
        total = vals.sum() + cash_v
        out[i] = total
        if resets[i] and i != n - 1:
            vals = w * total               # 拉回目标（现金保持固定占比）
    return pd.Series(out, index=days, dtype=float)


def holdings_rows(symbols, names: dict, weights: dict, first_close: dict,
                  last_close: dict) -> list:
    """持仓表行：`{symbol,name,weight,cost,last,pnl,data_ok}`。

    `cost` = 基期收盘（模拟按权重买入）·`pnl` = 最新/成本 − 1 · 没数据 ⇒ `data_ok=False`（界面写"数据不足"）。
    """
    rows = []
    for s in (symbols or []):
        s = str(s)
        c0, c1 = first_close.get(s), last_close.get(s)
        ok = bool(c0 and c1 and float(c0) > 0)
        rows.append({"symbol": s, "name": str((names or {}).get(s) or ""),
                     "weight": round(float((weights or {}).get(s) or 0.0), 2),
                     "cost": float(c0) if c0 else None,
                     "last": float(c1) if c1 else None,
                     "pnl": (float(c1) / float(c0) - 1.0) if ok else None,
                     "data_ok": ok})
    return rows


def max_drawdown(nav) -> float:
    """最大回撤（**正数**表示回撤幅度，如 0.23 = −23%）。"""
    s = pd.Series(nav, dtype=float).dropna()
    if s.empty:
        return float("nan")
    peak = s.cummax()
    return float((1.0 - s / peak).max())


def annualized(nav) -> float:
    """年化收益（**几何**，按 244 交易日折算）；不足 2 个点 ⇒ NaN（不编）。"""
    s = pd.Series(nav, dtype=float).dropna()
    if len(s) < 2 or float(s.iloc[0]) <= 0:
        return float("nan")
    total = float(s.iloc[-1]) / float(s.iloc[0])
    years = (len(s) - 1) / float(TRADING_DAYS_PER_YEAR)
    if years <= 0:
        return float("nan")
    return float(total ** (1.0 / years) - 1.0)


def period_return(nav) -> float:
    """区间总收益（首→末）。"""
    s = pd.Series(nav, dtype=float).dropna()
    if len(s) < 2 or float(s.iloc[0]) <= 0:
        return float("nan")
    return float(s.iloc[-1]) / float(s.iloc[0]) - 1.0


def today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


__all__ = ["build_returns", "nav_series", "holdings_rows", "max_drawdown", "annualized",
           "period_return", "TRADING_DAYS_PER_YEAR", "today_str"]
