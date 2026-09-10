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
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.widgets.chart_pane import ChartPane
from ui.widgets.chart_style import CROSSHAIR_COLOR, style_axis

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

        self._glw = pg.GraphicsLayoutWidget()
        self._readout = QLabel("")
        self._readout.setStyleSheet("color: #616161; font-size: 12px; padding: 1px 6px;")
        self._readout.setVisible(False)

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

    def set_crosshair(self, enabled: bool) -> None:
        self._crosshair_enabled = bool(enabled)
        self._readout.setVisible(self._crosshair_enabled)
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
        if self._date_axis:
            try:
                label = _dt.datetime.fromtimestamp(float(x)).strftime('%Y-%m-%d')
            except (ValueError, OSError, OverflowError):
                label = f"{x:.2f}"
        else:
            label = f"#{int(round(x))}"
        self._readout.setText(f"{pane.name}   X={label}   Y={y:,.2f}")
