# ui/widgets/formula_library.py
"""公式配方库对话框（§7-B3 P7）—— 浏览 / 载入 / 改名 / 删除。

【职责边界】
  只做"选一条配方并把它交回调用方"，**不碰行情数据、不绘图、不猜目标窗格**：
  载入后具体怎么用，由页面决定（行情页保留每段目标；回测页只用文本，见 §7-B3 P7）。
  这样同一个对话框可以被两个页面共用，不必各写一套（§9-O7 的教训）。

【为什么单独一个文件】
  `ui/dialogs/` 放"用户主动打开的一次性窗口"，这里虽只有 200 行，但它是**跨页面共用件**，
  放在 widgets 下与 `function_segments.py`（同样是跨页面共用控件）保持一致。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                             QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QPushButton, QVBoxLayout)

from data.formula_store import (SOURCE_LABELS, normalize_segments,
                                segments_as_tuples)
from ui.widgets.custom_widgets import mono_font_css   # ★v1.46 §10-15 开源等宽栈（唯一出口）

_BTN_QSS = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; border-radius:6px; "
            "padding:6px 12px; font-weight:bold; color:#424242; }"
            "QPushButton:hover { background:#EDEDED; }")
_BTN_PRIMARY_QSS = ("QPushButton { background:#1976D2; color:white; border:none; border-radius:6px; "
                    "padding:7px 16px; font-weight:bold; } QPushButton:hover { background:#1565C0; }")
_BTN_DANGER_QSS = ("QPushButton { background:#FFEBEE; border:1px solid #FFCDD2; border-radius:6px; "
                   "padding:6px 12px; font-weight:bold; color:#D32F2F; }")


def preview_text(formula: dict) -> str:
    """把一条配方渲染成"给人看"的文本（列表右侧预览用；纯函数，可断言）。"""
    formula = formula or {}
    segments = normalize_segments(formula.get("segments"))
    lines = [
        f"名称：{formula.get('name', '')}",
        f"来源：{SOURCE_LABELS.get(formula.get('source'), '未知')}"
        f"　·　段数：{len(segments)}"
        f"　·　参数：{formula.get('params_text') or '（无）'}",
        f"保存：{formula.get('updated_at', '') or '—'}"
        f"　　最近使用：{formula.get('used_at') or '从未'}",
        "",
    ]
    for index, (_text, target) in enumerate(segments_as_tuples({"segments": segments}), start=1):
        target_label = {"main": "主图"}.get(target, target.upper())
        lines.append(f"—— 函数段 {index}（目标：{target_label}）——")
        lines.append(segments[index - 1]["text"])
        lines.append("")
    return "\n".join(lines).rstrip()


class FormulaLibraryDialog(QDialog):
    """配方库窗口。

    用法::

        dlg = FormulaLibraryDialog(store, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            formula = dlg.selected_formula()      # dict
    """

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self._selected_formula: dict | None = None

        self.setWindowTitle("📚 公式配方库")
        self.resize(880, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("公式配方库")
        title.setStyleSheet("font-size:16px; font-weight:bold; color:#212121;")
        lay.addWidget(title)
        hint = QLabel("把常用的函数存成配方，换标的/重启后一键载入。"
                      "「目标窗格」只在行情页生效；送回测页时只带入函数与参数。")
        hint.setStyleSheet("color:#8A94A6; font-size:12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(12)

        self.lst_formulas = QListWidget()
        self.lst_formulas.setFixedWidth(240)
        self.lst_formulas.currentItemChanged.connect(lambda *_: self._refresh_preview())
        body.addWidget(self.lst_formulas)

        self.txt_preview = QPlainTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setStyleSheet(
            "QPlainTextEdit { border:1px solid #E7EAF0; border-radius:8px; background:#FCFCFD; "
            + mono_font_css() + " font-size:12px; padding:8px; }")
        body.addWidget(self.txt_preview, 1)
        lay.addLayout(body, 1)

        bar = QHBoxLayout()
        self.btn_load = QPushButton("✅ 载入选中")
        self.btn_load.setStyleSheet(_BTN_PRIMARY_QSS)
        self.btn_load.clicked.connect(self.load_selected)
        bar.addWidget(self.btn_load)

        self.btn_rename = QPushButton("✏️ 改名")
        self.btn_rename.setStyleSheet(_BTN_QSS)
        self.btn_rename.clicked.connect(self.rename_selected)
        bar.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.setStyleSheet(_BTN_DANGER_QSS)
        self.btn_delete.setToolTip("删除这条配方（不可撤销，会二次确认）")
        self.btn_delete.clicked.connect(self.delete_selected)
        bar.addWidget(self.btn_delete)
        bar.addStretch()

        self.btn_close = QPushButton("关闭")
        self.btn_close.setStyleSheet(_BTN_QSS)
        self.btn_close.clicked.connect(self.reject)
        bar.addWidget(self.btn_close)
        lay.addLayout(bar)

        self.refresh()

    # ==========================================
    # 对外
    # ==========================================
    def selected_formula(self) -> dict | None:
        """点过「载入选中」后返回该配方；取消/未选返回 None。"""
        return self._selected_formula

    def current_formula(self) -> dict | None:
        item = self.lst_formulas.currentItem()
        return None if item is None else self._store.get(item.data(Qt.ItemDataRole.UserRole))

    def refresh(self, keep_id: str = "") -> None:
        """重建列表（载入/删除/改名后调用）。"""
        self.lst_formulas.clear()
        formulas = self._store.list_formulas()
        for formula in formulas:
            item = QListWidgetItem(formula["name"])
            item.setData(Qt.ItemDataRole.UserRole, formula["id"])
            item.setToolTip(formula.get("params_text") or "（无参数）")
            self.lst_formulas.addItem(item)
        if formulas:
            row = 0
            if keep_id:
                for index in range(self.lst_formulas.count()):
                    if self.lst_formulas.item(index).data(Qt.ItemDataRole.UserRole) == keep_id:
                        row = index
                        break
            self.lst_formulas.setCurrentRow(row)
        else:
            self.txt_preview.setPlainText(
                "库还是空的。\n\n在行情页/回测页点「💾 存为配方…」即可把当前函数存进来。")
        self._refresh_buttons()

    # ==========================================
    # 交互
    # ==========================================
    def load_selected(self):
        formula = self.current_formula()
        if formula is None:
            return
        self._selected_formula = formula
        self._store.touch(formula["id"])      # 记录"用过了"（也是自动恢复的依据）
        self.accept()

    def rename_selected(self):
        formula = self.current_formula()
        if formula is None:
            return
        new_name, ok = QInputDialog.getText(self, "重命名配方", "新名称：",
                                            text=formula["name"])
        if not ok:
            return
        if not self._store.rename(formula["id"], new_name):
            QMessageBox.warning(self, "无法重命名",
                                "名称为空，或已存在同名配方（同名会互相覆盖，请换一个名字）。")
            return
        self.refresh(keep_id=formula["id"])

    def delete_selected(self):
        formula = self.current_formula()
        if formula is None:
            return
        answer = QMessageBox.question(
            self, "删除配方",
            f"确定删除配方「{formula['name']}」吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(formula["id"])
        self.refresh()

    # ==========================================
    # 内部
    # ==========================================
    def _refresh_preview(self):
        formula = self.current_formula()
        self.txt_preview.setPlainText("" if formula is None else preview_text(formula))
        self._refresh_buttons()

    def _refresh_buttons(self):
        has_selection = self.current_formula() is not None
        for button in (self.btn_load, self.btn_rename, self.btn_delete):
            button.setEnabled(has_selection)
