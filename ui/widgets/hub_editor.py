# ui/widgets/hub_editor.py
"""ƒ 函数总库的**编辑器**（★1.61 / §7-B16 · H2 · 方案书 `docs/JIAN_HUB_PLAN.md`）。

【落点唯一（方案书验收③）】全站**只有这里**能改函数资产的内容 —— 浮窗
  （`formula_hub_panel`）只许"载入 / 去总库编辑"，各功能页只许"载入 / 同步最新"。
【语法体检】真引擎 = `core.formula.program.parse_program`（整段程序口径，与回测/扫描一致）：
  编译错误 ⇒ `FormulaCompileError` 的**人话原文**进结果条；已知但本期不渲染的绘图函数
  ⇒ **非阻断**提示（`program.unsupported`，§11.5-14：绝不把存量函数掐死在载入上）。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                             QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from core.formula.program import parse_program
from ui.dialogs.formula_overlay import TARGET_CHOICES   # 窗格选项唯一真源（别在本文件另抄一份）
from ui.widgets.custom_widgets import (FLAT_QSS, NoWheelComboBox,
                                       mono_font_css, mini_label)

_RESULT_QSS = {
    "ok": "color:#2E7D32; background:#EAF7EE; border-radius:8px; padding:7px 10px;",
    "warn": "color:#E65100; background:#FFF8E1; border-radius:8px; padding:7px 10px;",
    "err": "color:#C62828; background:#FDECEA; border-radius:8px; padding:7px 10px;",
}


class FormulaAssetEditor(QWidget):
    """一条函数资产的编辑表单：名称 + 函数段（一段一行）+ 默认目标窗格 + 参数 + 检测。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        name_row = QHBoxLayout()
        name_row.addWidget(mini_label('名称'))
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText('给函数起个名字（同名保存 = 覆盖那条）')
        name_row.addWidget(self.txt_name, 1)
        root.addLayout(name_row)

        lbl = QLabel('函数段（一段一行；空行忽略 —— 改动文本后按一行一段重排）')
        lbl.setStyleSheet("font-size:12px; color:#8A94A6;")
        root.addWidget(lbl)
        self.txt_code = QPlainTextEdit()
        self.txt_code.setPlaceholderText(
            "例：\nMA5:MA(C,5);\nDIF:=EMA(C,12)-EMA(C,26);\nMACD:(DIF-EMA(DIF,9))*2,COLORSTICK;")
        self.txt_code.setMinimumHeight(170)
        self.txt_code.setStyleSheet("QPlainTextEdit { " + mono_font_css()
                                    + " font-size:12.3px; }")
        root.addWidget(self.txt_code, 1)

        row = QHBoxLayout()
        row.addWidget(mini_label('默认窗格'))
        self.cmb_target = NoWheelComboBox()
        for label, value in TARGET_CHOICES:
            self.cmb_target.addItem(label, value)
        row.addWidget(self.cmb_target)
        row.addSpacing(10)
        row.addWidget(mini_label('参数'))
        self.txt_params = QLineEdit()
        self.txt_params.setPlaceholderText('P1(12), P2(26)（可空）')
        row.addWidget(self.txt_params, 1)
        self.btn_check = QPushButton('🔎 检测语法')
        self.btn_check.setStyleSheet(FLAT_QSS)
        row.addWidget(self.btn_check)
        root.addLayout(row)

        self.lbl_result = QLabel('')
        self.lbl_result.setWordWrap(True)
        self.lbl_result.hide()
        root.addWidget(self.lbl_result)
        self._show_result('', '')

        # ★1.61 / §7-B16：本表单"按行 = 段"编辑 ⇒ 必须记住**原来的分段与每段窗格**，
        #   否则保存时会把行情页配方的分段窗格（如 `sub1`/`main`）压成同一个（真丢数据）。
        #   ⚠ 更要紧的一点：**段的文本本身可能含换行**（行情页的 MACD 段就是两行）
        #     ⇒ 按行切会把一段拆成两段。所以"文本一字未动"时必须**原样回放原分段**。
        self._orig_targets: list[str] = []
        self._orig_segments: list[dict] = []
        self._loaded_text: str | None = None

    # ---------------- 进出 ----------------
    def load_asset(self, asset: dict) -> None:
        """把一条资产填进表单（走 `load_segments`，口径唯一）。"""
        asset = asset or {}
        self.load_segments(str(asset.get('name') or ''),
                           asset.get('segments') or [],
                           str(asset.get('params_text') or ''))

    def load_segments(self, name: str, segments, params_text: str = '') -> None:
        """用「名称 + 段落（可带 `target`）+ 参数」预填表单 —— A 页与浮窗都走这里。

        窗格规则：**逐行保留原段的目标**（`_orig_targets`）；「默认窗格」下拉只决定
        **新增行**（以及行数与原来不一致时）的落点 —— 这样"只改函数文本"不会顺手改掉窗格。
        """
        self.txt_name.setText(str(name or ''))
        self.txt_params.setText(str(params_text or ''))
        segs = list(segments or [])
        valid = {value for _label, value in TARGET_CHOICES}

        def _text_of(s):
            return str(s.get('text') or '') if isinstance(s, dict) else str(s or '')

        def _target_of(s):
            t = str(s.get('target') or 'main') if isinstance(s, dict) else 'main'
            return t if t in valid else 'main'

        self._orig_segments = [{'text': _text_of(s), 'target': _target_of(s)} for s in segs]
        self._orig_targets = [s['target'] for s in self._orig_segments]
        self.txt_code.setPlainText('\n'.join(s['text'] for s in self._orig_segments))
        self._loaded_text = self.txt_code.toPlainText()     # 记下"载入时的文本"（判"有没有动过"）
        first = self._orig_targets[0] if self._orig_targets else 'main'
        idx = self.cmb_target.findData(first)
        self.cmb_target.setCurrentIndex(idx if idx >= 0 else 0)
        self._show_result('', '')

    def new_asset(self) -> None:
        """新建空表单（给一行出厂示例，别让用户对着空框发呆）。"""
        self.txt_name.clear()
        self.txt_params.clear()
        self.txt_code.setPlainText('MA5:MA(C,5);')
        self._orig_targets = []
        self._orig_segments = []
        self._loaded_text = None            # 新建 ⇒ 一律走"一行一段"，不做原样回放
        self.cmb_target.setCurrentIndex(0)
        self._show_result('', '')

    def texts(self) -> list[str]:
        """当前表单里的函数段（一行为一段；空行忽略）—— 检测与保存共用同一口径。"""
        return [ln.strip() for ln in self.txt_code.toPlainText().splitlines() if ln.strip()]

    def to_payload(self) -> dict | None:
        """表单 → 资产 payload（调用方再交给 `formula_store.upsert`）。

        名称必填（空 = None，调用方提示）；函数段为空也算无效 —— 绝不存一条空资产
        （`formula_store.make_formula` 的既有铁律，这里先拦一层给出更近的提示）。
        """
        name = self.txt_name.text().strip()
        if not name:
            return None
        raw = self.txt_code.toPlainText()
        if self._orig_segments and raw == self._loaded_text:
            # **文本一字未动 ⇒ 原样回放原分段**（段的文本本身可能含换行：行情页的 MACD 段就是两行；
            #  按行切会把它拆成两段、窗格也跟着错位 —— 那是静默改数据）。
            texts = [s['text'] for s in self._orig_segments]
            targets = [s['target'] for s in self._orig_segments]
        else:
            texts = self.texts()
            if not texts:
                return None
            default = str(self.cmb_target.currentData() or 'main')
            # 改了文本 ⇒ 按"一行一段"重排；有原值就沿用窗格，新增行落「默认窗格」。
            targets = [self._orig_targets[i] if i < len(self._orig_targets) else default
                       for i in range(len(texts))]
        return {'name': name, 'params_text': self.txt_params.text().strip(),
                'texts': texts, 'targets': targets}

    def check(self) -> tuple[str, str]:
        """跑真引擎体检（`parse_program` 整段口径）。返回 `(ok|warn|err, 人话)`。

        ⚠ 「🔎 检测语法」只管**语法**，**不要求先填名称** —— 名称是"保存"的要求
          （在 `to_payload` 里拦）；在这里拦会让用户对着一段完全合法的函数看到
          "名称和函数段都不能是空的"，纯属误导（它检测的是语法，不是表单完整性）。
        """
        texts = self.texts()
        if not texts:
            return 'err', '✗ 函数段是空的 —— 先写一段函数再检测'
        try:
            program = parse_program('\n'.join(texts))
        except Exception as e:                          # noqa: BLE001 —— 引擎异常也要给人话
            msg = str(e).strip() or type(e).__name__
            return 'err', f'✗ {msg}'
        n = program.unsupported_count
        if n:
            names = '、'.join(program.unsupported)
            return ('warn', f'⚠ 语法通过；{n} 处「{names}」本期不渲染 —— '
                            '载入/回测时会忽略并提示（非阻断，不影响其余语句）')
        return 'ok', f'✓ 语法通过（{len(texts)} 段）'

    def show_check(self, state: str, msg: str) -> None:
        self._show_result(state, msg)

    def _show_result(self, state: str, msg: str) -> None:
        if not state:
            self.lbl_result.hide()
            return
        self.lbl_result.setStyleSheet(_RESULT_QSS.get(state, _RESULT_QSS['ok']))
        self.lbl_result.setText(msg)
        self.lbl_result.show()
