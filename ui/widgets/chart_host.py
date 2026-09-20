# ui/widgets/chart_host.py
"""
图表宿主「多窗格」（§7-B3 B② · P2）。

【为什么要有这个文件】
  一个通达信式 K 线工作面 = **主图 + N 张副图（附图指标）**，它们：
    · 上下堆叠、高度可调；
    · **共用同一个 x 轴**（缩放/平移联动，pyqtgraph `setXLink`）；
    · 只有最下面一张显示日期轴；
    · 鼠标移动时**十字光标跨窗格同步**（竖线贯穿全部窗格、横线只留在悬停窗格）。
  把这套逻辑收在一个宿主里，P3（渲染器接入回测页）/ P4（行情页公式叠层）/
  P5（副图指标）就不必各自用 `addPlot` 拼窗格 —— 这也是 §10-12 的落点要求。

【分工】
  · `ChartPane`（P0）：**单张**窗格 = PlotItem + 叠层容器 + 标注容器。
  · `ChartHost`（本文件）：**多张**窗格的编排者（结构 / 联动 / 日期轴 / 十字光标）。
  · `OverlayPainter`（P3）：往**某个 pane** 上画公式 IR。
  三者不可互相越权：Host 不画图元，Painter 不管窗格，Pane 不做编排。

【纪律】
  · 十字光标是**宿主级 UI 设施**，既不是公式叠层（管线 A）也不是用户标注（管线 B），
    因此**直接挂在 PlotItem 上**、不进 `ChartPane` 的两个容器 —— 否则一旦
    `clear_overlays()`（渲染器重绘时必调）就会把光标一起删掉。
  · 主区控件必须显式 `stretch=1`（§11.5-13 的 Qt 布局坑）。
"""
from __future__ import annotations

import datetime as _dt

import pyqtgraph as pg
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ui.widgets.chart_pane import ChartPane
from ui.widgets.chart_style import (AXIS_TEXT_WIDTH, CROSSHAIR_COLOR, style_axis,
                                    unify_axis_width)

DEFAULT_MAIN_STRETCH = 3
DEFAULT_SUB_STRETCH = 1
_CROSSHAIR_Z = 1e6

# 非最下窗格的底部轴处理策略（v6.8）
AXIS_HIDE = 'hide'            # 整根底部轴隐藏（默认；多窗格最干净）
AXIS_NO_VALUES = 'no_values'  # 保留轴线、只隐藏刻度值（行情页沿用既有观感）


class _Crosshair:
    """单张窗格上的十字光标（竖线 + 横线），默认隐藏。"""

    def __init__(self, pane: ChartPane, color: str = CROSSHAIR_COLOR, width: int = 1):
        pen = pg.mkPen(color, width=width, style=Qt.PenStyle.DashLine)
        self.vertical = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self.horizontal = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        self._pane = pane
        for line in (self.vertical, self.horizontal):
            line.setZValue(_CROSSHAIR_Z)
            # ignoreBounds：光标不能把视图范围撑大
            pane.plot_item.addItem(line, ignoreBounds=True)
        self.set_visible(False)

    def set_visible(self, visible: bool) -> None:
        self.vertical.setVisible(visible)
        self.horizontal.setVisible(visible)

    def set_vertical(self, x: float) -> None:
        self.vertical.setPos(x)

    def set_horizontal(self, y: float) -> None:
        self.horizontal.setPos(y)

    def detach(self) -> None:
        for line in (self.vertical, self.horizontal):
            try:
                self._pane.plot_item.removeItem(line)
            except Exception:  # noqa: BLE001 —— 已移除不致命
                pass


