# ui/widgets/chart_pane.py
"""
图表宿主的「单个窗格」最小抽象（§7-B3 B② · P0）。

【为什么要有这个文件 · §7-B3 D1】
  §7-B3 的渲染器 `OverlayPainter` 需要一个「宿主」来挂载图元。如果直接传裸
  `PlotItem`，就等于把渲染器**写死成单图** —— 一旦后面要加副图（P5）、行情页
  公式叠层（P4）、复盘 K 线回放复用，三处都得返工。因此 **P0 必须早于 P3**：
  先把「一个窗格」抽象出来，渲染器只认 `ChartPane`。

【一个 pane 是什么】
  一个 `PlotItem`（窗格本体）+ 两个互不混用的容器：
    · 公式叠层（管线 A）—— 随数据/参数重算，**不持久**（OverlayPainter 负责往这里放）；
    · 用户标注（管线 B）—— 持久到 (标的, 周期)，**逐个可删**（P6 才实现）。
  二者只共用这块舞台，禁止混进同一个数据结构（§7-B3 C）。

【纪律】
  · 本模块**只做容器与坐标下沉**，不含任何业务逻辑、不读数据、不发网络。
  · 全 app 需要「在一个窗格上挂图元」的地方，一律经 `ChartPane`；
    禁止业务页面直接对 `PlotItem.addItem` 反复施加无主的图元（会漏清理、会错位）。
"""
from __future__ import annotations

import pyqtgraph as pg


class ChartPane:
    """一个图表窗格 = PlotItem + 公式叠层容器 + 用户标注容器。

    :param target:   `pg.PlotItem` / `pg.PlotWidget` / 另一个 `ChartPane`
    :param name:     窗格名（如 'main' / 'vol' / 'macd'），供宿主与调试定位
    :param role:     'main'（主图）| 'sub'（副图）
    """

    def __init__(self, target, name: str = "main", role: str = "main"):
        if isinstance(target, ChartPane):
            target = target.plot_item
        # 持有源对象强引用：PlotItem 的 C++ 对象归它的宿主控件所有，
        # 若调用方只传了 `pg.PlotWidget()` 而自己不留引用，Python 侧一 GC，
        # ViewBox 就被销毁，后续 addItem 会报 "wrapped C/C++ object ... has been deleted"。
        self._source = target
        if isinstance(target, pg.PlotWidget):
            target = target.getPlotItem()
        if not isinstance(target, pg.PlotItem):
            raise TypeError(
                f"ChartPane 需要一个 pyqtgraph PlotItem 或 PlotWidget，收到 {type(target).__name__}")

        self._plot_item: pg.PlotItem = target
        self.name = name
        self.role = role
        self._overlay_items: list = []      # 管线 A：公式叠层（可整体清理）
        self._annotation_items: list = []   # 管线 B：用户标注（P6 接线）

    # ---------------- 基本访问 ----------------
    @property
    def plot_item(self) -> pg.PlotItem:
        """窗格本体。渲染器可以据此取 ViewBox / 设置范围，但**不应**绕过本类长期持有。"""
        return self._plot_item

    @property
    def view_box(self):
        return self._plot_item.getViewBox()

    @classmethod
    def wrap(cls, target, name: str = "main", role: str = "main") -> "ChartPane":
        """宽容入口：已经是 ChartPane 就原样返回，否则包一层。"""
        if isinstance(target, ChartPane):
            return target
        return cls(target, name=name, role=role)

    # ---------------- 管线 A：公式叠层 ----------------
    def add_overlay(self, item):
        """把一个绘图图元挂到本窗格（由 OverlayPainter 调用），返回该图元。"""
        self._plot_item.addItem(item)
        self._overlay_items.append(item)
        return item

    def clear_overlays(self):
        """清空所有公式叠层图元（换公式 / 重渲染时调用）。"""
        for item in self._overlay_items:
            try:
                self._plot_item.removeItem(item)
            except Exception:  # noqa: BLE001 —— 已移除/未挂载时不致命，继续清理
                pass
        self._overlay_items.clear()

    @property
    def overlay_items(self) -> list:
        return list(self._overlay_items)

    # ---------------- 管线 B：用户标注（P6 占位） ----------------
    def add_annotation(self, item):
        """挂一个用户标注图元（P6 实现交互与持久化；此处仅提供对称容器）。"""
        self._plot_item.addItem(item)
        self._annotation_items.append(item)
        return item

    def clear_annotations(self):
        for item in self._annotation_items:
            try:
                self._plot_item.removeItem(item)
            except Exception:  # noqa: BLE001
                pass
        self._annotation_items.clear()

    @property
    def annotation_items(self) -> list:
        return list(self._annotation_items)
