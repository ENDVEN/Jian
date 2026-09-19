# ui/widgets/annotation_layouts.py
"""画线类型的**落点 / 回读 / 规范化**（v6.29 · §4 体积铁律的拆分，非新能力）。

【为什么单独一个文件】
  `annotation_shapes.py`（规格表）在 v6.28 之后冲到 700+ 行 —— §4 的处置写得很明确：
  **把 `place_*` 与 `read_*` 拆出来**。本文件就是那两族 + 三个"纯数据"的上下文对象：
  · `DrawCtx`  —— 画一条标注需要的全部上下文（交互层准备，规格表与派生画法消费）
  · `PlaceCtx` —— "默认落在哪"需要的可视区间与日期轴
  · `read_*`   —— 拖动松手后：图元 → `[[日期, 价], ...]`（**坐标一律经 `DateAxis` 换成日期**）
  · `place_*`  —— 新建时的默认锚点（`create_default` 老路径；用户点出来的主路径在绘制会话）
  · `reg_*`    —— 回归通道独有的"算出来的几何"（拟合 / 夹边界 / 规范化 / 贴回）

【铁律】
  · 本文件**只做坐标换算与算术**：不碰存储、不碰交互状态、不 import `annotation_shapes`
    （否则成环 —— 规格表反过来要用这里的东西）。
  · 回读的"取整 / 夹边界"口径必须与 `place_*`、`normalize` **完全一致**，
    否则会出现"存进去的价 ≠ 按存储重算的价"（§11.5-53）。
"""
from __future__ import annotations

from dataclasses import dataclass

from data.annotations import DateAxis, regression_channel


# ==========================================
# 上下文
# ==========================================
@dataclass
class DrawCtx:
    """画一条标注需要的全部上下文（**交互层只准备这些，不认识任何具体画法**）。"""

    kind: str
    item: dict                 # 存储里的标注对象（points 已是"日期 + 价格"）
    color: str
    axis: DateAxis             # 日期 ↔ bar 序号
    view_box: object           # pyqtgraph ViewBox（场景坐标 ↔ 数据坐标）
    size: int                  # 数据根数（射线/周期线要"延伸到数据末尾"）
    pen: object                # callable(color, selected, dashed) -> QPen
    on_change: object          # callable() —— 拖动**松手**后落盘（+ 需要时重建附属图元）
    on_persist: object         # callable() —— 只落盘、**不重建**（给"可拖动的附属图元"用，见 `deco_cross`）
    on_select: object          # callable() —— 点中图元
    closes: object = None      # 收盘价序列（**只有回归通道用**；页面 `bind()` 喂进来，与 §7-B6 STEP 5
                               #  "读数条只认本次渲染的那份 df"同一条纪律，不加第二条数据链路）


@dataclass
class PlaceCtx:
    """新建标注时的默认落点：当前可视区间 + 日期轴（用户随后拖动微调）。"""

    axis: DateAxis
    x0: float
    x1: float
    y0: float
    y1: float
    size: int
    closes: object = None     # 收盘价序列（**只有回归通道的默认落点要用**：
                              # 有它才能把默认三点落在"真实回归通道"上，§7-B9 STEP 4 同一份数据）

    @property
    def mid_y(self) -> float:
        value = (self.y0 + self.y1) / 2.0
        return value if value else 1.0

    def date_at(self, fraction: float) -> str:
        return self.axis.index_to_date(self.x0 + (self.x1 - self.x0) * fraction)

    def price_at(self, fraction: float) -> float:
        return self.y0 + (self.y1 - self.y0) * fraction


# ==========================================
# 回读坐标（拖动松手后 → 存回"日期 + 价格"）
# ==========================================
def read_handles(ctx: DrawCtx, primary, extras, indexes) -> list | None:
    """ROI 手柄（场景坐标）→ 数据坐标 → 日期。"""
    positions = [position for _handle, position in primary.getSceneHandlePositions()]
    if len(positions) <= max(indexes):
        return None
    out = []
    for index in indexes:
        view = ctx.view_box.mapSceneToView(positions[index])
        date_label = ctx.axis.index_to_date(view.x())
        if not date_label:
            return None
        out.append([date_label, float(view.y())])
    return out


def read_roi(ctx: DrawCtx, primary, extras) -> list | None:
    count = len(primary.getSceneHandlePositions())
    return read_handles(ctx, primary, extras, tuple(range(count)))


