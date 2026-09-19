# ui/widgets/annotation_shapes.py
"""画线类型的**图元规格表**（v6.25 · §7-B8 R11「30+ 类型」落地）。

【为什么要有这个文件】
  目录里 32 种画线类型，v6.24 只实现了 5 种（其余标「待实现」）。剩下 22 种如果
  直接塞进 `annotation_layer.py`，那个文件必然越过 400 线（§4 体积铁律），而且
  "加一种类型要动三处"（画法 / 拖完回读坐标 / 新建时默认落在哪）—— 典型的
  §11.5-11「改一处漏一处」。所以按**一种类型一个规格**收口成本文件：

      `ShapeSpec` = ① 要几个锚点 ② 怎么画（主图元 + 附属图元）③ 拖完怎么读回坐标
                    ④ 新建时默认落在哪 ⑤ 拖动后要不要重建附属图元

  ⇒ `annotation_layer.py` 从此**不认识任何具体画法**（加类型不改交互层）；
    与类型无关的图元小件在 `annotation_items.py`、由主图元派生的**附属图元**
    （档位 / 标签 / 箭头头）在 `annotation_decos.py`、
    **落点 / 回读 / 规范化**在 `annotation_layouts.py`（v6.29 按 §4 处置拆出去的）。
    本文件只剩"注册 + 主图元怎么造"。

【三条铁律（与 `annotation_layer` 的契约）】
  · **主图元必须可点选**：选中是"逐个独立删除"的前提（管线 B 的硬要求，§7-B3 C）；
  · **附属图元必须登记成 extras**：随主图元一起删，否则留下"没人管的线"（§11.5-15）；
  · **坐标一律经 `DateAxis` 换成日期**：绝不存 bar 序号（§11.5-18 防漂移）。

【零业务依赖】本文件只认识 pyqtgraph 与 `data.annotations` 的语义常量，
不读行情、不碰存储 —— 交互层（`annotation_layer`）负责存与删。
"""
from __future__ import annotations

from dataclasses import dataclass

import pyqtgraph as pg

from data.annotations import glyph_of
from ui.widgets import annotation_decos as decos
from ui.widgets.annotation_items import (_ClickableText, _RegionBand, connect, highlight,
                                         infinite, points_to_xy)
# ★v6.29（§4 处置）：上下文对象 + 落点 + 回读 + 回归几何统一搬进 `annotation_layouts`。
#   ⚠ 这几个名字**历史上在本文件定义**（交互层/冒烟仍从 `shapes` 取，如
#     `shapes.PlaceCtx` / `shapes.DrawCtx`）⇒ 这里**再导出**一份（§11.7：公共面不改名）。
from ui.widgets.annotation_layouts import (DrawCtx, PlaceCtx,  # noqa: F401
                                           fit_from_x, normalize_reg_channel, place_band,
                                           place_box, place_channel, place_extremes,
                                           place_fan, place_hray, place_head_shoulder,
                                           place_measure, place_one, place_pair,
                                           place_ray, place_reg_channel, place_span,
                                           place_triangle, place_wave, read_band, read_box,
                                           read_channel, read_cross, read_hray,
                                           read_infinite, read_reg_channel, read_roi,
                                           read_span, read_text, reg_clamp, reg_fit,
                                           reg_price, reshape_reg_channel)
# 本文件内部的旧名（`_xy` / `_connect` / `_infinite`）保留为别名 —— 实现统一在 items
_xy = points_to_xy
_connect = connect
_infinite = infinite


# ==========================================
# 内部工具：主图元（**能拖能选的那一个**）
# ==========================================
def _roi_pts(ctx: DrawCtx, pts, *, dashed: bool = False):
    """两点线段 ROI（趋势线 / 斐波 / 测量 / 价格测量… 的主图元，两端可拖）。"""
    graphic = pg.LineSegmentROI([[x, y] for x, y in pts],
                                pen=ctx.pen(ctx.color, False, dashed))
    _connect(graphic, ctx)
    return graphic


