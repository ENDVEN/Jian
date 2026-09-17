# ui/widgets/watch_row_delegate.py
"""自选清单的**行绘制**（v6.24 · §7-B8 R15 / 2b 余项）：`名称 · 代码（右对齐）· 涨跌列`。

【为什么必须用 delegate，而不是往行里塞 widget】
  · `setItemWidget` 会**把选中高亮盖掉**（那个 widget 有自己的背景，且不参与
    `QListWidget` 的选中态绘制）—— 页面上"选了哪一行"就看不出来了；
  · 几十行各建一个 widget 比自绘**慢一个量级**；
  · delegate 是"自己画文字"⇒ 选中 / 悬停 / 键盘导航**全都还是原生行为**。

【数据从哪来】**全部写在 item 的 data role 上**（不在 delegate 里回查页面）：
delegate 只管画，页面只管填 —— 这样"行显示什么"是可断言的（读 role 即可）。
⚠ `ROLE_SYMBOL` 复用 `UserRole`：既有代码与断言都靠它取代码，**不许改成别的 role**。
"""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication, QStyle, QStyledItemDelegate

ROLE_SYMBOL = Qt.ItemDataRole.UserRole          # ⚠ 契约：既有代码靠它取代码
ROLE_CHANGE_TEXT = Qt.ItemDataRole.UserRole + 1  # 涨跌文本（"+1.23%" / "—"）
ROLE_CHANGE_DIR = Qt.ItemDataRole.UserRole + 2   # 方向：见下面四个常量

DIR_UP, DIR_DOWN, DIR_FLAT, DIR_UNKNOWN = 1, -1, 0, None

ROW_HEIGHT = 27
CHANGE_COLUMN_WIDTH = 56        # 涨跌列固定宽 ⇒ 各行小数点对齐（不随数字长短抖）
SYMBOL_COLUMN_WIDTH = 62        # 代码列固定宽 ⇒ 右对齐（用户点名要的）
PADDING = 10
# ⚠ **排序模式**下行首手柄带 `⣿` 的宽度 —— 这个数**必须只有一处**：
#   delegate 按它画手柄、列表按它判"这次按下算不算拖拽"（§7-B8 R15 的闸 2）。
#   两处各写一个数 ⇒ 画出来的手柄和能拖的区域错开（用户会觉得"拖不动"）。
HANDLE_WIDTH = 22

NAME_COLOR = "#3A4250"
NAME_COLOR_SELECTED = "#1565C0"
SYMBOL_COLOR = "#9AA4B2"
DIR_COLORS = {DIR_UP: "#4CAF50", DIR_DOWN: "#F44336", DIR_FLAT: "#5B6472"}
UNKNOWN_COLOR = "#C3CAD4"       # "—"：**没数据就说没数据**（不显示 0.00% 那种假数）
HANDLE_COLOR = "#9AA4B2"        # 排序模式下行首 `⣿` 手柄的颜色


def set_change(item, text: str, direction) -> None:
    """把涨跌写进行数据（页面填、delegate 读）。`direction` 用上面四个常量。"""
    item.setData(ROLE_CHANGE_TEXT, str(text or ""))
    item.setData(ROLE_CHANGE_DIR, direction)


def change_of(item) -> tuple:
    """读回 `(文本, 方向)`（断言用：行显示什么，读这里就知道）。"""
    return (str(item.data(ROLE_CHANGE_TEXT) or ""), item.data(ROLE_CHANGE_DIR))


class WatchRowDelegate(QStyledItemDelegate):
    """三段式画一行：名称（可省略号）· 代码（右对齐）· 涨跌（固定列，色随方向）。

    **排序模式**下额外在行首画一个 `⣿` 手柄 —— 它既是"现在能拖了"的视觉提示，
    也是闸 2 里"唯一能拖的热区"（否则用户根本不知道往哪按）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sort_mode = False

    def set_sort_mode(self, on: bool) -> None:
        self._sort_mode = bool(on)

    def is_sort_mode(self) -> bool:
        return self._sort_mode

    def sizeHint(self, option, index):          # noqa: N802
        return QSize(0, ROW_HEIGHT)

    def paint(self, painter, option, index):    # noqa: N802
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget is not None else QApplication.style()
        # 先让原生风格画**背景与选中态**（这一步不能省：省了就没有蓝底高亮）
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem,
                            option, painter, option.widget)

        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        symbol = str(index.data(ROLE_SYMBOL) or "")
        change_text = str(index.data(ROLE_CHANGE_TEXT) or "")
        direction = index.data(ROLE_CHANGE_DIR)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        right = option.rect.right() - PADDING

        # ① 最右：涨跌列（固定宽右对齐 ⇒ 各行小数点成一条线）
        if change_text:
            change_rect = option.rect.adjusted(
                option.rect.width() - PADDING - CHANGE_COLUMN_WIDTH, 0,
                -PADDING, 0)
            painter.setPen(QColor(DIR_COLORS.get(direction, UNKNOWN_COLOR)))
            font = QFont(option.font)
            font.setBold(direction in DIR_COLORS)
            painter.setFont(font)
            painter.drawText(change_rect, int(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter), change_text)
            right = change_rect.left()

        # ② 中间偏右：代码（右对齐，用户点名要求）
        if symbol:
            symbol_rect = option.rect.adjusted(
                max(option.rect.left(), right - SYMBOL_COLUMN_WIDTH - 8), 0, 0, 0)
            symbol_rect.setRight(right - 8)
            painter.setPen(QColor(SYMBOL_COLOR))
            font = QFont(option.font)
            font.setBold(False)
            font.setPointSizeF(max(7.5, option.font.pointSizeF() - 1.1))
            painter.setFont(font)
            painter.drawText(symbol_rect, int(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter), symbol)
            right = symbol_rect.left()

        # ②.5 排序模式：行首画 `⣿` 手柄（既是提示，也是闸 2 里唯一能拖的热区）
        name_left = PADDING
        if self._sort_mode:
            handle_rect = option.rect.adjusted(0, 0, 0, 0)
            handle_rect.setRight(option.rect.left() + HANDLE_WIDTH)
            painter.setPen(QColor(HANDLE_COLOR))
            font = QFont(option.font)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(handle_rect, int(Qt.AlignmentFlag.AlignCenter),
                             "⣿")
            name_left = HANDLE_WIDTH + 8

        # ③ 左侧：名称（放不下就省略号 —— 绝不把文字压到和代码叠在一起）
        name_rect = option.rect.adjusted(name_left, 0, 0, 0)
        name_rect.setRight(max(name_rect.left() + 20, right - 6))
        painter.setPen(QColor(NAME_COLOR_SELECTED if selected else NAME_COLOR))
        font = QFont(option.font)
        font.setBold(selected)
        painter.setFont(font)
        elided = QFontMetrics(font).elidedText(
            name, Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(name_rect, int(Qt.AlignmentFlag.AlignLeft
                                        | Qt.AlignmentFlag.AlignVCenter), elided)
        painter.restore()