def read_channel(ctx: DrawCtx, primary, extras) -> list | None:
    """平行通道：p1/p2 = 基线两端（ROI 手柄），p3 = **宽度手柄当前的价位**。

    ⚠ p3 只取"价位"，日期跟着 p1 —— 宽度本来就是一个**竖直偏移**，没有日期含义。
    """
    pts = read_handles(ctx, primary, extras, (0, 1))
    if not pts or len(pts) < 2:
        return None
    stored = ctx.item.get("points") or []
    old_dy = (float(stored[2][1]) - float(stored[0][1])) if len(stored) >= 3 else 0.0
    old_handle_y = float(stored[2][1]) if len(stored) >= 3 else None
    handle = next((extra for extra in extras or []
                   if getattr(extra, "_role", "") == "width"), None)
    if handle is None:
        price = pts[0][1] + old_dy
    else:
        current = float(handle.pos().y())
        # ⚠ 判据："手柄有没有被动过" —— 手柄没动 ⇒ **宽度点随基线平移**（间距不变，
        # 这才是"平行通道"）；手柄被拖了 ⇒ 用新价位（只有宽度变）。
        price = pts[0][1] + old_dy if (old_handle_y is not None
                                       and abs(current - old_handle_y) < 1e-9) else current
    return [pts[0], pts[1], [pts[0][0], price]]


def read_box(ctx: DrawCtx, primary, extras) -> list | None:
    """矩形 / 椭圆：存外接矩形的两角点。"""
    pos, size = primary.pos(), primary.size()
    x0, y0 = float(pos.x()), float(pos.y())
    x1, y1 = x0 + float(size.x()), y0 + float(size.y())
    return [[ctx.axis.index_to_date(x0), y0], [ctx.axis.index_to_date(x1), y1]]


def read_hray(ctx: DrawCtx, primary, extras) -> list | None:
    """水平射线：**强制同价**（用户把某一端拖斜了也不存斜的 —— 它叫"水平"射线）。"""
    pts = read_roi(ctx, primary, extras)
    if not pts or len(pts) < 2:
        return None
    return [[pts[0][0], pts[0][1]], [pts[1][0], pts[0][1]]]


def read_band(ctx: DrawCtx, primary, extras) -> list | None:
    """价格带：只有**价位**有意义（横向贯穿全图），日期沿用创建时的锚点。"""
    low, high = primary.getRegion()
    stored = ctx.item.get("points") or []
    first = stored[0][0] if stored else ""
    second = stored[1][0] if len(stored) > 1 else first
    return [[first, float(low)], [second, float(high)]]


def read_span(ctx: DrawCtx, primary, extras) -> list | None:
    """时间区间：只有**日期**有意义（竖向贯穿全图），价位沿用创建时的锚点。"""
    low, high = primary.getRegion()
    stored = ctx.item.get("points") or []
    first = stored[0][1] if stored else 0.0
    second = stored[1][1] if len(stored) > 1 else first
    return [[ctx.axis.index_to_date(low), first],
            [ctx.axis.index_to_date(high), second]]


def read_cross(ctx: DrawCtx, primary, extras) -> list | None:
    """交叉线：主图元是水平线（价），附属图元是垂直线（日期）。"""
    if not extras:
        return None
    date_label = ctx.axis.index_to_date(extras[0].value())
    if not date_label:
        return None
    return [[date_label, float(primary.value())]]


def read_text(ctx: DrawCtx, primary, extras) -> list | None:
    """文字类：自由摆放（拖到哪就存哪，不锁在原来的日期上）。"""
    position = primary.pos()
    date_label = ctx.axis.index_to_date(position.x())
    if not date_label:
        return None
    return [[date_label, float(position.y())]]


def read_infinite(ctx: DrawCtx, primary, extras) -> list | None:
    """水平线 / 垂直线：只有一个值有意义，另一个沿用存储。"""
    stored = ctx.item.get("points") or [["", 0.0]]
    anchor = stored[0]
    if ctx.kind == "vline":
        date_label = ctx.axis.index_to_date(primary.value())
        if not date_label:
            return None
        return [[date_label, float(anchor[1])]]
    return [[anchor[0], float(primary.value())]]


# ==========================================
# 回归通道：由**收盘价算出来**的那部分几何（§11.5-53）
# ==========================================
def reg_clamp(ctx: DrawCtx, x: float) -> float:
    """把 bar 序号夹进**有数据的范围**。

    ⚠ 用户完全可能把手柄拖到窗口外（甚至负数）—— 回归本身只能在有数据的范围内做，
    而 `regression_channel` 内部会**静默夹住**区间；如果不在这里先夹，`reg_price`
    就会按**没夹过的 x0** 去外推 ⇒ 存进去一个离谱的价格（实测 102 → 76.8，§11.5-53）。
    """
    return float(min(max(float(x), 0.0), float(max(ctx.size - 1, 0))))


