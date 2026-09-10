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
                             QPushButton, QPlainTextEdit, QSizePolicy)

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
        texts() -> list[str]       # 各段当前文本 (空段保留，由调用方决定是否跳过)
        set_texts(list[str])       # 整体载入 (用于策略还原 / 对话框初始化)
        accessories() -> list      # 每段附件控件（accessory_factory 生成，可为 None）
        set_editable(bool)         # 检测通过后可锁住编辑区避免误改
    accessory_factory: 回调 f(段序号) -> QWidget|None，给每段挂一个额外控件（如目标窗格下拉）。

    【v6.7 修的两个真实 Bug（对话框里才暴露，回测页因在滚动容器里没显形）】
      ① **僵尸段**：`removeWidget + deleteLater()` 只把控件移出布局，在事件循环真正删除前
         它**仍是可见子控件** → 对话框里出现两个"函数段 1"。修法：先 `setParent(None)`
         立刻脱离父级（不可见、不参与绘制），再 `deleteLater()`。
      ② **排版塌陷**：编辑框原为 `setFixedHeight(96)`，父级分到多余高度时没有任何控件
         能承接 → Qt 把空档塞进段内部，标签被顶到最上、编辑框被推到很下面。
         修法：给编辑框 `Expanding` 纵向策略 + 最小高度，让多余高度**变成编辑区**。
    """

    changed = pyqtSignal()

    def __init__(self, placeholder: str, parent=None, *, accessory_factory=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._accessory_factory = accessory_factory
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

        self.btn_add_seg = QPushButton("＋ 添加函数段")
        self.btn_add_seg.setToolTip("再粘一段函数（如抄来的 MACD/KDJ）。"
                                    "多段在同一个变量池中顺序求值，后段可引用前段变量。")
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
        # v6.7：不再 setFixedHeight（那会让多余高度变成"标签与编辑框之间的大空档"）；
        # 改为最小高度 + 纵向 Expanding，多余高度直接变成可编辑面积（Bug ② 的根治）。
        editor.setMinimumHeight(110)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        head = QHBoxLayout()
        lbl = QLabel(f"· 函数段 {len(self._segments) + 1}")
        lbl.setStyleSheet(_HEADER_QSS)
        head.addWidget(lbl)
        head.addStretch()
        # v6.8：每段可挂一个"附件控件"（如行情页的目标窗格下拉）。
        # 回测页不传 factory ⇒ 行为零变化；附件放在"删除该段"左侧、右对齐。
        wrap.accessory = None
        if self._accessory_factory is not None:
            accessory = self._accessory_factory(len(self._segments))
            if accessory is not None:
                wrap.accessory = accessory
                head.addWidget(accessory)
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
        # v6.7：先脱离父级（立刻不可见），再排队删除 —— 否则 deleteLater 生效前
        # 它仍作为可见子控件挂在 _seg_box 上，表现为"多出一个同名函数段"（Bug ①）。
        wrap.setParent(None)
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
            wrap.setParent(None)      # v6.7：必须！否则留下可见的"僵尸段"（Bug ①）
            wrap.deleteLater()
        self._segments.clear()
        for t in texts:
            self.append_segment(t)
        self._renumber()
        self.changed.emit()

    def accessories(self) -> list:
        """按段顺序返回"每段附件控件"（未配置 `accessory_factory` 时全部为 None）。"""
        return [getattr(w, 'accessory', None) for w in self._iter_wraps()]

    def set_editable(self, editable: bool):
        for e in self._segments:
            e.setReadOnly(not editable)
