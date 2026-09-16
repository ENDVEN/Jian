# ui/widgets/desk_formula.py
"""ƒ 用户公式：编辑 / 编译 / 资产化 / 互送（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】把"用户贴进来的函数文本"变成"面板状态 + 可渲染的图层"：
  ① 编辑（`FormulaOverlayDialog`）→ 段与参数进页面状态；
  ② 编译成 programs（**失败不炸页面**，只写回执）；
  ③ 资产化（存配方 / 配方库载入 —— `data/formula_store.py` 门面）；
  ④ 与「📐 市场回测」互送（经主窗口转交，两个页面互不 import）。

【求值/落笔不在这里】`_formula_layers` / `_paint_layers` 属渲染装配，在
`ui/widgets/desk_layers.py`（本模块只负责"编译 + 回执 + 资产化"）。

【约定】状态留页面：`_formula_segments / _formula_params_text / _formula_programs /
_formula_error / _formula_store / cb_formula / lbl_formula_status / _sub_visible`，
本模块只承载行为，读写一律走 `self.page.X`。
"""
from PyQt6.QtWidgets import QDialog, QInputDialog, QMessageBox

from core.formula.program import FormulaProgramError, parse_program
from core.utils import parse_params_text
from data.formula_store import (SOURCE_MARKET, make_formula, segments_as_tuples)
from ui.dialogs.formula_overlay import FormulaOverlayDialog
from ui.widgets.chart_layers import scale_mismatch_hint
from ui.widgets.formula_library import FormulaLibraryDialog