def fit_from_x(ctx: DrawCtx, x0: float, x1: float):
    """按 bar 区间做最小二乘（回归通道唯一的拟合入口，读/画/贴回都用它）。

    数据源 = `ctx.closes`（页面 `bind()` 喂进来的那一份，不另开数据链路）。
    ⚠ 调用方先把 x 交给 `reg_clamp`（本函数不替调用方决定"夹不夹"，免得两处口径）。
    """
    return regression_channel(getattr(ctx, "closes", None), x0, x1)


def reg_price(fit, x: float, x0: float) -> float:
    """回归中线在 bar 序号 `x` 处的拟合价（`start` 是区间起点 `x0` 处的拟合值）。"""
    return float(fit["start"]) + float(fit["slope"]) * (float(x) - float(x0))


def xy_point(ctx: DrawCtx, point):
    """`[日期, 价]` → `(bar 序号, 价)`；日期不在轴内 / 价不是数 → None（本点不参与）。"""
    try:
        date_label, price = point
    except (TypeError, ValueError):
        return None
    index = ctx.axis.date_to_index(date_label)
    if index is None:
        return None
    try:
        return (float(index), float(price))
    except (TypeError, ValueError):
        return None


def reg_fit(ctx: DrawCtx):
    """回归通道的拟合（区间取**前两个锚点**的 bar 序号）。

    :return: `(fit, x0, x1)`；数据不够 / 没有收盘价 → None（不画，也不编）。
    """
    pts = [xy_point(ctx, point) for point in (ctx.item.get("points") or [])]
    pts = [point for point in pts if point is not None]
    if len(pts) < 2:
        return None
    x0 = reg_clamp(ctx, min(pts[0][0], pts[1][0]))
    x1 = reg_clamp(ctx, max(pts[0][0], pts[1][0]))
    fit = fit_from_x(ctx, x0, x1)
    return (fit, x0, x1) if fit else None


def normalize_reg_channel(ctx: DrawCtx, points) -> list | None:
    """把用户点出来的三点规范化成**存储口径**（落库前调用，纯计算、不碰图元）。

    p1/p2 的**价取拟合值**（中线是算出来的，用户点的价只用来定拟合区间）；
    p3 原样保留（它就是"通道区间点"：到中线的距离 = 带宽）。
    ⇒ 这样"存储里的锚点"和"图上画的线"从第一帧起就一致
    （用户原话："点击的起点和终点并不对应通道线该有的地方"）。
    """
    pts = [xy_point(ctx, point) for point in (points or [])]
    pts = [p for p in pts if p is not None]
    if len(pts) < 2:
        return None
    x0 = reg_clamp(ctx, round(pts[0][0]))
    x1 = reg_clamp(ctx, round(pts[1][0]))
    x0, x1 = min(x0, x1), max(x0, x1)
    fit = fit_from_x(ctx, x0, x1)
    first = ctx.axis.index_to_date(x0)
    second = ctx.axis.index_to_date(x1)
    if not fit or not first or not second:
        return None
    band_point = ([str(points[2][0]), float(points[2][1])] if len(points) >= 3
                  else [second, reg_price(fit, x1, x0) + float(fit["band"])])
    return [[first, reg_price(fit, x0, x0)], [second, reg_price(fit, x1, x0)], band_point]


def reshape_reg_channel(ctx: DrawCtx, primary) -> None:
    """★v6.29：**把中线重新贴回回归结果**（用户拍板："调整后整个通道要跟着变"）。

    为什么必须单独有这一步：主图元是"算出来的中线"，可用户拖手柄时会把它拖到别处；
    只重建附属图元就会出现 **"中线在 A、上下轨在 B"** 的分裂 —— 用户原话
    "一旦调整回归通道线之后整个通道也并不会进行相对应的调整"。
    这里按新区间重算回归，再把**主图元自己的两个手柄**挪到拟合线上
    （`movePoint(..., finish=False)`：不许再触发一次"拖动结束"，否则死循环）。
    """
    found = reg_fit(ctx)
    if not found:
        return
    fit, x0, x1 = found
    handles = primary.getHandles()
    if len(handles) < 2:
        return
    for handle, x in zip(handles, (x0, x1)):
        primary.movePoint(handle, (x, reg_price(fit, x, x0)), finish=False)


