# ui/dialogs/formula_overlay.py
"""
行情页「公式叠加」编辑器（§7-B3 P4/P5 · v6.8 支持多副图）。

【职责边界 · §10-3】
  本对话框只做三件事：**收集函数文本 + 参数 + 每段的目标窗格 → 自检 → 交给行情页**；
  它**不碰行情数据、不绘图**。求值与渲染由行情页 `ui/views/trading_desk.py` 走
  `execute_programs_with_draws_grouped` + `OverlayPainter`（全 app 唯一叠层渲染器）。
  ⚠ `ui/views/market.py` 已于 v6.12 删除，别再照旧路径找它。

【为什么"目标窗格"是每段一个】
  用户手里的函数分两类：**主图函数**（均线类，与股价同量级）与**副图函数**
  （MACD/RSI/成交量量级）。后者若叠在主图，主图坐标轴会被撑到认不出 K 线。
  而且不同副图函数之间量级也可能差很远（量能 vs 振荡指标），所以副图还分 1/2/3 格。
  **但各段仍共用同一个变量池**（后段引用前段变量）—— 求值只有一次，
  引擎侧靠 `execute_programs_with_draws_grouped` 把 draws 按段归位（v6.8）。

【v6.7 修过的两条 UI 纪律仍然有效】§11.5-15：删控件必须 `setParent(None)`；
容器分到多余高度时必须有可伸缩子控件承接。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                             QLineEdit, QMenu, QPushButton, QScrollArea,
                             QToolButton, QVBoxLayout)

from core.formula.program import (FormulaProgramError, parse_program,
                                  probe_missing_parameters)
from core.utils import parse_params_text
from ui.widgets.custom_widgets import NoWheelComboBox
from ui.widgets.function_segments import FunctionSegments

TARGET_MAIN = 'main'
TARGET_SUB1 = 'sub1'
TARGET_SUB2 = 'sub2'
TARGET_SUB3 = 'sub3'

# 目标窗格选项（value 会写进 DrawSpec 的归属，行情页据此建窗格）
TARGET_CHOICES = (
    ("主图", TARGET_MAIN),
    ("副图 1", TARGET_SUB1),
    ("副图 2", TARGET_SUB2),
    ("副图 3", TARGET_SUB3),
)
_TARGET_VALUES = {value for _label, value in TARGET_CHOICES}

_HINT_QSS = "QLabel { color:#8A94A6; font-size:12px; }"
_FIELD_QSS = ("QLineEdit { font-size:13px; padding:6px 10px; border:1px solid #E0E0E0; "
              "border-radius:6px; background:white; }")
_BTN_QSS = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; border-radius:6px; "
            "padding:6px 12px; font-weight:bold; color:#424242; }"
            "QPushButton:hover { background:#EDEDED; }")

_TARGET_HELP = (
    "主图 = 与股价**同一量级**（均线、价格线、状态柱）；"
    "副图 = **不同量级**的指标（MACD / RSI / 量能…），会单独占一格、有自己的坐标轴，不会压扁主图。"
)

# 示例模板（通用通达信写法，非任何人的私有公式）
_EXAMPLES = {
    'main': (
        "{主图指标示例：与股价同量级，直接叠在 K 线上（目标选「主图」）}\n"
        "快线: MA(C,5), COLORWHITE;\n"
        "慢线: MA(C,20), COLORYELLOW, LINETHICK2;"
    ),
    'sub': (
        "{副图指标示例：与股价不同量级 —— 目标请选「副图 1」}\n"
        "DIF := EMA(C,12) - EMA(C,26);\n"
        "DEA := EMA(DIF,9);\n"
        "柱: (DIF - DEA) * 2, COLORWHITE;\n"
        "STICKLINE((DIF - DEA) * 2 > 0, 0, (DIF - DEA) * 2, 3, 0), COLORFF0000;\n"
        "STICKLINE((DIF - DEA) * 2 <= 0, (DIF - DEA) * 2, 0, 3, 0), COLOR00FF00;"
    ),
}


def _target_combo() -> NoWheelComboBox:
    """一段的"目标窗格"下拉（§10-9：统一用 NoWheel 控件族）。"""
    combo = NoWheelComboBox()
    for label, value in TARGET_CHOICES:
        combo.addItem(label, value)
    combo.setToolTip("这段函数画出来的东西放到哪一格")
    return combo


class FormulaOverlayDialog(QDialog):
    """编辑「主图 / 副图」公式叠加。

    调用方式：
        dlg = FormulaOverlayDialog(self, segments=[(text, target), ...], params_text=...)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.result_segments()   # -> [(text, target), ...]；空列表 = 移除叠加
            dlg.params_text()
    """

    def __init__(self, parent=None, *, segments=None, params_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("公式叠加 · 在行情图上显示你自己的指标")
        self.resize(900, 640)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("公式叠加")
        title.setStyleSheet("font-size:16px; font-weight:bold; color:#212121;")
        lay.addWidget(title)
        guide = QLabel("粘贴通达信式函数即可。多段共享同一个变量池：后段可直接引用前段算出的变量。"
                       + _TARGET_HELP)
        guide.setStyleSheet(_HINT_QSS)
        guide.setWordWrap(True)
        lay.addWidget(guide)

        # ---------- 函数编辑区（每段右侧带"目标窗格"下拉；可滚动） ----------
        self.segments = FunctionSegments(
            "在此粘贴函数（多段共享变量池）",
            accessory_factory=lambda _index: _target_combo())
        if segments:
            self.segments.set_texts([text for text, _target in segments])
            for combo, (_text, target) in zip(self.segments.accessories(), segments):
                index = combo.findData(target if target in _TARGET_VALUES else TARGET_MAIN)
                combo.setCurrentIndex(max(0, index))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.segments)
        lay.addWidget(scroll, 1)

        # ---------- 参数 ----------
        param_row = QHBoxLayout()
        param_row.setSpacing(8)
        param_label = QLabel("函数参数")
        param_label.setStyleSheet("font-weight:bold; color:#757575; font-size:12px;")
        param_label.setToolTip("函数里用到的自定义参数（如 L1、N）在此赋值；"
                               "留空时「检测」会告诉你还缺哪些。")
        param_row.addWidget(param_label)
        self.txt_params = QLineEdit(params_text)
        self.txt_params.setPlaceholderText("形如 L1=5; L2=20（多个用分号或逗号隔开）")
        self.txt_params.setStyleSheet(_FIELD_QSS)
        param_row.addWidget(self.txt_params, 1)
        lay.addLayout(param_row)

        # ---------- 状态回执 ----------
        self.lbl_status = QLabel("尚未检测。建议先点「🧪 检测」。")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size:12px; color:#8A94A6;")
        lay.addWidget(self.lbl_status)

        # ---------- 动作栏 ----------
        bar = QHBoxLayout()
        self.btn_check = QPushButton("🧪 检测")
        self.btn_check.setStyleSheet(_BTN_QSS)
        self.btn_check.setToolTip("检查语法、探测缺失参数、列出本期不渲染的绘图语句")
        self.btn_check.clicked.connect(self.check_function)
        bar.addWidget(self.btn_check)

        self.btn_example = QToolButton()
        self.btn_example.setText("📋 示例模板")
        self.btn_example.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_example.setStyleSheet(_BTN_QSS + "QToolButton::menu-indicator { image: none; }")
        example_menu = QMenu(self.btn_example)
        example_menu.addAction("主图指标示例（均线叠加）", lambda: self._insert_example('main'))
        example_menu.addAction("副图指标示例（MACD 柱 + 线）", lambda: self._insert_example('sub'))
        self.btn_example.setMenu(example_menu)
        bar.addWidget(self.btn_example)

        self.btn_clear = QPushButton("🗑 清空")
        self.btn_clear.setStyleSheet(_BTN_QSS)
        self.btn_clear.setToolTip("清空内容后点「应用」即移除全部叠加")
        self.btn_clear.clicked.connect(self.clear_function)
        bar.addWidget(self.btn_clear)
        bar.addStretch()

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.btn_ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok.setText("应用到行情图")
        self.btn_ok.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; border:none; border-radius:6px; "
            "padding:7px 16px; font-weight:bold; } QPushButton:hover { background:#1565C0; }")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.apply_function)
        self.buttons.rejected.connect(self.reject)
        bar.addWidget(self.buttons)
        lay.addLayout(bar)

    # ==========================================
    # 对外：调用方读取结果
    # ==========================================
    def result_segments(self) -> list:
        """`[(函数文本, 目标窗格), ...]`；空列表表示"移除全部叠加"。"""
        targets = self.segments.accessories()
        result = []
        for index, text in enumerate(self.segments.texts()):
            if not (text or '').strip():
                continue
            combo = targets[index] if index < len(targets) else None
            target = combo.currentData() if combo is not None else TARGET_MAIN
            result.append((text.strip(), target if target in _TARGET_VALUES else TARGET_MAIN))
        return result

    def result_texts(self) -> list[str]:
        """仅函数文本（兼容旧调用方；目标请用 `result_segments()`）。"""
        return [text for text, _target in self.result_segments()]

    def params_text(self) -> str:
        return self.txt_params.text().strip()

    def result_params(self) -> dict:
        return parse_params_text(self.params_text())

    # ==========================================
    # 交互
    # ==========================================
    def _insert_example(self, key: str):
        """插入通用示例 —— 并把该段的目标窗格自动切到对应值（用例子教，比堆文字有效）。"""
        target = TARGET_MAIN if key == 'main' else TARGET_SUB1
        self.segments.set_texts([_EXAMPLES[key]])
        for combo in self.segments.accessories():
            if combo is None:
                continue
            index = combo.findData(target)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._set_status(True, "已插入示例：可以「🧪 检测」后直接应用，或按自己的思路改写。")

    def clear_function(self):
        self.segments.set_texts([""])
        self.txt_params.setText("")
        self._set_status(True, "已清空。点「应用」即移除全部公式叠加。")

    def check_function(self) -> bool:
        """语法 + 缺参探测 + 未渲染提示；通过返回 True（文案与回测页同源）。"""
        programs = self._compile()
        if programs is None:
            return False

        params = self.result_params()
        try:
            missing, _ = probe_missing_parameters(programs, params)
        except FormulaProgramError as e:
            self._set_status(False, f"❌ {e}")
            return False
        if missing:
            self._set_status(False, f"❌ 缺少参数: {'、'.join(missing)}。"
                                    f"请在「函数参数」中填写后重新检测。")
            return False

        variables, unsupported, count = [], [], 0
        for program in programs:
            count += program.unsupported_count
            for name in program.output_names:
                if name not in variables:
                    variables.append(name)
            for name in program.unsupported:
                if name not in unsupported:
                    unsupported.append(name)

        parts = [f"✓ 可运行：识别 {len(variables)} 个变量"]
        if variables:
            parts.append("、".join(variables[:6]) + ("…" if len(variables) > 6 else ""))
        if unsupported:
            parts.append(f"⚠ 本期不渲染 {count} 处（{'、'.join(unsupported)}）")
        self._set_status(True, "　".join(parts))
        return True

    def apply_function(self):
        # 空内容 = 移除叠加（用户按过「清空」），不算错误
        if not self.result_segments():
            self.accept()
            return
        if not self.check_function():
            return
        self.accept()

    # ==========================================
    # 内部
    # ==========================================
    def _compile(self):
        segments = self.result_segments()
        if not segments:
            self._set_status(False, "❌ 请先粘贴函数内容（或点「🗑 清空」以移除叠加）。")
            return None
        programs = []
        for idx, (text, _target) in enumerate(segments, start=1):
            try:
                programs.append(parse_program(text))
            except FormulaProgramError as e:
                self._set_status(False, f"❌ 函数段 {idx}: {e}")
                return None
        return programs

    def _set_status(self, ok: bool, message: str):
        self.lbl_status.setText(message)
        self.lbl_status.setToolTip(message)     # 长文案会被省略号截断，完整内容进 tooltip
        self.lbl_status.setStyleSheet(
            f"font-size:12px; color:{'#4CAF50' if ok else '#F44336'}; font-weight:bold;")
