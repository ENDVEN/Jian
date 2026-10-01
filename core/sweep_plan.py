# core/sweep_plan.py
"""
参数稳健性研究（§7-B15）· 网格纯计算（SW-0）。

无 Qt、无 IO、无网络 —— 只吃参数与日期字符串，产出"网格计划"与"区间校验意见"。
UI 在点「▶ 运行」**之前**实时显示组合数 / 预计耗时，并把不合法的研究拦在这里
（方案书 §3 步3/步4、§8-7：超限返回"拒绝 + 降档建议"，绝不硬跑）。

口径（与 docs/JIAN_SWEEP_PLAN.md 同源，改动必须两边同步）：
- 维数 ≤ MAX_DIMS(2)、每维档位 ≤ MAX_LEVELS_PER_DIM(30)、组合 ≤ MAX_COMBOS(2000)。
  ⚠ 2 维 × 30 档 = 900，仍小于 2000 —— MAX_COMBOS 是**第二道保险**
  （放宽维数/档数时它先兜底），不是摆设；冒烟里两道都各有断言（断言读常量，不写死数字）。
- 档位由 (起, 止, 步长) 等差生成并 round 到 6 位小数：0.1+0.2 = 0.30000000000000004
  这类浮点尾巴会让"同一参数"在快照复现 / 缓存键里对不上号。
- 区间校验是纯字符串日期比较（本模块不读盘）：起止有序、样本内终点 < 样本外起点
  （**共一天也算重叠 = 泄漏**）、四条边界落在数据范围内（范围由调用方按标的实测传入）。
- "IS 与 OOS 两段独立回测"的口径见方案书 §7；本模块只负责把不合法的挡在运行之前。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import product

MAX_DIMS = 2               # MVP：热力图 / 邻域都按 ≤2 维设计；>2 维在界面挑 2 维
#: 每维档位上限（★1.66 由 15 放宽到 30 —— 用户："跑回测的电脑正常不会太差"）。
#: 2 维 × 30 档 = 900 组合，仍远小于 `MAX_COMBOS` ⇒ 第二道保险照旧兜底；
#: 耗时按 `estimate_seconds`（900 × 2 段 × 55ms ≈ 99 秒，运行前就写在界面上）。
MAX_LEVELS_PER_DIM = 30
MAX_COMBOS = 2000          # 组合总数上限（第二道保险，见模块 docstring）
REF_BARS = 3000            # 耗时预估的参考 bar 数（方案书 §6 计算预算）
REF_MS_PER_RUN = 55.0      # 同上：单次回测 30–80ms 的中值
RUNS_PER_COMBO = 2         # 每组跑两段：样本内 + 样本外

_DATE_FMT = "%Y-%m-%d"

_INTERVAL_LABELS = {"is_start": "样本内起点", "is_end": "样本内终点",
                    "oos_start": "样本外起点", "oos_end": "样本外终点"}


@dataclass(frozen=True)
class SweepDimension:
    """一维参数的档位集合（values 升序，已 round 防漂移）。"""

    name: str
    values: tuple[float, ...]

    @property
    def n_levels(self) -> int:
        return len(self.values)


@dataclass
class GridPlan:
    """一次参数扫描的网格计划。`rejection` 非空 = 已拒绝（此时 combos 为空）。"""

    dims: tuple[SweepDimension, ...]
    combos: tuple[dict[str, float], ...]
    n_combos: int
    est_seconds: float
    rejection: str = ""

    @property
    def ok(self) -> bool:
        return not self.rejection


def _dim_problem(dim: SweepDimension) -> str:
    """单维合法性检查（build_grid 的唯一闸门用；工厂产出的维也在这里复检）。"""
    if not str(dim.name or "").strip():
        return "参数名不能为空"
    if dim.n_levels < 2:
        return (f"参数「{dim.name}」只落出 {dim.n_levels} 档 ⇒ 步长不小于区间（或起=止）："
                f"这一维相当于固定值，从网格中去掉它（固定为策略保存值）")
    if dim.n_levels > MAX_LEVELS_PER_DIM:
        return (f"参数「{dim.name}」有 {dim.n_levels} 档，超过每维 ≤{MAX_LEVELS_PER_DIM} 档的上限"
                f" ⇒ 加大步长或收窄区间")
    return ""


def make_dimension(name: str, start: float, stop: float, step: float) -> tuple[SweepDimension | None, str]:
    """从 (起, 止, 步长) 造一维档位。成功返回 (维度, "")，失败返回 (None, 拒绝原因 + 建议)。"""
    label = str(name or "").strip()
    if not label:
        return None, "参数名不能为空"
    try:
        a, b, s = float(start), float(stop), float(step)
    except (TypeError, ValueError):
        return None, f"参数「{label}」的起止/步长必须是数字"
    if not (a == a and b == b and s == s) or a in (float("inf"), float("-inf")) or b in (float("inf"), float("-inf")):
        return None, f"参数「{label}」的起止/步长不能是无穷或空值"
    if s <= 0:
        return None, f"参数「{label}」的步长必须大于 0"
    if b < a:
        return None, f"参数「{label}」的起点必须 ≤ 终点（反了就自己调换着填，不替你猜）"
    n = int((b - a) / s + 1e-9) + 1
    if n < 2:
        return None, (f"参数「{label}」只落出 1 档 ⇒ 步长不小于区间（或起=止）："
                      f"这一维相当于固定值，从网格中去掉它（固定为策略保存值）")
    if n > MAX_LEVELS_PER_DIM:
        suggested = (b - a) / (MAX_LEVELS_PER_DIM - 1)
        return None, (f"参数「{label}」会落出 {n} 档，超过每维 ≤{MAX_LEVELS_PER_DIM} 档的上限"
                      f" ⇒ 把步长加大到 ≥{suggested:.6g}（或收窄区间）")
    values = tuple(round(a + k * s, 6) for k in range(n))
    # 1e-9 容差只是用来数档位；真超终点的尾巴丢弃（防 (b-a)/s 有余数时多算一格）
    values = tuple(v for v in values if v <= b + 1e-9)
    return SweepDimension(label, values), ""


def estimate_seconds(n_combos: int, n_bars: int = REF_BARS, per_run_ms: float | None = None) -> float:
    """预计耗时（秒）= 组数 × 每组 RUNS_PER_COMBO 段 × 单段毫秒。

    单段毫秒默认按方案书 §6 的量级（3000 根日线 ≈55ms）随 bar 数线性缩放；
    实测后可由调用方传入 per_run_ms 校准，口径仍以本函数为唯一出口。
    """
    per = per_run_ms if per_run_ms is not None else REF_MS_PER_RUN * max(int(n_bars), 1) / REF_BARS
    return int(n_combos) * RUNS_PER_COMBO * per / 1000.0


def build_grid(dims: tuple[SweepDimension, ...], n_bars: int = REF_BARS) -> GridPlan:
    """生成网格计划。**这是运行前的唯一闸门**：任何超限都返回"拒绝 + 建议"，不产出组合。"""
    dims = tuple(dims)
    if len(dims) == 0:
        return GridPlan(dims, (), 0, 0.0, rejection="至少要有一维参数进网格 ⇒ 不带参数的配方没有可扫的东西")
    if len(dims) > MAX_DIMS:
        return GridPlan(dims, (), 0, 0.0,
                        rejection=f"一次最多扫 {MAX_DIMS} 维（热力图与邻域都按 {MAX_DIMS} 维设计）"
                                  f" ⇒ 挑 {MAX_DIMS} 维进网格，其余参数固定为策略保存值")
    for d in dims:
        problem = _dim_problem(d)
        if problem:
            return GridPlan(dims, (), 0, 0.0, rejection=problem)
    # ★R4 血案（真机探针实测）：**两维选了同一个参数** ⇒ 组合字典的两个键同名、
    #   25 格折叠成 5 格 ⇒ 矩阵（按组合）与网格（按格子）**对不上** ⇒ 统计装配必失败。
    #   这不是"用户手滑"，是闸门该拦的事（§8-7：超限/无意义一律拒绝 + 说清怎么改）。
    names = [d.name for d in dims]
    if len(set(names)) != len(names):
        return GridPlan(dims, (), 0, 0.0,
                        rejection="两维选了**同一个参数**（同一参数不能在两个方向上各变一遍）"
                                  " ⇒ 把第 2 维换成另一个参数，或选「（第 2 维不用）」")
    combos = tuple(dict(zip((d.name for d in dims), values))
                   for values in product(*(d.values for d in dims)))
    if len(combos) > MAX_COMBOS:
        return GridPlan(dims, (), 0, 0.0,
                        rejection=f"组合数 {len(combos)} 超过上限 {MAX_COMBOS} ⇒ 加大步长或减少维数")
    est = estimate_seconds(len(combos), n_bars=n_bars)
    return GridPlan(dims, combos, len(combos), est)


def neighborhood_indices(dims: tuple[SweepDimension, ...]) -> tuple[tuple[int, ...], ...]:
    """每个组合的邻域（**含自身**）：沿每一维 ±1 档、边界取存在者。

    返回表与 build_grid 的 combos **同序** —— sweep_stats 的邻域统计按这张表取邻居。
    方案书 §2 的"3×3 共 9 格"：2 维 = 9 格（角 4 / 边 6 / 心 9）；1 维 = 3 格（端 2 / 中 3）。
    """
    counts = [d.n_levels for d in dims]
    if not counts:
        return ()
    # combos 序 = itertools.product 序（末维变化最快）⇒ 组合索引 = Σ pos[k]·stride[k]
    strides = [1] * len(counts)
    for k in range(len(counts) - 2, -1, -1):
        strides[k] = strides[k + 1] * counts[k + 1]
    table = []
    for pos in product(*(range(n) for n in counts)):
        options = [range(max(0, p - 1), min(n - 1, p + 1) + 1)
                   for p, n in zip(pos, counts)]
        table.append(tuple(sum(p * s for p, s in zip(cell, strides))
                           for cell in product(*options)))
    return tuple(table)


@dataclass(frozen=True)
class StudyInterval:
    """一次研究的样本内 / 样本外区间（'YYYY-MM-DD' 字符串，与引擎口径一致）。

    ★R7 **合并区间**（用户 2026-10-01 拍板）：`more` = 其余**窗口对**（每项
    `(内起, 内止, 外起, 外止)`，时间升序）。非空 ⇒ 本次研究是"合并研究"：
    逐对窗口**各自独立回测**（每段从空仓开始 ⇒ **段与段之间没有持仓**），
    再把逐日收益**按日期拼接**成一条序列 —— 统计（年化 / Rank IC / PBO）都在这条
    拼接序列上算（用户已批口径；⚠ PBO 的 CSCV 分段会被窗口边界切断，读 PBO 时记住这点）。
    四格 `is_*` / `oos_*` 始终 = **第一对**窗口（校验/引擎都按逐对来，不用包络）。
    """

    is_start: str
    is_end: str
    oos_start: str
    oos_end: str
    more: tuple[tuple[str, str, str, str], ...] = ()

    @property
    def merge_count(self) -> int:
        """窗口对数（1 = 常规单窗口研究）。"""
        return 1 + len(self.more)

    def pairs(self) -> tuple[tuple[str, str, str, str], ...]:
        """全部窗口对（第一对在前；时间升序由调用方保证）。"""
        return ((self.is_start, self.is_end, self.oos_start, self.oos_end), *self.more)

    def span(self) -> tuple[str, str]:
        """**包络**（首对内起 → 末对外止）—— 只给界面显示用，绝不拿去回测或校验。"""
        ps = self.pairs()
        return (min(p[0] for p in ps), max(p[3] for p in ps))


def validate_interval(iv: StudyInterval,
                      data_start: str = "", data_end: str = "") -> tuple[str, ...]:
    """校验一次研究区间；返回**问题清单**（空元组 = 通过）。

    三条铁规矩（方案书 §3 步4 / §8）：
    ① 起止有序（起点 ≤ 终点）；
    ② 样本内终点 < 样本外起点 —— **共一天也算重叠 = 泄漏**；
    ③ 四条边界落在数据范围内（范围由调用方按标的实测传入，本模块不读盘）。
    """
    more = tuple(getattr(iv, "more", ()) or ())
    if more:
        # ★R7：合并研究 ⇒ **逐对窗口各自校验**（不能拿包络校验：牛→熊 的多对窗口里，
        #   第 2 对的样本内起点晚于第 1 对的样本外终点是**正常**的）。
        problems: list[str] = []
        for i, w in enumerate(iv.pairs(), 1):
            for p in validate_interval(StudyInterval(*w), data_start, data_end):
                problems.append(f"第 {i} 对窗口：{p}")
        # 另外：**同类窗口之间不许重叠**（重叠 = 同一段被算两遍，收益被重复计入）
        ps = iv.pairs()
        for i, a in enumerate(ps):
            for j, b in enumerate(ps[i + 1:], i + 2):
                for (x0, x1), (y0, y1), tag in (((a[0], a[1]), (b[0], b[1]), "样本内"),
                                                ((a[2], a[3]), (b[2], b[3]), "样本外")):
                    if str(x0) <= str(y1) and str(y0) <= str(x1):
                        problems.append(f"第 {i + 1} 对与第 {j} 对在{tag}上时间重叠"
                                        "（同一段会被算两遍，收益重复计入）")
        return tuple(problems)
    problems: list[str] = []
    dates: dict[str, object] = {}
    for key in _INTERVAL_LABELS:
        raw = str(getattr(iv, key, "") or "").strip()
        try:
            dates[key] = datetime.strptime(raw, _DATE_FMT).date()
        except ValueError:
            problems.append(f"{_INTERVAL_LABELS[key]}「{raw}」不是 YYYY-MM-DD 日期")
    if len(dates) < len(_INTERVAL_LABELS):
        return tuple(problems)          # 日期残缺，后续比较没有意义
    if dates["is_start"] > dates["is_end"]:
        problems.append("样本内起点晚于终点 ⇒ 先把区间理顺")
    if dates["oos_start"] > dates["oos_end"]:
        problems.append("样本外起点晚于终点 ⇒ 先把区间理顺")
    if dates["is_end"] >= dates["oos_start"]:
        problems.append("样本内与样本外重叠（重叠 = 泄漏）⇒ 把样本外起点推迟到样本内终点之后")

    def _bound(raw: str) -> object:
        try:
            return datetime.strptime(str(raw or "").strip(), _DATE_FMT).date()
        except ValueError:
            return None

    lo, hi = _bound(data_start), _bound(data_end)
    if lo is not None:
        if dates["is_start"] < lo:
            problems.append(f"样本内起点早于本地数据最早日（{data_start}）⇒ 起点推后")
        if dates["oos_start"] < lo:
            problems.append(f"样本外起点早于本地数据最早日（{data_start}）⇒ 起点推后")
    if hi is not None:
        if dates["is_end"] > hi:
            problems.append(f"样本内终点晚于本地数据最新日（{data_end}）⇒ 终点提前")
        if dates["oos_end"] > hi:
            problems.append(f"样本外终点晚于本地数据最新日（{data_end}）⇒ 终点提前")
    return tuple(problems)
