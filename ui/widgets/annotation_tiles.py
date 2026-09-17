# ui/widgets/annotation_tiles.py
"""画线类型目录的**可视件**（v6.24 · §7-B8 R10/R11）。

三件东西：
  · `CategoryHeader` —— 分类标题（**分类色条 + 名称 + 条数**，色相是"让 32 种不乱"的关键）；
  · `AnnotationTile` —— 一个类型：`图标 · 名称 · 编号`（未实现的额外带「待实现」小标）；
  · `StickyScrollArea` —— 带**吸顶分类标题**的滚动区（R11 第 4 条）。

【尺寸纪律】面板高度**不随类型数增长**（R11 硬指标）：滚动区由页面给一个固定高度，
新增类型只是列表变长 —— 这正是用户要的"**避免后续随着类型变多影响观感**"。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                             QVBoxLayout, QWidget)

from ui.widgets.annotation_icons import ICON_H, ICON_W, make_icon
from ui.widgets.custom_widgets import ClickFrame

TILE_HEIGHT = 46
TILE_MIN_WIDTH = 132

_TILE_QSS = (
    "QFrame#AnnoTile { background:#FFFFFF; border:1px solid #E8EDF4; border-radius:8px; }"
    "QFrame#AnnoTile:hover { background:#F7FBFF; border-color:#A9C7EA; }"
    "QFrame#AnnoTile QLabel { border:none; background:transparent; }"
    "QLabel#AnnoTileName { font-size:10.6px; color:#3A4250; }"
    "QLabel#AnnoTileNum { font-size:9px; color:#B6BEC9; font-weight:700; }"
    "QLabel#AnnoTileTodo { font-size:9px; color:#8A94A6; }")
_TILE_QSS_ON = (
    "QFrame#AnnoTile { background:#E8F2FE; border:1px solid #BBDEFB; border-radius:8px; }"
    "QFrame#AnnoTile QLabel { border:none; background:transparent; }"
    "QLabel#AnnoTileName { font-size:10.6px; font-weight:800; color:#1565C0; }"
    "QLabel#AnnoTileNum { font-size:9px; color:#1976D2; font-weight:700; }"
    "QLabel#AnnoTileTodo { font-size:9px; color:#8A94A6; }")
_TILE_QSS_TODO = (
    "QFrame#AnnoTile { background:#FBFCFE; border:1px dashed #DFE6EF; border-radius:8px; }"
    "QFrame#AnnoTile:hover { background:#F4F7FB; border-color:#C9D6E5; }"
    "QFrame#AnnoTile QLabel { border:none; background:transparent; }"
    "QLabel#AnnoTileName { font-size:10.6px; color:#8A94A6; }"
    "QLabel#AnnoTileNum { font-size:9px; color:#C3CAD4; font-weight:700; }"
    "QLabel#AnnoTileTodo { font-size:9px; color:#B08A5A; }")

HEADER_QSS = ("QLabel#CategoryHeader { color:#FFFFFF; font-size:11px; font-weight:800;"
              " padding:3px 8px; border-radius:5px; background:%s; }")


class CategoryHeader(QLabel):
    """分类标题（分类色条 + 名称 + 条数）—— 滚动时会被 `StickyScrollArea` 克隆到顶部吸住。"""

    def __init__(self, name: str, count: int, color: str, parent=None):
        super().__init__(f"{name}　{count} 种", parent)
        self.setObjectName("CategoryHeader")
        self.setStyleSheet(HEADER_QSS % color)
        self.color = color
        self.setFixedHeight(22)


class AnnotationTile(ClickFrame):
    """一个画线类型：图标（语义示意）+ 名称 + 编号；未实现的带「待实现」小标。"""

    sigPick = pyqtSignal(str)

    def __init__(self, entry: dict, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("AnnoTile")
        self.kind = str(entry.get("kind") or "")
        self.number = int(entry.get("num") or 0)
        self.implemented = bool(entry.get("implemented"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(TILE_MIN_WIDTH)
        self.setFixedHeight(TILE_HEIGHT)
        self.setToolTip(self._tooltip(entry))

        col = QVBoxLayout(self)
        col.setContentsMargins(7, 5, 7, 5)
        col.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(4)
        icon = QLabel()
        # 未实现的也用**分类色**画图标（"它将来长什么样"照样一眼看得出），只是整体淡化
        icon.setPixmap(make_icon(str(entry.get("icon") or ""),
                                 color if self.implemented else "#C3CAD4", ICON_W, ICON_H))
        top.addWidget(icon)
        top.addStretch()
        self._todo = QLabel("" if self.implemented else "待实现")
        self._todo.setObjectName("AnnoTileTodo")
        top.addWidget(self._todo)
        self._num = QLabel(str(self.number))
        self._num.setObjectName("AnnoTileNum")
        top.addWidget(self._num)
        col.addLayout(top)

        self._name = QLabel(str(entry.get("name") or ""))
        self._name.setObjectName("AnnoTileName")
        col.addWidget(self._name)

        self._selected = False
        self.set_selected(False)
        self.sigClicked.connect(lambda: self.sigPick.emit(self.kind))

    @staticmethod
    def _tooltip(entry: dict) -> str:
        key = "① ~ ⑨ 可直接按数字键切换（快捷键）" if 1 <= int(entry.get("num") or 0) <= 9 else ""
        if entry.get("implemented"):
            return f"{entry.get('name')}（编号 {entry.get('num')}）\n选中后在图上点「➕ 添加标注」。\n{key}"
        return (f"{entry.get('name')}（编号 {entry.get('num')}）· **待实现**\n"
                f"它已在目录里登记（这样你知道它会归到哪一类），但**现在还不能画**。\n{key}")

    def set_selected(self, value: bool) -> None:
        self._selected = bool(value)
        if not self.implemented:
            self.setStyleSheet(_TILE_QSS_TODO)
        else:
            self.setStyleSheet(_TILE_QSS_ON if self._selected else _TILE_QSS)

    def is_selected(self) -> bool:
        return self._selected

    def name_text(self) -> str:
        return self._name.text()

    def todo_text(self) -> str:
        return self._todo.text()


class StickyScrollArea(QScrollArea):
    """带**吸顶分类标题**的滚动区。

    【为什么要吸顶】32 种分 6 类，滚动时"当前这类叫什么、什么颜色"必须一直看得见 ——
    否则用户滚到一半就丢了参照（R11 四件事里的第 4 条）。
    实现 = 在视口上浮一个**标题克隆**：只当"该类的真实标题已滚出视口上沿"时才出现，
    所以正常滚动时不会看到两个标题打架。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sections: list = []          # [(y, 文本, 颜色), ...]
        self._float = QLabel(self.viewport())
        self._float.setObjectName("StickyCategory")
        self._float.setVisible(False)
        self._float.raise_()
        self.verticalScrollBar().valueChanged.connect(self._sync_sticky)

    def set_sections(self, sections) -> None:
        """登记"每个分类标题在容器里的 y 坐标"（容器布局完成后调用一次）。"""
        self._sections = sorted(sections, key=lambda item: item[0])
        self._sync_sticky()

    def sticky_text(self) -> str:
        return self._float.text() if self._float.isVisibleTo(self) else ""

    def _sync_sticky(self, *_):
        top = self.verticalScrollBar().value()
        current = None
        for y, text, color in self._sections:
            # ⚠ 判据是**严格小于** `top`：滚到最上面（top=0、标题 y=0）时真实标题就在眼前，
            #   再浮一个克隆会出现"两个标题打架"（实测踩到）。只有它**被滚出去**才吸顶。
            if y < top:
                current = (text, color)
        if current is None:
            self._float.setVisible(False)
            return
        text, color = current
        self._float.setText(text)
        self._float.setStyleSheet(
            f"background:{color}; color:#FFFFFF; font-size:11px; font-weight:800;"
            f" padding:3px 8px; border-bottom-right-radius:6px;")
        self._float.setGeometry(0, 0, self.viewport().width(), 22)
        self._float.raise_()
        self._float.setVisible(True)

    def resizeEvent(self, event):          # noqa: N802
        super().resizeEvent(event)
        self._sync_sticky()


def build_catalog_widget(tiles: dict, headers: dict, on_pick) -> QWidget:
    """装配"6 类 × N 种"的目录容器。

    :param tiles:   出参：`{kind: AnnotationTile}`（页面留作同步选中态用）
    :param headers: 出参：`{分类键: CategoryHeader}`
    :param on_pick: 点某个类型时的回调（**走页面既有的 `select_tool` 入口**，
                    不另开一条行为路径 —— §11.5-11）
    """
    from ui.widgets import annotation_catalog as catalog

    container = QWidget()
    col = QVBoxLayout(container)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(6)
    for key, name, color, items in catalog.grouped():
        header = CategoryHeader(name, len(items), color)
        headers[key] = header
        col.addWidget(header)
        grid = QGridLayout()
        grid.setSpacing(5)
        grid.setContentsMargins(0, 0, 0, 0)
        for index, entry in enumerate(items):
            tile = AnnotationTile(entry, color)
            tile.sigPick.connect(on_pick)
            tiles[tile.kind] = tile
            grid.addWidget(tile, index // 2, index % 2)
        col.addLayout(grid)
    col.addStretch()
    return container