def read_reg_channel(ctx: DrawCtx, primary, extras) -> list | None:
    """回归通道：p1/p2 = 拟合区间两端，p3 = **通道区间点（宽度手柄）**。

    ⚠ 语义定死（§11.5-53）：**p3 就是"你希望某条轨经过的那个价位"**，p3 到中线的
    距离 = 上下轨带宽（`deco` 画成以中线对称的 ±band）。拖动起点/终点**只改拟合区间**，
    p3 原地不动 ⇒ 轨道依然经过你给的那个点（可预期，不会"越调越跑"）。
    ⚠ p1/p2 的 **y 一律取拟合值**（不取手柄当前 y）：中线是"算出来的"，
    存进去的必须等于 `reshape` 之后图上的位置，否则"存储 ↔ 画面"当场分裂。
    """
    positions = [position for _handle, position in primary.getSceneHandlePositions()]
    if len(positions) < 2:
        return None
    views = [ctx.view_box.mapSceneToView(position) for position in positions]
    # ⚠ 一律**取整到 bar 序号 + 夹进数据范围**再拟合：
    #   ① 存储里只有"日期"，小数 bar 序号取整之后拟合区间就变了 ⇒ 存进去的价格与
    #      "按存储重算"的价格对不上（存储 ↔ 画面分裂）；
    #   ② 手柄可以被拖到窗口外，区间不夹住就会外推出离谱价格（§11.5-53）。
    #   回归本来也是"按每根 bar 的收盘价"做的，取整+夹住不是将就，是本来就该这样。
    x0, x1 = sorted((reg_clamp(ctx, round(views[0].x())),
                     reg_clamp(ctx, round(views[1].x()))))
    fit = fit_from_x(ctx, x0, x1)
    if not fit:
        return None
    first = ctx.axis.index_to_date(x0)
    second = ctx.axis.index_to_date(x1)
    if not first or not second:
        return None
    stored = ctx.item.get("points") or []
    handle = next((extra for extra in extras or []
                   if getattr(extra, "_role", "") == "width"), None)
    band_point = None
    if handle is not None:
        view = ctx.view_box.mapSceneToView(handle.scenePos())
        date_label = ctx.axis.index_to_date(view.x())
        band_point = [date_label, float(view.y())] if date_label else None
    if band_point is None:              # 没有宽度手柄（极端情况）⇒ 保留原来的带宽点
        band_point = ([str(stored[2][0]), float(stored[2][1])] if len(stored) >= 3
                      else [second, reg_price(fit, x1, x0) + float(fit["band"])])
    return [[first, reg_price(fit, x0, x0)], [second, reg_price(fit, x1, x0)],
            band_point]


def _xy_point(ctx: DrawCtx, point):
    """`[日期, 价]` → `(bar 序号, 价)`；日期不在轴内 / 价不是数 → None（本点不参与）。"""
    try:
        date_label, price = point
    except (TypeError, ValueError):
        return None
    index = ctx.axis.date_to_index(date_label)
    if index is None:
        return None
    try:
        return (float(index), float(price))
    except (TypeError, ValueError):
        return None


# ==========================================
# 新建时的默认落点（用户随后拖）
# ==========================================
def place_one(ctx: PlaceCtx) -> list:
    """单点类型的默认落点。

    ⚠ 用 **0.65 倍可视宽度**而不是"最右边一根"：文字类标注的锚点在左侧、文字向右排，
    落在最后一根上会**被图表右边缘裁掉**（看着像"没画出来"）。
    """
    return [[ctx.date_at(0.65), ctx.mid_y]]


def place_pair(ctx: PlaceCtx, f0: float = 0.2, f1: float = 0.8) -> list:
    return [[ctx.date_at(f0), ctx.mid_y], [ctx.date_at(f1), ctx.mid_y]]


def place_extremes(ctx: PlaceCtx) -> list:
    """斐波 / 百分比线：默认"可视区间的高点 → 低点"（用户拖两个手柄调成真实波段）。"""
    return [[ctx.date_at(0.0), ctx.y1], [ctx.date_at(1.0), ctx.y0]]


def place_span(ctx: PlaceCtx) -> list:
    return place_pair(ctx, 0.2, 0.6)


def place_band(ctx: PlaceCtx) -> list:
    """价格带 / 价格测量：同一天、上下两条价位。"""
    date_label = ctx.date_at(0.75)
    return [[date_label, ctx.price_at(0.35)], [date_label, ctx.price_at(0.65)]]


def place_box(ctx: PlaceCtx) -> list:
    return [[ctx.date_at(0.25), ctx.price_at(0.30)], [ctx.date_at(0.70), ctx.price_at(0.70)]]


