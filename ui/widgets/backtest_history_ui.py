# ui/widgets/backtest_history_ui.py
"""🗂 运行历史「版式 + 渲染」（§7-A4 · v1.37 立 · **v1.46 按样板重做**）。

【分工】本模块只造控件、只把数据画出来；**不碰存档、不调 M1 页**。
业务与接线全在 `ui/views/backtest_history.py`（薄壳：状态 + 信号连接）。

【v1.46 重做：三件事】
  ① **kind 差异全部查表** —— 列 / 过滤轴 / 可用动作来自 `ui/widgets/history_kinds.py`，
     本文件里**没有任何 `if kind == ...`**（旧版散在 6 处，改一种 kind 要动 6 个地方）。
  ② **M2/M3 有自己的形态** —— 旧版直接照抄 M1：4 个"累计/胜率/成交/平均单笔"胶囊
     （横截面没有这些概念）+ 一块画不出净值的空白图（132px 纯浪费）。现在用
     `ScanStatBar`（**四态占比条**：命中/未命中/数据不足/被粗筛剔除）+ 条件全文（可复制）
     + 粗筛摘要；M2/M3 **不放净值图**。
  ③ **窄栏不再挤掉列表** —— 旧版动作行 6 个按钮挤一行，实测预览栏最小宽 **612px**
     ⇒ 分割器被迫把宽度给右栏、左列表被裁（用户报的"右侧展开栏遮挡列表"）。
     现在动作行走 `FlowHost`（按宽度自动换行）+ 删除按钮隔离到最右 + 左右各设最小宽。

【两条渲染纪律（沿用）】
  ① 表格数字着色用 **delegate**，不用 `item.setForeground` —— 后者在"整行选中"时会与
     蓝色高亮叠成"红绿字压在蓝底上"（用户实测反馈）。
  ② 迷你净值曲线的买卖点**必须画在曲线上**（用成交日净值定位，不是成交价 —— 量纲不同）。
"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                             QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPlainTextEdit, QPushButton, QSizePolicy, QSplitter,
                             QStyle, QStyledItemDelegate, QStyleOptionViewItem,
                             QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
                             QWidget)

from config import settings
from core.cross_section import human_amount, human_mktcap
from data.backtest_archive import KIND_M1, KIND_LABELS, SOURCE_LABELS
from ui.widgets.chart_style import apply_pokorny_style
from ui.widgets.custom_widgets import (FlowHost, ScrollRegion, apply_ui_font,
                                       mono_font_css)
from ui.widgets.history_kinds import ACTION_ORDER, KIND_SPECS, spec_of

__all__ = ['HistoryFilterBar', 'HistoryTable', 'HistoryPreviewPane',
           'HistorySettingsBar', 'MiniEquityChart', 'ScanStatBar', 'SectionCard',
           'build_history_layout', 'COL_PIN', '_SignedValueDelegate']

# ---- 配色（与全站一致的语义色；文字色取"可读版"，避免高饱和）----
_MONEY = "#1B7F3B"
_LOSS = "#B3261E"
_MUTED = "#8A94A6"
_TEXT = "#1F2430"
_ACCENT = "#1976D2"
_CENTER = Qt.AlignmentFlag.AlignCenter
_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

_CARD_QSS = "QFrame#HistCard{background:#fff;border:1px solid #E4E9F0;border-radius:10px;}"
_PILL_QSS = ("background:#F5F6F8;border-radius:8px;padding:8px 10px;"
             "font-size:12px;color:#8A94A6;")
_TABLE_QSS = (
    "QTableWidget{background:#fff;alternate-background-color:#F7F9FC;font-size:12.5px;"
    " border:1px solid #E7EAF0;border-radius:8px;gridline-color:transparent;}"
    "QTableWidget::item{padding:6px 8px;border:none;}"
    # 选中行：浅蓝底 + 深色字 —— 显式覆盖单元格前景色，杜绝"蓝底红绿字"
    "QTableWidget::item:selected{background:#E3F2FD;color:#1F2430;}"
    "QHeaderView::section{background:#F4F6FA;color:#5B6472;font-weight:bold;"
    " padding:6px;border:none;}"
)
_FLAT_QSS = ("QPushButton{border:1px solid #E4E9F0;background:#fff;border-radius:8px;"
             " padding:6px 12px;font-size:13px;color:#1F2430;}"
             "QPushButton:hover{background:#F3F8FE;border-color:#BBDEFB;color:#1976D2;}"
             "QPushButton:disabled{color:#B8C2D0;background:#F5F6F8;border-color:#EDF0F5;}")
_PRIMARY_QSS = ("QPushButton{background:#1976D2;color:#fff;font-weight:bold;border:none;"
                " border-radius:8px;padding:7px 14px;}"
                "QPushButton:hover{background:#1565C0;}"
                "QPushButton:disabled{background:#B7D3F0;}")
_DANGER_QSS = ("QPushButton{border:1px solid #F0DAD7;background:#fff;border-radius:8px;"
               " padding:6px 12px;font-size:13px;color:#B3261E;}"
               "QPushButton:hover{background:#FDECEA;}"
               "QPushButton:disabled{color:#E0BDB9;background:#F7F8FA;border-color:#EDF0F5;}")
_SECT_QSS = (
    "QFrame#HistSect{background:#FFFFFF;border:1px solid #EDF0F5;border-radius:8px;}"
    "QFrame#HistSectHead{background:#FAFBFD;border:none;"
    " border-top-left-radius:7px;border-top-right-radius:7px;}"
    "QLabel#HistSectTitle{font-size:12.5px;font-weight:bold;color:#3A4250;"
    " border:none;background:transparent;}"
    "QLabel#HistSectMeta{font-size:11.5px;color:#8A94A6;border:none;background:transparent;}")
_CODE_QSS = ("QPlainTextEdit#HistCode{background:#1E2633;color:#D7E2F2;border:none;"
             + mono_font_css() + "font-size:11.5px;padding:8px;}")
_STATBAR_QSS = ("QFrame#HistStatBar{background:#F5F6F8;border:1px solid #EDF0F5;"
                "border-radius:6px;}")

# 四态占比条的段（顺序 = 画法顺序；颜色 = 语义色，与结果表 KPI 同源）
SCAN_SEGMENTS = (
    ('hit', '命中', '#2E7D32'),
    ('miss', '未命中', '#9AA3B2'),
    ('insufficient', '数据不足', '#FB8C00'),
    ('filtered', '被粗筛剔除', '#C9D2DE'),
)

COL_PIN = 0          # ★ 列（两种 kind 都是第 0 列）—— 验收断言按它取 pin 单元格
COL_TIME = 1         # 时间列（行主键 `_ID_ROLE` 挂在这一列上）
_SIGN_ROLE = Qt.ItemDataRole.UserRole + 1
_ID_ROLE = Qt.ItemDataRole.UserRole


class _SignedValueDelegate(QStyledItemDelegate):
    """给「胜率 / 累计」列按正负着色；**选中态直接交给样式表**（不再叠色）。

    之所以用 delegate 而不是 `item.setForeground`：后者会与 `::item:selected`
    的蓝色高亮打架 —— 选中行上出现红/绿字（用户实测反馈"点一下就有颜色"）。
    ⚠ v1.46：**哪些列要着色由 kind 声明表决定**（`ColumnSpec.signed`），不再写死列号。
    """

    def __init__(self, table):
        super().__init__(table)
        self._table = table

    def paint(self, painter, option, index):  # noqa: N802 —— Qt 命名约定
        kind = self._table.sign_kind(index.column())
        if kind and not (option.state & QStyle.StateFlag.State_Selected):
            sign = index.data(_SIGN_ROLE)
            if sign is not None:
                option = QStyleOptionViewItem(option)
                option.palette.setColor(QPalette.ColorRole.Text,
                                        QColor(_MONEY if sign >= 0 else _LOSS))
        super().paint(painter, option, index)


# ==========================================
# L1 · 过滤条
# ==========================================
class HistoryFilterBar(QWidget):
    """一行操作轴：kind 过滤 + 只看重点 + 过滤轴（标的/范围）+ 搜索 + 刷新。

    过滤轴的**标题与占位文字随 kind 变**（M1 = 标的/策略，M2/M3 = 范围/条件）——
    旧版在 M2/M3 下仍写着"按 标的 / 策略 搜索"，而它们根本没有标的。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        title = QLabel("🗂 运行历史")
        title.setStyleSheet(f"font-size:15px;font-weight:bold;color:{_TEXT};")
        lay.addWidget(title)

        self.cmb_kind = QComboBox()
        self.cmb_kind.setToolTip("按类型过滤历史：M1 单股回测 / M2 全市场筛选 / M3 广度统计")
        for spec in KIND_SPECS.values():
            self.cmb_kind.addItem(spec.tab_label, spec.kind)
        self.cmb_kind.setCurrentIndex(0)
        lay.addWidget(self.cmb_kind)

        self.chk_pinned = QCheckBox("只看重点 ★")
        self.chk_pinned.setStyleSheet(f"color:{_MUTED};font-size:12px;")
        lay.addWidget(self.chk_pinned)

        self.lbl_facet = QLabel("标的")
        self.lbl_facet.setStyleSheet(f"color:{_MUTED};font-size:12px;")
        lay.addWidget(self.lbl_facet)

        self.cmb_facet = QComboBox()
        self.cmb_facet.setMinimumWidth(160)
        self.cmb_facet.setToolTip("按标的/范围过滤（只列出历史里出现过的）")
        lay.addWidget(self.cmb_facet)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("按 标的 / 策略 搜索")
        self.ed_search.setFixedWidth(170)
        lay.addWidget(self.ed_search)

        lay.addStretch(1)

        self.btn_refresh = QPushButton("↻ 刷新")
        self.btn_refresh.setStyleSheet(_FLAT_QSS)
        lay.addWidget(self.btn_refresh)

    # ---------- 读 ----------
    def current_kind(self) -> str:
        return self.cmb_kind.currentData() or KIND_M1

    def current_facet(self) -> str:
        return self.cmb_facet.currentData() or ""

    # ---------- 写 ----------
    def apply_spec(self, spec) -> None:
        """过滤轴的标题 / 占位文字 / 「全部」条目的措辞随 kind 变。"""
        self.lbl_facet.setText(spec.facet_label)
        self.ed_search.setPlaceholderText(spec.search_hint)
        self.cmb_facet.setItemText(0, f"全部{spec.facet_label}")

    def set_options(self, pairs: list, facet_label: str = "") -> None:
        """重建过滤下拉（`[(值, 显示名)]`）；尽量保持当前选择。"""
        keep = self.current_facet()
        self.cmb_facet.blockSignals(True)
        self.cmb_facet.clear()
        self.cmb_facet.addItem(f"全部{facet_label}" if facet_label else "全部", "")
        for value, label in pairs:
            self.cmb_facet.addItem(f"{label} {value}".strip(), value)
        idx = self.cmb_facet.findData(keep)
        self.cmb_facet.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_facet.blockSignals(False)


