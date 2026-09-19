# ui/widgets/annotation_items.py
"""标注的**可复用图元小件**（v6.25 · §7-B8 R11）—— 与具体画线类型**无关**的底层零件。

【为什么单独一个文件】规格表（`annotation_shapes.py`）按"一种类型一个规格"增长，
类型越多它越长；把**与类型无关的零件**（可点选文字 / 可点选区间带 / 箭头头 /
虚线档位 / 标签 / 高亮分发）抽出来，规格表就只剩"类型语义"本身 ——
两个文件各自职责单一，都不越过 400 线（§4 体积铁律）。

【铁律】
  · `pg.TextItem` / `pg.LinearRegionItem` 都**不发点击信号** ⇒ 必须子类补信号，
    否则"逐个独立删除"（管线 B 的硬要求，§7-B3 C）直接不成立 —— v6.10 的
    `_ClickableText` 与本轮的 `_RegionBand` 是**同一类坑**，别踩第二次；
  · pyqtgraph 覆写了 `mouseMoveEvent` 且不调父类 ⇒ `ItemIsMovable` 无效，
    拖动必须自己实现（§11.4「让图元跟着鼠标走」）；
  · 高亮分发（`highlight`）是**唯一入口**：不同图元的"看得见"不是同一个属性
    （文字改字色 / 区间带改填充 / 其余改画笔），禁止页面各自 if/else。
"""
from __future__ import annotations

from math import atan2, degrees

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal

from ui.widgets import chart_style

# ---- 可视常量（**全 app 唯一来源**；`annotation_layer` 从这里再导出，既有 import 零改动）----
LINE_WIDTH = 2
SELECTED_WIDTH = 3
SELECTED_COLOR = "#FF6F00"          # 选中高亮色（与默认蓝明显区分）
TRENDLINE_SPAN = (0.2, 0.8)         # 新建标注默认横向跨度（占可视宽度比例）
# 各档水平位的颜色（越低越深，视觉上"越便宜越吸引"）；斐波/百分比/扩展共用
FIB_COLORS = ("#90A4AE", "#78909C", "#607D8B", "#546E7A", "#455A64", "#37474F", "#263238")
FIB_LEVEL_WIDTH = 1
ARROW_LEN = 13                      # 箭头头部长度（px，pxMode=True ⇒ 不随缩放变大）
PREVIEW_COLOR = "#90CAF9"           # **绘制预览**的颜色（笔一律虚线；比正式色淡一号）
# ⚠ 填充透明度**不在本文件**：全 app 唯一口径 = `chart_style.annotation_fill`
#   （用户实测高饱和填充盖住 K 线；将来深色主题也只改那一处）