def place_triangle(ctx: PlaceCtx) -> list:
    return [[ctx.date_at(0.25), ctx.price_at(0.30)],
            [ctx.date_at(0.55), ctx.price_at(0.78)],
            [ctx.date_at(0.85), ctx.price_at(0.30)]]


def place_channel(ctx: PlaceCtx) -> list:
    """平行通道：基线两端 + 一个"宽度点"（默认约 1/5 屏高）。"""
    return [[ctx.date_at(0.20), ctx.price_at(0.40)],
            [ctx.date_at(0.75), ctx.price_at(0.40)],
            [ctx.date_at(0.20), ctx.price_at(0.62)]]


def place_ray(ctx: PlaceCtx) -> list:
    return place_pair(ctx, 0.20, 0.55)


def place_hray(ctx: PlaceCtx) -> list:
    """水平射线：起点在可视区左侧，终点顶到**最后一根**（这就是"射线"的落法）。"""
    return [[ctx.date_at(0.20), ctx.mid_y],
            [ctx.axis.index_to_date(max(ctx.size - 1, 0)), ctx.mid_y]]


def place_measure(ctx: PlaceCtx) -> list:
    return [[ctx.date_at(0.25), ctx.price_at(0.35)], [ctx.date_at(0.70), ctx.price_at(0.65)]]


def place_wave(ctx: PlaceCtx) -> list:
    """波浪（降级版）：默认给 5 个高低交错的拐点（用户随后逐个拖到自己认定的浪型上）。"""
    return [[ctx.date_at(fraction), ctx.price_at(0.32 if index % 2 == 0 else 0.72)]
            for index, fraction in enumerate((0.15, 0.30, 0.45, 0.60, 0.75))]


def place_reg_channel(ctx: PlaceCtx) -> list:
    """回归通道的默认三点：区间（可视区 20%~80%）+ 通道区间点（落在自动 ±2σ 上）。

    ⚠ 有收盘价就按**真实回归**落点 —— 这样"默认画出来"正好贴在通道上
    （`create_default` 这条老路径与"用户点三点"的落点语义一致）；没有收盘价才退化成屏高的一小段。
    """
    # ⚠ 取整到 bar 序号（与 `read_reg_channel` 同一条口径）：不取整 ⇒ 存进去的价格
    #   与"按存储重算"的价格对不上（回归本来就是按每根 bar 的收盘价做的）。
    x0 = float(round(ctx.x0 + (ctx.x1 - ctx.x0) * 0.2))
    x1 = float(round(ctx.x0 + (ctx.x1 - ctx.x0) * 0.8))
    date0 = ctx.axis.index_to_date(x0)
    date1 = ctx.axis.index_to_date(x1)
    fit = fit_from_x(ctx, x0, x1)
    if not fit or not date0 or not date1:
        floor = max((ctx.y1 - ctx.y0) * 0.1, 1e-6)
        return [[ctx.date_at(0.2), ctx.mid_y], [ctx.date_at(0.8), ctx.mid_y],
                [ctx.date_at(0.8), ctx.mid_y + floor]]
    # ⚠ σ 可能真的是 0（这段几乎是一条直线）⇒ 通道会退化成"一条线"（看不见也拖不到）。
    #   这里只给**默认手柄位置**兜一个 5% 屏高（不是编造数据：σ 的真值照样由回归算，标签照实写）。
    band = max(float(fit["band"]), (ctx.y1 - ctx.y0) * 0.05)
    return [[date0, reg_price(fit, x0, x0)],
            [date1, reg_price(fit, x1, x0)],
            [date1, reg_price(fit, x1, x0) + band]]


def place_fan(ctx: PlaceCtx) -> list:
    """甘氏扇形：起点 + 一条**温和向上**的参考线（这条线就是 1×1）。

    ⚠ 默认必须"看得见、拖得动"：所以参考线放在可视区间内、斜率取屏高的 1/4 左右，
    用户嫌它太陡/太缓，直接拖第二点即可（这就是"可调整"的入口）。
    """
    return [[ctx.date_at(0.25), ctx.price_at(0.5)],
            [ctx.date_at(0.65), ctx.price_at(0.75)]]


def place_head_shoulder(ctx: PlaceCtx) -> list:
    """头肩（降级版）：左肩 → 头（更高）→ 右肩。"""
    return [[ctx.date_at(0.25), ctx.price_at(0.55)],
            [ctx.date_at(0.50), ctx.price_at(0.85)],
            [ctx.date_at(0.75), ctx.price_at(0.55)]]
