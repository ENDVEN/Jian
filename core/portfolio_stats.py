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

    ⚠★1.88 **必须用交集，不能用并集**（用户 2026-10-27 指出的口径问题）：
      并集 + 缺失日记 0 收益 = 把"这只票还没上市"当成"持有一动不动" ⇒
      组合净值在早期被稀释成一条**假的平滑曲线**，"全部区间"因此是个**伪命题**。
      交集 = **所有成分都有数据的第一天**才是组合真正的起点（也是唯一诚实的起点）。

    · 单票中间缺失（停牌）⇒ 用 0 收益补（这段确实没法交易，且两端都有价）；
    · 返回的 Series 已按交易日列表对齐（长度一致，便于矩阵运算）。
    """
    rets = {str(k): _frame_returns(v) for k, v in (frames or {}).items()}
    rets = {k: v for k, v in rets.items() if len(v)}
    if not rets:
        return [], {}
    # 交集：**所有成分都有数据的交易日**才算组合的交易日（见上方口径说明）
    days = sorted(set.intersection(*(set(v.index) for v in rets.values())))
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


#: 市场归属（按代码前缀；**这是展示口径，不参与任何收益计算**）
MARKET_LABELS = (("sh", "沪市"), ("sz", "深市"), ("bj", "北交所"), ("other", "其他"))


def market_of(symbol: str) -> str:
    """代码 → 市场键（沪 6 / 深 0 或 3 / 北 4 或 8 / 其余 other）。

    ⚠ 只按**代码段**判，不查数据源：指数、ETF 也照此归类（ETF 多在 51/15 段 ⇒ 归"沪/深"，与行情页一致）。
    """
    s = str(symbol or "").strip()
    if not s:
        return "other"
    c = s[0]
    if c in ("6", "5"):          # 6=沪股 · 5=沪市基金/ETF（510300 这类）
        return "sh"
    if c in ("0", "3", "1"):     # 0/3=深股 · 1=深市基金/ETF（159xxx）
        return "sz"
    if c in ("4", "8"):
        return "bj"
    return "other"


def market_mix(members, cash: float = 0.0) -> list:
    """市场分布：`[(label, pct)]`（按权重求和；现金单独一项，0% 也保留 —— 用户要"看得见现金"）。"""
    agg = {}
    for m in (members or []):
        key = market_of(m.get("symbol"))
        agg[key] = agg.get(key, 0.0) + float(m.get("weight") or 0.0)
    out = [(label, agg.get(key, 0.0)) for key, label in MARKET_LABELS]
    out.append(("现金", max(0.0, float(cash or 0.0))))
    return out


def industry_mix(members, industry_map: dict = None, cash: float = 0.0) -> list:
    """行业分布：`[(行业名, pct)]`，**找不到行业 ⇒ 「未分类」**（不猜、不丢）。"""
    agg = {}
    for m in (members or []):
        name = str((industry_map or {}).get(str(m.get("symbol"))) or "").strip() or "未分类"
        agg[name] = agg.get(name, 0.0) + float(m.get("weight") or 0.0)
    out = sorted(agg.items(), key=lambda kv: -kv[1])
    out.append(("现金", max(0.0, float(cash or 0.0))))
    return out


__all__ += ["MARKET_LABELS", "market_of", "market_mix", "industry_mix"]


def nav_with_costs(days, returns: dict, weights: dict, cash: float = 0.0,
                   rebalance: str = "monthly", rate: float = 0.0003) -> dict:
    """**含换手成本**的净值 + 每次再平衡的明细（纯函数）。

    成本模型（用户 2026-10-26 口径：**双边、每次再平衡按成交额收**）：
      · 目标权重 `w`（已按 `1 − 现金比` 归一）；
      · 月末把各票市值拉回 `w × 总市值`：**成交额 = Σ|目标市值 − 当前市值|**（买卖两侧都算）；
      · **成本 = 成交额 × 每边费率**（`rate` 就是"每边"的费率，双边已含在 Σ|Δ| 里）。

    ⚠ 毛/净走**两条独立模拟**：净那条每次再平衡把成本**永久扣掉**（不回填），
      否则会出现"扣了又追平"的假净值（我先写错过一次）。

    返回 `{nav_net, nav_gross, events, turnover_total, cost_total, cost_pct}`；
    `events[i]["trades"]` = 该次调仓的**逐票增减**（`symbol / delta_pct / action`）。
    """
    days = list(days or ())
    syms = [k for k in (weights or {}) if k in (returns or {})]
    empty = {"nav_net": pd.Series(dtype=float), "nav_gross": pd.Series(dtype=float),
             "events": [], "turnover_total": 0.0, "cost_total": 0.0, "cost_pct": 0.0}
    if not days or not syms:
        return empty
    w = np.array([max(0.0, float(weights[k])) for k in syms], dtype=float)
    tot = w.sum()
    if tot <= 0:
        return empty
    w = w / tot * (1.0 - float(cash or 0.0) / 100.0)
    R = np.vstack([np.asarray(returns[k], dtype=float) for k in syms])
    n = len(days)
    resets = _month_end_mask(days) if str(rebalance) == "monthly" else np.zeros(n, dtype=bool)
    cash_v = float(cash or 0.0) / 100.0
    fee = float(rate or 0.0)

    def _sim(deduct: bool):
        vals = w.copy()
        out = []
        events, turn_sum, cost_sum = [], 0.0, 0.0
        for i in range(n):
            if i > 0:
                vals = vals * (1.0 + R[:, i])
            total = float(vals.sum() + cash_v)
            out.append(total)
            if resets[i] and i != n - 1 and total > 0:
                target = w * total
                trade = float(np.abs(target - vals).sum())
                cost = trade * fee if deduct else 0.0
                if trade > 1e-12:
                    # ⚠ 换手额与"扣不扣成本"无关 ⇒ **两条模拟都要累计**
                    #   （我先只在 deduct 分支累加，导致 gross 那条的 turn_sum 恒 0）
                    turn_sum += trade / total / 2.0 * 100.0
                    if deduct and cost > 0:
                        # ★1.89：记**逐票增减**（用户要"何时对哪只票加了/减了"）
                        _d = target - vals
                        _tr = []
                        for _i, _sym in enumerate(syms):
                            _pct = float(_d[_i]) / total * 100.0
                            if abs(_pct) >= 0.01:
                                _tr.append({"symbol": str(_sym),
                                            "delta_pct": round(_pct, 3),
                                            "action": "增持" if _pct > 0 else "减持"})
                        _tr.sort(key=lambda t: -abs(t["delta_pct"]))
                        events.append({"date": days[i],
                                       "turnover_pct": round(trade / total / 2.0 * 100.0, 4),
                                       "cost_pct": round(cost / total * 100.0, 6),
                                       "cost": round(cost, 10),
                                       "trades": _tr})
                        cost_sum += cost
                vals = target * ((total - cost) / total)
        return out, events, turn_sum, cost_sum

    gross_vals, _e_g, turn_sum, _c_g = _sim(False)
    net_vals, events, _t_n, cost_sum = _sim(True)
    nav_gross = pd.Series(gross_vals, index=days, dtype=float)
    nav_net = pd.Series(net_vals, index=days, dtype=float)
    g_end = float(nav_gross.iloc[-1])
    return {"nav_net": nav_net, "nav_gross": nav_gross, "events": events,
            "turnover_total": round(turn_sum, 4), "cost_total": round(cost_sum, 10),
            "cost_pct": round((1.0 - float(nav_net.iloc[-1]) / g_end) * 100.0, 4) if g_end else 0.0}


__all__ += ["nav_with_costs"]
