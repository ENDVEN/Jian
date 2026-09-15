# ui/widgets/backtest_summary_bar.py
"""
📐 回测页「配置摘要条」（1.22 · 样板 A · 渐进披露的 L2 层）。

【为什么要有它（用户实测反馈驱动）】
用户原话："函数段、条件段、大盘段占据了大量的软件页面篇幅……我基本不会变动了，
视觉停留主要还是在下半部分的回测数据部分，但现阶段页面把下面的回测数据压缩得太厉害了，
加了什么功能都会压缩下方回测数据部分的体积。"

根因不是"东西太多"，而是**所有区块同一优先级平铺**：低频高占地的配置区
（函数 / 条件 / 大盘门控 / 风控 / 成交）与高频长停留的结果区抢同一份纵向空间。

【本组件的定位】把"我到底配了什么"压成**一行可点的胶囊（chip）**：
  · 常显 = 状态摘要（不必展开就能确认配置，解决"看不见配置"的焦虑）；
  · 点击 = 请求展开对应编辑卡片（见 `backtest_panes.py`，手风琴：一次只开一张）；
  · 于是页面常态只剩「摘要条 1 行 + 结果区吃满剩余高度」。

【职责边界】纯展示 + 点击转发，**零业务逻辑**：
  显示什么由页面 `set_value()` 灌入（单一事实来源永远是各控件本身，这里不做二次判断）；
  点击只发信号，开/关由页面决定。

【为什么 chip 不用富文本】QPushButton 不渲染 HTML；用纯文本即可满足
"图标 + 名称 + 当前值"三要素，且天然支持键盘聚焦（无障碍更好）。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

_BAR_QSS = ("QFrame#SummaryBar { background: #FFFFFF; border: 1px solid #E7EAF0; "
            "border-radius: 12px; }")

# chip 四种状态：(底色, 边框, 字色)
_CHIP_STATES = {
    "on":  ("#FBFCFE", "#E7EAF0", "#3C4552"),
    "ok":  ("#F2FAF4", "#D6EEDA", "#256B34"),
    "off": ("#FAFBFC", "#E7EAF0", "#B4BECB"),
    "sel": ("#E8F2FE", "#A9C7EA", "#1257A8"),   # 当前展开的那张卡片
}
_CHIP_QSS = ("QPushButton {{ text-align: left; padding: 5px 12px; border-radius: 14px;"
             " background: {bg}; border: 1px solid {bd}; color: {fg};"
             " font-size: 12.5px; font-weight: 600; }}"
             "QPushButton:hover {{ border-color: #A9C7EA; background: #F4F9FF; }}")

_RUN_QSS = ("QPushButton { background: #1976D2; color: white; font-weight: bold;"
            " padding: 7px 20px; border: none; border-radius: 9px; font-size: 13.5px; }"
            "QPushButton:hover { background: #1565C0; }"
            "QPushButton:disabled { background: #B8C6D8; }")
_GHOST_QSS = ("QPushButton { color: #1976D2; background: transparent; border: 1px solid #BBDEFB;"
              " border-radius: 9px; padding: 6px 13px; font-weight: bold; font-size: 12.5px; }"
              "QPushButton:hover { background: #E3F2FD; }")


class SummaryBar(QFrame):
    """一行 chips：低频配置的"状态 + 入口"，也是 ▶ 运行的主操作位（样板 A）。"""

    # chip 被点击 → 页面展开/收起对应卡片（key 见 CHIPS）
    sig_chip_clicked = pyqtSignal(str)
    # 「⚙ 编辑配置」→ 页面打开上次用过的卡片
    sig_edit_clicked = pyqtSignal()

    # (key, 图标 + 名称) —— 固定顺序 = 用户配置时的心智顺序（先函数、再条件、后风控）
    CHIPS = (
        ("fn", "ƒ 函数"),
        ("cond", "⇄ 条件"),
        ("index", "📉 大盘门控"),
        ("risk", "🛡 风控"),
        ("fill", "🎯 成交"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SummaryBar")
        self.setStyleSheet(_BAR_QSS)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(8)

        self._chips: dict[str, QPushButton] = {}
        self._labels: dict[str, str] = {}
        self._states: dict[str, str] = {}
        self._active: str | None = None

        for key, label in self.CHIPS:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"查看 / 修改「{label.split(' ', 1)[-1]}」配置（点击展开，再点收起）")
            btn.clicked.connect(lambda _=False, k=key: self.sig_chip_clicked.emit(k))
            self._chips[key] = btn
            self._labels[key] = label
            self._states[key] = "on"
            lay.addWidget(btn)

        lay.addStretch()

        # 运行状态回执（原「运行条」的那句提示搬到这里，紧挨 ▶ 更符合"改完就看回执"）
        self.lbl_status = QLabel("完成检测并配置买卖条件后即可运行")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #1976D2;")
        lay.addWidget(self.lbl_status)

        self.btn_edit = QPushButton("⚙ 编辑配置")
        self.btn_edit.setStyleSheet(_GHOST_QSS)
        self.btn_edit.clicked.connect(self.sig_edit_clicked)
        lay.addWidget(self.btn_edit)

        self.btn_run = QPushButton("▶ 开始回测")
        self.btn_run.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run.setStyleSheet(_RUN_QSS)
        lay.addWidget(self.btn_run)

        self._apply_styles()

    # ---------- 对外接口（页面调用） ----------
    def set_value(self, key: str, text: str, state: str = "on"):
        """更新某个 chip 的"当前值"文案与状态色（on / ok / off）。"""
        if key not in self._chips:
            return
        self._chips[key].setText(f"{self._labels[key]}　{text}")
        self._states[key] = state if state in _CHIP_STATES else "on"
        self._apply_styles()

    def set_active(self, key: str | None):
        """高亮"当前正展开"的那张卡片对应的 chip（None = 全收起）。"""
        self._active = key
        self._apply_styles()

    def set_status(self, text: str):
        self.lbl_status.setText(text)

    def set_run_enabled(self, enabled: bool):
        self.btn_run.setEnabled(bool(enabled))

    # ---------- 内部 ----------
    def _apply_styles(self):
        for key, btn in self._chips.items():
            state = "sel" if key == self._active else self._states.get(key, "on")
            bg, bd, fg = _CHIP_STATES[state]
            btn.setStyleSheet(_CHIP_QSS.format(bg=bg, bd=bd, fg=fg))
