# ui/widgets/watch_sort_list.py
"""自选清单的**拖拽排序列表**（v6.24 · §7-B8 R15）—— 用"三道闸"防误触。

【为什么不是简单开 `InternalMove`】用户原话："对于分组内容比较少的面板 ⬆⬇ 完全够用，
但是**大分组或许就不够了**，所以请你也看看后续能不能搞个**拖拽**……但是请你一定要考虑
用户**误触**的情况，所以拖拽这种情况最好**有个判断**。"

三道闸（核心思路 = **让"拖"与"点"在物理上分开**）：
  1. **先进入排序模式**：平时是 `NoDragDrop` ⇒ 列表**根本不响应拖动**，浏览时手滑不会
     改动任何顺序（闸 1 由 `set_sort_mode` 控制）；
  2. **只认行首 `⣿` 手柄**：`mousePressEvent` 记住"这次按下是不是落在手柄带里"，
     `startDrag` 不满足就**直接吞掉** ⇒ "点行"与"拖行"是两个完全不同的热区；
  3. **可撤销**：由页面负责（进排序模式时拍一张顺序快照，撤销就照它回写）。

【为什么刻意用"撤销"而不是"二次确认弹窗"】拖拽本身已是明确意图，每次拖完弹窗会很烦；
而"撤销"对"拖歪了一格"最有效、且不打断心流（见 §7-B8 R15 的设计说明）。

【⚠ 大列表最容易被漏掉的一条】**边缘自动滚动**：拖到列表可视区上下边缘时要自动滚动，
否则几十只的列表根本拖不到远处。Qt 的 `setAutoScroll(True)` + `autoScrollMargin` 就是它
（默认虽为 True，但**显式写出来**才不会被后人误关）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QListWidget

# 手柄带宽度**从 delegate 引**（它才是行布局的主人）——
# 两边各写一个数会导致"画出来的手柄"与"能拖的区域"错开，用户会觉得"拖不动"
from ui.widgets.watch_row_delegate import HANDLE_WIDTH


class DragHandleListWidget(QListWidget):
    """只从行首 `⣿` 手柄发起拖动的列表（闸 1 + 闸 2 都在这里，闸 3 在页面）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sort_mode = False
        self._drag_armed = False        # 本次按下是否落在手柄带里
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # 落位提示线：Qt 原生画（拖到上半 ⇒ 插前面，下半 ⇒ 插后面）
        self.setDropIndicatorShown(True)
        # ⚠ 边缘自动滚动（大列表能否拖到远处全靠它）
        self.setAutoScroll(True)
        self.setAutoScrollMargin(24)
        self.set_sort_mode(False)

    # ---- 闸 1：排序模式 ----
    def is_sort_mode(self) -> bool:
        return self._sort_mode

    def set_sort_mode(self, on: bool) -> None:
        """进 / 出排序模式。**平时必须完全不能拖**（这就是闸 1 的全部意义）。"""
        self._sort_mode = bool(on)
        self._drag_armed = False
        if self._sort_mode:
            self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.setAcceptDrops(True)
        else:
            self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            self.setAcceptDrops(False)
        self.viewport().update()

    # ---- 闸 2：只认手柄 ----
    def is_drag_armed(self) -> bool:
        """本次按下是否"武装"了拖拽（供断言与人眼核对）。"""
        return bool(self._drag_armed)

    def _hit_handle(self, point) -> bool:
        item = self.itemAt(point)
        if item is None:
            return False
        return (point.x() - self.visualItemRect(item).left()) <= HANDLE_WIDTH

    def mousePressEvent(self, event):           # noqa: N802
        point = event.position().toPoint()
        # ⚠ 判据是"**按下点**"而不是"松开点"：拖拽由 press 之后的手势决定，
        #   用松开点判会在手指移动过程里产生"从手柄起、却因为在行中部松手而不拖"的怪现象
        self._drag_armed = bool(self._sort_mode and event.button() == Qt.MouseButton.LeftButton
                                and self._hit_handle(point))
        super().mousePressEvent(event)

    def startDrag(self, supported_actions):     # noqa: N802
        if not (self._sort_mode and self._drag_armed):
            return          # 闸 2：不是从 ⣿ 起的拖 —— **吞掉**，什么都不发生
        super().startDrag(supported_actions)
