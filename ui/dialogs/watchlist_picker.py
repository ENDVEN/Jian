# ui/dialogs/watchlist_picker.py
"""从自选股里挑选 → 批量移入某个分组（§7-B8 R2 的**第二种添加入口**）。

【为什么单独一个弹窗、而不是塞进侧栏】侧栏宽 338px，装不下"可多选的长清单"；
而"整理分组"是一次性的批量动作，弹窗更贴合"选完就走"的心智，也不长期占版面。

【与「快添加」的分工（两者不是重复，是两件事）】
  · 侧栏的**快添加** = 把**新标的**加进某个分组（会新建自选记录）；
  · 本弹窗 = 把**已在自选里**的票**换个分组**（**只改归类 —— 绝不新建、绝不删除**）。

【为什么用原生多选而不是自绘复选框】Qt 里"点整行"与"点勾选框"的命中区会互相打架
（自己再连 `itemClicked` 去 toggle，点勾选框时会被 toggle 两次 ⇒ 看着像坏的）。
`ExtendedSelection` 是原生可靠的手感：点一下选一只，Ctrl/Shift 多选 ——
所以按钮上直接写「移入（3 只）」，用户不必猜自己选了几只。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout)

from ui.widgets.custom_widgets import COMBO_QSS_SMALL

_PICKER_QSS = (
    "QDialog { background:#F7F9FC; }"
    "QListWidget { background:white; border:1px solid #E4E9F0; border-radius:9px; outline:none;"
    " font-size:12.5px; color:#3A4250; }"
    "QListWidget::item { padding:7px 9px; border-bottom:1px solid #F4F7FB; }"
    "QListWidget::item:selected { background:#E8F2FE; color:#1565C0; }")
_BTN_QSS = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; border-radius:6px;"
            " padding:8px 18px; font-weight:bold; color:#424242; }"
            "QPushButton:hover { background:#EDEDED; }")
_BTN_PRIMARY_QSS = ("QPushButton { background:#1976D2; color:white; border:none; border-radius:6px;"
                    " padding:8px 18px; font-weight:bold; }"
                    "QPushButton:hover { background:#1565C0; }"
                    "QPushButton:disabled { background:#B9CFE6; color:#EEF4FB; }")


class WatchlistPickerDialog(QDialog):
    """勾选/多选自选里的若干只 → 选目标分组 → 「移入」。

    对外只暴露两个问题：`selected_symbols()`（**选了哪些**）与 `target_group()`（**移到哪**）——
    真正落库由 `DeskWatch.move_selected_to_group()` 做，本类**不碰 store**
    （弹窗只负责"问用户"，不负责"改数据"；这样它也能脱离 store 单独验收）。
    """

    def __init__(self, entries, groups, current_group: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("从自选股里挑选")
        self.resize(368, 470)
        self.setStyleSheet(_PICKER_QSS)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)

        hint = QLabel("点一下选一只，按住 Ctrl / Shift 可多选；选好目标分组后点「移入」。\n"
                      "只改归类 —— 不会新建、也不会删除任何自选股。")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:11.4px; color:#8A94A6;")
        box.addWidget(hint)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for entry in (entries or []):
            item = QListWidgetItem(
                f"{entry.get('name') or entry.get('symbol')}　{entry.get('symbol')}"
                f"　·　当前：{entry.get('group') or ''}")
            item.setData(Qt.ItemDataRole.UserRole, entry.get("symbol"))
            self.list_widget.addItem(item)
        box.addWidget(self.list_widget, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("移入"))
        self.cmb_group = QComboBox()
        self.cmb_group.setStyleSheet(COMBO_QSS_SMALL)
        for name in (groups or []):
            self.cmb_group.addItem(name, name)
        if current_group:
            index = self.cmb_group.findData(current_group)
            if index >= 0:
                self.cmb_group.setCurrentIndex(index)
        row.addWidget(self.cmb_group, 1)
        box.addLayout(row)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addStretch()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet(_BTN_QSS)
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)
        self.btn_move = QPushButton("移入")
        self.btn_move.setStyleSheet(_BTN_PRIMARY_QSS)
        self.btn_move.clicked.connect(self.accept)
        buttons.addWidget(self.btn_move)
        box.addLayout(buttons)

        self.list_widget.itemSelectionChanged.connect(self._sync_button)
        self._sync_button()

    # ---- 对外只回答两个问题 ----
    def selected_symbols(self) -> list:
        return [str(item.data(Qt.ItemDataRole.UserRole))
                for item in self.list_widget.selectedItems()]

    def target_group(self) -> str:
        return str(self.cmb_group.currentData() or "")

    # ---- 按钮状态 ----
    def _sync_button(self) -> None:
        """把"选了几只"写在按钮上，并在没选时禁用 ——
        点了什么都不做的按钮最让人困惑（§10-10 同款：动作要先说清后果）。
        """
        count = len(self.selected_symbols())
        self.btn_move.setText(f"移入（{count} 只）" if count else "移入")
        self.btn_move.setEnabled(bool(count))
