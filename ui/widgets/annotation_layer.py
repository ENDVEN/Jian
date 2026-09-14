# ui/widgets/annotation_layer.py
"""用户标注交互层（§7-B3 ④ · P6）—— 画线 / 选中 / **逐个独立删除**。

【职责边界 · 三条纪律】
  1. **只管管线 B**（用户手绘）。公式叠层是管线 A，两者的数据与生命周期**绝不混用**
     （§7-B3 C / §10-12）：本层对象**持久化**到 `(标的, 周期)`，而叠层随参数重算即消失。
  2. 对象模型与持久化在 `data/annotations.py`（零 Qt）；本文件只做"Qt 图元 + 交互"。
     这里**不写 JSON、不碰路径** —— 迁移存储实现时本文件一行都不用改。
  3. 本文件是**全 app 唯一的标注交互入口**：行情页现在用它，将来复盘页回放 / P8 重做
     也复用它，**禁止各页面各写一套**（§9-O7「改一处漏三处」的教训）。

【图元选型（都挂到 `ChartPane` 的标注容器）】
  · trend → `pg.LineSegmentROI`：自带两端手柄，拖动调整手感最好（与旧版趋势线一致）
  · hline → `pg.InfiniteLine(angle=0)`；vline → `pg.InfiniteLine(angle=90)`
  因为走的是 `add_annotation()`，所以换公式时的 `clear_overlays()` **不会误删标注**，
  重渲染时的 `clear_annotations()` 也**不会碰到公式叠层** —— 两条管线物理隔离。

【拖动即保存】ROI 用 `sigRegionChangeFinished`、InfiniteLine 用
`sigPositionChangeFinished`：只在**松手后**落盘一次，不在拖动过程中疯狂写文件。
"""
from __future__ import annotations

import logging

import pyqtgraph as pg

from data.annotations import (FIB_RATIOS, KIND_FIB, KIND_HLINE, KIND_LABELS,
                              KIND_TEXT, KIND_TREND, KIND_VLINE, PERIOD_DAILY,
                              AnnotationStore, DEFAULT_COLOR, DateAxis, fib_levels,
                              make_annotation)

logger = logging.getLogger(__name__)

# 新建标注默认横向跨度（占当前可视宽度的比例）
TRENDLINE_SPAN = (0.2, 0.8)
# 选中高亮色（与默认蓝区分明显，保证"哪条被选中"一眼可见）
SELECTED_COLOR = "#FF6F00"
LINE_WIDTH = 2
SELECTED_WIDTH = 3

# 工具栏可创建的标注类型（**唯一事实来源**：页面下拉直接用它，别再手写一份）
DRAWABLE_KINDS = (KIND_TREND, KIND_HLINE, KIND_VLINE, KIND_FIB, KIND_TEXT)
# 斐波那契各档位的水平位颜色（越低越深，视觉上"越便宜越吸引"）
FIB_COLORS = ("#90A4AE", "#78909C", "#607D8B", "#546E7A", "#455A64", "#37474F", "#263238")
FIB_LEVEL_WIDTH = 1


