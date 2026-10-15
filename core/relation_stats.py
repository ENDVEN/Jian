# core/relation_stats.py
"""★1.73 / §7-B16 期 0：把 M3「与指数的关系」这件事的**判据与切分**收成纯函数。

【为什么单独一件】这些是**统计口径**，不是界面细节：
  · 判据（什么样的条件配什么样的图）必须是**一个**函数 —— 界面只许读结果，不许自己再判一遍
    （§11.5-112 同族：两处写必然漂）；
  · 它们必须能**离线单测**（零 Qt / 零网络 / 零盘）⇒ 放 `core/`，冒烟里逐条钉边界。

【本模块解决的核心统计问题（用户 2026-10-12 提问驱动）】
  "每天几百上千只命中"的条件**不能当事件统计** —— 命中家数 ≠ 事件数：
  同一天里全市场股票同向涨跌 ⇒ "某天 1500 只命中"其实是**1 个观测**（伪重复），
  按家数算 n 会虚高约千倍、p 值随之失去意义。正确口径 = 按**交易日**或**独立事件**计 n。
  ⇒ 本模块把"该按什么口径看"做成 `gate_decision()`，把"独立事件怎么数"做成
    `independent_event_positions()`。

【设计稿与方案书】`design/1.72-m3-multi-plan-ui/e-选图规则.html`（这一页就是它的可视化）·
  `docs/JIAN_M3_MULTI_PLAN.md` §1/§3 期 0。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    'MODE_EVENT', 'MODE_BINNED', 'MODE_CONTINUOUS', 'MODE_UNKNOWN',
    'DEFAULT_SPARSE_MAX', 'DEFAULT_FREQ_MIN', 'DEFAULT_INDEP_GAP',
    'SPARSE_MAX_RANGE', 'FREQ_MIN_RANGE', 'INDEP_GAP_RANGE', 'PREF_KEY',
    'MIN_SAMPLE', 'EVENT_MIN', 'PERM_SEED',
    'GateDecision', 'hit_day_stats', 'independent_event_positions',
    'gate_decision', 'clamp_thresholds', 'thresholds_from_prefs',
    'forward_returns', 'conditional_forward_returns', 'event_study',
    'lead_lag_corr', 'rank_ic_of', 'permutation_p',
]

# ==========================================
# 1) 阈值（**默认值 + 合法域**；用户可在设置页与相关页面就地改 —— 不许写死）
# ==========================================
# 口径：命中**天数**占比（= 有命中的交易日 / 全部交易日）—— 不是命中家数占比。
DEFAULT_SPARSE_MAX = 5.0     # < 它 ⇒ 像"事件"（每天只有很少的票命中）⇒ 可做事件对齐图 / 色带
DEFAULT_FREQ_MIN = 30.0      # ≥ 它 ⇒ 基本天天命中 = "状态"不是"事件" ⇒ 只能看占比 / IC / 回归
DEFAULT_INDEP_GAP = 5        # 独立事件：与**上一个被接受**的命中相隔 ≥ 这么多交易日才算新事件

SPARSE_MAX_RANGE = (0.5, 50.0)
FREQ_MIN_RANGE = (5.0, 99.0)
INDEP_GAP_RANGE = (1, 60)

# 偏好落点（`ui/settings_registry` 声明、`core/preferences.DEFAULTS` 供默认 —— 三处同源）
PREF_KEY = 'sweep3dense'

MODE_EVENT = 'event'             # 稀疏事件 ⇒ 事件对齐图 / K 线色带 可用
MODE_BINNED = 'binned'           # 半稀疏 ⇒ 占比分档 + 前向收益
MODE_CONTINUOUS = 'continuous'   # 频繁 ⇒ 只当连续指标（占比 / IC / 回归）
MODE_UNKNOWN = 'unknown'         # 还没跑过扫描，无从判定（**如实说**，不猜）


@dataclass(frozen=True)
class GateDecision:
    """选图判据的**唯一出口**（界面直接显示 `reason` / `suggest`，不再自己组织文案）。"""
    mode: str
    event_ok: bool               # 事件对齐图 / K 线色带 能不能用
    ratio_pct: float | None      # 命中天数占比（%；`None` = 还没有结果）
    reason: str                  # 为什么（含数字，给人看）
    suggest: str                 # 那该看什么


# ==========================================
# 2) 天数口径：把"逐日命中家数"折成判据要的两个数
# ==========================================
def hit_day_stats(hits_per_day) -> dict:
    """逐日命中家数 ⇒ `{'days', 'hit_days', 'ratio_pct'}`（**分母是交易日数**）。

    ⚠ 这是全模块**唯一**算"命中天数占比"的地方：分母用**交易日数**，不是家数、也不是全样本
      （与 M3 的"占比 = 命中 / 有效"同源纪律；§5.3 口径唯一）。
    ⚠ 入参容错：`None` / 空 / 含 NaN 都能跑（NaN 不计为命中）；**不抛**（界面每帧都在调它）。
    ⚠ 不能写 `hits_per_day or []` —— pandas Series 的布尔求值会抛（"truth value is ambiguous"）。
    """
    if hits_per_day is None:
        return {'days': 0, 'hit_days': 0, 'ratio_pct': 0.0}
    vals = []
    for v in hits_per_day:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            fv = 0.0
        vals.append(0.0 if math.isnan(fv) else fv)
    days = len(vals)
    hit_days = sum(1 for v in vals if v > 0)
    return {'days': days, 'hit_days': hit_days,
            'ratio_pct': (hit_days / days * 100.0) if days else 0.0}


# ==========================================
# 3) 独立事件切分（n 才不会虚高）
# ==========================================
def independent_event_positions(flags, gap: int = DEFAULT_INDEP_GAP) -> list[int]:
    """把逐日命中布尔序列切成**独立事件**，返回被接受的**位置**（升序）。

    口径（★写死在这里，别处不许再判）：
      · 第一天命中即接受；
      · 此后**只接受与「上一个被接受的事件」相隔 ≥ `gap` 个交易日**的命中日。
    【为什么按"与上一个被接受事件"而不是"与上一次命中"】一段行情会连续命中几十天，
      必须**塌成一个**事件；若按"上次命中"算，连续段里每隔 gap 天就会冒出一个"新事件"
      ⇒ n 再次虚高（正是"命中家数不是事件数"的同族错误）。
    【边界】`gap=5` 时相隔**恰好 5** 个交易日 ⇒ **算独立**（`>=`）；相隔 4 ⇒ 不算。
      这条边界有断言钉着 —— 改判据必须先改断言。
    ⚠ NaN / None 一律**不算命中**（诚实：算不出来就不算，不拿 0 或 1 顶替）。
    """
    if flags is None:
        return []
    step = max(1, int(gap))
    out: list[int] = []
    last: int | None = None
    for i, f in enumerate(flags):
        try:
            hit = bool(f) and (f == f)          # `f == f` 为 False ⇒ NaN ⇒ 不算命中
        except Exception:                        # noqa: BLE001 —— 脏对象一律当"非命中"
            hit = False
        if not hit:
            continue
        if last is None or (i - last) >= step:
            out.append(i)
            last = i
    return out


# ==========================================
# 4) 判据：什么样的条件配什么样的图
# ==========================================
def gate_decision(ratio_pct, sparse_max: float = DEFAULT_SPARSE_MAX,
                  freq_min: float = DEFAULT_FREQ_MIN) -> GateDecision:
    """按**命中天数占比**判"该用哪种表现"（左闭右开，边界写死并有断言钉住）。

        `[0, sparse_max)`        ⇒ `event`      事件对齐图 / 色带可用
        `[sparse_max, freq_min)` ⇒ `binned`     占比分档 + 前向收益
        `[freq_min, ∞)`          ⇒ `continuous` 占比 / IC / 回归

    【为什么这条判据必须存在】用户 2026-10-12 实测困惑："每天几百上千只命中，
      真的能用色带 / 对齐图看前向窗口去统计相关性吗？" —— 答案取决于**命中天数占比**
      （家数占比无关）：占比一高，"事件"这个前提就崩了（命中日连成片），
      色带会铺满整张图、什么也读不出来。软件应当**主动拦住**并给出替代，而不是画一张废图。
    """
    try:
        ratio = float(ratio_pct)
    except (TypeError, ValueError):
        ratio = float('nan')
    if math.isnan(ratio) or ratio < 0:
        return GateDecision(
            mode=MODE_UNKNOWN, event_ok=False, ratio_pct=None,
            reason='还没有扫描结果，无法判定该用哪种表现',
            suggest='先跑一次扫描（M3 ▶ 开始扫描），拿到"命中天数占比"再回来看这一页')
    lo = float(sparse_max)
    hi = float(freq_min)
    if ratio < lo:
        return GateDecision(
            mode=MODE_EVENT, event_ok=True, ratio_pct=ratio,
            reason=f'命中天数占比 {ratio:.1f}% < 稀疏闸 {lo:g}% ⇒ 它是**稀疏事件**',
            suggest='可以做事件对齐图（命中 ±20 日）与 K 线色带；'
                    '同时给"全部命中日"和"独立事件"两个 n，并配置换检验')
    if ratio < hi:
        return GateDecision(
            mode=MODE_BINNED, event_ok=False, ratio_pct=ratio,
            reason=f'命中天数占比 {ratio:.1f}% 落在 {lo:g}%~{hi:g}% 之间 ⇒ 半稀疏，'
                   '事件与事件之间会互相重叠',
            suggest='把占比分 5 档看每档的前向收益（n = 交易日数）+ 置换检验；'
                    '事件对齐图可作参考但样本数会虚高')
    return GateDecision(
        mode=MODE_CONTINUOUS, event_ok=False, ratio_pct=ratio,
        reason=f'命中天数占比 {ratio:.1f}% ≥ 频密闸 {hi:g}% ⇒ 它几乎天天命中，'
               '是**状态**不是**事件**（色带会铺满整张图，读不出东西）',
        suggest='把"命中占比"当一条连续指标：占比分档 / Rank IC / 稳健回归（n = 交易日数）；'
                '若想问"命中的股票之后表现如何"，那是横截面问题，请用 M2')


# ==========================================
# 5) 阈值取值：夹合法域 + **交叉修正如实回报**（不静默）
# ==========================================
def clamp_thresholds(sparse_max=DEFAULT_SPARSE_MAX, freq_min=DEFAULT_FREQ_MIN,
                     indep_gap=DEFAULT_INDEP_GAP) -> dict:
    """把三个阈值修进合法域；**每一处修正都在 `notes` 里如实说明**（§10-4 不静默）。

    :return: `{'sparse_max','freq_min','indep_gap','notes':[一句句人话]}`

    ⚠ 纪律：**坏值绝不静默回落** —— 用户手改偏好、旧版本遗留、跨版本脏数据都会走到这里，
      静默改名/改值等于"我偷偷替他做了决定"（本项目吃过这个亏，§9-D）。
    ⚠ 交叉约束：`freq_min` 必须 **严格大于** `sparse_max`（否则中间那档不存在）⇒
      自动抬到 `sparse_max + 5`，并**明说抬了**。
    """
    notes: list[str] = []

    def _num(v, lo, hi, default, name):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            fv = float('nan')
        if math.isnan(fv):
            notes.append(f'{name} 取值无法识别 ⇒ 回落默认 {default:g}')
            return float(default)
        if fv < lo or fv > hi:
            fixed = min(max(fv, lo), hi)
            notes.append(f'{name} {fv:g} 超出合法域 [{lo:g}, {hi:g}] ⇒ 已夹到 {fixed:g}')
            return float(fixed)
        return fv

    s = _num(sparse_max, SPARSE_MAX_RANGE[0], SPARSE_MAX_RANGE[1],
             DEFAULT_SPARSE_MAX, '稀疏闸')
    f = _num(freq_min, FREQ_MIN_RANGE[0], FREQ_MIN_RANGE[1],
             DEFAULT_FREQ_MIN, '频密闸')
    try:
        g = int(round(float(indep_gap)))
    except (TypeError, ValueError):
        g = int(DEFAULT_INDEP_GAP)
        notes.append(f'独立事件间隔取值无法识别 ⇒ 回落默认 {DEFAULT_INDEP_GAP}')
    if g < INDEP_GAP_RANGE[0] or g > INDEP_GAP_RANGE[1]:
        fixed_g = min(max(g, INDEP_GAP_RANGE[0]), INDEP_GAP_RANGE[1])
        notes.append(f'独立事件间隔 {g} 超出合法域 [{INDEP_GAP_RANGE[0]}, {INDEP_GAP_RANGE[1]}]'
                     f' ⇒ 已夹到 {fixed_g}')
        g = fixed_g
    if f <= s:                                   # 交叉约束：中间那档必须存在
        want = min(s + 5.0, FREQ_MIN_RANGE[1])
        notes.append(f'频密闸 {f:g}% 不高于稀疏闸 {s:g}%（中间的"分档"这一档会消失）'
                     f' ⇒ 已把频密闸抬到 {want:g}%')
        f = want
    return {'sparse_max': s, 'freq_min': f, 'indep_gap': g, 'notes': notes}


def thresholds_from_prefs() -> dict:
    """从偏好读数并夹好 —— **界面取阈值的唯一入口**（别处不许自己 `preferences.get`）。

    ⚠ 惰性 import `core.preferences`：本模块要被冒烟当纯函数反复调用，
      导入期不拉起任何有副作用的东西。
    """
    from core.preferences import preferences

    raw = preferences.get(PREF_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    return clamp_thresholds(raw.get('sparse_max', DEFAULT_SPARSE_MAX),
                            raw.get('freq_min', DEFAULT_FREQ_MIN),
                            raw.get('indep_gap', DEFAULT_INDEP_GAP))


# ==========================================
# 6) ★1.75 / §7-B16 期 3：**与指数的关系**（前向收益 / 事件对齐 / 领先滞后 / IC / 置换检验）
#   【为什么不另起模块】它们与前五节同属"用命中序列回答关系问题"这一件事，且都用同一份阈值与
#     同一个 `independent_event_positions`；另起模块只会多出一个口径入口（§11.5-112）。
#   【输入约定】一律吃 **pandas**：`flags`（逐日命中：家数或布尔，index = 交易日）与
#     `closes`（指数收盘，index = 交易日）。本层**不做时间对齐、不插值、不前向填充** ——
#     两边 index 取交集，交不上的地方如实留 NaN（造数据比缺数据更坏）。
#   【单位】所有收益/涨跌都是**小数**（0.012 = +1.2%），只有 `event_study` 的路径是 **%**（画图用）。
#   【纪律】`MIN_SAMPLE` 之下的结论**必须**标注"样本不足，仅参考"（界面据此显示，别自己判）。
# ==========================================
MIN_SAMPLE = 30          # 条件前向收益的最小样本（低于它 ⇒ `enough=False`）
EVENT_MIN = 10           # 事件对齐路径的最少事件数（不够 ⇒ 整段 `enough=False`）
PERM_SEED = 20261015     # 置换检验默认种子（固定 ⇒ 结论可复现、可被复述）


def _as_float_series(values):
    """把 `None` / 空 / 数组 / Series 统一成 float `Series`（**不抛**；NaN 原样保留）。"""
    import pandas as _pd

    if values is None:
        return _pd.Series(dtype=float)
    if isinstance(values, _pd.Series):
        return values.astype(float)
    return _pd.Series(list(values), dtype=float)


def forward_returns(closes, windows=(5, 10, 20)) -> dict:
    """**无条件**前向收益（基线）：`{window: Series}`，`r_t = C_{t+w} / C_t − 1`。

    窗口单位 = **数据点**（日线数据 ⇒ 交易日）。末尾 w 个点必然是 NaN（未来还不知道）✓。
    """
    c = _as_float_series(closes)
    out = {}
    for w in windows:
        step = max(1, int(w))
        out[step] = (c.shift(-step) / c - 1.0)
    return out


def conditional_forward_returns(flags, closes, windows=(5, 10, 20)) -> dict:
    """**条件 vs 基线**前向收益 —— 回答"命中之后指数怎么走"。

    `{window: {'n','mean','median','baseline_mean','baseline_median','diff','enough'}}`
    （`diff` = 条件均值 − 基线均值；单位 = 小数）。`enough=False` ⇒ 界面必须写"样本不足，仅参考"。
    """
    f = _as_float_series(flags).fillna(0.0)
    base = forward_returns(closes, windows)
    hit = f > 0
    out = {}
    for w, fwd in base.items():
        aligned_hit = hit.reindex(fwd.index, fill_value=False)
        vals = fwd[aligned_hit].dropna()
        allv = fwd.dropna()
        n = int(vals.shape[0])
        out[w] = {
            'n': n,
            'mean': float(vals.mean()) if n else float('nan'),
            'median': float(vals.median()) if n else float('nan'),
            'baseline_mean': float(allv.mean()) if allv.shape[0] else float('nan'),
            'baseline_median': float(allv.median()) if allv.shape[0] else float('nan'),
            'enough': n >= MIN_SAMPLE,
        }
        out[w]['diff'] = out[w]['mean'] - out[w]['baseline_mean']
    return out


def event_study(flags, closes, *, window: int = 20, gap: int = DEFAULT_INDEP_GAP) -> dict:
    """事件对齐路径（期 3 的"图 C"数据源）：横轴 = 相对命中日 −window…+window 的**累计涨跌 %**。

    :return: `{'offsets','mean','median','se','n_hit_days','n_independent','enough'}`
      · `mean` / `median`：每个偏移上、所有事件日"相对命中日指数"的累计涨跌（%）的均值/中位数；
      · `se`：均值的标准误（画 ±1σ 带用；样本 <2 ⇒ NaN）；
      · `n_hit_days` = 命中**交易日**数（按天算的那个 n）；`n_independent` = 独立事件数
        （连续命中塌成一个 ⇒ **两个 n 并列**，这是"n 会虚高"的正解）；
      · 每个偏移上样本不足 ⇒ 该点 NaN（图上**断开**，不插值）。
    """
    import numpy as _np
    import pandas as _pd

    f = _as_float_series(flags).fillna(0.0)
    c = _as_float_series(closes)
    idx = f.index.intersection(c.index)
    f = f.reindex(idx)
    c = c.reindex(idx)
    n = len(idx)
    W = max(1, int(window))
    offsets = list(range(-W, W + 1))
    vals = {o: [] for o in offsets}
    hit_pos = [i for i in range(n) if float(f.iloc[i]) > 0]
    flags_np = (f > 0).to_numpy()
    indep = set(independent_event_positions(flags_np, gap=gap))
    for pos in hit_pos:
        p0 = float(c.iloc[pos])
        if not _np.isfinite(p0) or p0 <= 0:
            continue
        for o in offsets:
            j = pos + o
            if 0 <= j < n:
                cj = float(c.iloc[j])
                if _np.isfinite(cj) and cj > 0:
                    vals[o].append((cj / p0 - 1.0) * 100.0)
    mean, median, se = {}, {}, {}
    for o in offsets:
        arr = _np.asarray(vals[o], dtype=float)
        if arr.size:
            mean[o] = float(arr.mean())
            median[o] = float(_np.median(arr))
            se[o] = (float(arr.std(ddof=1) / _np.sqrt(arr.size))
                     if arr.size > 1 else float('nan'))
        else:
            mean[o] = median[o] = se[o] = float('nan')
    n_hit = len(hit_pos)
    return {'offsets': offsets, 'mean': mean, 'median': median, 'se': se,
            'n_hit_days': n_hit,
            'n_independent': len(indep & set(hit_pos)),
            'enough': n_hit >= EVENT_MIN}


def lead_lag_corr(ratio, closes, *, lags=range(-20, 21)) -> dict:
    """领先滞后相关：`{lag: r}` —— 占比序列与指数**日收益**在第 `lag` 期的 Pearson 相关。

    **符号口径（写死，有断言钉住）**：`lag < 0` ⇒ **指标领先指数**
    （例：`lag=−5` = "今天的占比"与"5 个交易日**之后**的指数收益"相关；峰值落在负侧 = 领先）。
    ⚠ 相关 ≠ 因果：界面措辞一律写"同期 / 领先 N 期相关"，不许写"预测"。
    """
    import pandas as _pd

    r = _as_float_series(ratio).astype(float)
    c = _as_float_series(closes).astype(float)
    idx = r.index.intersection(c.index)
    r = r.reindex(idx)
    ret = c.reindex(idx).pct_change()
    out = {}
    for lag in lags:
        # ⚠ 符号口径（本轮实测踩过，靠"人工构造领先 5 期"的断言逮住）：
        #   `Series.shift(k)` 是**把数据往后挪 k 期** ⇒ 行 t 拿到 t−k 的值。
        #   要"行 t 拿**未来** t+k 的收益"必须 `shift(-k)`。所以 lag<0（指标领先）时
        #   要取未来 ⇒ **`shift(lag)`**（lag 是负数，正好取到未来）。
        #   我第一版写成 `shift(-lag)` ⇒ 整个轴**左右翻转**（峰值跑到 +5，与设计稿的
        #   "负 = 指标领先"完全相反），是断言把它抓出来的。
        other = ret.shift(int(lag))
        pair = _pd.concat([r, other], axis=1).dropna()
        if pair.shape[0] < 3 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
            out[int(lag)] = float('nan')
            continue
        out[int(lag)] = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
    return out


def rank_ic_of(ratio, closes, *, window: int = 20):
    """占比 vs 未来 `window` 期收益的 **Rank IC** —— **复用 `core.sweep_stats.rank_ic`**。

    ⚠ 不许另写一套 IC（§11.5-112）：仓库的 IC 口径已在参数研究里定稿（样本 <2 / 任一侧常数 ⇒ NaN）。
    """
    import pandas as _pd

    from core.sweep_stats import rank_ic

    r = _as_float_series(ratio)
    fwd = forward_returns(closes, (window,))[int(window)]
    pair = _pd.concat([r, fwd], axis=1).dropna()
    if pair.shape[0] < 2:
        return float('nan')
    return float(rank_ic(pair.iloc[:, 0].to_numpy(), pair.iloc[:, 1].to_numpy()))


def permutation_p(flags, closes, *, window: int = 20, draws: int = 1000,
                  seed: int = PERM_SEED) -> dict:
    """置换检验：把"命中日"随机打乱 `draws` 次，看"条件前向收益 − 基线"这个差**有多大比例能被随机凑出来**。

    :return: `{'observed','p','draws','seed','reason'}`；
      `p = (#{ |随机差| ≥ |实测差| } + 1) / (draws + 1)`（**加一**：draws 次全不超也有下界）。
    【为什么必须有它】多方案 × 多窗口比较极易"刷"出假关系；p 把"巧合"挡在软件里，
      而且**固定 seed ⇒ 可复现**（结论能被复述，这才是这一卡的价值）。
    命中太少（<2）/ 全命中 / 有效点 <10 ⇒ `p = NaN` 并给 `reason`（**不做检验，也不冒充结果**）。
    """
    import numpy as _np

    f = _as_float_series(flags).fillna(0.0)
    fwd = forward_returns(closes, (window,))[int(window)]
    idx = f.index.intersection(fwd.index)
    flags_np = (f.reindex(idx) > 0).to_numpy()
    vals = fwd.reindex(idx).to_numpy(dtype=float)
    ok = _np.isfinite(vals)
    flags_np, vals = flags_np[ok], vals[ok]
    n = int(flags_np.shape[0])
    n_hit = int(flags_np.sum())
    if n < 10 or n_hit < 2 or n_hit >= n:
        return {'observed': float('nan'), 'p': float('nan'), 'draws': 0, 'seed': int(seed),
                'reason': '样本不足（命中太少 / 全命中 / 有效点不足）⇒ 不做置换检验'}
    obs = float(vals[flags_np].mean() - vals.mean())
    rng = _np.random.default_rng(int(seed))
    ge = 0
    for _ in range(int(draws)):
        pick = rng.choice(n, size=n_hit, replace=False)
        if abs(float(vals[pick].mean() - vals.mean())) >= abs(obs):
            ge += 1
    return {'observed': obs, 'p': (ge + 1.0) / (int(draws) + 1.0),
            'draws': int(draws), 'seed': int(seed), 'reason': ''}