def _poly_pts(ctx: DrawCtx, pts, *, closed: bool = False, dashed: bool = False):
    """多点折线 ROI（三角形 / 平行通道 / 水平射线的主图元，每个顶点都能拖）。"""
    graphic = pg.PolyLineROI([[x, y] for x, y in pts], closed=closed,
                             pen=ctx.pen(ctx.color, False, dashed))
    _connect(graphic, ctx)
    return graphic


def _box(ctx: DrawCtx, pts, factory):
    """矩形 / 椭圆：两角点 → `factory(pos, size)`（size 必须为正，否则 ROI 会反向）。"""
    (x0, y0), (x1, y1) = pts[0], pts[1]
    left, right = min(x0, x1), max(x0, x1)
    low, high = min(y0, y1), max(y0, y1)
    graphic = factory((left, low), (max(right - left, 1e-6), max(high - low, 1e-6)),
                      pen=ctx.pen(ctx.color, False, False))
    _connect(graphic, ctx)
    return graphic


def _text(ctx: DrawCtx, text: str, *, anchor=(0.0, 0.5), border=None, fill=None):
    return _ClickableText(text, color=ctx.color, anchor=anchor, border=border, fill=fill,
                          on_click=ctx.on_select, on_moved=ctx.on_change)


# ==========================================
# 规格表（一种类型 = 一行；加类型**只改这里**）
# ==========================================
@dataclass(frozen=True)
class ShapeSpec:
    """一种画线类型的全部画法（①锚点数 ②画法 ③回读 ④默认落点 ⑤是否重建附属图元）。"""

    kind: str
    points: int
    make: object                    # (DrawCtx) -> 主图元 | None
    deco: object = None             # (DrawCtx, 主图元) -> [附属图元]
    read: object = None             # (DrawCtx, 主图元, 附属图元) -> [[日期, 价], ...] | None
    place: object = None            # (PlaceCtx) -> 默认锚点
    view_dependent: bool = False    # 画法**依赖当前视图**（斐波弧）⇒ 缩放要重算
    snap: object = None             # (DrawCtx, 主图元) -> 回正图元（水平射线用）
    normalize: object = None        # (DrawCtx, points) -> points —— **纯计算**地把"用户点出来的
                                    # 锚点"规范成存储口径（回归通道：中线价取拟合值，§11.5-53）
    reshape: object = None          # (DrawCtx, 主图元) -> None —— **主图元本身是算出来的**
                                    # （回归通道的中线由回归结果决定）⇒ 拖动后要把主图元也重贴一遍，
                                    # 否则出现"中线在 A、上下轨在 B"的分裂（§11.5-53）
    label: str = ""
    # ⚠ **没有 `rebuild` 字段**（v6.26 H-7 删掉）：只要有附属图元（`deco`），
    #   拖动后就**必须**重建 —— 文字标注/档位/标签全是锚点的派生物，不跟着动就是 bug
    #   （用户实测"改了点位，文字停原地不动"）。要不要重建由 `deco is not None` 推导，
    #   **不给每种类型自己声明的机会**（声明式字段 = 忘写一个就是一个静默 bug）。


def _make_segment(ctx: DrawCtx, *, dashed: bool = False):
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts or len(pts) < 2 else _roi_pts(ctx, pts, dashed=dashed)


def _make_poly(ctx: DrawCtx, *, closed: bool):
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts or len(pts) < 2 else _poly_pts(ctx, pts, closed=closed)


def _make_channel(ctx: DrawCtx):
    """平行通道的**主图元 = 基线**（两点，两端可拖）。

    ⚠ v6.25 这里给的是"四个可自由拖的角点" ⇒ 拖完就不是平行四边形了（用户实测拍桌）。
    现在基线只管基线，**平行线 / 填充带 / 宽度手柄都在 `deco_channel`**，
    平行性由"整条基线平移同一个 dy"保证 —— 结构上就不可能再拖歪（§7-B9 C3）。
    """
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 3:
        return None
    return _roi_pts(ctx, [pts[0], pts[1]])


