# ui/widgets/backtest_history_ui.py
"""
🗂 运行历史「版式 + 渲染」（§7-A4 · v1.37 · 1.22 拆分同款约定）。

【分工】本模块只造控件、只把数据画出来；**不碰存档、不调 M1 页**。
业务与接线全在 `ui/views/backtest_history.py`（那里是薄壳：状态 + 信号连接）。
构件清单：
  · `HistoryFilterBar`  —— L1 操作轴（kind / 只看重点 / 标的 / 搜索 / 刷新）
  · `HistoryTable`      —— 左列表（9 列 + 选中即预览）；`sig_selection_changed`
  · `MiniEquityChart`   —— 右预览的迷你净值曲线（含买卖点，落在曲线上）
  · `HistoryPreviewPane`—— 右预览整块（KPI 胶囊 + 迷你图 + 可折叠参数 + 动作行）
  · `HistorySettingsBar`—— 页脚只读区（自动存档开关 + 上限 / 占用）

【两条渲染纪律】
  ① **表格数字着色用 delegate**，不用 `item.setForeground` —— 后者在"整行选中"时
     会和蓝色高亮叠成"红绿字压在蓝底上"，既丑又难读（用户实测反馈）。
  ② 迷你净值曲线的买卖点**必须画在曲线上**（用成交日净值定位，不是成交价 —— 量纲不同）。
"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QPushButton, QSizePolicy, QSplitter, QStyle,
                             QStyledItemDelegate, QStyleOptionViewItem, QTableWidget,
                             QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from config import settings
from data.backtest_archive import KIND_LABELS, KIND_M1, RESERVED_KINDS, SOURCE_LABELS
from ui.widgets.chart_style import apply_pokorny_style

# ---- 配色（与全站一致的语义色；文字色取"可读版"，避免高饱和）----
_MONEY = "#1B7F3B"
_LOSS = "#B3261E"
_MUTED = "#8A94A6"
_TEXT = "#1F2430"
_ACCENT = "#1976D2"

_CARD_QSS = "QFrame#HistCard{background:#fff;border:1px solid #E4E9F0;border-radius:10px;}"
_PILL_QSS = ("background:#F5F6F8;border-radius:8px;padding:8px 10px;"
             "font-size:12px;color:#8A94A6;")
_TABLE_QSS = (
    "QTableWidget{background:#fff;alternate-background-color:#F7F9FC;"
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

# 列表列（唯一事实来源：表头 / 取值 / 着色列号都从这里推）
COLUMNS = ["★", "时间", "标的", "策略", "区间", "胜率", "累计", "笔数", "来源"]
COL_PIN, COL_TIME, COL_SYMBOL, COL_STRATEGY, COL_RANGE, COL_WIN, COL_CUM, COL_TRADES, COL_SRC = range(9)

# 着色列 → {正/负}；其余列不着色（保持干净）
_SIGNED_COLUMNS = {COL_CUM: {"pos": _MONEY, "neg": _LOSS},
                   COL_WIN: {"pos": _MONEY, "neg": _LOSS}}
_SIGN_ROLE = Qt.ItemDataRole.UserRole + 1
_ID_ROLE = Qt.ItemDataRole.UserRole


class _SignedValueDelegate(QStyledItemDelegate):
    """给"累计 / 胜率"列按正负着色；**选中态直接交给样式表**（不再叠色）。

    之所以用 delegate 而不是 `item.setForeground`：后者会与 `::item:selected`
    的蓝色高亮打架 —— 选中行上出现红/绿字（用户实测反馈"点一下就有颜色"）。
    """

    def paint(self, painter, option, index):  # noqa: N802 —— Qt 命名约定
        spec = _SIGNED_COLUMNS.get(index.column())
        if spec is not None and not (option.state & QStyle.StateFlag.State_Selected):
            sign = index.data(_SIGN_ROLE)
            if sign is not None:
                option = QStyleOptionViewItem(option)
                option.palette.setColor(
                    QPalette.ColorRole.Text, QColor(spec["pos"] if sign >= 0 else spec["neg"]))
        super().paint(painter, option, index)


# ==========================================
# L1 · 过滤条
# ==========================================
class HistoryFilterBar(QWidget):
    """一行操作轴：kind 过滤（M2/M3 置灰标"预留"）+ 只看重点 + 标的 + 搜索 + 刷新。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        title = QLabel("🗂 运行历史")
        title.setStyleSheet(f"font-size:15px;font-weight:bold;color:{_TEXT};")
        lay.addWidget(title)

        self.cmb_kind = QComboBox()
        self.cmb_kind.setToolTip("本轮只实现 M1 单股回测的历史；M2 / M3 为后续增量（schema 已预留 kind）")
        model = self.cmb_kind.model()
        for i, (kind, label) in enumerate(KIND_LABELS.items()):
            self.cmb_kind.addItem(label if kind not in RESERVED_KINDS else f"{label}（预留）", kind)
            if kind in RESERVED_KINDS:
                item = model.item(i)
                if item is not None:
                    item.setEnabled(False)      # 置灰不可选：不让用户点进一个空列表
        self.cmb_kind.setCurrentIndex(0)
        lay.addWidget(self.cmb_kind)

        self.chk_pinned = QCheckBox("只看重点 ★")
        self.chk_pinned.setStyleSheet(f"color:{_MUTED};font-size:12px;")
        lay.addWidget(self.chk_pinned)

        self.cmb_symbol = QComboBox()
        self.cmb_symbol.setMinimumWidth(140)
        self.cmb_symbol.setToolTip("按标的过滤（只列出历史里出现过的标的）")
        lay.addWidget(self.cmb_symbol)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("按 标的 / 策略 搜索")
        self.ed_search.setFixedWidth(170)
        lay.addWidget(self.ed_search)

        lay.addStretch(1)

        self.btn_refresh = QPushButton("↻ 刷新")
        self.btn_refresh.setStyleSheet(_FLAT_QSS)
        lay.addWidget(self.btn_refresh)

    def current_kind(self) -> str:
        """当前 kind（M2/M3 不可选 ⇒ 恒为 M1）。"""
        return self.cmb_kind.currentData() or KIND_M1

    def current_symbol(self) -> str:
        return self.cmb_symbol.currentData() or ""

    def set_symbols(self, pairs: list) -> None:
        """重建标的下拉（`[(symbol, name)]`）；尽量保持当前选择。"""
        keep = self.current_symbol()
        self.cmb_symbol.blockSignals(True)
        self.cmb_symbol.clear()
        self.cmb_symbol.addItem("全部标的", "")
        for symbol, name in pairs:
            self.cmb_symbol.addItem(f"{name} {symbol}".strip(), symbol)
        idx = self.cmb_symbol.findData(keep)
        self.cmb_symbol.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_symbol.blockSignals(False)


