# core/sweep_stats.py
"""
参数稳健性研究（§7-B15）· 统计唯一真源（SW-1）。

★全站唯一实现 Rank IC / 一致性差(delta) / 邻域稳健 / PBO(CSCV) / 门槛筛选 的地方
（方案书 §8-1 源码级钉死：别处出现这些公式 = 违规）。

★入参契约（方案书 §8-16）：本模块**只吃收益矩阵与索引**（ndarray / 邻域表），
不收 `BacktestResult`、不 import `core.backtest` —— 统计层在物理上拿不到"全量结果对象"，
CSCV 内部的冠军规则只可能在 A 段口径下重算（从形状上杜绝"拿样本外选参数"的泄漏）。

口径（与 docs/JIAN_SWEEP_PLAN.md §7 同源，改动必须两边同步）：
- 绩效主口径 = 复利年化 (Π(1+r))^(244/n) − 1；n=0 ⇒ NaN；净值归零（Π ≤ 0）⇒ 诚实地板 -1.0。
- **Rank IC = Spearman(秩(IS 年化), 秩(OOS 年化))，样本集 = 全网格**（§8-15：与门槛无关；
  本函数没有门槛入口，被门槛筛掉的组一样参与秩相关）。任一侧常数 / 样本 <2 ⇒ NaN
  （界面显示 —，绝不冒充 0）。
- **邻域 = 沿每一维 ±1 档、含自身**（2 维 3×3=9 格 / 1 维 1×3=3 格）；
  邻域表来自 `sweep_plan.neighborhood_indices`（与 build_grid 的 combos 同序）。
- **候选排序键 = (邻域均值 ↓, OOS 年化 ↓, |Δ| ↑)，不含 IS 项**（§8-2 / §8-12）；
  **门槛（交易次数 / IS>0 / OOS>0）只筛不排**：先对全网格定序，再按门槛筛成员（顺序不动）。
- **PBO（CSCV，Bailey et al. 口径）**：逐日收益矩阵按 S 个**连续**块切分；对每个
  C(S, S/2) 划分：A 当 IS / B 当 OOS —— 冠军 = 排序键的 **IS 侧形态** =
  (邻域均值(A) ↓, 年化(A) ↓)，**只用 A 段收益**（|Δ| 与 OOS 项在 A 内不存在，自然退出；
  拿全量算 = 拿样本外选参数 = 踩红线①）。冠军在 B 上的秩百分位 < 0.5（掉到中位数以下）
  记一次"掉队"；PBO = 掉队占比。> 0.5 ⇒ 这套选参流程等于抛硬币（界面红字警示）。
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 244  # A股年交易日惯例；本模块唯一的年化口径出口


@dataclass(frozen=True)
class SweepMetrics:
    """一次研究的全部排序键指标（study_key_stats 的产物；候选表 / 结论条 / 散点全从这里取）。"""

    is_annual: np.ndarray     # (n,) 样本内复利年化
    oos_annual: np.ndarray    # (n,) 样本外复利年化
    delta: np.ndarray         # (n,) 一致性差 = oos − is（|Δ| 是排序键第三项）
    nb_mean: np.ndarray       # (n,) 邻域均值（在 OOS 年化上，含自身）
    nb_worst: np.ndarray      # (n,) 邻域最差（平台 vs 尖峰的对照读数）


def annual_returns(R, day_idx=None, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> np.ndarray:
    """每组合在给定交易日子集上的复利年化。

    R: (n_combos, n_days) 简单收益矩阵；day_idx 为空 = 全部天数。
    CSCV 的 A/B 段重算与本函数走同一条路（§8-16 的形状保证）。
    """
    Rm = np.asarray(R, dtype=float)
    if Rm.ndim != 2:
        raise ValueError("收益矩阵必须是 (n_combos, n_days) 二维")
    if day_idx is not None:
        Rm = Rm[:, np.asarray(day_idx, dtype=int)]
    n_days = Rm.shape[1]
    if n_days == 0:
        return np.full(Rm.shape[0], np.nan)
    growth = np.prod(1.0 + Rm, axis=1)
    with np.errstate(invalid="ignore"):
        out = np.where(growth > 0,
                       growth ** (periods_per_year / n_days) - 1.0,
                       -1.0)
    return out


def build_neighborhood_matrix(nb_table) -> tuple[np.ndarray, np.ndarray]:
    """邻域表（每项 = 含自身的组合索引元组）→ (0/1 矩阵 M, 每行格数 counts)。

    `M @ values / counts` = 邻域均值 —— CSCV 里 924 次重算全走这一条矩阵乘。
    """
    n = len(nb_table)
    M = np.zeros((n, n), dtype=float)
    for i, idxs in enumerate(nb_table):
        M[i, list(idxs)] = 1.0
    counts = np.array([len(idxs) for idxs in nb_table], dtype=float)
    if (counts == 0).any():
        raise ValueError("邻域表存在空行（每个组合的邻域至少要含自身）")
    return M, counts


def neighborhood_mean(values, M, counts) -> np.ndarray:
    """邻域均值（含自身；M/counts 见 build_neighborhood_matrix）。"""
    return (M @ np.asarray(values, dtype=float)) / counts


def neighborhood_worst(values, nb_table) -> np.ndarray:
    """邻域最差（尖峰的邻居里必有塌陷格；平台的最差也站得住）。"""
    v = np.asarray(values, dtype=float)
    return np.array([v[list(idxs)].min() for idxs in nb_table])


def rank_ic(is_annual, oos_annual) -> float:
    """Rank IC = Spearman(秩(IS 年化), 秩(OOS 年化))，**全网格一个数**（§2）。

    样本 <2 或任一侧为常数 ⇒ NaN —— 界面显示 "—"，绝不冒充 0。
    """
    ra = pd.Series(np.asarray(is_annual, dtype=float)).rank()
    rb = pd.Series(np.asarray(oos_annual, dtype=float)).rank()
    if len(ra) < 2 or ra.nunique() < 2 or rb.nunique() < 2:
        return float("nan")
    return float(np.corrcoef(ra.to_numpy(), rb.to_numpy())[0, 1])


def candidate_order(is_annual, oos_annual, nb_mean) -> np.ndarray:
    """全网格排序 = (邻域均值 ↓, OOS 年化 ↓, |Δ| ↑)，**不含 IS 项**（§8-2）。

    np.lexsort 的主键 = 最后一个；完全平局回落到组合序号（稳定、可复现）。
    """
    ia = np.asarray(is_annual, dtype=float)
    oa = np.asarray(oos_annual, dtype=float)
    nb = np.asarray(nb_mean, dtype=float)
    return np.lexsort((np.abs(oa - ia), -oa, -nb))


def apply_gate(order, trades, min_trades, is_annual, oos_annual) -> np.ndarray:
    """门槛**只筛不排**（§8-12）：先定序后筛成员；返回 order 的子序列（相对顺序不变）。

    门槛 = 交易次数 ≥ min_trades 且 IS 年化 > 0 且 OOS 年化 > 0（方案书 §2 排序规则）。
    """
    t = np.asarray(trades, dtype=float)
    ia = np.asarray(is_annual, dtype=float)
    oa = np.asarray(oos_annual, dtype=float)
    keep = (t >= float(min_trades)) & (ia > 0) & (oa > 0)
    return np.asarray(order)[keep[np.asarray(order)]]


def study_key_stats(R, is_idx, oos_idx, nb_table,
                    periods_per_year: int = TRADING_DAYS_PER_YEAR) -> SweepMetrics:
    """一次研究的全部排序键指标（唯一出口；Rank IC 另调 rank_ic，全网格口径 §8-15）。

    R: (n_combos, n_days)；is_idx / oos_idx: 各段在天轴上的索引（两段**独立回测**，
    天轴不重叠 —— 见方案书 §7 边界口径）。邻域统计取在 **OOS 年化**上（§2 ③）。
    """
    ia = annual_returns(R, np.asarray(is_idx, dtype=int), periods_per_year)
    oa = annual_returns(R, np.asarray(oos_idx, dtype=int), periods_per_year)
    M, counts = build_neighborhood_matrix(nb_table)
    return SweepMetrics(
        is_annual=ia,
        oos_annual=oa,
        delta=oa - ia,
        nb_mean=neighborhood_mean(oa, M, counts),
        nb_worst=neighborhood_worst(oa, nb_table),
    )


def _rank_pct(values) -> np.ndarray:
    """秩百分位（平均秩处理平局；完全平局 = 0.5 ⇒ 不算掉队，与"掉到中位数**以下**"一致）。"""
    return pd.Series(np.asarray(values, dtype=float)).rank(pct=True).to_numpy()


def platform_spike_flags(oos_annual, nb_mean, nb_worst,
                         platform_q: float = 75.0) -> tuple[np.ndarray, np.ndarray]:
    """把每个组合判成「平台」/「尖峰」——**判据的唯一出口**（热力图圈注 / 候选表列共用）。

    口径（用户 2026-10-01 二次拍板：**平台从严**）：
    - **平台**：`邻域均值 ≥ 上四分位（p75，即"前 25%"）` —— 周围一圈都站得住，**且是领先的那一组**。
      ⚠ 早期用的是"≥ 中位数"，但实测偏负的网格里它覆盖约一半格子（294 格中 150 格）⇒
      图上是一片绿雾、"等于什么也没说"；用户拍板收到 **前 25%**（图上才读得出"一块高地"）。
    - **尖峰**：`自身 ≥ p75(自身)` 且 `邻域最差 < 中位数(自身)` 且**非平台** —— 自己高、邻居却塌，
      正是"孤立的尖峰"（选它 ≈ 赌一个点）。
    两集**互斥**（平台优先）：同一个组合不会同时被标两种，图上不会有叠标歧义。
    退化（NaN / 常数）⇒ 全 False，绝不冒充判定（"不知道"就说不知道）。
    """
    own = np.asarray(oos_annual, dtype=float)
    nb = np.asarray(nb_mean, dtype=float)
    nw = np.asarray(nb_worst, dtype=float)
    empty = np.zeros(own.shape, dtype=bool)
    if own.size < 2 or not np.isfinite(own).any() or not np.isfinite(nb).any():
        return empty, empty
    nb_line = float(np.nanpercentile(nb, platform_q))     # 平台线（默认前 25%）
    mid_own = float(np.nanmedian(own))
    p75_own = float(np.nanpercentile(own, 75))
    platform = np.isfinite(nb) & (nb >= nb_line)
    spike = (np.isfinite(own) & (own >= p75_own) & np.isfinite(nw)
             & (nw < mid_own) & ~platform)
    return platform, spike


def rolling_ic(R, s_blocks: int = 12,
               periods_per_year: int = TRADING_DAYS_PER_YEAR) -> np.ndarray:
    """滚动 Rank IC（★R4 ④）：把天轴切 S 段，**逐段**看"前一半的排序能不能预测后一半"。

    【为什么要有它】全网格只报一个 Rank IC（`rank_ic`）会骗人：一个数看不出"它是全程稳定，
    还是只在某几段灵"。这里把同样的问法（秩相关）**逐段**问一遍 ⇒ 折线的**起伏**就是答案。

    口径（与 CSCV 同族：同一份 `R`、同样"切段 + 前段选/后段验"的思想，唯一差别是段内再二分）：
      段 b 的天 = `np.array_split(np.arange(t), S)[b]`；A = 该段前一半、B = 该段后一半；
      `ic[b] = rank_ic(年化(R[:, A]), 年化(R[:, B]))`。
    段内任一侧 < 2 天 / 秩为常数 ⇒ 该段 **NaN**（图上**断开**，不插值 —— 别造数据）。
    R: (n_combos, n_days) 全期（IS+OOS 拼接，与 `pbo_cscv` 吃同一份矩阵）。
    """
    Rm = np.asarray(R, dtype=float)
    S = int(s_blocks)
    if S < 2:
        raise ValueError(f"滚动 IC 的段数必须 ≥ 2（收到 {S}）")
    if Rm.ndim != 2 or Rm.shape[0] < 2 or Rm.shape[1] < S:
        return np.full(S, np.nan)
    out = np.full(S, np.nan)
    for b, days in enumerate(np.array_split(np.arange(Rm.shape[1]), S)):
        half = len(days) // 2
        if half < 2 or len(days) - half < 2:
            continue
        a_days, b_days = days[:half], days[half:]
        out[b] = rank_ic(annual_returns(Rm, a_days, periods_per_year),
                         annual_returns(Rm, b_days, periods_per_year))
    return out


def pbo_cscv(R, nb_table, s_blocks: int = 12,
             periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """PBO（CSCV）。伪代码与口径见模块 docstring / 方案书 §7。

    R: (n_combos, n_days) 全期（IS+OOS 拼接）逐日简单收益。S 奇数或 <2 ⇒ ValueError
    （不默默换口径）；天数不足 S / 组合 <2 ⇒ NaN（诚实，不冒充 0）。
    """
    Rm = np.asarray(R, dtype=float)
    if Rm.ndim != 2:
        return float("nan")
    n, t = Rm.shape
    if n < 2 or t < s_blocks:
        return float("nan")
    if s_blocks < 2 or s_blocks % 2 != 0:
        raise ValueError(f"CSCV 的段数 S 必须是不小于 2 的偶数（收到 {s_blocks}）")
    blocks = np.array_split(np.arange(t), s_blocks)
    M, counts = build_neighborhood_matrix(nb_table)
    splits = list(combinations(range(s_blocks), s_blocks // 2))
    below = 0
    for a_blocks in splits:
        a_days = np.concatenate([blocks[i] for i in a_blocks])
        b_days = np.concatenate([blocks[i] for i in range(s_blocks) if i not in a_blocks])
        # ---- 冠军只在 A 上选：排序键的 IS 侧形态（邻域均值(A) ↓, 年化(A) ↓）----
        a_annual = annual_returns(Rm, a_days, periods_per_year)
        nb_mean = neighborhood_mean(a_annual, M, counts)
        champ = int(np.lexsort((-a_annual, -nb_mean))[0])
        # ---- B 只用来"验"：冠军在 B 上的秩百分位是否掉到中位数以下 ----
        b_annual = annual_returns(Rm, b_days, periods_per_year)
        if _rank_pct(b_annual)[champ] < 0.5:
            below += 1
    return below / len(splits)