class _ClickableText(pg.TextItem):
    """可点选 + **可拖动**的文字类图元（文字 / 评论气泡 / 价格标签 / 符号标记）。

    【为什么要子类】`pg.TextItem` 既**不发点击信号**、也**不会自己跟着鼠标走**：
      · 没点击信号 ⇒ 用户永远选不中它，"逐个独立删除"直接不成立（§7-B3 C 的硬要求）；
      · 不会自己移动 ⇒ 文字只能停在你放它在的地方（P8 收尾前就是"放置式"）。

    【★★v6.28 · 为什么以前"拖不动 + 点不中"——探针实测坐实的机制】
      pyqtgraph 的 `GraphicsScene` 只在**没有任何图元接受 press** 时，才会发出
      `mouseClickEvent` / `mouseDragEvent`（框架原话："If no item accepts the mousePressEvent,
      then the scene will begin delivering mouseDrag and/or mouseClick events"）。
      而本类为了让 Qt 把图元当作"鼠标抓取者"、从而**稳定收到后续事件**，**必须接受 press**
      ⇒ 那两类 pyqtgraph 事件**永远不会来**：
        · 原来的 `mouseDragEvent`（拖动）与 `mouseClickEvent`（点选）**一次都没被执行过**；
        · 旧断言是"手搓假事件直接调 `mouseDragEvent`"⇒ 一直是绿的（§11.5-49）。
      **正确做法 = 全部走 Qt 自己的三件套**（实测都投得到）：
        press（接受 ⇒ 成为抓取者）→ `mouseMoveEvent`（按住左键时跟随）→ `mouseReleaseEvent`
        （**没移动 = 点击 ⇒ 选中**；移动过 = 拖动 ⇒ 松手落盘）。
      ⚠ 位移必须换算到**父坐标系**再 `setPos`：图元挂在 ViewBox 下面，场景坐标带着视图缩放，
      直接拿场景位移当数据位移，缩得越狠飘得越远。
    """

    DRAG_THRESHOLD = 3.0            # 小于这个像素位移算"点一下"，不算拖动

    def __init__(self, text: str, *, color: str = "#1976D2", anchor=(0.0, 0.5),
                 border=None, fill=None, on_click=None, on_moved=None):
        super().__init__(text, color=color, anchor=anchor, border=border, fill=fill)
        self._on_click = on_click
        self._on_moved = on_moved       # 拖动**松手后**回调一次（由层负责落盘）
        self._press_pos = None          # 按下时的**父坐标系**位置
        self._press_scene = None        # 按下时的场景坐标（算位移用）
        self._dragged = False
        self.setFlag(pg.QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    # ---- Qt 三件套（唯一可靠的投递路径）----
    def mousePressEvent(self, event):
        if event.button() == pg.QtCore.Qt.MouseButton.LeftButton:
            self._press_pos = self.pos()
            self._press_scene = event.scenePos()
            self._dragged = False
            event.accept()              # 接受 ⇒ 成为鼠标抓取者（后续 move/release 必到我这里）
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & pg.QtCore.Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        parent = self.parentItem()
        if parent is None:
            return super().mouseMoveEvent(event)
        # ⚠ 判"算不算拖动"必须用**场景坐标（≈像素）**，不能用数据坐标：
        #   数据坐标里 1 个单位可能是 0.01 元或 50 元，拿它当"像素阈值"会时灵时不灵
        #   （v6.28 实测：20 像素的拖动在 y 量程 0~1 的图上只有 0.02 ⇒ 被当成"没动"）。
        shift = event.scenePos() - self._press_scene
        if not self._dragged and abs(shift.x()) + abs(shift.y()) < self.DRAG_THRESHOLD:
            return                      # 手抖几个像素不算拖动（否则"点选"会被吃掉）
        self._dragged = True
        event.accept()
        # 位移换算到**父坐标系**再落位（图元挂在 ViewBox 下，场景坐标带着视图缩放）
        offset = (parent.mapFromScene(event.scenePos())
                  - parent.mapFromScene(self._press_scene))
        self.setPos(self._press_pos + offset)

    def mouseReleaseEvent(self, event):
        if event.button() == pg.QtCore.Qt.MouseButton.LeftButton and self._press_pos is not None:
            dragged = self._dragged
            self._press_pos = None
            self._press_scene = None
            self._dragged = False
            event.accept()
            if dragged:
                if callable(self._on_moved):
                    self._on_moved()    # 松手才落盘（拖动过程中不写文件）
            elif callable(self._on_click):
                self._on_click()        # 没移动 = 点在它身上 ⇒ 选中
            return
        super().mouseReleaseEvent(event)


class _RegionBand(pg.LinearRegionItem):
    """可点选的**区间带**（价格带 / 时间区间 / 时间尺 / 周期线 / 斐波时间）。

    【为什么要子类】`LinearRegionItem` 只有"区域变化"信号、**没有点击信号** ⇒
    不补这个信号就**没法单独选中/删除**，管线 B 的"逐个独立删除"直接不成立
    （与 `_ClickableText` 同源的理由，同一类坑别踩第二次）。
    """

    sigClicked = pyqtSignal(object)

    def __init__(self, values, orientation: str, color: str):
        super().__init__(values=values, orientation=orientation,
                         brush=band_brush(color, False), movable=True)
        self._color = color

    def mouseClickEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            self.sigClicked.emit(self)
            return
        super().mouseClickEvent(ev)     # 右键"取消拖动"等既有行为照旧

    def set_highlight(self, selected: bool) -> None:
        """区间带的"看得见"是填充色（它没有 pen），所以高亮改 brush。"""
        self.setBrush(band_brush(self._color, selected))


class _FillBand(pg.QtWidgets.QGraphicsPolygonItem):
    """半透明填充带（平行通道 / 回归通道用）—— 让"通道"在视觉上比一条普通线**粗一档**。

    【为什么要自己一个子类】用户原话："通道线最好跟普通线有一点区别"。
    纯线框看不出"这是一段区间"，而 pyqtgraph 没有现成的"平行四边形填充件"
    （`LinearRegionItem` 只能横平竖直）。
    ⚠ 它**不发点击信号**（`QGraphicsPolygonItem` 根本不是 pyqtgraph 的 GraphicsObject）
    ⇒ 只能当附属图元，随主图元一起删（§11.5-37）。
    """

    def __init__(self, points, color: str):
        super().__init__(pg.QtGui.QPolygonF([pg.QtCore.QPointF(float(x), float(y))
                                             for x, y in points]))
        # 只要填充、不要描边（描边会和两条边界线重影）
        self.setPen(pg.QtGui.QPen(pg.QtCore.Qt.PenStyle.NoPen))
        self._color = color
        self.setBrush(self._make_brush(False))

    def _make_brush(self, selected: bool):
        return pg.mkBrush(chart_style.annotation_fill(self._color, selected))

    def set_highlight(self, selected: bool) -> None:
        """填充带的高亮 = 换填充色（**不是**改画笔 —— 它没有可见的笔）。"""
        self.setBrush(self._make_brush(selected))


def band_brush(color: str, selected: bool):
    """区间带（价格带 / 时间区间）的填充 —— **唯一口径在 `chart_style.annotation_fill`**。"""
    return pg.mkBrush(chart_style.annotation_fill(color, selected))


def arrow_head(view_box, x0, y0, x1, y1, color: str):
    """按**屏幕方向**摆一个箭头（pxMode=True ⇒ 缩放不变大）。

    ⚠ 角度必须按场景坐标算：x 是"第几根"、y 是"多少钱"，两者量纲不同，
    直接用数据坐标算角度会得到一个歪的箭头。ViewBox 尚未布局时返回 None（本次不画）。
    """
    try:
        start = view_box.mapViewToScene(pg.QtCore.QPointF(float(x0), float(y0)))
        end = view_box.mapViewToScene(pg.QtCore.QPointF(float(x1), float(y1)))
    except Exception:  # noqa: BLE001 —— 布局未完成时拿不到变换，跳过这一次
        return None
    dx, dy = end.x() - start.x(), end.y() - start.y()
    # pyqtgraph 的约定：**angle=0 指向左**（-x），屏幕 y 向下 ⇒ 取反后再 atan2
    angle = degrees(atan2(-dy, -dx)) if (abs(dx) > 1e-9 or abs(dy) > 1e-9) else 90.0
    head = pg.ArrowItem(angle=angle, pxMode=True, headLen=ARROW_LEN, tipAngle=26,
                        tailLen=None, pen=None, brush=pg.mkBrush(color))
    head.setPos(float(x1), float(y1))
    return head


def level_line(x0, x1, price, color):
    """一档水平位 = 点状虚线（斐波 / 百分比 / 扩展共用同一张脸）。"""
    return pg.PlotDataItem([x0, x1], [price, price],
                           pen=pg.mkPen(color, width=FIB_LEVEL_WIDTH,
                                        style=pg.QtCore.Qt.PenStyle.DotLine))


def solid_line(points, color, dashed: bool = False):
    """折线（射线的延长段 / 扇形射线），虚线 = "这是衍生出来的，不是你画的主体"。"""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return pg.PlotDataItem(xs, ys, pen=pg.mkPen(
        color, width=LINE_WIDTH,
        style=pg.QtCore.Qt.PenStyle.DashLine if dashed
        else pg.QtCore.Qt.PenStyle.SolidLine))


def label(text: str, color: str, position, anchor=(0.0, 1.0)):
    """附属标签（档位 % / 测量结果）。不拦鼠标事件由 TextItem 默认决定 —— 它们不参与选中。"""
    item = pg.TextItem(text, color=color, anchor=anchor)
    item.setPos(float(position[0]), float(position[1]))
    return item


def calendar_days(points) -> int:
    """两个锚点之间的**自然日**天数（算不出来就返回 0，绝不猜，§10-4）。"""
    from datetime import date as _date

    if len(points or []) < 2:
        return 0
    try:
        first = _date.fromisoformat(str(points[0][0])[:10])
        second = _date.fromisoformat(str(points[1][0])[:10])
    except ValueError:
        return 0
    return abs((second - first).days)


# ==========================================
# 上下文胶水（主图元 / 附属图元两边的规格都要用的公共件）
# ==========================================
def points_to_xy(ctx, points) -> list | None:
    """[[日期, 价], ...] -> [(x序号, y价), ...]；任一锚点不在轴内 → None（本次不画）。"""
    out = []
    for point in points or []:
        try:
            date_label, price = point
        except (TypeError, ValueError):
            return None
        x = ctx.axis.date_to_index(date_label)
        if x is None:
            return None
        try:
            y = float(price)
        except (TypeError, ValueError):
            return None
        out.append((float(x), y))
    return out


def connect(graphic, ctx) -> None:
    """挂信号：点选 → `on_select`；拖动松手 → `on_change`（不同图元信号名不同）。

    ★★ v6.28：**必须先声明"左键归我"** —— pyqtgraph 的 `ROI` 默认
    `acceptedMouseButtons() == NoButton`，而它的 `mouseClickEvent` 里写着
    `elif self.acceptedMouseButtons() & ev.button(): ... sigClicked.emit(...)`
    ⇒ 不设这一句，**`sigClicked` 永远不发** ⇒ 趋势线/波浪/通道/斐波…**点线身选不中**
    （用户只能"清空"，不能逐个删 —— 管线 B 的硬要求直接不成立）。
    实测：`pg.LineSegmentROI(...).acceptedMouseButtons()` = `NoButton`（默认），
    设成 LeftButton 之后点击才落到 `sigClicked`（§11.5-51）。
    """
    if hasattr(graphic, "setAcceptedMouseButtons"):
        try:
            graphic.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        except Exception:  # noqa: BLE001 —— 极少数图元不支持时忽略
            pass
    if hasattr(graphic, "sigClicked"):
        graphic.sigClicked.connect(lambda *_a, **_k: ctx.on_select())
    for name in ("sigRegionChangeFinished", "sigPositionChangeFinished"):
        signal = getattr(graphic, name, None)
        if signal is not None:
            signal.connect(lambda *_a, **_k: ctx.on_change())


def pixel_scale(view_box) -> tuple:
    """每"1 根 bar" / 每"1 个价格单位"各占多少**像素**。

    ⚠ 依赖视图的画法（甘氏扇形 / 斐波弧）全靠它换算：x 是"第几根"、y 是"多少钱"，
    两者量纲不同，直接在数据坐标里画"45°"或"圆"都会被拉扁（§11.5-38）。
    """
    try:
        (x0, x1), (y0, y1) = view_box.viewRange()
        width = float(view_box.width() or 1)
        height = float(view_box.height() or 1)
    except Exception:  # noqa: BLE001 —— 尚未布局时给一个"不为零"的兜底
        return (1.0, 1.0)
    return (width / max(abs(float(x1) - float(x0)), 1e-9),
            height / max(abs(float(y1) - float(y0)), 1e-9))


def infinite(ctx, position: float, angle: int, *, dashed: bool = False):
    """可拖的全价位 / 全时段直线（水平线 / 垂直线 / 交叉线的一半）。"""
    graphic = pg.InfiniteLine(position, angle=angle, movable=True,
                              pen=ctx.pen(ctx.color, False, dashed))
    connect(graphic, ctx)
    return graphic


def highlight(graphic, color: str, selected: bool, pen) -> None:
    """选中高亮的**唯一入口**：不同图元的"看得见"不是同一个属性。

    · 文字类改文字色；· 区间带改填充（它没有 pen）；· 其余改画笔。
    """
    if isinstance(graphic, pg.TextItem):
        graphic.setColor(SELECTED_COLOR if selected else (color or "#1976D2"))
    elif hasattr(graphic, "set_highlight"):
        graphic.set_highlight(selected)
    elif hasattr(graphic, "setPen"):
        graphic.setPen(pen(color, selected))
