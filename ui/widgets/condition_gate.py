# ui/widgets/condition_gate.py
"""
② 买卖「条件组 Gate」控件 (v2) —— 支持多条件积木行 + 满足计数。

产品口径 (阶段A 定稿)：
- 一个 Gate = 若干「积木条件行」(变量 + 规则 + 数值) + 一条组合逻辑；
- 组合逻辑用「至少 N 个满足」统一表达：
      N = 条件总数  => 全部满足 (AND)
      N = 1         => 任一满足 (OR)
      其它 N        => 至少 N 个满足
- UI 不依赖 AND/OR 简单二分：真正的需求是“多条件只要满足若干就触发”。

与引擎的桥接：把 Gate 翻译成一条 DSL 表达式。
「至少 N 个」使用 runtime 新增的 COUNT_TRUE 原语，避免组合展开导致表达式爆炸。
本控件不碰 SQL/网络，只做“配置状态 -> DSL 文本”的纯转换，供回测视图调用。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                             QPushButton, QFrame)

from ui.widgets.custom_widgets import (NoWheelComboBox,
                                       NoWheelDoubleSpinBox)

_CARD_QSS = ("QFrame { background: white; border: 1px solid #E7EAF0; border-radius: 12px; }")
_CTRL_QSS = ("QComboBox { padding: 0 8px; border: 1px solid #E0E4EC; border-radius: 8px; "
             "background: white; font-size: 12px; color: #1F2430; }"
             "QComboBox:focus { border: 1px solid #1976D2; }")
_FLAT_QSS = ("QPushButton { color: #1976D2; background: transparent; border: none; "
             "padding: 0 6px; font-weight: bold; border-radius: 6px; font-size: 12px; }"
             "QPushButton:hover { background: #EEF4FD; }")

# 条件规则：显示文本 -> DSL 算子
CONDITION_RULES = [
    ("= (等于)", "eq"), ("出现 (由假变真)", "rise"), ("消失 (由真变假)", "fall"),
    ("> (大于)", "gt"), ("< (小于)", "lt"),
    (">= (大于等于)", "ge"), ("<= (小于等于)", "le"), ("≠ (不等于)", "ne"),
]
_VALUE_RULES = {"eq", "gt", "lt", "ge", "le", "ne"}
_RULE_KEY_TO_INDEX = {key: i for i, (_, key) in enumerate(CONDITION_RULES)}

# 组合逻辑键
LOGIC_ALL = "all"          # 全部满足 (=至少 N=条件数)
LOGIC_ANY = "any"          # 任一满足 (=至少 1)
LOGIC_AT_LEAST = "atleast" # 至少 N 个满足

_LOGIC_LABELS = {
    LOGIC_ALL: "全部满足 (AND)",
    LOGIC_ANY: "任一满足 (OR)",
    LOGIC_AT_LEAST: "至少 N 个满足",
}


def build_condition_expression(variable: str, rule: str, value: float) -> str:
    """单个积木条件行 -> DSL 表达式"""
    value_txt = f"{value:.6g}"
    return {
        "eq": f"{variable} = {value_txt}",
        "gt": f"{variable} > {value_txt}",
        "lt": f"{variable} < {value_txt}",
        "ge": f"{variable} >= {value_txt}",
        "le": f"{variable} <= {value_txt}",
        "ne": f"{variable} <> {value_txt}",
        "rise": f"CROSS({variable}, 0.5)",
        "fall": f"CROSS(0.5, {variable})",
    }.get(rule, "")


class _ConditionRow(QWidget):
    """一行积木条件：变量 | 规则 | 数值 | ✕"""

    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(self, variables: list, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.cb_var = NoWheelComboBox()
        self.cb_var.setMinimumWidth(120)
        self.cb_var.setStyleSheet(_CTRL_QSS)
        self.cb_var.currentIndexChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.cb_var, 3)

        self.cb_rule = NoWheelComboBox()
        self.cb_rule.setMinimumWidth(150)
        self.cb_rule.setStyleSheet(_CTRL_QSS)
        for text, _ in CONDITION_RULES:
            self.cb_rule.addItem(text)
        self.cb_rule.currentIndexChanged.connect(self._sync_value_visibility)
        self.cb_rule.currentIndexChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.cb_rule, 2)

        self.spin = NoWheelDoubleSpinBox()
        self.spin.setRange(-9999999, 9999999)
        self.spin.setDecimals(4)
        self.spin.setValue(1.0)
        self.spin.setMinimumWidth(90)
        self.spin.valueChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.spin, 2)

        btn_del = QPushButton("✕")
        btn_del.setFixedSize(24, 24)
        btn_del.setStyleSheet(_FLAT_QSS)
        btn_del.setToolTip("删除该条件")
        btn_del.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addWidget(btn_del)

        self.set_variables(variables)

    def set_variables(self, variables: list):
        """重建变量下拉；尽量保留原选中项，缺失则回退第一项"""
        prev = self.cb_var.currentData()
        self.cb_var.blockSignals(True)
        self.cb_var.clear()
        for var in variables:
            self.cb_var.addItem(str(var), var)
        if prev is not None:
            idx = self.cb_var.findData(prev)
            if idx >= 0:
                self.cb_var.setCurrentIndex(idx)
        elif self.cb_var.count():
            self.cb_var.setCurrentIndex(0)
        self.cb_var.blockSignals(False)

    def _sync_value_visibility(self, *_):
        key = CONDITION_RULES[self.cb_rule.currentIndex()][1]
        self.spin.setEnabled(key in _VALUE_RULES)

    def config(self) -> dict:
        return {
            "variable": self.cb_var.currentData() or "",
            "rule": CONDITION_RULES[self.cb_rule.currentIndex()][1],
            "value": self.spin.value(),
        }

    def load_config(self, cfg: dict):
        variable = cfg.get("variable") or ""
        rule = cfg.get("rule") or ""
        idx_var = self.cb_var.findData(variable)
        if idx_var >= 0:
            self.cb_var.setCurrentIndex(idx_var)
        if rule in _RULE_KEY_TO_INDEX:
            self.cb_rule.setCurrentIndex(_RULE_KEY_TO_INDEX[rule])
        try:
            self.spin.setValue(float(cfg.get("value", 1.0)))
        except (TypeError, ValueError):
            pass

    def expression(self) -> str:
        variable = self.cb_var.currentData() or ""
        key = CONDITION_RULES[self.cb_rule.currentIndex()][1]
        return build_condition_expression(variable, key, self.spin.value())


class ConditionGate(QWidget):
    """买卖侧一个条件组：若干积木行 + 满足计数逻辑 + DSL 预览。

    对外 API:
        set_variables(names)    # 共享变量池变更后重建各行动作，保留选中
        config() -> dict        # {logic, n, conditions:[...]} 供策略持久化
        load_config(dict)       # 从策略快照恢复 (兼容旧版单条件结构)
        expression() -> str     # 翻译成一条 DSL 表达式 (空串 = 无有效条件)
        set_gate_enabled(bool)  # 变量未就绪时整组禁用
    """

    changed = pyqtSignal()

    def __init__(self, title: str, color_hex: str, parent=None):
        super().__init__(parent)
        self._variables: list = []
        self._rows: list[_ConditionRow] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # —— 头部：标题 + 组合逻辑 ——
        head = QHBoxLayout()
        tag = QLabel(title)
        tag.setStyleSheet(f"font-weight: bold; color: {color_hex}; font-size: 13px;")
        head.addWidget(tag)
        head.addStretch()
        head.addWidget(self._mini("满足"))
        self.cb_logic = NoWheelComboBox()
        self.cb_logic.setStyleSheet(_CTRL_QSS)
        for key in (LOGIC_ALL, LOGIC_ANY, LOGIC_AT_LEAST):
            self.cb_logic.addItem(_LOGIC_LABELS[key], key)
        self.cb_logic.currentIndexChanged.connect(self._sync_n_spin)
        self.cb_logic.currentIndexChanged.connect(lambda *_: self._emit_changed())
        head.addWidget(self.cb_logic)
        self.spin_n = NoWheelDoubleSpinBox()
        self.spin_n.setRange(1, 999)
        self.spin_n.setDecimals(0)
        self.spin_n.setValue(1)
        self.spin_n.setMinimumWidth(56)
        self.spin_n.valueChanged.connect(lambda *_: self._emit_changed())
        head.addWidget(self.spin_n)
        lay.addLayout(head)

        # —— 条件行容器 ——
        self._rows_box = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_box)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(4)
        lay.addWidget(self._rows_box)

        self.btn_add = QPushButton("＋ 添加条件")
        self.btn_add.setStyleSheet(_FLAT_QSS)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self._append_row)
        lay.addWidget(self.btn_add)

        # —— DSL 预览 ——
        self.lbl_preview = QLabel(" ")
        self.lbl_preview.setStyleSheet(
            "font-size: 11px; font-family: Consolas, 'Microsoft YaHei', monospace; "
            "color: #424B5A; background:#F6F8FC; border-radius:6px; padding:4px 8px;")
        self.lbl_preview.setWordWrap(True)
        lay.addWidget(self.lbl_preview)

        # 默认一条空行 (逻辑默认"全部满足"=单条件，等价旧版体验)
        self._append_row()

    # ---------- 小构件 ----------
    @staticmethod
    def _mini(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 11px; color: #8A94A6;")
        return lbl

    # ---------- 行管理 ----------
    def _append_row(self):
        row = _ConditionRow(self._variables)
        row.changed.connect(self._refresh)
        row.remove_requested.connect(self._remove_row)
        self._rows_lay.addWidget(row)
        self._rows.append(row)
        self._refresh()

    def _remove_row(self, row):
        if row in self._rows:
            self._rows.remove(row)
            self._rows_lay.removeWidget(row)
            row.deleteLater()
            self._refresh()

    # ---------- 外部 API ----------
    def set_variables(self, variables: list):
        self._variables = list(variables or [])
        for row in self._rows:
            row.set_variables(self._variables)
        self._refresh()

    def set_gate_enabled(self, enabled: bool):
        for w in (self.cb_logic, self.spin_n, self.btn_add):
            w.setEnabled(enabled)
        for row in self._rows:
            for w in (row.cb_var, row.cb_rule, row.spin):
                w.setEnabled(enabled)

    def clear_rows(self):
        """清空全部条件行后补一条空行 (用于重新载入前的重置)"""
        for row in list(self._rows):
            self._rows.remove(row)
            self._rows_lay.removeWidget(row)
            row.deleteLater()
        self._append_row()

    def config(self) -> dict:
        conditions = [r.config() for r in self._rows if r.config().get("variable")]
        logic = self.cb_logic.currentData() or LOGIC_ALL
        return {
            "logic": logic,
            "n": int(self.spin_n.value()),
            "conditions": conditions,
        }

    def load_config(self, cfg: dict):
        """从策略快照恢复。兼容旧版单条件结构 {variable, rule, value}。

        顺序要点：先还原条件行、再设逻辑与 N，避免中间状态被 _refresh 钳制。
        """
        self.clear_rows()
        if not cfg:
            return
        # 旧版单条件 dict：逻辑字段缺失 -> 单条件等效，转成一行
        if "conditions" not in cfg:
            self._rows[0].load_config(cfg)
            self._refresh()
            return
        conditions = cfg.get("conditions") or []
        # 1) 先填条件行 (首行复用空行)
        if conditions:
            self._rows[0].load_config(conditions[0])
            for extra in conditions[1:]:
                self._append_row()
                self._rows[-1].load_config(extra)
        # 2) 再设组合逻辑
        logic = cfg.get("logic", LOGIC_ALL)
        idx_logic = self.cb_logic.findData(logic)
        if idx_logic >= 0:
            self.cb_logic.blockSignals(True)
            self.cb_logic.setCurrentIndex(idx_logic)
            self.cb_logic.blockSignals(False)
        # 3) 最后设 N (屏蔽信号，交由收尾 _refresh 统一刷新/钳制)
        try:
            self.spin_n.blockSignals(True)
            self.spin_n.setValue(int(cfg.get("n", 1)))
            self.spin_n.blockSignals(False)
        except (TypeError, ValueError):
            pass
        self._refresh()

    def expression(self) -> str:
        """翻译整组 -> DSL。空串 = 条件不足。"""
        exprs = [r.expression() for r in self._rows if r.config().get("variable")]
        if not exprs:
            return ""
        logic = self.cb_logic.currentData() or LOGIC_ALL
        n = max(1, int(self.spin_n.value()))
        if logic == LOGIC_AT_LEAST and len(exprs) > 1:
            n = min(n, len(exprs))
            return f"COUNT_TRUE({', '.join(exprs)}) >= {n}"
        if len(exprs) == 1:
            return exprs[0]
        if logic == LOGIC_ANY:
            return "(" + ") OR (".join(exprs) + ")"
        return "(" + ") AND (".join(exprs) + ")"

    # ---------- 内部刷新 ----------
    def _sync_n_spin(self, *_):
        logic = self.cb_logic.currentData()
        self.spin_n.setEnabled(logic == LOGIC_AT_LEAST)

    def _emit_changed(self):
        self._refresh()
        self.changed.emit()

    def _refresh(self):
        """逻辑切换后把 N 钳制到合理范围，并刷新 DSL 预览"""
        logic = self.cb_logic.currentData() or LOGIC_ALL
        n_rows = max(1, len([r for r in self._rows if r.config().get("variable")]))
        self.spin_n.setEnabled(logic == LOGIC_AT_LEAST)
        if logic == LOGIC_ALL:
            self.spin_n.setValue(n_rows)   # 全部满足 = N=条件数 (仅作展示)
        elif logic == LOGIC_ANY:
            self.spin_n.setValue(1)        # 任一满足 = N=1 (仅作展示)
        else:
            if int(self.spin_n.value()) > n_rows:
                self.spin_n.setValue(max(1, n_rows))
        expr = self.expression()
        self.lbl_preview.setText(expr if expr else " 尚未配置任何条件")
        self.lbl_preview.setToolTip(expr or "")