# ==========================================
# 左列表
# ==========================================
class HistoryTable(QTableWidget):
    """存档列表：**列由 kind 声明表决定**；选中一行即触发预览。只渲染，不加载记录。

    ⚠ 列宽策略（§11.5-69 的教训）：**不许 ResizeToContents**（动态测宽 ⇒ 每次填格
    都全表重测）。这里 = 全 Interactive → 填完数据 → **每个 kind 只测一次宽** →
    把声明的 `stretch` 列设成 Stretch（吃掉剩余宽度，避免常驻横向滚动条）。
    """

    sig_selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(0, 0, parent)
        self._spec = spec_of(KIND_M1)
        self._signed: dict = {}
        self._sized_kind = None
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setShowGrid(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        self.setStyleSheet(_TABLE_QSS)
        self.setItemDelegate(_SignedValueDelegate(self))
        self.itemSelectionChanged.connect(self.sig_selection_changed)

    # ---------- 渲染 ----------
    def populate(self, entries: list, kind: str = KIND_M1) -> None:
        """用索引条目重建表格（会清空选中；调用方负责恢复）。"""
        spec = spec_of(kind)
        self._spec = spec
        self._signed = {i: col.signed for i, col in enumerate(spec.columns) if col.signed}
        self.blockSignals(True)          # 重建期间不要回调，避免"半成品状态"外泄
        try:
            self.setColumnCount(len(spec.columns))
            self.setHorizontalHeaderLabels([col.title for col in spec.columns])
            self.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                for col, colspec in enumerate(spec.columns):
                    item = QTableWidgetItem(str(colspec.getter(entry)))
                    item.setTextAlignment(_CENTER if colspec.align == 'center' else _LEFT)
                    if colspec.tip_getter is not None:
                        item.setToolTip(str(colspec.tip_getter(entry) or ''))
                    if col == COL_TIME:
                        item.setData(_ID_ROLE, entry.get("id"))   # 行主键随行携带（不靠行号）
                    if colspec.signed == 'win':
                        win = entry.get("win_rate")
                        item.setData(_SIGN_ROLE, None if win is None else float(win) - 0.5)
                    elif colspec.signed == 'cum':
                        cum = entry.get("cumulative_return")
                        item.setData(_SIGN_ROLE, None if cum is None else float(cum))
                    self.setItem(row, col, item)
        finally:
            self.blockSignals(False)
        self._apply_widths(spec)

    def _apply_widths(self, spec) -> None:
        header = self.horizontalHeader()
        for col in range(self.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        if self._sized_kind != spec.kind:        # 每个 kind 只测一次（切 kind 才重测）
            self.resizeColumnsToContents()
            self._sized_kind = spec.kind
        for col, colspec in enumerate(spec.columns):
            if colspec.stretch:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

    def sign_kind(self, col: int) -> str:
        """该列是否需要按正负着色（供 delegate 查）。"""
        return self._signed.get(col, '')

    # ---------- 选中 ----------
    def current_id(self):
        """选中行的存档 id（没选中返回 None）。"""
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not rows:
            return None
        item = self.item(rows[0].row(), COL_TIME)
        return item.data(_ID_ROLE) if item is not None else None

    def select_by_id(self, rid) -> bool:
        """按 id 选中并滚动到该行；找不到返回 False。"""
        if not rid:
            return False
        for row in range(self.rowCount()):
            item = self.item(row, COL_TIME)
            if item is not None and item.data(_ID_ROLE) == rid:
                self.selectRow(row)
                self.scrollToItem(item)
                return True
        return False

    def update_row(self, entry: dict) -> bool:
        """就地更新一行的动态列（★ / 来源）—— pin 用，**不整表重建**（保住选中）。"""
        rid = entry.get("id")
        for row in range(self.rowCount()):
            item = self.item(row, COL_TIME)
            if item is None or item.data(_ID_ROLE) != rid:
                continue
            pin_item = self.item(row, COL_PIN)
            if pin_item is not None:
                pinned = bool(entry.get("pinned"))
                pin_item.setText("★" if pinned else "")
                pin_item.setToolTip("★ 重点：不被自动淘汰" if pinned else "标为「★ 重点」")
            src_item = self.item(row, self.columnCount() - 1)
            if src_item is not None:
                src_item.setText(SOURCE_LABELS.get(entry.get("source"), "自动"))
            return True
        return False


# ==========================================
# 右预览 · M1 专用：迷你净值曲线
# ==========================================
class MiniEquityChart(pg.PlotWidget):
    """迷你净值曲线 + 买卖点（点落在曲线上 —— 成交日净值定位）。**只有 M1 用。**"""

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_pokorny_style(self, background="w", margins=0)
        self.setFixedHeight(132)
        self.setMouseEnabled(False, False)       # 预览小图：不缩放不拖动
        self.getPlotItem().setLabel('left', '净值')
        self.getPlotItem().showAxis('bottom', False)
        self._empty()

    def _empty(self, text: str = "选中一份存档查看净值曲线"):
        self.clear()
        self.getPlotItem().setTitle(text, color="#9AA3B2", size="10pt")

    def set_series(self, rows: list) -> None:
        """画一次净值序列（含买卖点）。⚠ 方法名不能叫 `plot` —— 会遮蔽 `PlotWidget.plot`。"""
        rows = rows or []
        if not rows:
            self._empty("该存档没有净值序列")
            return
        self.clear()
        self.getPlotItem().setTitle("")
        ys = [float(r.get("equity") or 0.0) for r in rows]
        # ⚠ `PlotWidget` 的 `plot` 是 `__getattr__` 转发到 PlotItem 的，不在 MRO 里 ⇒
        # `super().plot(...)` 会 AttributeError；必须显式走 `getPlotItem().plot(...)`。
        self.getPlotItem().plot(list(range(len(ys))), ys, pen=pg.mkPen(_ACCENT, width=2))
        self.addLine(y=1.0, pen=pg.mkPen('#BDBDBD', style=Qt.PenStyle.DashLine))
        for key, symbol, color in (("buy_at", 't', settings.COLOR_PROFIT),
                                   ("sell_at", 'd', settings.COLOR_LOSS)):
            xs = [i for i, r in enumerate(rows) if r.get(key) is not None]
            if xs:
                self.addItem(pg.ScatterPlotItem(
                    x=xs, y=[float(rows[i][key]) for i in xs], symbol=symbol,
                    size=9, brush=pg.mkBrush(color), pen='w'))


# ==========================================
# 右预览 · M2/M3 专用：四态占比条
# ==========================================
class ScanStatBar(QWidget):
    """横截面快照的**四态占比条**（★v1.46 替代旧版 4 个 M1 语义的胶囊）。

    【为什么是"条"而不是 4 个数字】横截面最要紧的信息是**比例** ——
    "300 只里 256 只没数据"用四个孤立数字看不出来，用一条占比条一眼就是压倒性的橙色。
    段宽按只数比例分；太窄的段不写字（数字进 tooltip 与图例），绝不撑宽面板（§11.5-73）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.lbl_head = QLabel("—")
        self.lbl_head.setStyleSheet(f"font-size:12px;color:{_TEXT};")
        self.lbl_head.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.lbl_head)

        self.bar = QFrame()
        self.bar.setObjectName("HistStatBar")
        self.bar.setStyleSheet(_STATBAR_QSS)
        self.bar.setFixedHeight(22)
        self._bar_lay = QHBoxLayout(self.bar)
        self._bar_lay.setContentsMargins(0, 0, 0, 0)
        self._bar_lay.setSpacing(0)
        lay.addWidget(self.bar)

        self._segs = {}
        for key, _name, color in SCAN_SEGMENTS:
            seg = QLabel("")
            seg.setAlignment(_CENTER)
            seg.setMinimumWidth(0)
            seg.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            seg.setStyleSheet(f"background:{color};color:#fff;font-size:11px;font-weight:bold;")
            seg.hide()
            self._bar_lay.addWidget(seg)
            self._segs[key] = seg

        self.lbl_legend = QLabel("")
        self.lbl_legend.setWordWrap(True)
        self.lbl_legend.setStyleSheet(f"font-size:11.5px;color:{_TEXT};")
        lay.addWidget(self.lbl_legend)

    def clear(self) -> None:
        self.lbl_head.setText("—")
        for seg in self._segs.values():
            seg.hide()
            seg.setText("")
        self.lbl_legend.setText("")

    def render(self, counts: dict, elapsed_ms=None) -> None:
        counts = counts or {}
        total = int(counts.get('total') or 0) or 1
        valid = int(counts.get('valid') or 0)
        rate = counts.get('hit_rate')
        head = f"有效样本 {valid} / {total}"
        if rate is not None:
            head += f"      命中率 {float(rate) * 100:.1f}%"
        if elapsed_ms:
            head += f"      用时 {float(elapsed_ms) / 1000:.2f} s"
        self.lbl_head.setText(head)

        legend = []
        for key, name, color in SCAN_SEGMENTS:
            value = int(counts.get(key) or 0)
            seg = self._segs[key]
            idx = self._bar_lay.indexOf(seg)
            if value <= 0:
                seg.hide()
                self._bar_lay.setStretch(idx, 0)
                continue
            seg.show()
            seg.setText(str(value) if value / total >= 0.10 else "")
            seg.setToolTip(f"{name} {value} 只（{value / total * 100:.1f}%）")
            self._bar_lay.setStretch(idx, max(1, value))
            legend.append(f'<span style="color:{color}">■</span> {name} {value}')
        self.lbl_legend.setText("&nbsp;&nbsp;&nbsp;".join(legend))


# ==========================================
# 小件：带标题的卡片块
# ==========================================
class SectionCard(QFrame):
    """带标题行的小卡片（标题 + 右侧 meta / 动作 + 正文）。

    用于「筛选条件」「粗筛漏斗」等 —— 样式收敛在本文件（§10-9），业务页面不许就地写。
    """

    def __init__(self, title: str, meta: str = '', action: QWidget = None, parent=None):
        super().__init__(parent)
        self.setObjectName("HistSect")
        self.setStyleSheet(_SECT_QSS)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        head = QFrame()
        head.setObjectName("HistSectHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 7, 10, 7)
        hl.setSpacing(8)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("HistSectTitle")
        self.lbl_meta = QLabel(meta)
        self.lbl_meta.setObjectName("HistSectMeta")
        hl.addWidget(self.lbl_title)
        hl.addWidget(self.lbl_meta)
        hl.addStretch(1)
        if action is not None:
            hl.addWidget(action)
        box.addWidget(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(10, 8, 10, 10)
        self.body.setSpacing(6)
        box.addLayout(self.body)

    def set_meta(self, text: str) -> None:
        self.lbl_meta.setText(text or "")


# ==========================================
# 右预览
# ==========================================
class HistoryPreviewPane(QFrame):
    """右预览：头部 + 可滚动内容 + **钉底动作行**（按宽度自动换行）。

    · M1 内容 = 四胶囊 + 迷你净值图 + 参数详情（可折叠）；
    · M2/M3 内容 = 四态占比条 + 筛选条件（全文可复制）+ 粗筛摘要。
    只暴露控件与 `render(record)`；动作按钮的**信号连接在页面**（状态留页面）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HistCard")
        self.setStyleSheet(_CARD_QSS)
        self._actions = frozenset()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.lbl_head = QLabel("选中左侧一份存档查看")
        self.lbl_head.setWordWrap(True)
        self.lbl_head.setStyleSheet(f"font-size:13px;font-weight:bold;color:{_TEXT};")
        root.addWidget(self.lbl_head)

        # ---------- 可滚动内容区 ----------
        self.scroll = ScrollRegion()
        self.content = self.scroll.content
        # ★v1.46（用户 2026-09-25 实测）：段间距按样板定 **12px** —— 旧版 8px，且净值图
        #   自身没有边框、下沿紧贴下一块 ⇒ 观感是"图粘在「参数详情」标题上"（挤压感）。
        self.content.setSpacing(12)
        root.addWidget(self.scroll, 1)

        # M1：四胶囊
        self.pills_row = QWidget()
        pills = QHBoxLayout(self.pills_row)
        pills.setContentsMargins(0, 0, 0, 0)
        pills.setSpacing(8)
        self.pill_cum = QLabel("—")
        self.pill_win = QLabel("—")
        self.pill_trades = QLabel("—")
        self.pill_avg = QLabel("—")
        for pill in (self.pill_cum, self.pill_win, self.pill_trades, self.pill_avg):
            pill.setStyleSheet(_PILL_QSS)
            pill.setAlignment(_CENTER)
            pill.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            pills.addWidget(pill, 1)
        self.content.addWidget(self.pills_row)

        # M1：迷你净值图 —— ★v1.46：按样板 `.minichart` 包一层「白底 + 浅边框 + 圆角」，
        #   并把卡片内**下边距放大到 10px**：曲线/坐标轴与下一块之间因此有了呼吸
        #   〔用户 2026-09-25 实测：净值图下面直接接「参数详情」、"完全没有留空、有挤压感"〕
        self.chart = MiniEquityChart()
        self.chart_card = QFrame()
        self.chart_card.setObjectName("HistMini")
        self.chart_card.setStyleSheet(
            "QFrame#HistMini{background:#fff;border:1px solid #EDF0F5;border-radius:8px;}")
        _mini = QVBoxLayout(self.chart_card)
        _mini.setContentsMargins(6, 6, 6, 10)
        _mini.setSpacing(0)
        _mini.addWidget(self.chart)
        self.content.addWidget(self.chart_card)

        # M1：参数详情（可折叠，默认只给摘要）
        self.btn_params = QToolButton()
        self.btn_params.setText("▸ 参数详情")
        self.btn_params.setCheckable(True)
        self.btn_params.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_params.setStyleSheet(
            f"QToolButton{{border:none;color:{_ACCENT};font-size:12px;font-weight:bold;}}")
        self.btn_params.toggled.connect(self._on_toggle_params)
        self.sect_params = SectionCard("参数详情", action=self.btn_params)
        self.lbl_params = QLabel("")
        self.lbl_params.setWordWrap(True)
        self.lbl_params.setStyleSheet("font-size:12px;color:#3A4150;border:none;background:transparent;")
        self.lbl_params.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sect_params.body.addWidget(self.lbl_params)
        self.content.addWidget(self.sect_params)
        self._params_text = ""
        self._params_full = ""

        # M2/M3：四态占比条
        self.statbar = ScanStatBar()
        self.content.addWidget(self.statbar)

        # M2/M3：筛选条件（等宽代码块 + 复制）
        self.btn_copy = QPushButton("复制")
        self.btn_copy.setStyleSheet(_FLAT_QSS)
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.clicked.connect(self._on_copy_formula)
        self.sect_condition = SectionCard("筛选条件", action=self.btn_copy)
        self.txt_formula = QPlainTextEdit()
        self.txt_formula.setObjectName("HistCode")
        self.txt_formula.setStyleSheet(_CODE_QSS)
        self.txt_formula.setReadOnly(True)
        self.txt_formula.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.txt_formula.setMaximumHeight(132)
        self.txt_formula.setMinimumHeight(64)
        self.sect_condition.body.addWidget(self.txt_formula)
        self.content.addWidget(self.sect_condition)

        # M2/M3：粗筛漏斗摘要
        self.sect_filter = SectionCard("粗筛漏斗")
        self.lbl_filter = QLabel("")
        self.lbl_filter.setWordWrap(True)
        self.lbl_filter.setStyleSheet("font-size:12px;color:#3A4150;border:none;background:transparent;")
        self.sect_filter.body.addWidget(self.lbl_filter)
        self.content.addWidget(self.sect_filter)
        self.content.addStretch(1)

        # ---------- 钉底动作行（窄栏自动换行 + 删除隔离到最右）----------
        self._buttons = {}
        self.actions_host = FlowHost(spacing=8)      # 5 个常规动作：按可用宽度自动换行
        self._build_actions()
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(8)
        actions_row.addWidget(self.actions_host, 1)
        actions_row.addWidget(self._buttons['del'], 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(actions_row)

    # ---------------- 动作按钮 ----------------
    def _build_actions(self) -> None:
        specs = (
            ('view', "👁 载入查看", _PRIMARY_QSS,
             "忠实回放当天结果（只读，不影响你正在编辑的配置）"),
            ('reuse', "↺ 复用参数", _FLAT_QSS, "把这份快照的配置灌回编辑器（可改后再跑）"),
            ('rerun', "▶ 重跑", _FLAT_QSS, "复用参数 + 按当前行情重跑（会自动补齐最新数据）"),
            ('send', "📤 送行情页", _FLAT_QSS, "把这份函数段送到「📈 市场行情」看图"),
            ('pin', "☆ 重点", _FLAT_QSS, "标为重点后不被自动淘汰"),
            ('del', "🗑 删除", _DANGER_QSS, "删除这份存档文件（二次确认）"),
        )
        for acc, text, qss, tip in specs:
            btn = QPushButton(text)
            btn.setStyleSheet(qss)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setEnabled(False)
            self._buttons[acc] = btn
        # 危险动作物理隔离（§10-10）：常规动作进"可换行"区，删除**单独钉在最右**。
        for acc in ACTION_ORDER:
            if acc != 'del':
                self.actions_host.flow.addWidget(self._buttons[acc])

    def action_button(self, acc: str):
        """按 `history_kinds` 的动作标识取按钮（页面据此连信号，别去够私有名）。"""
        return self._buttons.get(acc)

    # ---------------- 渲染 ----------------
    def clear(self) -> None:
        self.lbl_head.setText("选中左侧一份存档查看")
        for pill, text in ((self.pill_cum, "累计 —"), (self.pill_win, "胜率 —"),
                           (self.pill_trades, "成交 —"), (self.pill_avg, "平均单笔 —")):
            pill.setText(text)
            pill.setStyleSheet(_PILL_QSS)
        self.chart._empty()
        self.btn_params.setChecked(False)
        self.lbl_params.setText("")
        self.statbar.clear()
        self.txt_formula.setPlainText("")
        self.sect_condition.set_meta("")
        self.lbl_filter.setText("")
        self.sect_filter.set_meta("")
        self.set_actions_enabled(False)

    def render(self, record: dict) -> None:
        spec = spec_of(record.get("kind", KIND_M1))
        self._actions = spec.actions
        scan = bool(spec.scan)
        # ⚠ 图要**连同它的卡片**一起收 —— 只隐藏 `chart` 会在右栏留下一个空白边框框
        for widget in (self.pills_row, self.chart_card, self.sect_params):
            widget.setVisible(not scan)
        for widget in (self.statbar, self.sect_condition, self.sect_filter):
            widget.setVisible(scan)
        if scan:
            self._render_scan(record, spec)
        else:
            self._render_backtest(record)
        self.set_actions_enabled(True)      # 选中 ⇒ 动作可用（可见性另按声明表裁）
        self._apply_action_visibility()
        self.actions_host.sync_height()

    def _render_backtest(self, record: dict) -> None:
        meta = record.get("meta") or {}
        kpi = record.get("kpi") or {}
        cum = float(kpi.get("cumulative_return") or 0.0)
        win = float(kpi.get("win_rate") or 0.0)
        avg = kpi.get("avg_return_pct")

        head = f"{meta.get('name') or ''} {meta.get('symbol') or ''}".strip() or "（未知标的）"
        head += f" · {record.get('created_at') or ''}"
        if record.get("pinned"):
            head += " · ★重点"
        head += f"\n策略：{meta.get('strategy_name') or '（未保存）'}"
        self.lbl_head.setText(head)

        self.pill_cum.setText(f"累计 {cum * 100:+.1f}%")
        self.pill_cum.setStyleSheet(
            _PILL_QSS + f"color:{_MONEY if cum >= 0 else _LOSS};font-weight:bold;")
        self.pill_win.setText(f"胜率 {win * 100:.0f}%")
        self.pill_trades.setText(f"成交 {int(kpi.get('total_trades') or 0)} 笔")
        self.pill_avg.setText(
            f"平均单笔 {float(avg) * 100:+.2f}%" if avg is not None else "平均单笔 —")

        self.chart.set_series(record.get("equity") or [])

        start, end = meta.get("start_date") or "—", meta.get("end_date") or "—"
        seg_first = self._first_segment_line(meta.get("segments"))
        self._params_text = (
            f"区间：{start} ~ {end}\n"
            f"买入：{meta.get('buy_expr') or '—'}\n"
            f"卖出：{meta.get('sell_expr') or '—'}\n"
            f"函数段（首行）：{seg_first}"
        )
        self._params_full = self._params_text + "\n" + self._extra_params(record)
        self.btn_params.setChecked(False)
        self.lbl_params.setText(self._params_text)

    def _render_scan(self, record: dict, spec) -> None:
        """M2/M3 预览：**范围/基准日 + 四态占比条 + 条件全文 + 粗筛摘要**（无净值图）。"""
        scope = record.get("scope") or {}
        cond = record.get("condition") or {}
        counts = record.get("counts") or {}
        day = record.get("day") or "—"
        label = scope.get("label") or "（未知范围）"
        code = str(scope.get("code") or "").strip()

        head = f"{label}{f'（{code}）' if code else ''}"
        if record.get("pinned"):
            head += " · ★重点"
        day_line = (f"基准日 {day}" if spec.columns[4].title == "基准日"
                    else f"区间 {record.get('range_start') or '—'} ~ {day}")
        head += (f"\n{day_line} · 存档于 {record.get('created_at') or ''} · 口径 前复权")
        self.lbl_head.setText(head)

        self.statbar.render(counts, elapsed_ms=record.get("elapsed_ms"))

        formula = str(cond.get("formula") or "")
        self.txt_formula.setPlainText(formula or "（无条件）")
        n_lines = len([ln for ln in formula.splitlines() if ln.strip()]) or (1 if formula else 0)
        self.sect_condition.set_meta(f"{len(cond.get('segments') or [])} 段 · {n_lines} 行")
        params = str(cond.get("params") or "")
        self.lbl_filter.setText(_thresholds_text(cond.get("thresholds")) +
                                (f"\n参数：{params}" if params else ""))
        self.sect_filter.set_meta(f"{_threshold_count(cond.get('thresholds'))} 项开启")

    # ---------------- 动作可用性 ----------------
    def _apply_action_visibility(self) -> None:
        """按 kind 的声明决定动作按钮：**不在声明里的直接隐藏**（不是灰着占位）。"""
        for acc, btn in self._buttons.items():
            btn.setVisible(acc in self._actions)

    def set_actions_enabled(self, on: bool) -> None:
        for acc, btn in self._buttons.items():
            btn.setEnabled(bool(on) and acc in self._actions)

    def set_pinned_state(self, pinned: bool) -> None:
        self._buttons['pin'].setText("★ 取消重点" if pinned else "☆ 重点")

    def _on_toggle_params(self, expanded: bool) -> None:
        self.btn_params.setText("▾ 参数详情" if expanded else "▸ 参数详情")
        self.lbl_params.setText(self._params_full if expanded else self._params_text)

    def _on_copy_formula(self) -> None:
        """复制条件全文（横截面快照最常用的动作）。"""
        text = self.txt_formula.toPlainText()
        QApplication.clipboard().setText(text or "")
        self.btn_copy.setText("已复制 ✓")
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("复制"))

    # ---------------- 文案小件 ----------------
    @staticmethod
    def _first_segment_line(segments) -> str:
        for seg in (segments or []):
            for line in str(seg).splitlines():
                if line.strip():
                    return line.strip()
        return "—"

    @staticmethod
    def _extra_params(record: dict) -> str:
        meta = record.get("meta") or {}
        config = record.get("config") or {}
        risk = meta.get("risk") or {}
        fill = meta.get("fill") or {}
        index = meta.get("index")
        lines = [f"参数：{meta.get('params_text') or '（无）'}"]
        risk_bits = []
        if risk.get("max_bars"):
            risk_bits.append(f"最长 {risk['max_bars']} 根")
        if risk.get("stop_loss_pct"):
            risk_bits.append(f"止损 {risk['stop_loss_pct']:g}%")
        if risk.get("take_profit_pct"):
            risk_bits.append(f"止盈 {risk['take_profit_pct']:g}%")
        if risk.get("trailing_pct"):
            risk_bits.append(f"回撤 {risk['trailing_pct']:g}%")
        lines.append("风控：" + (" · ".join(risk_bits) if risk_bits else "全部关闭"))
        lines.append("成交：" + _fill_text(fill))
        lines.append("大盘门控：" + (
            f"{index.get('symbol')}（买 {index.get('expr_buy') or '—'} / 卖 {index.get('expr_sell') or '—'}）"
            if index else "未启用"))
        n_buy = len((config.get("condition_buy") or {}).get("conditions") or [])
        n_sell = len((config.get("condition_sell") or {}).get("conditions") or [])
        lines.append(f"条件组：买 {n_buy} 条 · 卖 {n_sell} 条")
        segs = meta.get("segments") or []
        if len(segs) > 1:
            lines.append(f"函数段：共 {len(segs)} 段")
        return "\n".join(lines)


# ==========================================
# 文案小件（模块级，供预览复用）
# ==========================================
def _fill_text(fill: dict) -> str:
    """成交模型人话（复用引擎常量，页面不许另写一份）。"""
    from core.backtest import FILL_MODE_LABELS, tick_to_yuan
    mode = (fill or {}).get("fill_mode")
    label = FILL_MODE_LABELS.get(mode, str(mode or "默认"))
    tick = (fill or {}).get("trigger_tick")
    if mode == "trigger" and tick:
        return f"{label} · {tick_to_yuan(tick):.2f} 元"
    return label


def _threshold_count(thresholds) -> int:
    """开了几项粗筛（数值项非 None + 布尔项为真）。"""
    th = thresholds or {}
    numeric = ('min_amount', 'min_price', 'min_bars', 'min_turnover',
               'min_float_mktcap', 'max_float_mktcap', 'min_change_pct', 'max_change_pct')
    booleans = ('exclude_suspended', 'exclude_st', 'exclude_limit')
    return (sum(1 for k in numeric if th.get(k) is not None)
            + sum(1 for k in booleans if th.get(k)))


def _thresholds_text(thresholds) -> str:
    """粗筛阈值的人话摘要（用户量纲：万元 / 亿元，§10-10）。"""
    th = thresholds or {}
    parts = []
    if th.get('min_amount'):
        parts.append(f"成交额 ≥ {human_amount(float(th['min_amount']))}")
    if th.get('min_price'):
        parts.append(f"价格 ≥ {float(th['min_price']):g} 元")
    if th.get('min_bars'):
        parts.append(f"上市 ≥ {int(th['min_bars'])} 个交易日")
    if th.get('min_turnover'):
        parts.append(f"换手率 ≥ {float(th['min_turnover']) * 100:g}%")
    if th.get('min_float_mktcap'):
        parts.append(f"流通市值 ≥ {human_mktcap(float(th['min_float_mktcap']))}")
    if th.get('max_float_mktcap'):
        parts.append(f"流通市值 ≤ {human_mktcap(float(th['max_float_mktcap']))}")
    if th.get('exclude_suspended'):
        parts.append("剔停牌")
    if th.get('exclude_st'):
        parts.append("剔 ST / 退市")
    if th.get('exclude_limit'):
        parts.append("剔一字板")
    return ' · '.join(parts) if parts else '全部关闭（不做粗筛）'


# ==========================================
# 页脚 · 存档设置（只读 + 一个开关）
# ==========================================
class HistorySettingsBar(QFrame):
    """页脚：自动存档开关（页面连接写入偏好）+ 回执 + 上限/占用**只读**展示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(10)
        self.chk_auto = QCheckBox("每次回测 / 扫描自动存档")
        self.chk_auto.setToolTip("开=每次回测或扫描成功出结果后自动落一份不可变快照；"
                                 "关=只在需要时手动存")
        lay.addWidget(self.chk_auto)
        self.lbl_receipt = QLabel("")
        self.lbl_receipt.setStyleSheet(f"color:{_ACCENT};font-size:12px;")
        # 窄屏不撑窗：水平 Ignored ⇒ 长文本不抬高窗口最小宽度（§11.5-73）
        self.lbl_receipt.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.lbl_receipt, 1)
        self.lbl_caps = QLabel("")
        self.lbl_caps.setStyleSheet(f"color:{_MUTED};font-size:12px;")
        self.lbl_caps.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.lbl_caps, 1, Qt.AlignmentFlag.AlignRight)

    def set_receipt(self, text: str) -> None:
        """一行回执（长说明进 tooltip；单行标签不撑窗）。"""
        self.lbl_receipt.setText(text or "")
        self.lbl_receipt.setToolTip(text or "")

    def render_caps(self, caps: dict, stats: dict) -> None:
        mb = stats.get("bytes", 0) / (1024 * 1024)
        short = (f"上限 每标的/范围 {caps['per_symbol']} 份 / 共 {caps['total']} 份 · "
                 f"重点豁免淘汰 · 单份 ≤{caps['max_mb']}MB")
        full = (short + f"\n当前 {stats.get('count', 0)} 份（重点 {stats.get('pinned', 0)} 份 · "
                        f"占用 {mb:.2f} MB）。超限时按时间淘汰最旧的非重点存档。")
        self.lbl_caps.setText(f"{short} · 当前 {stats.get('count', 0)} 份")
        self.lbl_caps.setToolTip(full)


# ==========================================
# 组装：整页版式（页面只调它 + 连信号）
# ==========================================
def build_history_layout(page: QWidget) -> dict:
    """在 `page` 上装配版式，返回 {名字: 控件}（页面按名取用并连接信号）。

    纵向层次：L1 过滤条（1 行）→ L0 主体（左列表 3 : 右预览 2）→ 页脚设置（1 行）。

    ⚠ 分割器**不允许把任一侧拖到 0**（`setChildrenCollapsible(False)`）+ 左右各给
    最小宽：旧版没有这两条，而预览栏的动作行最小宽 612px ⇒ 窄窗下左列表被挤到
    横向滚动、看起来像"右侧展开栏把列表遮住了"（用户实测反馈）。
    """
    # ★v1.46：字体**只在这里钉一次**（§10-9「字体只此一处」）—— 开源/免费商用栈优先，
    #   见 `custom_widgets.UI_FONT_STACK`；本机实测用上哪一款进启动日志（`ui_font_status()`）。
    apply_ui_font(page)
    root = QVBoxLayout(page)
    root.setContentsMargins(6, 6, 6, 6)
    root.setSpacing(10)

    widgets = {
        "filter_bar": HistoryFilterBar(),
        "table": HistoryTable(),
        "preview": HistoryPreviewPane(),
        "settings": HistorySettingsBar(),
    }

    root.addWidget(widgets["filter_bar"])

    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.addWidget(widgets["table"])
    splitter.addWidget(widgets["preview"])
    splitter.setChildrenCollapsible(False)
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 2)
    splitter.setSizes([720, 460])
    widgets["table"].setMinimumWidth(320)
    widgets["preview"].setMinimumWidth(330)
    widgets["splitter"] = splitter
    root.addWidget(splitter, 1)

    root.addWidget(widgets["settings"])
    return widgets
