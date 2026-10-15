# ui/widgets/breadth_items.py
"""📋 M3「统计项」面板：一行一个**判定变量**（★1.73 / §7-B16 期 1）。

【它解决的问题】同一段公式常含多个可判定变量（如"情绪≥80"与"情绪<20"），而过去一次扫描
  只能看**一个** —— 想看两个极端就得扫两遍，还无法同屏对比（用户 2026-10-12 的原话：
  "我想看看这两个极端数据到底跟上证指数有什么关系"）。现在内核**一次扫描全部拿到**
  （`scan(..., signal_names=[…])`），本面板只负责三件事：
  **哪些上屏 · 各自什么颜色 · 谁是焦点**。

【状态在哪】列表本体在**页面**（`p._items`）—— 本面板只渲染 + 发请求信号（§7-B16 约定：
  widgets 模块不自己存副本，只读写 `p.X`）。每项 = `{'key','label','color','visible'}`。
  面板**不改** `p._items`：改由 `breadth_flow` 落地（唯一写入点，§9-D），改完回灌
  `set_items()` 重画 —— 这样"面板显示"与"真实状态"不可能分叉。

【为什么竖排（每项一行）而不是平铺 chips】抽屉宽度只有 525~640（§11.5-127 实测），
  横排 3~4 个 chip 就会被压到截断；**窄容器默认竖排**是本项目的排版纪律。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from ui.widgets.breadth_rows import ROW_COLORS
from ui.widgets.gate_hint import verdict_badge
from ui.widgets.styles import FLAT_QSS

__all__ = ['BreadthItemsPanel', 'MAX_ITEMS']

# 上屏上限（设计稿「布局统筹规则表」的 7~12 档：**焦点行 + 迷你条**，行区自己滚动）。
#   ★1.73 收尾：6 → **12** —— 设计稿那一档原本就是"两列网格 **或** 焦点 + 迷你"二选一，
#   本版选**焦点 + 迷你**（已实现：焦点置顶 + 3 倍高、行区竖向滚动），所以上限可以放到 12；
#   \>12 项按设计稿走"折叠"（硬上限 + 明确提示，不做假入口）。
MAX_ITEMS = 12


def _small_btn(text: str, tip: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(FLAT_QSS)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tip)
    btn.setFixedWidth(28)
    return btn


class BreadthItemsPanel(QWidget):
    """统计项列表（渲染 + 请求信号）。**不持有状态**。"""

    add_requested = pyqtSignal(str)          # 判定变量名
    remove_requested = pyqtSignal(str)
    toggle_visible_requested = pyqtSignal(str)
    focus_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._available: list[str] = []
        self._items: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self.body = QWidget()
        self._body_lay = QVBoxLayout(self.body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(3)
        root.addWidget(self.body)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.cb_add = QComboBox()
        self.cb_add.setMinimumWidth(150)
        self.cb_add.setToolTip('从**这段公式**的可判定变量里挑一个上屏（同一段公式一次扫描全部拿到）')
        row.addWidget(self.cb_add, 1)
        self.btn_add = QPushButton('＋ 添加统计项')
        self.btn_add.setStyleSheet(FLAT_QSS)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self._on_add)
        row.addWidget(self.btn_add)
        root.addLayout(row)

        self.lbl_hint = QLabel('')
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet('font-size: 11px; color: #8A94A6;')
        root.addWidget(self.lbl_hint)

    # ==========================================
    # 喂数据（页面 → 面板，单向）
    # ==========================================
    def set_available(self, signals) -> None:
        """这段公式里**可当判定变量**的名字（`core.cross_section.signal_names(公式)`）。"""
        self._available = [str(s) for s in (signals or [])]
        used = {str(it.get('key') or '') for it in self._items}
        self.cb_add.blockSignals(True)
        self.cb_add.clear()
        for name in self._available:
            if name not in used:
                self.cb_add.addItem(name, name)
        self.cb_add.blockSignals(False)
        self.cb_add.setEnabled(self.cb_add.count() > 0 and len(self._items) < MAX_ITEMS)
        self.btn_add.setEnabled(self.cb_add.count() > 0 and len(self._items) < MAX_ITEMS)

    def set_items(self, items) -> None:
        """按页面的**唯一真源**重画（每项 `{'key','label','color','visible'}`）。"""
        self._items = [dict(it) for it in (items or [])]
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not self._items:
            empty = QLabel('还没有统计项 —— 从上面选一个判定变量「＋ 添加」，'
                           '就会多出一行（与指数副图共享同一条 x 轴）')
            empty.setWordWrap(True)
            empty.setStyleSheet('font-size: 11.5px; color: #8A94A6;')
            self._body_lay.addWidget(empty)
        for it in self._items:
            self._body_lay.addWidget(self._make_row(it))
        n = len(self._items)
        _extra = (f' · 已 {n} 项：行区<b>自己滚动</b>（指数副图固定贴底、不会被压扁）；'
                  f'点任一项的 ★ 设为焦点行（置顶 + 3 倍高）'
                  if n >= 4 else '')
        self.lbl_hint.setText(
            f'已上屏 {n} 项（上限 {MAX_ITEMS}）· 每项一行：柱 = 当天占比（可在展示里切家数）、'
            f'线 = 5 周均 · ★ = 焦点行（置顶且更高）· 同一段公式的多个判定变量'
            f'<b>一次扫描</b>全部拿到。{_extra}' if n else '')
        self.set_available(self._available)          # 已用项从下拉里去掉

    def _make_row(self, it: dict) -> QWidget:
        key = str(it.get('key') or '')
        visible = bool(it.get('visible', True))
        focus = bool(it.get('focus', False))
        row = QFrame()
        row.setObjectName('ItemRow')
        row.setStyleSheet(
            '#ItemRow { background: %s; border: 1px solid %s; border-radius: 8px; }'
            % ('#F2F8FF' if focus else '#FFFFFF', '#BBDEFB' if focus else '#E7EAF0'))
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 4, 6, 4)
        lay.setSpacing(6)
        dot = QLabel('●')
        dot.setStyleSheet(f"color: {it.get('color') or ROW_COLORS[0]}; font-size: 13px;")
        lay.addWidget(dot)
        name = QLabel(str(it.get('label') or key))
        name.setToolTip(f'判定变量 `{key}`（公式里的一条输出；扫描时取的信号就是它）')
        name.setStyleSheet('font-size: 12px;' + ('' if visible else ' color: #B4BECB;'))
        lay.addWidget(name, 1)
        # ★1.74 期 2：**三道闸徽标**（"这个条件能不能用事件对齐图看"一眼可见）——
        #   文案/颜色/判据全部来自 `gate_hint.verdict_badge`（判据在 `core.relation_stats`），
        #   本面板只贴一个标签，绝不自己判阈值。
        _text, _tip, _color = verdict_badge(it.get('verdict'))
        badge = QLabel(_text)
        badge.setToolTip(_tip)
        badge.setStyleSheet(f'font-size: 10.5px; color: {_color}; border: 1px solid {_color};'
                            ' border-radius: 7px; padding: 0px 5px;')
        lay.addWidget(badge)
        btn_vis = _small_btn('👁' if visible else '🚫',
                             '显示 / 隐藏这一行（隐藏 = 不上屏，**不重扫**）')
        btn_vis.clicked.connect(lambda _c=False, k=key: self.toggle_visible_requested.emit(k))
        lay.addWidget(btn_vis)
        btn_focus = _small_btn('★' if focus else '☆',
                               '设为焦点行（置顶 + 约 1.6 倍高；再点一次取消）')
        btn_focus.clicked.connect(lambda _c=False, k=key: self.focus_requested.emit(k))
        lay.addWidget(btn_focus)
        btn_del = _small_btn('✕', '从本页移除这一项（**不重扫**；公式本身不变）')
        btn_del.clicked.connect(lambda _c=False, k=key: self.remove_requested.emit(k))
        lay.addWidget(btn_del)
        return row

    def _on_add(self) -> None:
        key = str(self.cb_add.currentData() or '')
        if key:
            self.add_requested.emit(key)

    # ---------- 面板自己的状态（只读给断言用；**业务状态的真源永远在页面** `p._items`）----------
    #   ⚠ ★1.74 复核删掉了 `item_keys()` / `available_options()` 两个零引用的方法：
    #     面板不持业务状态，需要"现在上屏了哪几项"请问页面（`p._items`）或图（`chart.row_keys()`）。
