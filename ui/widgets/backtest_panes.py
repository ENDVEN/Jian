# ui/widgets/backtest_panes.py
"""
📐 回测页「编辑卡片 + 配置抽屉」（1.22 · 样板 A 的 L3 层 · §9-L 拆分）。

【版式定位】配置区按"使用频率 × 视线停留"分层的第 3 层：
  L0 结果区（常驻吃满）→ L1 工具栏/区间（一行）→ **L2 摘要条（一行 chips）**
  → **L3 本文件的五张卡片 + `EditDrawer` 右侧遮罩抽屉**。
  卡片默认不在页面上出现，点摘要条胶囊才由抽屉**浮**出来（覆盖层，不动页面布局），
  所以结果区高度自始至终不变 —— 这正是"把空间还给回测结果"的落点。

【为什么是抽屉而不是"就地展开"】用户实测拍板：就地展开会把结果区挤矮、卡片撑满整页，
**不好看**；抽屉浮在上面既保留样板 A 的观感，又完全不占用结果区空间。

【本文件与页面的分工】
  本文件 = **纯视图**：只负责把控件建出来、摆整齐、暴露成属性；
  页面（`ui/views/backtest.py`） = **唯一的接线者与业务方**：
  连信号、读配置（`_risk_config` / `_fill_config` / `ConditionGate.config()`）、落盘。
  这样卡片可以被 `tests/smoke_pages_overlay.py` 通过页面属性照常访问
  （页面把控件暴露为同名属性），重构不改变既有断言口径。

【五张卡片 = 摘要条五个 chip 的一一对应】
  fn    ƒ 函数          → FunctionPane    （低频：一次粘贴后基本不动）
  cond  ⇄ 买卖条件      → ConditionPane   （中频：逻辑经常微调）
  index 📉 大盘门控      → IndexPane       （低频：多数人不开）
  risk  🛡 风控离场      → RiskPane        （中频：定了就不常动）
  fill  🎯 成交模型      → FillPane        （中频：v6.17/§7-B5 新增）
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QFrame, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QScrollArea,
                             QStackedWidget, QVBoxLayout, QWidget)

from config import settings
from core.backtest import FILL_CLOSE, FILL_MODE_LABELS, FILL_NEXT_OPEN, FILL_TRIGGER
from data.akshare_feed import INDEX_PRESETS
from ui.widgets.condition_gate import ConditionGate
# ⚠ 后 4 个是**再导出**：`mini_label` / `hint_icon` / `TAB_QSS_*` 的**定义**已于 v6.21
# 上收到 `custom_widgets.py`（§7-B6 STEP 1，样式/构件单一来源）。这里 import 进来只为
# **保持既有导入路径不变** —— `ui/views/backtest.py` 仍从本模块 import 它们，断言零改动。
from ui.widgets.custom_widgets import (COMBO_QSS, FLAT_QSS, NoWheelComboBox,  # noqa: F401
                                       NoWheelDoubleSpinBox, SPINBOX_QSS,
                                       TAB_QSS_OFF, TAB_QSS_ON,  # noqa: F401（再导出）
                                       hint_icon, mini_label)    # noqa: F401（再导出）
from ui.widgets.function_segments import FunctionSegments

# ==========================================
# 共享样式（原先散在页面 _setup_ui 里就地写死，现收敛到这里一份）
# ==========================================
CARD_QSS = "QFrame { background: white; border: 1px solid #E7EAF0; border-radius: 12px; }"

# ★v6.70 / §9-F③：`FLAT_QSS` 的定义已上收到 `custom_widgets.flat_qss()`（唯一出口）——
#   它名字不带“回测”却全站 6 处在引，放在这里就是归属漂移的本体；本模块只从那里 import。

ACTION_QSS = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; "
              "border-radius:8px; padding:4px 10px; font-weight:bold; color:#424242; }"
              "QPushButton:hover { background:#EDEDED; }")

SEND_QSS = ("QPushButton { background:#E8F1FF; border:1px solid #BBDEFB; border-radius:8px; "
            "padding:4px 10px; font-weight:bold; color:#1976D2; }"
            "QPushButton:hover { background:#D6E8FF; }")

DETECT_QSS = ("QPushButton { background:#E8F1FF; color:#1976D2; font-weight:bold; "
              "padding:4px 14px; border-radius:8px; border:none;}"
              "QPushButton:hover{background:#D6E8FF;}"
              "QPushButton:disabled{background:#F0F3F8; color:#A7AEBE;}")




# ==========================================
# 表单小构件
# ==========================================
# `mini_label` / `hint_icon` 已上收到 `ui/widgets/custom_widgets.py`（v6.21 · §7-B6 STEP 1），
# 本文件只负责再导出（见文件顶部 import）。下一条 `number_spin` 仍属回测页专属（风控/成交参数口径）。
def number_spin(tooltip: str, value: float, lo: float, hi: float,
                decimals: int) -> NoWheelDoubleSpinBox:
    """带说明的数值输入框（回测页所有风控/成交参数都用它，样式与步长同源）。

    【v6.18 修 · 用户实测倒逼】步长必须跟着**小数位**自适应，不能写死。
    历史 Bug：原先写死 `1 if decimals == 0 else 0.5`，对"2 位小数"的控件
    （成交模型的「买卖价要多等」，范围 0.01~1.00）按一次上箭头就 +0.5 → 被上限夹住，
    用户反馈：「直接跳到 0.2 并且无法继续上调，没有过渡价格」。
    规则：0 位 → 1；1 位 → 0.5；≥2 位 → 10^-decimals（2 位即 0.01，与 A股最小变动价一致）。
    """
    spin = NoWheelDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSingleStep(1 if decimals == 0 else (0.5 if decimals == 1 else 10.0 ** -decimals))
    # 宽度留足：原生箭头 + 数值 + 边距，避免窄控件挤压箭头导致热区与图标不符
    spin.setMinimumWidth(72)
    spin.setToolTip(tooltip)
    # 【一致性】与买卖条件组的数值控件共用同一套样式（原生渲染）。
    # 切勿在此就地写 QDoubleSpinBox 半截 QSS —— 会破坏子控件度量，
    # 造成箭头图标不一致 + 上箭头只有部分区域可点（见 custom_widgets.SPINBOX_QSS）。
    spin.setStyleSheet(SPINBOX_QSS)
    return spin


# ==========================================
# 卡片基类
# ==========================================
class EditPane(QFrame):
    """一张配置卡片 = 标题行（含操作按钮）+ 内容体。

    【1.22 定稿】卡片**不再自带"收起"按钮**、也不再由页面"就地展开"：
    它的开合一律交给容器决定 —— 目前唯一容器是下面的 `EditDrawer`
    （右侧遮罩抽屉），关闭动作由抽屉的 ✕ / Esc / 点遮罩承担。
    原因（用户实测）：就地展开虽然直观，但会把结果区往下挤矮、卡片又撑满整页，**不好看**。
    """

    def __init__(self, key: str, title: str, accent: str = "#1976D2",
                 tab_label: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self.tab_label = tab_label or title
        self.setStyleSheet(CARD_QSS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 6, 10, 12)
        lay.setSpacing(6)

        self.head = QHBoxLayout()
        self.head.setSpacing(6)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {accent};")
        self.head.addWidget(self.lbl_title)
        self.head.addStretch()

        lay.addLayout(self.head)

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(8)
        lay.addWidget(self.body)

        self._lay = lay

    def add_head(self, widget):
        """往标题行尾部追加操作按钮（顺序 = 调用顺序，整体右对齐）。"""
        self.head.addWidget(widget)

    def set_flat(self, flat: bool):
        """抽屉内用"无边框"外观（避免"卡片套卡片"），独立摆放时用卡片外观。"""
        self.setStyleSheet(_FLAT_PANE_QSS if flat else CARD_QSS)


_FLAT_PANE_QSS = "QFrame { background: transparent; border: none; }"


class ClickCatcher(QFrame):
    """遮罩层：把页面内容压暗并**吞掉点击**（点它 = 关闭抽屉，样板 A 的 scrim）。"""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):  # noqa: N802 —— Qt 命名
        self.clicked.emit()
        super().mousePressEvent(event)


class EditDrawer(QFrame):
    """右侧配置抽屉（1.22 · 样板 A 的 L3 落点）= 遮罩 + 抽屉 + 顶部页签。

    【为什么是覆盖层而不是"就地展开"】用户实测结论："就地展开虽然直观但不美观"
    —— 展开会把结果区挤矮，卡片宽度撑满整页，视觉很散。
    抽屉走覆盖层：**完全不动页面布局**，结果区高度自始至终不变，配置浮在它上面。

    【几何必须自己算】覆盖层不进布局，尺寸要在页面 `resizeEvent` 里 setGeometry
    （抽屉宽 = min(560, 页面宽 × 0.42)，高 = 整页高）—— 见 §11.5-26。

    【页签】抽屉自带一排页签，可在五张卡片间直接切换，不必"关掉再点另一个胶囊"。
    """

    sig_closed = pyqtSignal()
    sig_pane_changed = pyqtSignal(str)

    def __init__(self, panes, parent=None):
        super().__init__(parent)
        self.setObjectName("EditDrawer")
        self.setStyleSheet("QFrame#EditDrawer { background: #FFFFFF;"
                           " border-left: 1px solid #E7EAF0; }")
        self._panes = list(panes)
        self._tabs = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # —— 头部：标题 + 关闭 ——
        head = QWidget()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(16, 12, 12, 8)
        head_lay.setSpacing(8)
        title = QLabel("配置")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2430;")
        head_lay.addWidget(title)
        sub = QLabel("改完直接点「▶ 开始回测」—— 结果区不受影响")
        sub.setStyleSheet("font-size: 11.5px; color: #8A94A6;")
        head_lay.addWidget(sub)
        head_lay.addStretch()
        self.btn_close = QPushButton("关闭 ✕")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet(
            "QPushButton { color:#1976D2; background:transparent; border:1px solid #BBDEFB;"
            " border-radius:8px; padding:5px 12px; font-weight:bold; font-size:12.5px; }"
            "QPushButton:hover { background:#E3F2FD; }")
        self.btn_close.setToolTip("也可以按 Esc，或直接点抽屉外面（遮罩）关闭")
        self.btn_close.clicked.connect(self.sig_closed)
        head_lay.addWidget(self.btn_close)
        lay.addWidget(head)

        # —— 页签：抽屉内直接切换 ——
        tabs = QWidget()
        tabs_lay = QHBoxLayout(tabs)
        tabs_lay.setContentsMargins(12, 0, 12, 6)
        tabs_lay.setSpacing(6)
        for pane in self._panes:
            btn = QPushButton(pane.tab_label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=pane.key: self.show_pane(k))
            tabs_lay.addWidget(btn)
            self._tabs[pane.key] = btn
        tabs_lay.addStretch()
        lay.addWidget(tabs)

        # —— 内容：五张卡片做成一叠（超高可滚动）——
        self._stack = QStackedWidget()
        for pane in self._panes:
            pane.set_flat(True)          # 抽屉内不用卡片边框，避免"卡片套卡片"
            # 【关键 · 真实踩到】卡片必须"贴顶 + 尾部留白"，**不能直接塞进 QStackedWidget**：
            # 直接塞会被拉满抽屉整高，卡片内部那些自带伸缩项的布局（ConditionGate /
            # 条件积木行）就会把行与行之间撑开 —— 表现为"一大片空白 + 控件全散在最底部"。
            # 修法：外面套一层容器并 addStretch()，卡片按自身 sizeHint 贴顶（§11.5-27）。
            holder = QWidget()
            hold_lay = QVBoxLayout(holder)
            hold_lay.setContentsMargins(0, 0, 0, 0)
            hold_lay.setSpacing(0)
            hold_lay.addWidget(pane)
            hold_lay.addStretch()
            self._stack.addWidget(holder)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        self._scroll.setWidget(self._stack)
        lay.addWidget(self._scroll, 1)

    # ---------- 对外 ----------
    def show_pane(self, key: str):
        """切到某张卡片（页签高亮同步）。"""
        for i, pane in enumerate(self._panes):
            if pane.key == key:
                self._stack.setCurrentIndex(i)
                break
        for k, btn in self._tabs.items():
            on = (k == key)
            btn.setStyleSheet(TAB_QSS_ON if on else TAB_QSS_OFF)
        self.sig_pane_changed.emit(key)

    @property
    def current_key(self) -> str:
        idx = self._stack.currentIndex()
        return self._panes[idx].key if 0 <= idx < len(self._panes) else ""

    @property
    def scroll_area(self) -> QScrollArea:
        """供页面在打开时把内容滚回顶部（切卡片时保持"从头看"）。"""
        return self._scroll



# ==========================================
# ① ƒ 函数
# ==========================================
class FunctionPane(EditPane):
    def __init__(self, parent=None):
        super().__init__("fn", "ƒ 函数（可多段 · 共享变量池）", "#1976D2", "ƒ 函数", parent)

        # —— P7：公式资产化 + 与行情页互送（与「🩺 检测」同排，都属于"对这段函数的操作"）——
        self.btn_library = QPushButton("📚 配方库")
        self.btn_library.setStyleSheet(ACTION_QSS)
        self.btn_library.setToolTip("载入已保存的公式配方（含行情页存下的那些）")

        self.btn_save_formula = QPushButton("💾 存为配方")
        self.btn_save_formula.setStyleSheet(ACTION_QSS)
        self.btn_save_formula.setToolTip("把下面的函数与参数存进配方库；同名即覆盖")

        self.btn_send_market = QPushButton("📤 送到行情页")
        self.btn_send_market.setStyleSheet(SEND_QSS)
        self.btn_send_market.setToolTip("把函数与参数送到「📈 市场行情」的公式叠加区，"
                                        "在真实 K 线上看它长什么样（每段默认落主图）")

        self.btn_detect = QPushButton("🩺 检测")
        self.btn_detect.setStyleSheet(DETECT_QSS)

        for w in (self.btn_library, self.btn_save_formula, self.btn_send_market, self.btn_detect):
            self.add_head(w)

        self.segments = FunctionSegments(
            "MA5 := MA(C, 5);\n"
            "UPTREND := C > MA5;\n"
            "GOLD: CROSS(MA(C,5), MA(C,20)), COLORRED;\n\n"
            "粘贴你编写的整段函数后点击「检测函数」(示例为通用公开写法)")
        self.body_lay.addWidget(self.segments)

        self.lbl_detect = QLabel("尚未检测")
        self.lbl_detect.setWordWrap(True)
        self.lbl_detect.setStyleSheet("font-size: 12px; color: #9AA3B2;")
        self.body_lay.addWidget(self.lbl_detect)


# ==========================================
# ② ⇄ 买卖条件组
# ==========================================
class ConditionPane(EditPane):
    def __init__(self, parent=None):
        super().__init__("cond", "⇄ 买卖条件组（每个条件一行 · 满足计数触发）", "#1976D2",
                         "⇄ 买卖条件", parent)

        self.add_head(hint_icon(
            "组合逻辑=满足计数：全部满足(AND) / 任一满足(OR) / 至少 N 个满足；"
            "底部预览为该组实时翻译出的表达式。每行规则：变量 + 算子 + 数值。"))

        param_row = QHBoxLayout()
        param_row.addWidget(mini_label("函数参数"))
        self.txt_params = QLineEdit()
        self.txt_params.setPlaceholderText("形如 N1=5 N2=20（对所有函数段统一生效）")
        self.txt_params.setFixedHeight(30)
        self.txt_params.setStyleSheet(
            "QLineEdit { padding: 0 10px; border: 1px solid #E0E4EC; border-radius: 8px;"
            " background: white; font-size: 13px; }")
        param_row.addWidget(self.txt_params, 1)
        self.body_lay.addLayout(param_row)

        gates = QHBoxLayout()
        gates.setSpacing(16)
        self.gate_buy = ConditionGate("买入条件", settings.COLOR_PROFIT_TEXT)
        self.gate_sell = ConditionGate("卖出条件", settings.COLOR_LOSS_TEXT)
        gates.addWidget(self.gate_buy, 1)
        gates.addWidget(self.gate_sell, 1)
        self.body_lay.addLayout(gates)


# ==========================================
# ③ 📉 大盘 / 指数 regime 门控 (阶段C)
# ==========================================
class IndexPane(EditPane):
    def __init__(self, parent=None):
        super().__init__("index", "📉 大盘 / 指数 regime 门控（可选）", "#6A1B9A",
                         "📉 大盘门控", parent)

        top = QHBoxLayout()
        self.chk_index_enable = QCheckBox("启用大盘先决条件")
        top.addWidget(self.chk_index_enable)
        top.addWidget(mini_label("指数"))

        self.cmb_index = NoWheelComboBox()
        self.cmb_index.setEditable(True)
        self.cmb_index.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # 关闭自动补全：手输代码不应被预设文本接管
        completer = self.cmb_index.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.cmb_index.setStyleSheet(COMBO_QSS)
        for code, name in INDEX_PRESETS.items():
            self.cmb_index.addItem(f"{code}  {name}", code)
        self.cmb_index.setCurrentIndex(0)
        self.cmb_index.setFixedHeight(30)
        top.addWidget(self.cmb_index, 1)

        self.lbl_index_status = QLabel("")
        self.lbl_index_status.setStyleSheet("font-size: 11px; color: #8A94A6;")
        top.addWidget(self.lbl_index_status)
        top.addWidget(hint_icon(
            "指数 regime 门控：用与个股相同的函数段对所选指数再求值，指数侧变量自动加 IDX_ 前缀。"
            "买入：个股条件与「指数买入许可」同时成立才进场；"
            "卖出：个股条件或「指数卖出破位」任一成立即离场。"
            "首次回测若本地无指数数据将自动联网同步。"))
        self.body_lay.addLayout(top)

        gates = QHBoxLayout()
        gates.setSpacing(16)
        self.gate_index_buy = ConditionGate("指数买入许可", "#6A1B9A")
        self.gate_index_sell = ConditionGate("指数卖出破位", "#E65100")
        gates.addWidget(self.gate_index_buy, 1)
        gates.addWidget(self.gate_index_sell, 1)
        self.body_lay.addLayout(gates)


# ==========================================
# 🛡 风控离场 (阶段B)
# ==========================================
class RiskPane(EditPane):
    def __init__(self, parent=None):
        super().__init__("risk", "🛡 风控离场（任一项设 0 = 关闭）", "#E65100", "🛡 风控", parent)

        self.add_head(hint_icon(
            "硬性保护规则：盘中触发即离场，优先于卖出信号，谁先到谁执行。"
            "任意一项设 0 即关闭；悬停各项输入框可看单独说明。"))

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(mini_label("最长持仓"))
        self.spin_risk_bars = number_spin(
            "若持有超过 N 根 K 线仍未卖出则当日收盘强平", 0, 0, 999, 0)
        row.addWidget(self.spin_risk_bars)
        row.addWidget(mini_label("根"))
        row.addWidget(mini_label("固定止损"))
        self.spin_risk_stop = number_spin(
            "收盘/盘中自开仓价回撤达到该百分比即离场 (0=关闭)", 0, 0, 100, 1)
        row.addWidget(self.spin_risk_stop)
        row.addWidget(mini_label("%"))
        row.addWidget(mini_label("固定止盈"))
        self.spin_risk_take = number_spin(
            "自开仓价上涨达到该百分比即止盈离场 (0=关闭)", 0, 0, 100, 1)
        row.addWidget(self.spin_risk_take)
        row.addWidget(mini_label("%"))
        row.addWidget(mini_label("移动止盈回撤"))
        self.spin_risk_trail = number_spin(
            "自持仓最高点回落该百分比即离场，保护浮盈 (0=关闭)", 0, 0, 100, 1)
        row.addWidget(self.spin_risk_trail)
        row.addWidget(mini_label("%"))
        row.addStretch()
        self.body_lay.addLayout(row)


# ==========================================
# 🎯 成交模型 (v6.17 · §7-B5)
# ==========================================
# ⚠【文案铁律 · 用户实测反馈驱动】界面上**不许**出现"跳 / 当根 / K线 / 条件单"这类
#   行话当唯一解释 —— 主说明一律用人话 + 具体数字；术语只允许作为 tooltip 的补充。
#   并且必须有"看得见的教学入口"（📖 按钮 + 行内实时说明），不能只藏在悬停里。
class FillPane(EditPane):
    def __init__(self, parent=None):
        super().__init__("fill", "🎯 成交模型（信号出现后按什么价成交）", "#1565C0",
                         "🎯 成交模型", parent)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(mini_label("什么时候成交"))

        self.cmb_fill_mode = NoWheelComboBox()
        self.cmb_fill_mode.setStyleSheet(COMBO_QSS)
        self.cmb_fill_mode.setFixedHeight(30)
        self.cmb_fill_mode.setMinimumWidth(240)
        for mode in (FILL_NEXT_OPEN, FILL_CLOSE, FILL_TRIGGER):
            self.cmb_fill_mode.addItem(FILL_MODE_LABELS[mode], mode)
        self.cmb_fill_mode.setToolTip(
            "信号在当天收盘后才判定，所以「什么时候真的成交」由你在这里定。\n"
            "三档的详细区别（带具体价格例子）请点右侧「📖 三档怎么选？」。")
        top.addWidget(self.cmb_fill_mode)

        # 「多等多少钱才动手」只对第三档有意义 —— 不做成"看不懂的常驻参数"
        self._fill_offset_box = QWidget()
        off = QHBoxLayout(self._fill_offset_box)
        off.setContentsMargins(0, 0, 0, 0)
        off.setSpacing(6)
        off.addWidget(mini_label("买卖价要多等"))
        self.spin_fill_offset = number_spin(
            "只有「价格冲破 / 跌破才成交」用到它：\n"
            "买入触发价 = 信号日最高价 + 这个数；卖出触发价 = 信号日最低价 − 这个数。\n"
            "默认 0.01 元 = A股最小变动价格（交易所俗称「1 跳」）；箭头每次调 0.01 元，\n"
            "也可以直接用键盘输入（如 0.35）。\n"
            "等得越多 → 越不容易被碰到 → 越不容易成交。",
            0.01, 0.01, 1.00, 2)
        off.addWidget(self.spin_fill_offset)
        off.addWidget(mini_label("元才动手"))
        top.addWidget(self._fill_offset_box)
        top.addStretch()

        self.btn_fill_help = QPushButton("📖 三档怎么选？")
        self.btn_fill_help.setStyleSheet(FLAT_QSS)
        self.btn_fill_help.setToolTip("用具体价格例子讲清三档的区别，以及为什么"
                                      "「当天买的当天不能卖」")
        self.add_head(self.btn_fill_help)
        self.body_lay.addLayout(top)

        # 行内实时说明：**这就是"用户指引"的主体**（随选择变化，不必悬停也能看懂）
        self.lbl_fill_desc = QLabel("")
        self.lbl_fill_desc.setStyleSheet("font-size: 12px; color: #3C4552;")
        self.lbl_fill_desc.setWordWrap(True)
        self.body_lay.addWidget(self.lbl_fill_desc)

        self.lbl_fill_t1 = QLabel("🔒 所有档位都遵守：今天买的，今天不能卖")
        self.lbl_fill_t1.setStyleSheet("font-size: 12px; color: #6A1B9A; font-weight: bold;")
        self.lbl_fill_t1.setToolTip(
            "A股规定今天买入的股票今天不能卖出，回测同样照此执行 —— 否则结果会比现实好看。\n"
            "· 买入当天就跌穿止损（或涨到止盈）→ 当天卖不掉，只能第二天一开盘就卖，\n"
            "  第二天的跳空低开由你承担；\n"
            "· 「最长持仓 1 天」实际会变成第二天收盘才卖；\n"
            "· 同一天里卖出之后不会立刻又买回来（否则等于白交两次手续费、持仓却没变）。")
        self.body_lay.addWidget(self.lbl_fill_t1)