class _ClickableText(pg.TextItem):
    """可点选 + **可拖动**的文字标注（v6.13 补拖动）。

    【为什么要子类】`pg.TextItem` 既**不发点击信号**、也**不会自己跟着鼠标走**：
      · 没点击信号 ⇒ 用户永远选不中它，"逐个独立删除"直接不成立（§7-B3 C 的硬要求）；
      · 不会自己移动 ⇒ 文字只能停在你放它在的地方（P8 收尾前就是"放置式"）。
    【为什么不能只设 ItemIsMovable】pyqtgraph 覆写了 `mouseMoveEvent` 并**不调用父类实现**，
    所以 Qt 内建的"可移动图元"移动逻辑根本不执行 —— 必须自己在 `mouseDragEvent` 里改坐标。
    """

    def __init__(self, text: str, *, color: str = DEFAULT_COLOR, anchor=(0.0, 0.5),
                 on_click=None, on_moved=None):
        super().__init__(text, color=color, anchor=anchor)
        self._on_click = on_click
        self._on_moved = on_moved       # 拖动**松手后**回调一次（由层负责落盘）
        self._press_pos = None
        self.setFlag(pg.QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def mousePressEvent(self, event):
        if event.button() == pg.QtCore.Qt.MouseButton.LeftButton:
            self._press_pos = self.pos()      # 记下起点，拖动时按"位移量"跟随
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDragEvent(self, event):
        if event.button() != pg.QtCore.Qt.MouseButton.LeftButton or self._press_pos is None:
            return super().mouseDragEvent(event)
        event.accept()
        self.setPos(self._press_pos + (event.scenePos() - event.buttonDownScenePos()))
        if event.isFinish():                  # 松手才落盘，拖动过程中不写文件
            self._press_pos = None
            if callable(self._on_moved):
                self._on_moved()

    def mouseClickEvent(self, event):
        if event.button() == pg.QtCore.Qt.MouseButton.LeftButton and callable(self._on_click):
            self._on_click()
            event.accept()
            return True
        return super().mouseClickEvent(event)


class AnnotationLayer:
    """把「某标的 + 某周期」的用户标注画到一个图表宿主上，并提供增删交互。

    :param host:  `ui/widgets/chart_host.py` 的 ChartHost（标注固定落在**主图**上）
    :param store: `data/annotations.py` 的 AnnotationStore
    :param on_changed: 内容变化回调（页面据此刷新"N 条标注"回执）
    """

    def __init__(self, host, store: AnnotationStore, *, period: str = PERIOD_DAILY,
                 on_changed=None):
        self._host = host
        self._store = store
        self._period = str(period or PERIOD_DAILY)
        self._on_changed = on_changed
        self._symbol = ""
        self._axis = DateAxis([])
        self._tool = ""          # 当前工具（'' = 浏览模式，不新建）
        self._selected = ""
        self._items: dict = {}   # id -> 主图元（可拖/可点选的那一个）
        self._extras: dict = {}  # id -> [附属图元]（斐波那契的各档水平位与标签）

    # ==========================================
    # 绑定 / 渲染
    # ==========================================
    def bind(self, symbol: str, dates, period: str = None) -> int:
        """切换标的 / 周期 / 数据窗口后重新绑定并重绘，返回画出的条数。

        每次重渲染都调它 —— 标注**从存储里读回来重画**，所以"切走再切回"不会丢。

        :param period: 给出则一并切换周期（行情工作台的日/周/月）。
            标注按 `(标的, **周期**)` 分开存是本项目的既定设计（§7-B3 P6）：
            日线上画的线不该出现在周线上 —— 两种周期的横轴根本不是同一批 bar。
        """
        self._symbol = str(symbol or "")
        if period:
            self._period = str(period)
        # ⚠ 不能写 `dates or []`：dates 常直接来自 `df['date']`（Series），布尔求值会抛异常
        self._axis = DateAxis(dates if dates is not None else [])
        self._selected = ""
        return self.render()

    def render(self) -> int:
        """按当前绑定从存储读全量并重画（幂等，可安全重复调用）。"""
        self.clear_view()
        drawn = 0
        for item in self._store.list(self._symbol, self._period):
            if self._draw_item(item) is not None:
                drawn += 1
        if self._selected and self._selected in self._items:
            self._highlight(self._selected)
        return drawn

    def clear_view(self) -> None:
        """只清"画在图上的东西"，**不动存储**（重渲染 / 切标的时用）。"""
        pane = self._host.main_pane
        for item_id in list(self._items):
            self._forget(item_id)
        self._items.clear()
        self._extras.clear()

    def _forget(self, item_id: str) -> None:
        """把一个标注的**主图元 + 全部附属图元**从窗格摘掉（图元与容器必须同步，§11.5-15）。"""
        pane = self._host.main_pane
        graphic = self._items.pop(item_id, None)
        if graphic is not None:
            pane.remove_annotation(graphic)
        for extra in self._extras.pop(item_id, []):
            pane.remove_annotation(extra)

    # ==========================================
    # 工具与新建
    # ==========================================
    @property
    def tool(self) -> str:
        return self._tool

    def set_tool(self, kind: str) -> None:
        """'': 浏览模式（点线条只选中）；'trend'/'hline'/'vline': 该模式的"添加"按钮生效。"""
        self._tool = str(kind or "")

    def tool_label(self) -> str:
        return KIND_LABELS.get(self._tool, "") if self._tool else ""

    def create_default(self, kind: str = None, *, text: str = "") -> dict | None:
        """在当前**可视窗口**放一条默认标注并落盘（用户随后拖动微调）。

        :param text: 文字标注的内容（`KIND_TEXT` 必填；空内容会被模型层拒绝）
        :return: 落库后的标注对象；未绑定标的 / 无数据 / 内容非法时返回 None。
        """
        kind = str(kind or self._tool or "")
        if kind not in DRAWABLE_KINDS or not self._symbol:
            return None
        if self._axis.size == 0:
            return None

        (x_min, x_max), (y_min, y_max) = self._view_range()
        y_mid = (y_min + y_max) / 2.0
        if not y_mid:
            y_mid = 1.0

        if kind == KIND_TREND:
            points = [
                [self._axis.index_to_date(x_min + (x_max - x_min) * TRENDLINE_SPAN[0]), y_mid],
                [self._axis.index_to_date(x_min + (x_max - x_min) * TRENDLINE_SPAN[1]), y_mid],
            ]
        elif kind == KIND_FIB:
            # 默认锚点 = 当前可视区间的"高点 → 低点"，用户拖两个手柄调成真实波段即可
            points = [[self._axis.index_to_date(x_min), y_max],
                      [self._axis.index_to_date(x_max), y_min]]
        else:
            # 水平线 / 垂直线 / 文字都只需一个锚点（都在可视范围内，拖一下即可）
            points = [[self._axis.index_to_date(x_max), y_mid]]

        try:
            item = self._store.upsert(make_annotation(
                self._symbol, kind, points, period=self._period, text=text))
        except ValueError as e:  # 锚点/文字非法 → 不落库、不画（绝不存一条画不出来的记录）
            logger.warning(f"新建标注失败: {e}")
            return None

        self.render()
        self.select(item["id"])
        self._notify()
        return item

    # ==========================================
    # 选中 / 删除
    # ==========================================
    @property
    def selected_id(self) -> str:
        return self._selected

    def select(self, item_id: str) -> None:
        """选中（空串 = 取消选中）。**逐个独立删除**就靠它定位目标。"""
        self._selected = str(item_id or "")
        for known_id in self._items:
            self._highlight(known_id)
        self._notify()      # 让页面刷新"删除选中"按钮的可用状态

    def delete(self, item_id: str) -> bool:
        """删除**指定**一条标注（存储 + 图元同时移除；复合标注连附属图元一起）。"""
        self._forget(item_id)
        removed = self._store.delete(self._symbol, self._period, item_id)
        if self._selected == item_id:
            self._selected = ""
        self._notify()
        return removed

    def delete_selected(self) -> bool:
        return self.delete(self._selected) if self._selected else False

    def clear_all(self) -> int:
        """清空当前标的的全部标注（页面侧需先向用户二次确认，§10-10）。"""
        removed = self._store.clear(self._symbol, self._period)
        self.clear_view()
        self._selected = ""
        self._notify()
        return removed

    def count(self) -> int:
        return self._store.count(self._symbol, self._period)

    # ==========================================
    # 内部：绘制 / 回写
    # ==========================================
    def _view_range(self):
        view_range = self._host.main_pane.view_box.viewRange()
        return (float(view_range[0][0]), float(view_range[0][1])), \
               (float(view_range[1][0]), float(view_range[1][1]))

    def _x(self, date_label):
        """日期 -> bar 序号；不在轴内返回 None（该条标注本次不画，绝不画到错位置）。"""
        position = self._axis.date_to_index(date_label)
        return None if position is None else float(position)

    def _pen(self, color: str, selected: bool = False, dashed: bool = False):
        return pg.mkPen(color=SELECTED_COLOR if selected else (color or DEFAULT_COLOR),
                        width=SELECTED_WIDTH if selected else LINE_WIDTH,
                        style=pg.QtCore.Qt.PenStyle.DashLine if dashed
                        else pg.QtCore.Qt.PenStyle.SolidLine)

    def _highlight(self, item_id: str) -> None:
        stored = self._store.get(self._symbol, self._period, item_id) or {}
        graphic = self._items.get(item_id)
        if graphic is None:
            return
        color = stored.get("color") or DEFAULT_COLOR
        selected = (item_id == self._selected)
        if isinstance(graphic, pg.TextItem):        # 文字没有 pen，改文字色
            graphic.setColor(SELECTED_COLOR if selected else color)
        else:
            graphic.setPen(self._pen(color, selected=selected))

    def _draw_item(self, item: dict):
        kind = item.get("kind")
        color = item.get("color") or DEFAULT_COLOR
        points = item.get("points") or []
        pane = self._host.main_pane

        if kind in (KIND_TREND, KIND_FIB) and len(points) == 2:
            x0, x1 = self._x(points[0][0]), self._x(points[1][0])
            if x0 is None or x1 is None:
                return None
            graphic = pg.LineSegmentROI(
                [[x0, float(points[0][1])], [x1, float(points[1][1])]],
                pen=self._pen(color, dashed=(kind == KIND_FIB)))
            # 斐波那契的各档水平位依赖这两个手柄 → 拖完要"回写 + 重画附属图元"
            handler = (self._rebuild if kind == KIND_FIB else self._persist_from_view)
            graphic.sigRegionChangeFinished.connect(lambda *_, i=item["id"]: handler(i))
            graphic.sigClicked.connect(lambda *_, i=item["id"]: self.select(i))
            if kind == KIND_FIB:
                self._draw_fib_levels(item, graphic)
        elif kind == KIND_TEXT and points:
            x = self._x(points[0][0])
            if x is None:
                return None
            graphic = _ClickableText(
                item.get("text") or "标注", color=color, anchor=(0.0, 0.5),
                on_click=lambda i=item["id"]: self.select(i),
                on_moved=lambda i=item["id"]: self._persist_from_view(i))
            graphic.setPos(x, float(points[0][1]))
            graphic.setToolTip(f"文字标注：{item.get('text') or ''}"
                               f"（拖动可移动、松手自动保存；点它选中，Delete 删除）")
        elif kind in (KIND_HLINE, KIND_VLINE) and points:
            if kind == KIND_HLINE:
                position, angle = float(points[0][1]), 0
            else:
                position = self._x(points[0][0])
                angle = 90
                if position is None:
                    return None
            graphic = pg.InfiniteLine(position, angle=angle, movable=True,
                                      pen=self._pen(color))
            graphic.sigPositionChangeFinished.connect(
                lambda *_, i=item["id"]: self._persist_from_view(i))
            graphic.sigClicked.connect(lambda *_, i=item["id"]: self.select(i))
        else:
            return None   # 未支持的 kind（如预留的文字）本次不画，也不报错

        pane.add_annotation(graphic)
        self._items[item["id"]] = graphic
        return graphic

    def _draw_fib_levels(self, item: dict, primary) -> None:
        """按主图元（ROI）的两个锚点画出**各档水平位 + 右侧标签**。

        这些是"附属图元"：必须登记进 `_extras`，删/清/重建时跟主图元一起处理，
        否则会留下"没人管的水平线"（§11.5-15 同类教训）。
        """
        points = self._points_from_graphic(item, primary) or []
        levels = fib_levels(points)
        if not levels:
            return
        x0, x1 = self._x(points[0][0]), self._x(points[1][0])
        if x0 is None or x1 is None:
            return
        pane = self._host.main_pane
        extras = []
        for index, (ratio, price) in enumerate(levels):
            color = FIB_COLORS[index % len(FIB_COLORS)]
            line = pg.PlotDataItem(
                [x0, x1], [price, price],
                pen=pg.mkPen(color, width=FIB_LEVEL_WIDTH,
                             style=pg.QtCore.Qt.PenStyle.DotLine))
            pane.add_annotation(line)
            extras.append(line)

            label = pg.TextItem(f"{ratio * 100:.1f}%  {price:.2f}", color=color,
                                anchor=(0.0, 1.0))
            label.setPos(x1, price)
            pane.add_annotation(label)
            extras.append(label)
        self._extras[item["id"]] = extras

    def _rebuild(self, item_id: str) -> None:
        """斐波那契专用：拖动结束 → 回写坐标 → 按新锚点重画各档水平位。"""
        self._persist_from_view(item_id)
        item = self._store.get(self._symbol, self._period, item_id)
        primary = self._items.get(item_id)
        if item is None or primary is None or item.get("kind") != KIND_FIB:
            return
        pane = self._host.main_pane
        for extra in self._extras.pop(item_id, []):
            pane.remove_annotation(extra)
        self._draw_fib_levels(item, primary)

    def _persist_from_view(self, item_id: str) -> None:
        """把用户拖动后的**真实坐标**回写到存储（松手后触发一次）。"""
        item = self._store.get(self._symbol, self._period, item_id)
        graphic = self._items.get(item_id)
        if item is None or graphic is None:
            return
        points = self._points_from_graphic(item, graphic)
        if not points:
            return
        item["points"] = points
        try:
            self._store.upsert(item)
        except ValueError as e:  # noqa: BLE001 —— 坐标异常时不写坏数据，保留原值
            logger.warning(f"标注回写失败: {e}")
            return
        self._notify()

    def _points_from_graphic(self, item: dict, graphic) -> list | None:
        kind = item.get("kind")
        view_box = self._host.main_pane.view_box
        if kind in (KIND_TREND, KIND_FIB):
            # ROI 两个手柄的场景坐标 -> 数据坐标 -> 日期
            scene_positions = [position for _handle, position
                               in graphic.getSceneHandlePositions()]
            if len(scene_positions) != 2:
                return None
            views = [view_box.mapSceneToView(position) for position in scene_positions]
            return [[self._axis.index_to_date(v.x()), float(v.y())] for v in views]
        if kind == KIND_HLINE:
            return [[item["points"][0][0], float(graphic.value())]]
        if kind == KIND_VLINE:
            return [[self._axis.index_to_date(graphic.value()), float(item["points"][0][1])]]
        if kind == KIND_TEXT:
            # 文字是自由摆放的：x 也要跟着走（拖到哪就存哪，不锁在原来的日期上）
            position = graphic.pos()
            return [[self._axis.index_to_date(position.x()), float(position.y())]]
        return None

    def _notify(self) -> None:
        if callable(self._on_changed):
            self._on_changed()
