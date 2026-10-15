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
    'GateDecision', 'hit_day_stats', 'independent_event_positions',
    'gate_decision', 'clamp_thresholds', 'thresholds_from_prefs',
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
