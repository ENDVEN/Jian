# ui/widgets/desk_panel.py
"""行情工作台的「图标轨 + 分页面板」（v6.21 · §7-B6 STEP 4）—— **纯容器、零业务**。

【为什么独立成文件】`ui/views/trading_desk.py` 已 1216 行（§9-L 体积红线），
新能力一律落 `ui/widgets/*`（§10-12）；而且"图标轨 + 分页"与行情业务无关，
将来复盘页 / 数据管理页按 §10-14 收口时**可直接复用**。

【它只做三件事】① 竖向图标轨（互斥选中）；② 分页面板（每页一个**空容器**）；
③ 折起 / 展开。业务控件由页面自己 `addWidget` 搬进来 —— **容器不碰业务**，
所以它既不需要知道什么是"均线"，也不该自己去 new 任何业务控件。

【两条纪律（§10-14 / §11.5）】
  · 图标轨是 **L3 的入口**，只切换页，不做任何业务动作；
  · 控件"搬家"必须 `layout.addWidget(既有控件)`，**绝不重建** —— 否则信号连接全断、
    既有断言（按属性名访问控件）全废（1.22 已验证过这条）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget)

RAIL_WIDTH = 52
PANEL_MIN_WIDTH = 250
PANEL_MAX_WIDTH = 400
# 左栏折起时的总宽度 = 图标轨 + 左右间距（★STEP 4：折起必须**把宽度还给图表**）
RAIL_TOTAL_WIDTH = 60
# ⚠ 这是**"图标轨 + 面板"的合计宽**，不是面板自身的宽：
#   面板实际宽 = 398 - 52(图标轨) - 8(间距) = **338** —— 与 §7-B8 A 方案样板一致
#   （372 时代面板只有 312：分组胶囊一行放不下两个，虚胖。离屏渲染实测过）
PANEL_DEFAULT_WIDTH = 398

# 图标轨按钮：默认灰、选中蓝底 + 左侧竖条（与样板 A 的观感一致；样式只在本文件写一份）
RAIL_BTN_QSS = ("QPushButton { background: transparent; border: none; border-radius: 8px;"
                " color: #8A94A6; font-size: 16px; padding: 6px 0; }"
                "QPushButton:hover { background: #F2F5FA; color: #3C4552; }"
                "QPushButton:checked { background: #E8F2FE; color: #1976D2; font-weight: bold; }")
COLLAPSE_QSS = ("QPushButton { background: transparent; border: none; color: #8A94A6;"
                " font-size: 13px; padding: 2px 6px; border-radius: 6px; }"
                "QPushButton:hover { background: #F2F5FA; color: #1976D2; }")


class IconRail(QFrame):
    """竖向图标轨：互斥选中，点击只发信号（业务由页面决定）。"""

    sigClicked = pyqtSignal(str)

    def __init__(self, items, parent=None):
        """:param items: ``[(key, icon, tooltip), ...]``（顺序即显示顺序）"""
        super().__init__(parent)
        self.setObjectName("DeskIconRail")
        self.setFixedWidth(RAIL_WIDTH)
        self.setStyleSheet("QFrame#DeskIconRail { background: #FFFFFF;"
                           " border: 1px solid #E4E9F0; border-radius: 12px; }")
        self._buttons: dict[str, QPushButton] = {}
        self._order: list[str] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(4)
        for index, (key, icon, tooltip) in enumerate(items):
            button = QPushButton(icon)
            button.setCheckable(True)
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(RAIL_BTN_QSS)
            button.setToolTip(tooltip)
            button.setProperty("rail_key", key)
            self._group.addButton(button, index)
            lay.addWidget(button)
            self._buttons[key] = button
            self._order.append(key)
        lay.addStretch()
        self._group.idClicked.connect(self._on_clicked)

    # ---------- 对外 ----------
    def keys(self) -> list:
        return list(self._order)

    def button(self, key: str):
        return self._buttons.get(str(key))

    def set_current(self, key: str) -> bool:
        """把选中态对齐到某页（**幂等**：已经是它就不动）。"""
        button = self._buttons.get(str(key))
        if button is None:
            return False
        for other in self._buttons.values():
            other.setChecked(other is button)
        return True

    def current_key(self) -> str:
        for key, button in self._buttons.items():
            if button.isChecked():
                return key
        return ""

    # ---------- 内部 ----------
    def _on_clicked(self, index: int) -> None:
        if 0 <= index < len(self._order):
            self.sigClicked.emit(self._order[index])


class DeskPanel(QFrame):
    """分页面板：顶部一行（页名 + 折起按钮）+ 每页一个空容器。

    页面取到 `body(key)` 后往里 `addWidget(自己的控件)` 即可 —— 容器不碰业务。
    """

    sigCollapseRequested = pyqtSignal(str)      # 参数 = 当前页 key（页面据此记住状态）

    def __init__(self, items, parent=None):
        """:param items: ``[(key, title), ...]``（顺序即页顺序）"""
        super().__init__(parent)
        self.setObjectName("DeskPanel")
        self.setMinimumWidth(PANEL_MIN_WIDTH)
        self.setMaximumWidth(PANEL_MAX_WIDTH)
        self.setStyleSheet("QFrame#DeskPanel { background: #FFFFFF; border: 1px solid #E4E9F0;"
                           " border-radius: 12px; }")
        self._titles = {str(key): str(title) for key, title in items}
        self._order = [str(key) for key, _ in items]
        self._bodies: dict[str, QWidget] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.lbl_page = QLabel(self._titles.get(self._order[0], "") if self._order else "")
        self.lbl_page.setStyleSheet("font-size:12.5px; font-weight:bold; color:#3C4552;")
        head.addWidget(self.lbl_page)
        head.addStretch()
        self.btn_collapse = QPushButton("⇤ 折起")
        self.btn_collapse.setStyleSheet(COLLAPSE_QSS)
        self.btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collapse.setToolTip("折起工具面板，把宽度让给图表（点左侧图标可再展开）")
        self.btn_collapse.clicked.connect(
            lambda: self.sigCollapseRequested.emit(self.current_page()))
        head.addWidget(self.btn_collapse)
        lay.addLayout(head)

        self._stack = QStackedWidget()
        for key in self._order:
            holder = QWidget()
            holder_lay = QVBoxLayout(holder)
            holder_lay.setContentsMargins(0, 0, 0, 0)
            holder_lay.setSpacing(8)
            self._stack.addWidget(holder)
            self._bodies[key] = holder
        lay.addWidget(self._stack, 1)

    # ---------- 对外 ----------
    def keys(self) -> list:
        return list(self._order)

    def body(self, key: str) -> QWidget | None:
        """该页的**空容器**（页面把自己的控件 addWidget 进来）。"""
        return self._bodies.get(str(key))

    def body_layout(self, key: str):
        holder = self._bodies.get(str(key))
        return holder.layout() if holder is not None else None

    def show_page(self, key: str) -> bool:
        key = str(key)
        if key not in self._bodies:
            return False
        self._stack.setCurrentWidget(self._bodies[key])
        self.lbl_page.setText(self._titles.get(key, ""))
        return True

    def current_page(self) -> str:
        current = self._stack.currentWidget()
        for key, holder in self._bodies.items():
            if holder is current:
                return key
        return self._order[0] if self._order else ""

    def page_title(self, key: str) -> str:
        return self._titles.get(str(key), "")

    def set_page_title(self, key: str, text: str) -> None:
        key = str(key)
        if key in self._titles:
            self._titles[key] = str(text)
            if self.current_page() == key:
                self.lbl_page.setText(str(text))

    def stack(self) -> QStackedWidget:
        """只给断言/程序化检查用（业务代码请走 `show_page`）。"""
        return self._stack


class DeskPanelController:
    """左栏的"切页 / 折起"行为（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

    【为什么放在这里】图标轨 + 分页面板是**与行情业务无关的家具**（§10-14），
    "点图标切页 / 折起让宽度"自然跟着家具走；页面只保留**同名薄壳**。

    【约定】状态留页面：`desk_panel`（DeskPanel）、`rail`（IconRail）、`main_splitter`、
    `_desk_ui`（偏好）、`_panel_width_before`（折起前宽度）。本类只操作它们。
    """

    def __init__(self, page):
        self.page = page

    def on_rail_clicked(self, page_key: str) -> None:
        """点图标轨：若面板是折起的，先展开再切页（活动栏手感）。"""
        if self.is_panel_collapsed():
            self.set_panel_collapsed(False)
        self.show_rail_page(page_key)

    def show_rail_page(self, page: str) -> None:
        """切到某一页（工具行的 ✎ 入口也走这里）。"""
        p = self.page
        page = str(page or "watch")
        if not p.desk_panel.show_page(page):
            return
        p.rail.set_current(page)
        p._save_desk_ui(panel_page=page)

    def set_panel_collapsed(self, collapsed: bool) -> None:
        """折起/展开左栏面板（图标轨常驻，所以折起后仍能切页）。

        【为什么要手动调 splitter】QSplitter 记的是**绝对宽度**，子控件 `setVisible(False)`
        之后它不会主动把那段宽度让出去 —— 结果是"面板看不见了，左边却留一块空白"
        （离屏实测：折起前后图表宽度一模一样，1203 → 1203）。所以这里显式重排。

        【第二层（v6.22 补修）】`DeskPanel` 带 `setMinimumWidth(PANEL_MIN_WIDTH)`，
        而 QSplitter 用的是 `qSmartMinSize` —— 它把"显式最小宽度"与"**minimumSizeHint**"
        （面板内容撑出来的 343）取大 ⇒ 只 `setVisible(False)` / 只把 minWidth 归零都没用，
        左边仍留 ~340px 空白（离屏实测：折起后 left=269~403，而图标轨只要 60）。
        所以折起时**同时把 min/max 宽度压到 0**（Qt 会把 min 一起夹到 0），展开时还原。
        """
        p = self.page
        collapsed = bool(collapsed)
        if collapsed:
            p.desk_panel.setMinimumWidth(0)
            p.desk_panel.setMaximumWidth(0)
        else:
            p.desk_panel.setMinimumWidth(PANEL_MIN_WIDTH)
            p.desk_panel.setMaximumWidth(PANEL_MAX_WIDTH)
        splitter = getattr(p, "main_splitter", None)
        if splitter is not None:
            sizes = splitter.sizes()
            if len(sizes) == 2:
                total = max(sum(sizes), splitter.width())
                if collapsed:
                    p._panel_width_before = max(sizes[0], RAIL_TOTAL_WIDTH + 1)
                want_left = (RAIL_TOTAL_WIDTH if collapsed
                             else getattr(p, "_panel_width_before", PANEL_DEFAULT_WIDTH))
                splitter.setSizes([want_left, max(1, total - want_left)])
        p.desk_panel.setVisible(not collapsed)
        p._save_desk_ui(rail_collapsed=collapsed)

    def is_panel_collapsed(self) -> bool:
        """用 `isHidden()` 而不是 `isVisible()`：后者在"窗口本身没显示"（离屏/构造期）时也是 False。"""
        return self.page.desk_panel.isHidden()

    def toggle_panel_collapsed(self) -> None:
        self.set_panel_collapsed(not self.is_panel_collapsed())