class ChartHost(QWidget):
    """多窗格图表宿主：主图 + N 副图，x 轴联动 + 日期轴 + 十字光标。

    :param name:       主窗格名（默认 'main'）
    :param date_axis:  是否使用 `pg.DateAxisItem`（x 必须是 epoch 秒；默认 False = 沿用 bar 序号）
    :param crosshair:  是否启用十字光标
    :param sub_panes:  初始副窗格名列表（按顺序自下而上排在主图下方）
    """

    def __init__(self, parent=None, *, name: str = "main", date_axis: bool = False,
                 crosshair: bool = False, sub_panes=(),
                 bottom_axis_mode: str = AXIS_HIDE):
        super().__init__(parent)
        self._date_axis = bool(date_axis)
        self._bottom_axis_mode = (bottom_axis_mode if bottom_axis_mode in (AXIS_HIDE, AXIS_NO_VALUES)
                                  else AXIS_HIDE)
        self._crosshair_enabled = False
        self._panes: list[ChartPane] = []
        self._crosshairs: dict[str, _Crosshair] = {}
        self._stretch: dict[str, int] = {}
        self._fixed: dict[str, int] = {}     # 高度被钉死的窗格（行情页附图）
        # 分界线拖动调高（M3：家数/指数两窗格的空间用户自己分）：未启用 = None
        # ⚠ 拖动必须用"按下瞬间锁定的参考系"，绝不能拿实时几何反推 ——
        #   第一版就是每帧用新边界算比例：改权重→布局回流→边界搬家→下一帧又对着
        #   新边界算 ⇒ 正反馈振荡，用户手感就是"拖一点就失控/往上拖没反应"（v6.42 实测）。
        self._drag_pairs: tuple | None = None
        self._drag_tol = 10
        self._dragging = False
        self._drag_saved: dict | None = None
        self._drag_cursor = None
        self._drag_start_y = 0.0
        self._drag_start_f = 0.5
        self._drag_span = 1.0
        self._divider: QFrame | None = None      # 可见的分界把手（没有它用户根本不知道能拖）

        self._glw = pg.GraphicsLayoutWidget()
        self._readout = QLabel("")
        self._readout.setStyleSheet("color: #616161; font-size: 12px; padding: 1px 6px;")
        self._readout.setVisible(False)
        # 【v6.21 · §7-B6 STEP 2】读数条的"业务文案"由页面提供（宿主不猜业务）：
        #   provider(pane_name, x, y) -> str；未设置 / 返回空 / 抛异常 ⇒ 回退内置文案。
        self._readout_provider = None
        self._readout_forced = False          # 页面要求常显（不依赖十字光标开关）

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._readout)
        layout.addWidget(self._glw, 1)          # §11.5-13：主区显式抢走富余高度

        self._glw.scene().sigMouseMoved.connect(self._on_mouse_moved)

        self._create_pane(name, role="main", stretch=DEFAULT_MAIN_STRETCH)
        for sub in sub_panes:
            self.add_pane(sub)
        if crosshair:
            self.set_crosshair(True)

    # ==========================================
    # 结构：查询
    # ==========================================
    @property
    def main_pane(self) -> ChartPane:
        return self._panes[0]

    @property
    def panes(self) -> list[ChartPane]:
        """按「上 → 下」顺序返回全部窗格（第 0 个是主图）。"""
        return list(self._panes)

    @property
    def pane_names(self) -> list[str]:
        return [p.name for p in self._panes]

    @property
    def pane_order(self) -> list[str]:
        """当前窗格顺序（含主图；**第 0 个恒为主图**）—— 给断言与"记住上次顺序"用（§7-B8 R7）。"""
        return [p.name for p in self._panes]

    def pane(self, name: str) -> ChartPane | None:
        for item in self._panes:
            if item.name == name:
                return item
        return None

    @property
    def bottom_axis_pane(self) -> str:
        """当前显示底部日期/刻度轴的窗格名（总是最下面那张）。"""
        return self._panes[-1].name if self._panes else ""

    def x_linked(self, name: str) -> bool:
        """该窗格的 x 轴是否已联动到主图（pyqtgraph 0.14: `ViewBox.linkedView(axis)`）。"""
        pane = self.pane(name)
        if pane is None or pane is self._panes[0]:
            return False
        linked = pane.plot_item.vb.linkedView(pg.ViewBox.XAxis)
        return linked is self._panes[0].plot_item.vb

    # ==========================================
    # 结构：增删 / 高度
    # ==========================================
    def add_pane(self, name: str, *, stretch: int = None,
                 fixed_height: int = None) -> ChartPane:
        """在底部追加一张副图（不可与已有窗格重名）。

        :param fixed_height: 给定则把该窗格高度**钉死**（行情页附图沿用 150px 的旧观感）；
                             不给则按 `stretch` 权重比例分配。
        """
        return self._create_pane(name, role="sub", stretch=stretch,
                                 fixed_height=fixed_height)

    def clear_sub_panes(self) -> None:
        """删掉全部副图、只留主图 —— 给"每次重渲染都重建副图"的页面用（等价旧的 `layout.clear()`）。"""
        for pane in list(self._panes[1:]):
            self.remove_pane(pane.name)

    def clear_pane_content(self, name: str) -> None:
        """清空某窗格的**内容**（保留窗格本体与十字光标）。

        比 `PlotItem.clear()` 安全：后者会把宿主自己的设施（十字光标线）一起删掉。
        """
        pane = self.pane(name)
        if pane is None:
            return
        pane.clear_overlays()
        pane.clear_annotations()
        cross = self._crosshairs.get(name)
        keep = {id(cross.vertical), id(cross.horizontal)} if cross is not None else set()
        for item in list(pane.plot_item.items):
            if id(item) in keep:
                continue
            try:
                pane.plot_item.removeItem(item)
            except Exception:  # noqa: BLE001
                pass

    def setBackground(self, color) -> None:
        """透传给内部的 GraphicsLayoutWidget（页面统一背景色用）。"""
        self._glw.setBackground(color)

    def align_axis_widths(self, axis_name: str = 'left',
                          text_width: int = AXIS_TEXT_WIDTH) -> float:
        """让**全部窗格**的同一根轴共用**同一个固定宽度**（★ §7-B8 R8）
        —— 治"副图多了纵轴缩进不一致"，且**不留空白**。

        收口在 `chart_style.unify_axis_width`（全 app 唯一的轴宽度来源，§10-9 同类纪律），
        宿主这里只做"把窗格列表递过去"。

        【为什么现在不挑调用时机】第一版按"各窗格**天然宽度的最大值**"来算，于是
        ① 必须等画过一次才有准确值、② 会把窄窗格也撑到最宽那个而留出一大片空白
        （用户截图反馈）。第二版改用**固定预留宽度**（`style.tickTextWidth`）⇒
        与量程无关、与是否画过无关 ⇒ **幂等、可重复调用**，也不需要等一轮事件循环。
        :return: 实际使用的文本宽度；0.0 = 没做（没有窗格 / 失败）
        """
        return unify_axis_width([p.plot_item for p in self._panes], axis_name, text_width)

    def remove_pane(self, name: str) -> bool:
        """删除一张副图。主图不可删（返回 False）。"""
        pane = self.pane(name)
        if pane is None or pane is self._panes[0]:
            return False
        cross = self._crosshairs.pop(name, None)
        if cross is not None:
            cross.detach()
        try:
            self._glw.ci.removeItem(pane.plot_item)
        except Exception:  # noqa: BLE001
            pass
        self._panes.remove(pane)
        self._stretch.pop(name, None)
        self._fixed.pop(name, None)
        self._reindex_rows()
        self._refit_axes()
        return True

    def set_pane_stretch(self, name: str, stretch: int) -> bool:
        """调整窗格相对高度（stretch 越大越高，主图默认 3、副图默认 1）。"""
        if self.pane(name) is None:
            return False
        self._stretch[name] = max(0, int(stretch))
        self._apply_stretch()
        return True

    def pane_stretch(self, name: str) -> int:
        """读取窗格的相对高度权重（0 = 未登记）。"""
        return self._stretch.get(name, 0)

    # ==========================================
    # 分界线拖动调高（M3 用户拍板 2026-09-21："两个表中间加个分割线让我上下拖动"）
    # ==========================================
    def enable_divider_drag(self, above: str, below: str, *, tolerance: int = 10) -> bool:
        """在两张窗格的交界线上启用**拖动调高**；双击交界 = 恢复默认 3:1。

        【为什么做在宿主里】窗格行高/权重/重排都是宿主的职责（§10-12：宿主编排、
        页面不自己 `addPlot` 拼窗格）；任何上下堆叠的 ChartHost 都能复用（§9-U）。
        【可见性】画一条真正的"分界把手"（浅灰胶囊 + ⺀ 纹），否则功能等于没有；
        【拖动模型】按下瞬间锁定 (start_y, span, start_f)，位移按比例平移 ——
        不拿实时几何反推，杜绝"布局回流→边界搬家→振荡失控"（第一版的实测教训）。
        """
        if self.pane(above) is None or self.pane(below) is None:
            return False
        self._drag_pairs = (str(above), str(below))
        self._drag_tol = max(6, int(tolerance))
        # 给分界把手留出真实空间（默认行间距太窄，把手会盖住绘图区边缘）
        try:
            self._glw.ci.setSpacing(8)
        except Exception:  # noqa: BLE001 —— 布局不支持也不拦住主功能
            pass
        viewport = self._glw.viewport()
        self._divider = QFrame(viewport)
        self._divider.setStyleSheet(
            "QFrame { background:#D7DCE3; border:1px solid #C3CAD3; border-radius:4px; }")
        grip = QLabel('⣿', self._divider)        # 盲文实心点阵 = "可抓握"的视觉暗示
        grip.setStyleSheet("color:#8A94A6; font-size:11px; border:none; background:transparent;")
        grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grip.setGeometry(0, 0, 40, 6)
        grip.move(0, 0)                          # 位置在 _update_divider_position 里居中
        self._divider.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._divider.setFixedHeight(8)
        self._divider.hide()
        viewport.setMouseTracking(True)          # 没有按下也要知道鼠标在哪（悬停光标/把手高亮）
        viewport.installEventFilter(self)
        tip = str(self._glw.toolTip() or '')
        self._glw.setToolTip((tip + '\n' if tip else '')
                             + '拖动两图之间的灰色分界把手可调高度（上下都跟手）；'
                             + '双击把手恢复默认。')
        self._update_divider_position()
        return True

    def _update_divider_position(self) -> None:
        """把可见把手摆到当前交界（几何不可见就藏起来，绝不闪残影）。"""
        if self._divider is None:
            return
        geo = self._divider_geometry()
        if geo is None:
            self._divider.hide()
            return
        line_y, _top, _bot = geo
        width = max(40, self._divider.parent().width() - 20)
        self._divider.setGeometry(10, int(line_y) - 4, width, 8)
        grip = self._divider.findChild(QLabel)
        if grip is not None:
            grip.setGeometry(0, 0, width, 6)
        self._divider.show()
        self._divider.raise_()

    def _divider_geometry(self):
        """→ `(交界 y, 上窗格顶 y, 下窗格底 y)`（视口坐标）；窗格不可见返回 None。

        ⚠ PyQt6 的 `mapFromScene(QRectF)` 返回 **QPolygon**（不是 QRect）—— 只能逐点映射；
        离屏/首帧时几何可能退化（底≤顶），一律当"不可见"处理。"""
        if self._drag_pairs is None:
            return None
        above, below = self._drag_pairs
        pa, pb = self.pane(above), self.pane(below)
        if pa is None or pb is None:
            return None
        ra = pa.plot_item.getViewBox().sceneBoundingRect()
        rb = pb.plot_item.getViewBox().sceneBoundingRect()
        a_top = self._glw.mapFromScene(ra.topLeft()).y()
        a_bot = self._glw.mapFromScene(ra.bottomRight()).y()
        b_top = self._glw.mapFromScene(rb.topLeft()).y()
        b_bot = self._glw.mapFromScene(rb.bottomRight()).y()
        if a_bot <= a_top or b_bot <= b_top:
            return None
        return (a_bot + b_top) / 2.0, float(a_top), float(b_bot)

    def reset_divider_stretch(self) -> None:
        """恢复默认高度配比（主图 3 : 副图 1）。"""
        if self._drag_pairs is None:
            return
        above, below = self._drag_pairs
        self._stretch[above] = DEFAULT_MAIN_STRETCH
        self._stretch[below] = DEFAULT_SUB_STRETCH
        self._apply_stretch()
        self._update_divider_position()

    def eventFilter(self, obj, event):        # noqa: N802 —— Qt 命名
        """分界把手拖动/悬停光标/双击复位（只吃交界附近的鼠标事件）。

        ⚠ 整段 try/except：调高只是"装饰性"交互，几何异常绝不许打断图表本身（§10-2）。"""
        try:
            if self._drag_pairs is not None and obj is self._glw.viewport():
                t = event.type()
                if t == QEvent.Type.MouseButtonPress \
                        and event.button() == Qt.MouseButton.LeftButton:
                    geo = self._divider_geometry()
                    if geo is not None:
                        line_y, top_y, bot_y = geo
                        y = float(event.position().y())
                        if abs(y - line_y) <= self._drag_tol:
                            span = max(1.0, bot_y - top_y)
                            # 按下瞬间锁定参考系：之后只叠加**相对位移**，
                            # 布局回流再快也抖不起来（上下双向都跟手）
                            self._drag_start_y = y
                            self._drag_span = span
                            self._drag_start_f = min(max((y - top_y) / span, 0.1), 0.9)
                            self._dragging = True
                            self._drag_saved = dict(self._stretch)
                            return True
                elif t == QEvent.Type.MouseMove:
                    if self._dragging:
                        y = float(event.position().y())
                        f = self._drag_start_f + (y - self._drag_start_y) / self._drag_span
                        f = min(max(f, 0.1), 0.9)
                        above, below = self._drag_pairs
                        self._stretch[above] = int(round(f * 100))
                        self._stretch[below] = 100 - self._stretch[above]
                        self._apply_stretch()
                        self._update_divider_position()
                        return True
                    geo = self._divider_geometry()
                    if geo is not None:
                        near = abs(float(event.position().y()) - geo[0]) <= self._drag_tol
                        cursor = (Qt.CursorShape.SizeVerCursor if near
                                  else Qt.CursorShape.ArrowCursor)
                        if cursor is not self._drag_cursor:
                            self._drag_cursor = cursor
                            self._glw.viewport().setCursor(cursor)
                elif t == QEvent.Type.MouseButtonRelease and self._dragging:
                    self._dragging = False
                    self._update_divider_position()
                    return True
                elif t == QEvent.Type.MouseButtonDblClick \
                        and event.button() == Qt.MouseButton.LeftButton:
                    geo = self._divider_geometry()
                    if geo is not None and abs(float(event.position().y()) - geo[0]) \
                            <= self._drag_tol:
                        self.reset_divider_stretch()
                        return True
        except Exception:  # noqa: BLE001 —— 调高失败不能吃掉事件流
            self._dragging = False
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):             # noqa: N802 —— Qt 命名
        super().resizeEvent(event)
        self._update_divider_position()

    def move_pane(self, name: str, new_index: int) -> bool:
        """把某张副图挪到新的位置（★ §7-B8 R7）。

        :param name:      副图名（**主图不可移**：它是永远的第 0 张，返回 False）
        :param new_index: 目标位置 —— 1 = 主图下面第一格；越界自动夹到合法区间
        :return: 顺序**真的变了**才返回 True（原地不动 / 名字不存在都返回 False）

        【为什么需要它】用户实测原话："现阶段的副图有严格的顺序排列，用户没办法去调整顺序"。
        旧实现只有 `add_pane`（**永远追加到底部**），确实没有任何换序手段。

        【为什么不能只挪列表】换序必须**连带重算三件事**，少一件就出错：
          ① 行排布（`_reindex_rows` —— `QGraphicsGridLayout` 不会自动塌缩）；
          ② 高度权重（`_apply_stretch` —— stretch 是按行号设的）；
          ③ **底部刻度轴的归属**（`_refit_axes` —— "只有最下面那张显示刻度值"）。
          ⚠ 漏掉 ③ 会出现"日期轴挂在中间那张副图上"这种一眼可见的错。
        """
        pane = self.pane(name)
        if pane is None or pane is self._panes[0]:
            return False
        old_index = self._panes.index(pane)
        target = max(1, min(int(new_index), len(self._panes) - 1))
        if target == old_index:
            return False
        self._panes.pop(old_index)
        self._panes.insert(target, pane)
        self._reindex_rows()
        self._refit_axes()
        return True

    def set_pane_order(self, names) -> bool:
        """按给定名字顺序**整体重排**副图（主图永远第 0）—— 给"记住上次顺序"用（§7-B8 R7）。

        ⚠ 必须**给全**所有副图名：少给一个就返回 False 且**什么都不做** ——
        宁可拒绝，也不许"静默丢掉一张窗格"（§10-4 诚实原则）。
        """
        wanted = [str(n) for n in (names or [])]
        existing = {p.name: p for p in self._panes[1:]}
        if sorted(wanted) != sorted(existing):
            return False
        ordered = [existing[n] for n in wanted]
        before = [p.name for p in self._panes]
        self._panes = [self._panes[0]] + ordered
        if [p.name for p in self._panes] == before:
            return False
        self._reindex_rows()
        self._refit_axes()
        return True

    def clear(self) -> None:
        """清空所有窗格的内容（叠层 + 标注），**保留窗格结构**。"""
        for pane in self._panes:
            pane.clear_overlays()
            pane.clear_annotations()

    # ==========================================
    # 日期轴
    # ==========================================
    @property
    def date_axis(self) -> bool:
        return self._date_axis

    def set_date_axis(self, enabled: bool) -> None:
        """切换日期轴（`pg.DateAxisItem`）。启用时 x 必须传 epoch 秒。"""
        enabled = bool(enabled)
        if enabled == self._date_axis:
            return
        self._date_axis = enabled
        for pane in self._panes:
            self._swap_bottom_axis(pane)
        self._refit_axes()

    # ==========================================
    # 十字光标
    # ==========================================
    @property
    def crosshair_enabled(self) -> bool:
        return self._crosshair_enabled

    @property
    def readout_text(self) -> str:
        return self._readout.text()

    def crosshair_lines(self, pane_name: str):
        """返回该窗格的 `(竖线, 横线)`；窗格不存在返回 None（供测试/程序化定位）。"""
        cross = self._crosshairs.get(pane_name)
        return None if cross is None else (cross.vertical, cross.horizontal)

    def set_readout_provider(self, provider) -> None:
        """设置**读数条文案**的外部提供者（v6.21 · §7-B6 STEP 2）。

        【为什么交给页面】内置文案只能给"窗格名 / X / Y"，而工作台要的是**业务读数**
        （日期 + 开高低收 + 量 + 均线）。宿主**不猜业务**，只把 `(pane_name, x, y)`
        转交页面，由页面用真实 df 拼文案（§10-3：引擎/宿主出数据，页面定业务）。
        【纪律】provider 返回空串或抛异常 ⇒ **回退内置文案** —— 读数只是显示，
        绝不能因为它挂掉而影响图表（这条有断言守着）。
        """
        self._readout_provider = provider

    def set_readout_visible(self, visible: bool) -> None:
        """让读数条**常显**（不依赖十字光标开关）—— 工作台要它常驻显示最新一根的读数。"""
        self._readout_forced = bool(visible)
        self._readout.setVisible(self._readout_forced or self._crosshair_enabled)

    def set_readout_text(self, text: str) -> None:
        """直接写读数条文案（v6.21 · §7-B6 STEP 5）。

        【为什么不复用 `update_crosshair`】那会把十字光标**真的挪到**那一根上（画面上会看到
        两条线跳到最新一根）—— 而"不悬停时显示最新一根的读数"是**常驻摘要**，不该动画。
        """
        self._readout.setText(str(text or ""))

    def set_crosshair(self, enabled: bool) -> None:
        self._crosshair_enabled = bool(enabled)
        self._readout.setVisible(self._readout_forced or self._crosshair_enabled)
        if not self._crosshair_enabled:
            for cross in self._crosshairs.values():
                cross.set_visible(False)
            self._readout.setText("")

    def update_crosshair(self, pane_name: str, x: float, y: float) -> None:
        """按**数据坐标**定位十字光标（鼠标事件与程序化调用共用同一入口）。

        竖线在**全部窗格**同步（x 轴联动，视觉上贯穿）；横线只留在 `pane_name` 上。
        """
        pane = self.pane(pane_name)
        if pane is None:
            return
        for other in self._panes:
            cross = self._crosshairs.get(other.name)
            if cross is None:
                continue
            cross.vertical.setVisible(self._crosshair_enabled)
            cross.set_vertical(x)
            if other is pane:
                cross.horizontal.setVisible(self._crosshair_enabled)
                cross.set_horizontal(y)
            else:
                cross.horizontal.setVisible(False)
        self._update_readout(pane, x, y)

    # ==========================================
    # 内部
    # ==========================================
    def _create_pane(self, name: str, *, role: str, stretch: int = None,
                     fixed_height: int = None) -> ChartPane:
        if self.pane(name) is not None:
            raise ValueError(f"窗格名 '{name}' 已存在")
        plot_item = self._glw.addPlot(row=len(self._panes), col=0)
        pane = ChartPane(plot_item, name=name, role=role)
        self._panes.append(pane)
        if fixed_height:
            # 钉死高度：min == max，且行权重给 0（否则会被拉伸因子再放大）
            plot_item.setMinimumHeight(int(fixed_height))
            plot_item.setMaximumHeight(int(fixed_height))
            self._fixed[name] = int(fixed_height)
            self._stretch[name] = 0
        else:
            default = DEFAULT_MAIN_STRETCH if role == 'main' else DEFAULT_SUB_STRETCH
            self._stretch[name] = int(default if stretch is None else stretch)
        self._crosshairs[name] = _Crosshair(pane)
        self._relink()
        self._refit_axes()
        self._apply_stretch()
        return pane

    def _relink(self) -> None:
        if len(self._panes) < 2:
            return
        main = self._panes[0]
        for pane in self._panes[1:]:
            pane.plot_item.setXLink(main.plot_item)

    def _reindex_rows(self) -> None:
        """删除窗格后把剩余窗格按 0..n-1 重新排布（QGraphicsGridLayout 不做自动塌缩）。"""
        ci = self._glw.ci
        for pane in self._panes:
            try:
                ci.removeItem(pane.plot_item)
            except Exception:  # noqa: BLE001
                pass
        for row, pane in enumerate(self._panes):
            ci.addItem(pane.plot_item, row=row, col=0)
        self._apply_stretch()

    def _apply_stretch(self) -> None:
        layout = self._glw.ci.layout
        for row, pane in enumerate(self._panes):
            layout.setRowStretchFactor(row, self._stretch.get(pane.name, DEFAULT_SUB_STRETCH))

    def _refit_axes(self) -> None:
        """底部轴归属：只有最下面一张窗格显示**刻度值**（多窗格重复显示会互相压字）。

        非最下窗格按 `bottom_axis_mode` 处理：`axis_hide` 整根隐藏 / `no_values` 保留轴线。
        """
        if not self._panes:
            return
        last = self._panes[-1]
        for pane in self._panes:
            axis = pane.plot_item.getAxis('bottom')
            if pane is last:
                pane.plot_item.showAxis('bottom')
                axis.setStyle(showValues=True)
            elif self._bottom_axis_mode == AXIS_NO_VALUES:
                pane.plot_item.showAxis('bottom')
                axis.setStyle(showValues=False)
            else:
                pane.plot_item.hideAxis('bottom')

    def _swap_bottom_axis(self, pane: ChartPane) -> None:
        axis = (pg.DateAxisItem(orientation='bottom') if self._date_axis
                else pg.AxisItem(orientation='bottom'))
        pane.plot_item.setAxisItems({'bottom': axis})
        style_axis(pane.plot_item, 'bottom')   # 换轴后必须重新着色（§10-9）

    def _on_mouse_moved(self, pos) -> None:
        if not self._crosshair_enabled or not self._panes:
            return
        for pane in self._panes:
            vb = pane.plot_item.getViewBox()
            if vb.sceneBoundingRect().contains(pos):
                point = vb.mapSceneToView(pos)
                self.update_crosshair(pane.name, point.x(), point.y())
                return
        for cross in self._crosshairs.values():
            cross.set_visible(False)

    def _update_readout(self, pane: ChartPane, x: float, y: float) -> None:
        # 【v6.21 · §7-B6 STEP 2】先问页面（业务读数）；失败/空 ⇒ 静默回退内置文案。
        if self._readout_provider is not None:
            try:
                text = self._readout_provider(pane.name, x, y)
            except Exception:  # noqa: BLE001 —— 读数只是显示，绝不能连累图表
                text = ""
            if text:
                self._readout.setText(str(text))
                return
        if self._date_axis:
            try:
                label = _dt.datetime.fromtimestamp(float(x)).strftime('%Y-%m-%d')
            except (ValueError, OSError, OverflowError):
                label = f"{x:.2f}"
        else:
            label = f"#{int(round(x))}"
        self._readout.setText(f"{pane.name}   X={label}   Y={y:,.2f}")
