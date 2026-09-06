# ui/widgets/function_segments.py
"""
① 多函数段编辑器 (阶段A) —— 把单段粘贴升级为「多段共享变量池」。

为什么需要多段：
    用户手里的策略经常来自不同来源 (自己写的 / AI 生成 / 抄的标准 MACD、KDJ…)。
    旧版只能粘贴“一整段”，不会拼函数的用户没法把多个指标合流。

新模型：
    每个段都是一段独立的通达信式函数文本；检测/执行时按声明顺序在【同一个
    EvalContext】上运行 (见 core/formula/program.execute_programs)，因此：
      - 各段产出变量汇入同一个共享变量池，买卖条件可任意引用；
      - 后段可以引用前段产出的变量。
    本控件只负责「多段文本的组织与增删」，不碰解析/网络/SQL。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QPlainTextEdit)

_EDITOR_QSS = ("QPlainTextEdit { font-family: Consolas, 'Microsoft YaHei', monospace; "
               "font-size: 13px; border: 1px solid #E0E4EC; border-radius: 8px; "
               "background: #FAFBFD; padding: 6px; }")
_HEADER_QSS = ("QLabel { font-size: 12px; font-weight: bold; color: #8A94A6; }")
_FLAT_QSS = ("QPushButton { color: #8A94A6; background: transparent; border: none; "
             "padding: 2px 6px; font-weight: bold; border-radius: 6px; font-size: 11px; }"
             "QPushButton:hover { color: #F44336; background: #FDECEA; }")


class FunctionSegments(QWidget):
    """多段函数文本容器。

    对外 API:
        texts() -> list[str]       # 各段当前文本 (跳过空段? 由调用方定)
        set_texts(list[str])       # 整体载入 (用于策略还原)
        text_count() -> int
        set_editable(bool)         # 检测通过后可锁住编辑区避免误改
    """

    changed = pyqtSignal()

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._segments: list[QPlainTextEdit] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._lay = lay

        self._seg_box = QWidget()
        self._seg_lay = QVBoxLayout(self._seg_box)
        self._seg_lay.setContentsMargins(0, 0, 0, 0)
        self._seg_lay.setSpacing(8)
        lay.addWidget(self._seg_box)

        self.btn_add_seg = QPushButton("＋ 添加函数段（多段共享变量池，后段可引用前段）")
        self.btn_add_seg.setStyleSheet("QPushButton { color: #1976D2; background: transparent; "
                                       "border: none; padding: 2px 0; font-weight: bold; "
                                       "font-size: 12px; text-align: left; }"
                                       "QPushButton:hover { color: #0D5BB5; }")
        self.btn_add_seg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_seg.clicked.connect(self.append_segment)
        lay.addWidget(self.btn_add_seg)

        # 初始一段
        self.append_segment()
        self._renumber()

    # ---------- 段管理 ----------
    def append_segment(self, text: str = ""):
        editor = QPlainTextEdit()
        editor.setPlaceholderText(self._placeholder if not self._segments
                                  else "（可选）粘贴本段函数，变量自动进入共享池")
        editor.setStyleSheet(_EDITOR_QSS)
        if text:
            editor.setPlainText(text)
        editor.setFixedHeight(96)

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        head = QHBoxLayout()
        lbl = QLabel(f"· 函数段 {len(self._segments) + 1}")
        lbl.setStyleSheet(_HEADER_QSS)
        head.addWidget(lbl)
        head.addStretch()
        btn_del = QPushButton("✕ 删除该段")
        btn_del.setStyleSheet(_FLAT_QSS)
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.clicked.connect(lambda: self._remove_segment(wrap))
        head.addWidget(btn_del)
        v.addLayout(head)
        v.addWidget(editor)
        wrap.editor = editor
        wrap.lbl = lbl

        self._seg_lay.addWidget(wrap)
        self._segments.append(editor)
        self._renumber()
        self.changed.emit()
        return wrap

    def _remove_segment(self, wrap):
        if len(self._segments) <= 1:
            return  # 至少保留一段
        self._seg_lay.removeWidget(wrap)
        if wrap.editor in self._segments:
            self._segments.remove(wrap.editor)
        wrap.deleteLater()
        self._renumber()
        self.changed.emit()

    def _renumber(self):
        """删除一段后其余段序号保持连续"""
        wraps = [w for w in self._iter_wraps()]
        for i, wrap in enumerate(wraps):
            wrap.lbl.setText(f"· 函数段 {i + 1}")

    def _iter_wraps(self):
        for i in range(self._seg_lay.count()):
            item = self._seg_lay.itemAt(i)
            w = item.widget()
            if w is not None and hasattr(w, 'editor'):
                yield w

    # ---------- 对外 API ----------
    def texts(self) -> list[str]:
        return [e.toPlainText() for e in self._segments]

    def set_texts(self, texts: list):
        texts = [t for t in (texts or []) if t and t.strip()]
        if not texts:
            texts = [""]
        # 清空重建
        for wrap in list(self._iter_wraps()):
            self._seg_lay.removeWidget(wrap)
            wrap.deleteLater()
        self._segments.clear()
        for t in texts:
            self.append_segment(t)
        self._renumber()
        self.changed.emit()

    def set_editable(self, editable: bool):
        for e in self._segments:
            e.setReadOnly(not editable)