class DeskFormula:
    """公式的编辑/编译/资产化/互送（页面持状态，本类持行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 编辑 + 编译
    # ==========================================
    def edit_formula(self):
        p = self.page
        dialog = FormulaOverlayDialog(p, segments=p._formula_segments,
                                      params_text=p._formula_params_text)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        p._formula_segments = dialog.result_segments()
        p._formula_params_text = dialog.params_text()
        self._compile_formula()
        p.render_charts()
        p._refresh_chips()      # 段变了 ⇒ "公式副图 N"的候选也跟着变

    def _compile_formula(self):
        """把 (函数文本, 目标窗格) 编译成 programs（顺序与 `_formula_segments` 一一对应）。"""
        p = self.page
        p._formula_programs = []
        p._formula_error = ""
        if not p._formula_segments:
            self._set_formula_status(True, "未设置")
            return
        for index, (text, _target) in enumerate(p._formula_segments, start=1):
            try:
                p._formula_programs.append(parse_program(text))
            except FormulaProgramError as e:
                p._formula_error = f"函数段 {index}: {e}"
                return

    # ==========================================
    # 回执（★STEP 5：一行摘要 + tooltip 详解）
    # ==========================================
    def _report_formula_status(self, df):
        """写面板状态：图层数 + 落点分布，必要时补一句"该放副图"的引导。"""
        p = self.page
        if not p._formula_programs:
            return
        if not any(p._layer_formula.values()):
            return          # 已由 _formula_layers 写过 ❌，不覆盖
        main_count = len(p._layer_formula.get('main', []))
        sub_targets = sorted(t for t in p._layer_formula
                             if t != 'main' and p._layer_formula[t])
        message = (f"✓ {sum(len(v) for v in p._layer_formula.values())} 个图层 · "
                   f"主图 {main_count} · 副图 {len(sub_targets)} 格")
        hint = None
        if main_count and not df.empty:
            hint = scale_mismatch_hint(p._layer_formula.get('main', []),
                                       float(df['low'].min()), float(df['high'].max()))
        if hint:
            self._set_formula_status(
                True, message + "\n⚠ 主图部分与股价量级相差很大 · 建议改用副图", warn=True)
            p.lbl_formula_status.setToolTip(hint)
        else:
            self._set_formula_status(True, message)

    def _set_formula_status(self, ok: bool, message: str, *, warn: bool = False,
                            detail: str = ""):
        """公式回执（★STEP 5：**一行可读摘要**，窄面板不再靠 `\\n` 折行）。

        ⚠ 单行消息时 `toolTip()` 必须与 `text()` **逐字相同** —— 既有断言就是这么比的
        （§11.7：回执升级不许把既有口径改坏）。
        """
        p = self.page
        line = " · ".join(part.strip() for part in str(message or "").splitlines()
                          if part.strip())
        p.lbl_formula_status.setText(line)
        p.lbl_formula_status.setToolTip(str(detail or message or line).strip())
        color = '#E65100' if warn else ('#4CAF50' if ok else '#F44336')
        p.lbl_formula_status.setStyleSheet(f"font-size: 11px; color: {color};")

    # ==========================================
    # 资产化 + 互送（P7 · §7-B3 P7）
    # ==========================================
    def save_formula_as(self):
        p = self.page
        if not p._formula_segments:
            QMessageBox.information(
                p, "暂无公式",
                "先在「✏️ 编辑公式…」里粘贴并应用一段函数，再保存为配方。")
            return
        name, ok = QInputDialog.getText(p, "保存为配方", "配方名称（同名即覆盖）：")
        if not ok:
            return
        try:
            formula = make_formula(name, p._formula_segments,
                                   params_text=p._formula_params_text,
                                   source=SOURCE_MARKET)
        except ValueError as e:
            QMessageBox.warning(p, "无法保存", str(e))
            return
        saved = p._formula_store.upsert(formula)
        self._set_formula_status(True, f"✓ 已存入配方库：{saved['name']}")

    def open_formula_library(self):
        p = self.page
        dialog = FormulaLibraryDialog(p._formula_store, p)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        formula = dialog.selected_formula()
        if not formula:
            return
        self.receive_formula(segments_as_tuples(formula), formula.get("params_text", ""),
                             source_label=f"配方库「{formula['name']}」")

    def send_formula_to_backtest(self) -> int:
        """行情页 → 回测页（由主窗口转交，两个页面互不 import）；返回送过去的段数。"""
        p = self.page
        if not p._formula_segments:
            QMessageBox.information(
                p, "暂无公式", "先在「✏️ 编辑公式…」里写好函数，再送去回测。")
            return 0
        count = p.main_win.send_formula_to_backtest(
            p._formula_segments, p._formula_params_text)
        if count:
            self._set_formula_status(True, f"✓ 已把 {count} 段函数送到「📐 市场回测」")
        return count

    def receive_formula(self, segments, params_text: str = "",
                        source_label: str = "外部") -> int:
        """接收外来配方（回测页 / 配方库）并立即生效。

        :return: 实际载入的段数（0 = 内容为空，什么都没做）
        """
        p = self.page
        pairs = [(str(text), str(target)) for text, target in (segments or [])
                 if str(text or "").strip()]
        if not pairs:
            return 0
        p._formula_segments = pairs
        p._formula_params_text = str(params_text or "")
        p._sub_visible = {"sub1": True, "sub2": True, "sub3": True}   # 外来公式：副图先全开
        p.cb_formula.setChecked(True)     # 刚送来的公式就该看得见
        self._compile_formula()
        p.render_charts()
        p._refresh_chips()
        # 回执写在渲染**之后**：否则会被 `_report_formula_status` 的图层统计覆盖
        self._set_formula_status(True, f"✓ 已从{source_label}载入 {len(pairs)} 段函数")
        return len(pairs)

    def _restore_last_formula(self):
        """开机自动恢复"上次用过的配方" —— §7-B3 P7 要解决的"公式重启就丢"。"""
        p = self.page
        formula = p._formula_store.last_used()
        if not formula:
            return
        pairs = segments_as_tuples(formula)
        if not pairs:
            return
        p._formula_segments = pairs
        p._formula_params_text = formula.get("params_text", "")
        self._compile_formula()
        self._set_formula_status(True, f"✓ 已自动载入上次配方「{formula['name']}」"
                                       f"（{len(pairs)} 段）")