def _make_reg_channel(ctx: DrawCtx):
    """回归通道的主图元 = **拟合中线**（两点 = 区间两端，价由回归算出）。

    ⚠ 它是"算出来的主图元"：拖动后用 `reshape_reg_channel`（规格表的 `reshape` 字段）
    把它重新贴回回归结果，否则会出现"中线在 A、上下轨在 B"（§11.5-53）。
    """
    found = reg_fit(ctx)
    if not found:
        return None
    fit, x0, x1 = found
    return _roi_pts(ctx, [(x0, reg_price(fit, x0, x0)), (x1, reg_price(fit, x1, x0))],
                    dashed=True)


def _make_polyline(ctx: DrawCtx):
    """波浪（5 个拐点）—— 一条开放折线。**不做自动识别**（§7-B9 C4）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts or len(pts) < 2 else _poly_pts(ctx, pts, closed=False)


def _make_head_shoulder(ctx: DrawCtx):
    """头肩形态（降级版）= 左肩 / 头 / 右肩 三点折线（颈线在 deco 里近似画出）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 3:
        return None
    return _poly_pts(ctx, [pts[0], pts[1], pts[2]], closed=False)


def _make_rect(ctx: DrawCtx):
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts or len(pts) < 2 else _box(ctx, pts, pg.RectROI)


def _make_ellipse(ctx: DrawCtx):
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts or len(pts) < 2 else _box(ctx, pts, pg.EllipseROI)


def _make_band(ctx: DrawCtx, orientation: str):
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts or len(pts) < 2:
        return None
    if orientation == "horizontal":
        values = [min(pts[0][1], pts[1][1]), max(pts[0][1], pts[1][1])]
    else:
        values = [min(pts[0][0], pts[1][0]), max(pts[0][0], pts[1][0])]
    graphic = _RegionBand(values, orientation, ctx.color)
    _connect(graphic, ctx)
    return graphic


def _make_cross(ctx: DrawCtx):
    """交叉线：主图元 = 水平线（价）；垂直线在 `_deco_cross`（附属但同样可拖）。"""
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts else _infinite(ctx, pts[0][1], 0)


def _make_text(ctx: DrawCtx, *, border=None, fill=None, anchor=(0.0, 0.5)):
    pts = _xy(ctx, ctx.item.get("points"))
    if not pts:
        return None
    text = ctx.item.get("text") or glyph_of(ctx.kind) or "标注"
    graphic = _text(ctx, text, anchor=anchor, border=border, fill=fill)
    graphic.setPos(pts[0][0], pts[0][1])
    return graphic


def _make_comment(ctx: DrawCtx):
    return _make_text(ctx, border=pg.mkPen("#B0BEC5"), fill=pg.mkBrush("#FFFDE7"),
                      anchor=(0.0, 0.5))


def _make_mark(ctx: DrawCtx):
    return _make_text(ctx, anchor=(0.5, 0.5))


def _make_hline(ctx: DrawCtx):
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts else _infinite(ctx, pts[0][1], 0)


def _make_vline(ctx: DrawCtx):
    pts = _xy(ctx, ctx.item.get("points"))
    return None if not pts else _infinite(ctx, pts[0][0], 90)