# ==========================================
# 左列表
# ==========================================
class HistoryTable(QTableWidget):
    """存档列表：9 列；选中一行即触发预览。**只渲染，不加载记录**。"""

    sig_selection_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(COLUMNS)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.setStyleSheet(_TABLE_QSS)
        self.setItemDelegate(_SignedValueDelegate(self))
        self.itemSelectionChanged.connect(self.sig_selection_changed)

    def populate(self, entries: list) -> None:
        """用索引条目重建表格（会清空选中；调用方负责恢复选中）。"""
        self.blockSignals(True)          # 重建期间不要回调，避免"半成品状态"外泄
        self.setRowCount(len(entries))
        for row, e in enumerate(entries):
            cum, win = e.get("cumulative_return"), e.get("win_rate")
            start, end = str(e.get("start_date") or ""), str(e.get("end_date") or "")
            cells = [
                ("★" if e.get("pinned") else ""),
                str(e.get("created_at") or "")[5:16],
                f"{e.get('name') or ''} {e.get('symbol') or ''}".strip(),
                e.get("strategy_name") or "（未保存）",
                f"{start[2:]}~{end[2:]}" if start and end else "—",
                f"{win * 100:.0f}%" if win is not None else "—",
                f"{cum * 100:+.1f}%" if cum is not None else "—",
                str(e.get("total_trades", "—")),
                SOURCE_LABELS.get(e.get("source"), "自动"),
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col in (COL_PIN, COL_WIN, COL_CUM, COL_TRADES):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == COL_PIN:
                    item.setToolTip("★ 重点：不被自动淘汰" if e.get("pinned") else "标为「★ 重点」")
                if col == COL_TIME:
                    item.setData(_ID_ROLE, e.get("id"))     # 行主键随行携带（不靠行号索引）
                    item.setToolTip(str(e.get("created_at") or ""))
                if col == COL_WIN:
                    item.setData(_SIGN_ROLE, None if win is None else float(win) - 0.5)
                if col == COL_CUM:
                    item.setData(_SIGN_ROLE, None if cum is None else float(cum))
                self.setItem(row, col, item)
        self.blockSignals(False)

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
                pin_item.setText("★" if entry.get("pinned") else "")
                pin_item.setToolTip("★ 重点：不被自动淘汰" if entry.get("pinned") else "标为「★ 重点」")
            src_item = self.item(row, COL_SRC)
            if src_item is not None:
                src_item.setText(SOURCE_LABELS.get(entry.get("source"), "自动"))
            return True
        return False


# ==========================================
# 右预览
# ==========================================
class MiniEquityChart(pg.PlotWidget):
    """迷你净值曲线 + 买卖点（点落在曲线上 —— 成交日净值定位）。"""

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


class HistoryPreviewPane(QFrame):
    """右预览：头部 + KPI 胶囊 + 迷你净值 + 可折叠参数摘要 + 动作行。

    只暴露控件与 `render(record)`；动作按钮的**信号连接在页面**（状态留页面）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HistCard")
        self.setStyleSheet(_CARD_QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        self.lbl_head = QLabel("选中左侧一份存档查看")
        self.lbl_head.setWordWrap(True)
        self.lbl_head.setStyleSheet(f"font-size:13px;font-weight:bold;color:{_TEXT};")
        lay.addWidget(self.lbl_head)

        pills = QHBoxLayout()
        pills.setSpacing(8)
        self.pill_cum = QLabel("—")
        self.pill_win = QLabel("—")
        self.pill_trades = QLabel("—")
        self.pill_avg = QLabel("—")
        for pill in (self.pill_cum, self.pill_win, self.pill_trades, self.pill_avg):
            pill.setStyleSheet(_PILL_QSS)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pills.addWidget(pill, 1)
        lay.addLayout(pills)

        self.chart = MiniEquityChart()
        lay.addWidget(self.chart)

        # —— 参数摘要（默认只给一行，点「▸ 参数详情」展开完整快照）——
        self.btn_params = QToolButton()
        self.btn_params.setText("▸ 参数详情")
        self.btn_params.setCheckable(True)
        self.btn_params.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_params.setStyleSheet(
            f"QToolButton{{border:none;color:{_ACCENT};font-size:12px;font-weight:bold;}}")
        self.btn_params.toggled.connect(self._on_toggle_params)
        lay.addWidget(self.btn_params, 0, Qt.AlignmentFlag.AlignLeft)

        self.lbl_params = QLabel("")
        self.lbl_params.setWordWrap(True)
        self.lbl_params.setStyleSheet("font-size:12px;color:#3A4150;")
        self.lbl_params.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.lbl_params)
        # 摘要 / 展开两段文本（render 时填；先初始化，防"还没选就点开"报 AttributeError）
        self._params_text = ""
        self._params_full = ""

        lay.addStretch(1)
        lay.addLayout(self._build_actions())

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_view = QPushButton("👁 载入查看")
        self.btn_view.setStyleSheet(_PRIMARY_QSS)
        self.btn_view.setToolTip("忠实回放当天结果（只读，不影响你正在编辑的配置）")
        self.btn_reuse = QPushButton("↺ 复用参数")
        self.btn_reuse.setToolTip("把这份快照的配置灌回单股回测编辑器（可改后再跑）")
        self.btn_rerun = QPushButton("▶ 重跑")
        self.btn_rerun.setToolTip("复用参数 + 按当前行情重跑（会自动补齐最新数据）")
        self.btn_send = QPushButton("📤 送行情页")
        self.btn_send.setToolTip("把这份函数段送到「📈 市场行情」看图")
        self.btn_pin = QPushButton("☆ 重点")
        self.btn_pin.setToolTip("标为重点后不被自动淘汰")
        self.btn_del = QPushButton("🗑 删除")
        self.btn_del.setToolTip("删除这份存档文件（二次确认）")
        for btn in (self.btn_reuse, self.btn_rerun, self.btn_send, self.btn_pin, self.btn_del):
            btn.setStyleSheet(_FLAT_QSS)
        for btn in (self.btn_view, self.btn_reuse, self.btn_rerun, self.btn_send,
                    self.btn_pin, self.btn_del):
            btn.setEnabled(False)
            row.addWidget(btn)
        return row

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
        self.set_actions_enabled(False)

    def render(self, record: dict) -> None:
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
        self.set_actions_enabled(True)

    def set_actions_enabled(self, on: bool) -> None:
        for btn in (self.btn_view, self.btn_reuse, self.btn_rerun, self.btn_send,
                    self.btn_pin, self.btn_del):
            btn.setEnabled(on)

    def set_pinned_state(self, pinned: bool) -> None:
        self.btn_pin.setText("★ 取消重点" if pinned else "☆ 重点")

    def _on_toggle_params(self, expanded: bool) -> None:
        self.btn_params.setText("▾ 参数详情" if expanded else "▸ 参数详情")
        self.lbl_params.setText(self._params_full if expanded else self._params_text)

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


def _fill_text(fill: dict) -> str:
    """成交模型人话（复用引擎常量，页面不许另写一份）。"""
    from core.backtest import FILL_MODE_LABELS, tick_to_yuan
    mode = (fill or {}).get("fill_mode")
    label = FILL_MODE_LABELS.get(mode, str(mode or "默认"))
    tick = (fill or {}).get("trigger_tick")
    if mode == "trigger" and tick:
        return f"{label} · {tick_to_yuan(tick):.2f} 元"
    return label


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
        self.chk_auto = QCheckBox("每次回测自动存档")
        self.chk_auto.setToolTip("开=每次回测成功出结果后自动落一份不可变快照；关=只在需要时手动存")
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
        short = (f"上限 每标的 {caps['per_symbol']} 份 / 共 {caps['total']} 份 · "
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
    """
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
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 2)
    splitter.setSizes([640, 400])
    widgets["splitter"] = splitter
    root.addWidget(splitter, 1)

    root.addWidget(widgets["settings"])
    return widgets