def _snap_hray(ctx: DrawCtx, primary) -> None:
    """水平射线：把被拖斜的那一端**拉回**同一价位（存的是同价，图上也得是同价）。

    ⚠ 判据必须读**图元当前的手柄**（存进去的值已经被 `read_hray` 归一化了，
    拿它当判据 ⇒ 永远"看起来已经是水平的"，回正就成了摆设 —— §11.5-34 同族坑）。
    ⚠ `finish=False`：回正本身**不该**再触发一次"拖动结束"（否则回正 → 落盘 → 回正…）。
    """
    positions = [position for _handle, position in primary.getSceneHandlePositions()]
    if len(positions) < 2:
        return
    views = [ctx.view_box.mapSceneToView(position) for position in positions]
    price = views[0].y()
    if all(abs(view.y() - price) < 1e-9 for view in views):
        return                      # 已经是水平的 ⇒ 什么都不做（幂等，防回正循环）
    handles = primary.getHandles()
    if len(handles) < 2:
        return
    for index in range(1, len(views)):
        primary.movePoint(handles[index], (views[index].x(), price), finish=False)


SHAPES: dict[str, ShapeSpec] = {
    # ---- 趋势 / 通道 ----
    "trend": ShapeSpec("trend", 2, _make_segment, place=place_pair, read=read_roi,
                       label="两端可拖"),
    "ray": ShapeSpec("ray", 2, _make_segment, deco=decos.deco_ray, read=read_roi,
                     place=place_ray, label="延伸到数据末尾"),
    "channel": ShapeSpec("channel", 3, _make_channel, deco=decos.deco_channel,
                         read=read_channel, place=place_channel,
                         label="拖基线平移、拖 ⇕ 改宽度"),
    # ---- 水平 / 垂直 ----
    "hline": ShapeSpec("hline", 1, _make_hline, place=place_one, read=read_infinite,
                       label="上下拖改价位"),
    "vline": ShapeSpec("vline", 1, _make_vline, place=place_one, read=read_infinite,
                       label="左右拖改日期"),
    "hray": ShapeSpec("hray", 2, lambda ctx: _make_poly(ctx, closed=False),
                      deco=decos.deco_hray, read=read_hray, place=place_hray,
                      snap=_snap_hray, label="从起点向右延伸到未来"),
    "cross": ShapeSpec("cross", 1, _make_cross, deco=decos.deco_cross, read=read_cross,
                       place=place_one, label="横线竖线一起动"),
    "hband": ShapeSpec("hband", 2, lambda ctx: _make_band(ctx, "horizontal"),
                       read=read_band, place=place_band, label="拖上下边改区间"),
    # ---- 形态 ----
    "rect": ShapeSpec("rect", 2, _make_rect, read=read_box, place=place_box,
                      label="可拖可缩放"),
    "ellipse": ShapeSpec("ellipse", 2, _make_ellipse, read=read_box, place=place_box,
                         label="可拖可缩放"),
    "triangle": ShapeSpec("triangle", 3, lambda ctx: _make_poly(ctx, closed=True),
                          read=read_roi, place=place_triangle, label="三个顶点可拖"),
    "arrow": ShapeSpec("arrow", 2, _make_segment, deco=decos.deco_arrow, read=read_roi,
                       place=place_pair, label="末端带箭头"),
    # ---- 斐波 / 分割 ----
    "fib": ShapeSpec("fib", 2, lambda ctx: _make_segment(ctx, dashed=True),
                     deco=decos.FIB_DECO, read=read_roi, place=place_extremes,
                     label="7 档回撤"),
    "fib_ext": ShapeSpec("fib_ext", 2, lambda ctx: _make_segment(ctx, dashed=True),
                         deco=decos.FIB_EXT_DECO, read=read_roi, place=place_extremes,
                         label="外推档位"),
    "fib_fan": ShapeSpec("fib_fan", 2, _make_segment, deco=decos.deco_fan, read=read_roi,
                         place=place_extremes, label="4 条扇形射线（含 1/8）"),
    "fib_time": ShapeSpec("fib_time", 2, lambda ctx: _make_band(ctx, "vertical"),
                          deco=decos.deco_time_zones, read=read_span, place=place_span,
                          label="按时间比例分割"),
    "percent": ShapeSpec("percent", 2, lambda ctx: _make_segment(ctx, dashed=True),
                         deco=decos.PERCENT_DECO, read=read_roi, place=place_extremes,
                         label="八等分"),
    # ---- 时间 / 测量 ----
    "cycle": ShapeSpec("cycle", 2, lambda ctx: _make_band(ctx, "vertical"),
                       deco=decos.deco_cycle, read=read_span, place=place_span,
                       label="等距重复竖线"),
    "measure": ShapeSpec("measure", 2, _make_segment, deco=decos.deco_measure,
                         read=read_roi, place=place_measure, label="显示涨跌/根数"),
    "price_measure": ShapeSpec("price_measure", 2, _make_segment,
                               deco=decos.deco_price_measure, read=read_roi,
                               place=place_band, label="显示差价/幅度"),
    "time_ruler": ShapeSpec("time_ruler", 2, lambda ctx: _make_band(ctx, "vertical"),
                            deco=decos.deco_time_ruler, read=read_span, place=place_span,
                            label="显示根数/天数"),
    "time_span": ShapeSpec("time_span", 2, lambda ctx: _make_band(ctx, "vertical"),
                           read=read_span, place=place_span, label="竖向色带"),
    # ---- 文字 / 标记 ----
    "text": ShapeSpec("text", 1, _make_text, read=read_text, place=place_one,
                      label="可拖动"),
    "price_tag": ShapeSpec("price_tag", 1, _make_text, read=read_text, place=place_one,
                           label="文字=价位"),
    "marker": ShapeSpec("marker", 1, _make_mark, read=read_text, place=place_one,
                        label="箭头符号"),
    "comment": ShapeSpec("comment", 1, _make_comment, read=read_text, place=place_one,
                         label="气泡文字"),
    "dots": ShapeSpec("dots", 1, _make_mark, read=read_text, place=place_one,
                      label="圆点符号"),
    # ---- v6.26（§7-B9 STEP 4）：最后 5 种 ----
    # ★v6.29 三端（用户拍板）：起点 / 终点定拟合区间，第三个点 = **通道区间**（拖它改带宽）
    "reg_channel": ShapeSpec("reg_channel", 3, _make_reg_channel,
                             deco=decos.deco_reg_channel, read=read_reg_channel,
                             place=place_reg_channel, reshape=reshape_reg_channel,
                             normalize=normalize_reg_channel,
                             label="三点：起点 / 终点定区间，第三点=通道区间（可拖 ⇕ 改宽）"),
    # 甘氏扇形：**两点**（起点 + 参考点）；参考线 = 1×1，方向/比例全由用户拖出来
    "fan": ShapeSpec("fan", 2, _make_segment, deco=decos.deco_gann_fan, read=read_roi,
                     place=place_fan,
                     label="拖两点：第二点就是 1×1（方向与比例都由你定）"),
    "fib_arc": ShapeSpec("fib_arc", 2, _make_segment, deco=decos.deco_fib_arc, read=read_roi,
                         place=place_span, view_dependent=True,
                         label="同心弧，随缩放重算"),
    "wave": ShapeSpec("wave", 5, _make_polyline, deco=decos.deco_wave, read=read_roi,
                      place=place_wave, label="5 个拐点连成折线"),
    "head_shoulder": ShapeSpec("head_shoulder", 3, _make_head_shoulder,
                               deco=decos.deco_head_shoulder, read=read_roi,
                               place=place_head_shoulder, label="左肩/头/右肩"),
}

# 能画的类型（**唯一事实来源**：目录的 `implemented` 必须与它一致，冒烟有双向断言）
DRAWABLE_KINDS = tuple(SHAPES)


def spec_of(kind: str) -> ShapeSpec | None:
    return SHAPES.get(str(kind or ""))


def build_annotation(ctx: DrawCtx):
    """按规格画出一条标注：`(主图元, [附属图元])`；画不出来返回 None。"""
    spec = spec_of(ctx.kind)
    if spec is None:
        return None
    primary = spec.make(ctx)
    if primary is None:
        return None
    extras = list(spec.deco(ctx, primary) or []) if spec.deco else []
    return primary, extras
