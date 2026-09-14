# ui/views/trading_desk.py
"""📈 行情工作台（Trading Desk）—— §7-B3 **P8 行情页整体重做**。

【为什么新建文件而不是改 `market.py`】
  §10-12 / §9-L 的纪律：`market.py` 已 661 行越线，**禁止再往里堆**。
  P0–P7 已经把能力都做成了独立组件，所以 P8 是**"换壳不换芯"**：
  本页只做"装配 + 交互"，图表能力全部来自下面这些既有组件 ——
    · 窗格编排 / x 联动 / 日期轴 / 十字光标 → `ui/widgets/chart_host.py`
    · 公式叠层渲染（唯一渲染器）        → `ui/widgets/draw_overlay.py`
    · 内置指标 → 绘图 IR（统一图层协议）→ `ui/widgets/chart_layers.py`
    · 用户标注（管线 B：持久化 + 逐个删除）→ `ui/widgets/annotation_layer.py`
    · 量能 / MACD 副图内容              → `ui/widgets/indicator_panes.py`
    · 公式资产化 + 配方库               → `data/formula_store.py` + `ui/widgets/formula_library.py`
    · 数据同步（UI 不发网络）           → `ui/workers.py` → `data/sync_service.py`
  本文件**不新增任何绘图逻辑、不碰网络、不写 SQL**（§10-3）。

【P8 相对旧行情页的新增能力】
  ① **自选股**（`data/watchlist_store.py`）：列表/增删/上下移/双击切换；
  ② **周期切换**：日 / 周 / 月 —— `core.utils.resample_ohlcv` 就地聚合，
     列名与日线一致 ⇒ K 线/指标/公式/标注**全部零改动**；
     ⚠ 标注按 `(标的, **周期**)` 分开存：日线画的线不会跑到周线上（§7-B3 P6 的既定设计）；
  ③ **画线工具栏扩到 5 类**：趋势线 / 水平线 / 垂直线 / **斐波那契** / **文字**；
  ④ 布局重排：左侧控制台（自选+指标+附图+工具）可滚动，右侧图表独占富余高度。

【坐标轴自适应（§7-B4）】
  横轴刻度与纵轴量程**不在这里手算** —— 全部交给 `ui/widgets/adaptive_axis.py`：
  刻度按可视 bar 区间重算（放大后不再只剩一个刻度），每个窗格的 y 各自跟随可视区间
  （副图不再被全量极值压成一条线）。本页只负责回答"**每个窗格在可视区间内的数值范围**"
  这个业务问题（见 `_adaptive_providers`）。

【仍待做】分钟周期（§7 D3 远期，`kline_min` 分区已预留）。
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget)

from core.formula.program import (FormulaProgramError,
                                  execute_programs_with_draws_grouped, parse_program)
from core.indicators import TAEngine
from core.utils import normalize_period, parse_params_text, period_label, resample_ohlcv
from data.annotations import KIND_LABELS, KIND_TEXT, PERIOD_DAILY, AnnotationStore
from data.formula_store import (SOURCE_MARKET, get_formula_store, make_formula,
                                segments_as_tuples)
from data.market_db import DataLakeManager
from data.sync_service import (ADJUST_CHOICES, ADJUST_LABELS, ADJUST_QFQ,
                               adjust_label, friendly_fetch_message, zone_for_adjust)
from data.watchlist_store import WatchlistStore
from ui.dialogs.formula_overlay import FormulaOverlayDialog
from ui.widgets.adaptive_axis import AdaptiveAxes, slice_span
from ui.widgets.annotation_layer import DRAWABLE_KINDS, AnnotationLayer
from ui.widgets.chart_host import AXIS_NO_VALUES, ChartHost
from ui.widgets.chart_layers import (builtin_indicator_layers, layer_value_range,
                                     scale_mismatch_hint)
from ui.widgets.chart_pane import ChartPane
from ui.widgets.chart_style import apply_pokorny_style
from ui.widgets.custom_widgets import (COMBO_QSS_SMALL, CandlestickItem,
                                       NoWheelComboBox)
from ui.widgets.draw_overlay import OverlayPainter, overlay_extent
from ui.widgets.formula_library import FormulaLibraryDialog
from ui.widgets.indicator_panes import fill_macd_pane, fill_volume_pane
from ui.workers import SingleSyncWorker

logger = logging.getLogger(__name__)

# 附图（成交量 / MACD）统一高度
SUB_PLOT_HEIGHT = 150
# 默认可视 K 线根数，超出后只展示最近一段
DEFAULT_VISIBLE_BARS = 150
# 周期下拉顺序（中文标签取自 core.utils.PERIOD_LABELS，避免两处各写一份）
PERIOD_CHOICES = ("D", "W", "M")

_CARD_QSS = "QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"
_SECTION_QSS = "font-weight:bold; color:#757575; font-size:12px;"
_BTN_QSS = ("QPushButton { background:#F5F5F5; border:1px solid #E0E0E0; border-radius:4px; "
            "padding:5px; font-weight:bold; color:#424242; }"
            "QPushButton:hover { background:#EDEDED; }")
_BTN_PRIMARY_QSS = ("QPushButton { font-size:13px; font-weight:bold; color:white; "
                    "background:#1976D2; padding:7px 14px; border:none; border-radius:6px; }"
                    "QPushButton:hover { background:#1565C0; }")
_BTN_DANGER_QSS = ("QPushButton { background:#FFEBEE; border:1px solid #FFCDD2; border-radius:4px; "
                   "padding:5px; font-weight:bold; color:#D32F2F; }")


class TradingDeskView(QWidget):
    """行情工作台：自选股 + 周期 + 指标/公式 + 画线工具 + 图表（复用 P0–P7 组件）。"""

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.data_lake = DataLakeManager()
        self.watchlist = WatchlistStore()

        self.current_symbol = None
        self.current_name = ""
        self.current_df = pd.DataFrame()      # **原始日线**（周期切换的输入）
        self.current_period = "D"             # D / W / M
        # 复权口径（v6.13 · P8 收尾）：qfq = 前复权（默认，读 kline_daily）/
        # "" = 不复权（读 kline_daily_raw）。**两份数据各存一个分区**，见 sync_service.zone_for_adjust
        self.current_adjust = ADJUST_QFQ

        # 统一图层（§7-B3 D4）：内置指标与用户公式都产出 DrawData → 同一个 OverlayPainter
        self._layer_builtin: list = []
        self._layer_formula: dict = {}         # 目标窗格 -> [DrawData]
        self._layer_bars = 0
        self._layer_items: list = []
        self.formula_plots: dict = {}          # 目标窗格 -> PlotItem（副图按需创建）
        self._formula_segments: list = []      # [(函数文本, 目标窗格)]
        self._formula_params_text = ""
        self._formula_programs: list = []
        self._formula_error = ""
        self._formula_store = get_formula_store()      # 与回测页共用同一个实例

        self._annotation_store = AnnotationStore()
        self._annotations = None               # 需等 ChartHost 建好（见 _setup_ui）

        self._setup_ui()
        # P7：开机自动恢复"上次用过的配方" —— 直接治好"公式重启就丢"
        self._restore_last_formula()
        self._refresh_watchlist()

    # ==========================================
    # 界面装配
    # ==========================================
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addLayout(self._build_top_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_control_panel())
        splitter.addWidget(self._build_chart_area())
        splitter.setSizes([240, 1000])
        # 【§11.5-13】主区必须显式 stretch=1：否则顶部栏里的 QLabel 会吞掉整段富余高度
        layout.addWidget(splitter, 1)

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        title = QLabel("行情工作台")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        bar.addWidget(title)
        bar.addStretch()

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("输入代码或中文名 (如: 600519 或 茅台)")
        self.txt_search.setFixedWidth(250)
        self.txt_search.setStyleSheet(
            "QLineEdit { font-size: 14px; padding: 8px 15px; border: 1px solid #E0E0E0; "
            "border-radius: 6px; background: white; }")
        self.txt_search.returnPressed.connect(self.search_and_load)
        bar.addWidget(self.txt_search)

        self.btn_search = QPushButton("🔍 查阅")
        self.btn_search.setStyleSheet(_BTN_PRIMARY_QSS)
        self.btn_search.clicked.connect(self.search_and_load)
        bar.addWidget(self.btn_search)

        self.btn_sync = QPushButton("☁️ 云端同步")
        self.btn_sync.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; color: #1976D2; background: #E3F2FD; "
            "padding: 8px 15px; border: 1px solid #BBDEFB; border-radius: 6px; margin-left: 10px; }")
        self.btn_sync.setToolTip(
            "本地有数据 → 只补下载缺失的最新几天（快）；\n"
            "本地没数据 → 直接整段抓取。\n\n"
            "需要「丢弃本地重新整段下载」时，请到「🗄 数据管理」页用「重新全量下载」。")
        self.btn_sync.clicked.connect(self.sync_cloud)
        bar.addWidget(self.btn_sync)

        self.lbl_sync_status = QLabel("")
        self.lbl_sync_status.setStyleSheet("font-size: 12px; color: #8A94A6; margin-left: 8px;")
        bar.addWidget(self.lbl_sync_status)
        return bar

    def _build_control_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(_CARD_QSS)
        panel.setMinimumWidth(210)
        panel.setMaximumWidth(300)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # ---------- 📌 自选股 ----------
        outer.addWidget(self._section("📌 自选股"))
        self.lst_watch = QListWidget()
        self.lst_watch.setFixedHeight(150)
        self.lst_watch.itemDoubleClicked.connect(self._on_watch_activated)
        self.lst_watch.setToolTip("双击切换标的；下方按钮可加入/移除/调序")
        outer.addWidget(self.lst_watch)

        watch_row = QHBoxLayout()
        watch_row.setSpacing(4)
        self.btn_watch_add = QPushButton("★ 加入")
        self.btn_watch_add.setStyleSheet(_BTN_QSS)
        self.btn_watch_add.setToolTip("把当前标的加入自选（已在自选里则提示，不重复添加）")
        self.btn_watch_add.clicked.connect(self.add_to_watchlist)
        watch_row.addWidget(self.btn_watch_add)

        self.btn_watch_remove = QPushButton("🗑")
        self.btn_watch_remove.setStyleSheet(_BTN_DANGER_QSS)
        self.btn_watch_remove.setToolTip("从自选里移除选中项（不影响行情数据）")
        self.btn_watch_remove.clicked.connect(self.remove_from_watchlist)
        watch_row.addWidget(self.btn_watch_remove)

        self.btn_watch_up = QPushButton("⬆")
        self.btn_watch_up.setStyleSheet(_BTN_QSS)
        self.btn_watch_up.setToolTip("上移（顺序 = 你的关注顺序）")
        self.btn_watch_up.clicked.connect(lambda: self.move_watchlist(-1))
        watch_row.addWidget(self.btn_watch_up)

        self.btn_watch_down = QPushButton("⬇")
        self.btn_watch_down.setStyleSheet(_BTN_QSS)
        self.btn_watch_down.clicked.connect(lambda: self.move_watchlist(1))
        watch_row.addWidget(self.btn_watch_down)
        outer.addLayout(watch_row)

        # ---------- 🕐 周期 ----------
        outer.addSpacing(6)
        outer.addWidget(self._section("🕐 周期"))
        self.cb_period = NoWheelComboBox()
        self.cb_period.setStyleSheet(COMBO_QSS_SMALL)
        for value in PERIOD_CHOICES:
            self.cb_period.addItem(period_label(value), value)
        self.cb_period.setToolTip(
            "周线/月线由日线**就地聚合**（开=首 高=max 低=min 收=末 量=和），\n"
            "不额外下载数据；指标/公式/画线都跟着周期走。\n"
            "⚠ 画线按「标的 + 周期」分别保存：日线画的线不会显示在周线上。")
        self.cb_period.currentIndexChanged.connect(self._on_period_changed)
        outer.addWidget(self.cb_period)

        # ---------- 📐 复权 ----------
        outer.addSpacing(6)
        outer.addWidget(self._section("📐 复权"))
        self.cb_adjust = NoWheelComboBox()
        self.cb_adjust.setStyleSheet(COMBO_QSS_SMALL)
        for value in ADJUST_CHOICES:
            self.cb_adjust.addItem(ADJUST_LABELS[value], value)
        self.cb_adjust.setToolTip(
            "**前复权**（默认）：把历史价格按除权除息向前折算，看长期趋势/算指标用它；\n"
            "**不复权**：保留历史真实成交价，看当年的真实缺口与价位用它。\n\n"
            "两份数据**各存一个分区**（不复权 = 「数据管理」里的「日线行情 (不复权)」），\n"
            "所以来回切换不会覆盖、也不会重复下载；首次切过去若本地没有会自动同步。")
        self.cb_adjust.currentIndexChanged.connect(self._on_adjust_changed)
        outer.addWidget(self.cb_adjust)

        self.lbl_adjust_hint = QLabel("")
        self.lbl_adjust_hint.setWordWrap(True)
        self.lbl_adjust_hint.setStyleSheet("font-size: 11px; color: #8A94A6;")
        outer.addWidget(self.lbl_adjust_hint)

        # ---------- 🎛 主图叠加 ----------
        outer.addSpacing(6)
        outer.addWidget(self._section("🎛 主图叠加"))
        self.cb_ma = QCheckBox("均线 (MA 5/20/60)")
        self.cb_boll = QCheckBox("布林带 (BOLL)")
        for checkbox in (self.cb_ma, self.cb_boll):
            checkbox.setStyleSheet("QCheckBox { font-size: 12px; color: #424242; }")
            checkbox.stateChanged.connect(self.render_charts)
            outer.addWidget(checkbox)

        self.cb_formula = QCheckBox("自定义公式")
        self.cb_formula.setChecked(True)
        self.cb_formula.setStyleSheet("QCheckBox { font-size: 12px; color: #424242; }")
        self.cb_formula.setToolTip("显示/隐藏函数画出的线、状态柱、图标（与均线/布林带同一套图层协议）")
        self.cb_formula.stateChanged.connect(self.render_charts)
        outer.addWidget(self.cb_formula)

        self.btn_edit_formula = QPushButton("✏️ 编辑公式…")
        self.btn_edit_formula.setStyleSheet(_BTN_QSS)
        self.btn_edit_formula.setToolTip("粘贴通达信式函数，叠加到当前标的（每段可选主图/副图）")
        self.btn_edit_formula.clicked.connect(self.edit_formula)
        outer.addWidget(self.btn_edit_formula)

        for text, tip, slot in (
            ("💾 存为配方…", "把当前公式（含每段的主图/副图目标）存进配方库；同名即覆盖",
             self.save_formula_as),
            ("📚 配方库…", "浏览已保存的公式配方：载入 / 改名 / 删除", self.open_formula_library),
            ("📤 送去做回测", "把函数与参数送进「📐 市场回测」（回测不区分主图/副图）",
             self.send_formula_to_backtest),
        ):
            button = QPushButton(text)
            button.setStyleSheet(_BTN_QSS)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            outer.addWidget(button)

        self.lbl_formula_status = QLabel("未设置")
        self.lbl_formula_status.setWordWrap(True)
        self.lbl_formula_status.setStyleSheet("font-size: 11px; color: #8A94A6;")
        outer.addWidget(self.lbl_formula_status)

        # ---------- 📊 附图 ----------
        outer.addSpacing(6)
        outer.addWidget(self._section("📊 附图"))
        self.cb_vol = QCheckBox("成交量")
        self.cb_vol.setChecked(True)
        self.cb_macd = QCheckBox("MACD")
        for checkbox in (self.cb_vol, self.cb_macd):
            checkbox.setStyleSheet("QCheckBox { font-size: 12px; color: #424242; }")
            checkbox.stateChanged.connect(self.render_charts)
            outer.addWidget(checkbox)

        # ---------- 🛠 标注工具 ----------
        outer.addSpacing(6)
        outer.addWidget(self._section("🛠 标注工具"))
        self.cmb_tool = NoWheelComboBox()
        self.cmb_tool.setStyleSheet(COMBO_QSS_SMALL)
        self.cmb_tool.addItem("🖱 浏览（不新建）", "")
        for kind in DRAWABLE_KINDS:            # 类型清单与交互层同源（不手写第二份）
            self.cmb_tool.addItem(KIND_LABELS[kind], kind)
        self.cmb_tool.setToolTip(
            "选好类型后点「➕ 添加标注」；拖动线条/端点调整，**松手自动保存**。\n\n"
            "画线按「日期」保存，所以增量更新、前复权修正都不会让它跑偏；\n"
            "并且按「标的 + 周期」分开存（日线的线不会跑到周线上）。")
        self.cmb_tool.currentIndexChanged.connect(self._on_tool_changed)
        outer.addWidget(self.cmb_tool)

        self.btn_add_annotation = QPushButton("➕ 添加标注")
        self.btn_add_annotation.setStyleSheet(_BTN_QSS)
        self.btn_add_annotation.clicked.connect(self.add_annotation)
        outer.addWidget(self.btn_add_annotation)

        self.btn_delete_annotation = QPushButton("🧽 删除选中")
        self.btn_delete_annotation.setStyleSheet(
            "QPushButton { background:#FFF8E1; border:1px solid #FFE082; border-radius:4px; "
            "padding:5px; font-weight:bold; color:#E65100; }")
        self.btn_delete_annotation.setToolTip("先在图上点一下那条线（变橙色=已选中），"
                                              "再点这里 —— 也可以直接按 Delete 键")
        self.btn_delete_annotation.clicked.connect(self.delete_selected_annotation)
        outer.addWidget(self.btn_delete_annotation)

        self.btn_clear_lines = QPushButton("🗑️ 清空本标的标注")
        self.btn_clear_lines.setStyleSheet(_BTN_DANGER_QSS)
        self.btn_clear_lines.setToolTip("删除当前标的+周期下的全部标注（不可撤销，会二次确认）")
        self.btn_clear_lines.clicked.connect(self.clear_annotations)
        outer.addWidget(self.btn_clear_lines)

        self.lbl_annotation_status = QLabel("")
        self.lbl_annotation_status.setWordWrap(True)
        self.lbl_annotation_status.setStyleSheet("font-size: 11px; color: #8A94A6;")
        outer.addWidget(self.lbl_annotation_status)

        outer.addStretch()
        return panel

    def _build_chart_area(self) -> QFrame:
        container = QFrame()
        container.setStyleSheet(_CARD_QSS)
        box = QVBoxLayout(container)
        box.setContentsMargins(5, 5, 5, 5)

        # 窗格编排交给 ChartHost（§10-12）：主图常驻 + 副图按需；跨窗格十字光标
        self.host = ChartHost(bottom_axis_mode=AXIS_NO_VALUES, crosshair=True)
        self.host.setBackground('w')
        box.addWidget(self.host)

        # 自适应坐标轴总管（§7-B4）：本页只持有一个，每次重渲染 `attach` 一遍（幂等）
        self._axes = AdaptiveAxes(self.host)

        self.main_plot = self.host.main_pane.plot_item
        self._apply_pokorny_axis(self.main_plot)

        # 用户标注（管线 B）：宿主要建好才能挂；`on_changed` 让面板随时报"N 条标注"
        self._annotations = AnnotationLayer(
            self.host, self._annotation_store, period=PERIOD_DAILY,
            on_changed=self._refresh_annotation_status)
        self._refresh_annotation_status()

        # 键盘交互：Delete 删掉选中标注；Esc 回到浏览模式（免得手一抖在图上画出线）
        for key, slot in ((Qt.Key.Key_Delete, self.delete_selected_annotation),
                          (Qt.Key.Key_Escape, self._reset_tool)):
            QShortcut(QKeySequence(key), self).activated.connect(slot)
        return container

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(_SECTION_QSS)
        return label

    @staticmethod
    def _apply_pokorny_axis(plot_item):
        """委托 `chart_style`（全 app 图表轴样式唯一来源，§9-O7）。

        注意：本页图表来自 `GraphicsLayoutWidget.addPlot()`，拿到的是 PlotItem 而非
        PlotWidget，`chart_style` 内部已兼容两种类型。
        """
        return apply_pokorny_style(plot_item, background=None, margins=0)

    # ==========================================
    # 自选股
    # ==========================================
    def _refresh_watchlist(self):
        self.lst_watch.clear()
        for entry in self.watchlist.entries_all():
            item = QListWidgetItem(f"{entry['name'] or entry['symbol']}　{entry['symbol']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["symbol"])
            self.lst_watch.addItem(item)

    def _selected_watch_symbol(self) -> str:
        item = self.lst_watch.currentItem()
        return "" if item is None else str(item.data(Qt.ItemDataRole.UserRole) or "")

    def add_to_watchlist(self):
        if not self.current_symbol:
            QMessageBox.information(self, "先选一个标的", "请先查阅一个标的，再把它加入自选。")
            return
        try:
            added = self.watchlist.add(self.current_symbol, self.current_name)
        except ValueError as e:
            QMessageBox.warning(self, "无法加入自选", str(e))
            return
        self._refresh_watchlist()
        self.lbl_sync_status.setText(
            f"已加入自选：{self.current_name or self.current_symbol}" if added
            else "该标的已在自选里")

    def remove_from_watchlist(self):
        symbol = self._selected_watch_symbol()
        if not symbol or not self.watchlist.remove(symbol):
            self.lbl_sync_status.setText("请先在自选列表里选中一项")
            return
        self._refresh_watchlist()
        self.lbl_sync_status.setText(f"已从自选移除：{symbol}")

    def move_watchlist(self, delta: int):
        symbol = self._selected_watch_symbol()
        if not symbol or not self.watchlist.move(symbol, delta):
            return
        self._refresh_watchlist()
        for row in range(self.lst_watch.count()):
            if self.lst_watch.item(row).data(Qt.ItemDataRole.UserRole) == symbol:
                self.lst_watch.setCurrentRow(row)
                break

    def _on_watch_activated(self, item: QListWidgetItem):
        symbol = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if symbol:
            self.load_symbol(symbol, self.watchlist.display_name(symbol))

    # ==========================================
    # 查询 / 同步（UI 不发网络：统一走 SingleSyncWorker → MarketSyncService）
    # ==========================================
    def search_and_load(self):
        keyword = self.txt_search.text().strip()
        if not keyword:
            return
        result = self.main_win.engine.search_symbol(keyword)   # 经门面取数，UI 不碰 DAO
        if result.empty:
            QMessageBox.warning(self, "未找到", "未找到该标的，请确认花名册已更新。")
            return
        self.load_symbol(str(result.iloc[0]['symbol']), str(result.iloc[0]['name']))

    def load_symbol(self, symbol: str, name: str = "") -> bool:
        """载入某标的：**数据湖优先**，没有才联网。

        :return: True = 本地命中并已渲染；False = 转后台联网同步（见 `_on_sync_finished`）。

        读哪个分区由**当前复权口径**决定（`zone_for_adjust`）—— 切复权就是切分区，
        两个分区的数据互不覆盖（§11.5-19：跨模块键一律走规范化函数，别自己拼字符串）。
        """
        self.current_symbol = str(symbol)
        self.current_name = str(name or self.watchlist.display_name(symbol))
        # 顺手把自选里的名称刷新为花名册里的最新名称（旧名不当真相）
        if self.watchlist.update_name(self.current_symbol, self.current_name):
            self._refresh_watchlist()

        zone = zone_for_adjust(self.current_adjust)
        if self.data_lake.exists(zone, self.current_symbol):
            df = self.data_lake.load_data(zone, self.current_symbol)
            if not df.empty:
                self.current_df = df
                self.render_charts()
                self._refresh_adjust_hint(loaded_from_lake=True)
                return True
        self.sync_cloud()      # 本地没数据 → 走"全量"分支（结果由 _on_sync_finished 收尾）
        return False

    def sync_cloud(self):
        """把当前标的同步到最新（本地有=增量 / 没有=全量）。

        【为什么名字不叫 force_sync】它**不是**强制全量（§9-O4 的历史教训）：
        全量重下统一放在「🗄 数据管理」页，避免误触把 2010 起的整段重下一遍。
        """
        if not self.current_symbol:
            QMessageBox.information(self, "提示", "请先搜索并选中一个标的，再进行云端同步。")
            return
        self.btn_sync.setEnabled(False)
        self.lbl_sync_status.setText("正在同步…")
        self.fetch_thread = SingleSyncWorker(
            self.current_symbol, zone=zone_for_adjust(self.current_adjust),
            force_full=False, parent=self)
        self.fetch_thread.finished.connect(self._on_sync_finished)
        self.fetch_thread.start()

    def _on_sync_finished(self, result: dict):
        self.btn_sync.setEnabled(True)
        symbol = str(result.get("symbol", self.current_symbol) or self.current_symbol)

        # 【竞态防护】拉取期间用户可能已切换标的，过期结果必须丢弃（§9-O5）
        if symbol != self.current_symbol:
            self.lbl_sync_status.setText("")
            return

        if not result.get("ok"):
            self.lbl_sync_status.setText("同步失败")
            QMessageBox.warning(self, "行情同步失败", friendly_fetch_message(symbol, result))
            return

        if result.get("skipped"):
            self.lbl_sync_status.setText("已是最新，无需更新")
        else:
            added = int(result.get("added", 0) or 0)
            self.lbl_sync_status.setText(f"已更新，新增 {added} 行" if added > 0 else "已更新")

        zone = zone_for_adjust(self.current_adjust)
        df = self.data_lake.load_data(zone, symbol)
        if df.empty:
            QMessageBox.critical(self, "错误", f"{symbol} 行情拉取失败（未取得数据）。")
            return
        self.current_df = df
        self.render_charts()
        self._refresh_adjust_hint(loaded_from_lake=True)

    # ==========================================
    # 周期
    # ==========================================
    def _on_period_changed(self, *_):
        period = normalize_period(self.cb_period.currentData())
        if period == self.current_period:
            return
        self.current_period = period
        self.render_charts()

    # ==========================================
    # 复权（v6.13 · P8 收尾）
    # ==========================================
    def _on_adjust_changed(self, *_):
        """切换复权口径：换分区重新载入（本地没有就自动联网同步）。

        ⚠ 不复权与前复权是**两份独立数据**，所以这里不是"重算"，而是**重新取数**；
        也因此**画线不会跟着走**（不复权的价格坐标跟前复权完全不同，
        硬搬过去会画在莫名其妙的位置）—— 面板会明确提示这一点。
        """
        adjust = self.cb_adjust.currentData()
        adjust = ADJUST_QFQ if adjust is None else str(adjust)
        if adjust == self.current_adjust:
            return
        self.current_adjust = adjust
        if self._annotations is not None:       # 构造期可能还没挂好（本函数先于 _build_chart_area）
            self._annotations.clear_view()       # 先清掉旧口径的线，避免"挂在错误价位"上闪一下
        if not self.current_symbol:
            self._refresh_adjust_hint()
            return
        if not self.load_symbol(self.current_symbol, self.current_name):
            # 本地没有这一份 → 已转后台同步：面板立刻交代清楚，别让用户盯着旧图纳闷
            # （此时**不报根数** —— 手上那份是另一个口径的数据，报出来就是误导）
            self._refresh_adjust_hint(pending=True)

    def _adjust_warning(self) -> str:
        """不复权的两个已知差异（前复权时为空串）。文案只在这里写一份，两处回执共用。"""
        if self.current_adjust == ADJUST_QFQ:
            return ""
        return "⚠ 不复权按真实价显示：指标/收益会含除权跳空；画线也不与前复权共用"

    def _refresh_adjust_hint(self, loaded_from_lake: bool = False, pending: bool = False):
        """复权面板回执：现在看的是哪一份、以及"不复权"下的两个已知差异。

        :param pending: True = 刚切过去、正在联网取这一份（不显示根数，避免报旧口径的行数）
        """
        zone = zone_for_adjust(self.current_adjust)
        label = adjust_label(self.current_adjust)
        rows = len(self.current_df) if self.current_df is not None else 0
        if pending:
            text = f"当前：{label}\n正在从云端取这一份数据…"
        elif rows:
            text = f"当前：{label} · {rows} 根"
        else:
            text = f"当前：{label}"
        warning = self._adjust_warning()
        if warning:
            text += "\n" + warning
        if loaded_from_lake:
            text += f"\n（本地命中：{zone}）"
        self.lbl_adjust_hint.setText(text)
        self.lbl_adjust_hint.setToolTip(
            f"数据湖分区：{zone}\n"
            f"「数据管理」页可单独查看/删除这一份（另一份不受影响）。")

    def prepared_df(self) -> pd.DataFrame:
        """当前**显示用**的行情：按周期重采样 + 按开关计算指标。

        ⚠ 顺序不能反：先在周线上聚合出 OHLC，再算 MA —— 否则算出来的是"日线 MA 被抽样"，
        与通达信的"5 周均线"不是一回事。
        """
        if self.current_df is None or len(self.current_df) == 0:
            return pd.DataFrame()
        df = resample_ohlcv(self.current_df, self.current_period)
        if df.empty:
            return df
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
        if df.empty:
            return df
        selected = [key for key, checkbox in
                    (('ma', self.cb_ma), ('boll', self.cb_boll), ('macd', self.cb_macd))
                    if checkbox.isChecked()]
        return TAEngine.apply(df, selected)

    # ==========================================
    # 渲染（幂等，可安全重复调用）
    # ==========================================
    def render_charts(self):
        self.host.clear_sub_panes()
        self.formula_plots = {}
        self._layer_builtin = []
        self._layer_formula = {}
        self._layer_items = []
        self.host.clear_pane_content('main')    # 保留窗格与十字光标，只清内容
        if self._annotations is not None:
            # 只清"画在图上的标注"，**不动存储** —— 本函数末尾会按当前周期读回来重画
            self._annotations.clear_view()

        df = self.prepared_df()
        if df.empty:
            self.main_plot.setTitle(
                "<span style='color:#8A94A6; font-size:13px;'>"
                "输入代码后点「🔍 查阅」，或双击左侧自选股开始</span>")
            self._refresh_annotation_status()
            return

        x_data = list(range(len(df)))
        self.main_plot.setTitle(self._title_text(df))
        self.main_plot.addItem(CandlestickItem(
            [(i, row['open'], row['close'], row['low'], row['high'])
             for i, row in df.iterrows()]))

        # ---- 统一图层：内置指标与用户公式**都翻成 DrawData**，窗格全部就位后一次落笔 ----
        self._layer_builtin = builtin_indicator_layers(
            df, ma=self.cb_ma.isChecked(), boll=self.cb_boll.isChecked())
        self._layer_formula = self._formula_layers(df)
        self._layer_bars = len(df)
        self._report_formula_status(df)

        if self.cb_vol.isChecked():
            vol_pane = self.host.add_pane('vol', fixed_height=SUB_PLOT_HEIGHT)
            self._apply_pokorny_axis(vol_pane.plot_item)
            fill_volume_pane(vol_pane.plot_item, df, x_data)

        if self.cb_macd.isChecked():
            macd_pane = self.host.add_pane('macd', fixed_height=SUB_PLOT_HEIGHT)
            self._apply_pokorny_axis(macd_pane.plot_item)
            fill_macd_pane(macd_pane.plot_item, df, x_data)

        # ---- 公式副图（v6.8：每段可选 副图 1/2/3，按需创建）----
        if self.cb_formula.isChecked():
            for target in sorted(self._layer_formula):
                if target == 'main' or not self._layer_formula[target]:
                    continue
                pane = self.host.add_pane(target, fixed_height=SUB_PLOT_HEIGHT)
                self._apply_pokorny_axis(pane.plot_item)
                span = layer_value_range(self._layer_formula[target])
                if span and span[0] <= 0 <= span[1]:
                    # 穿越 0 的振荡型指标给一条零轴参考线（不穿越就不画，免得误导）
                    pane.plot_item.addLine(
                        y=0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
                self.formula_plots[target] = pane.plot_item

        self._paint_layers()

        if len(df) > DEFAULT_VISIBLE_BARS:
            self.main_plot.getViewBox().setXRange(len(df) - DEFAULT_VISIBLE_BARS, len(df))

        # ---- 自适应坐标轴（§7-B4）：横轴刻度随可视区间重算 + 每个窗格 y 跟随可视区间 ----
        # ⚠ 必须放在 setXRange **之后**：attach 内部会按当前的 x 区间算一次刻度与量程
        self._axes.attach(df['date'], self._adaptive_providers(df))

        # 【P6】K 线 + 可视窗口就位后再恢复标注；**按 (标的, 周期) 取**，日线画线不串到周线
        self._annotations.bind(self.current_symbol, df['date'], period=self.current_period)
        self._refresh_annotation_status()
        self._refresh_adjust_hint()

    def _title_text(self, df) -> str:
        end_date = df['date'].iloc[-1].strftime('%Y-%m-%d')
        display_name = self.current_name or self.current_symbol
        return (f"<span style='color:#212121; font-size:16px; font-weight:bold;'>"
                f"{display_name} ({self.current_symbol})</span> "
                f"<span style='color:#757575; font-size:12px;'> "
                f"{period_label(self.current_period)} · {adjust_label(self.current_adjust)}"
                f" | 共 {len(df)} 根 | 截至 {end_date}</span>")

    # ==========================================
    # 自适应坐标轴 provider（§7-B4）：本页唯一要算的东西
    # ==========================================
    def _adaptive_providers(self, df) -> dict:
        """逐窗格回答"**可视 bar 区间内**的 (最低, 最高)" —— 其余全归 `adaptive_axis`。

        为什么必须由页面给：每个窗格的数据形状不同，公共件不该猜业务：
          · 主图 = K 线高低 ∪ **叠层极值**（公式线/状态柱可能跑出 K 线范围，不并进来会被裁掉）；
          · 量柱以 **0 为基线**（否则柱底会浮在"可视最低量"上，视觉上说谎）；
          · MACD 必须**含 0**（零轴是它的读数基准，丢了就看不出一根柱子是正是负）；
          · 公式副图 = 该段叠层自身的极值。
        范围一律裁到可视窗口，NaN（指标预热区 / 该 bar 无叠层）由 `slice_span` 自动忽略。
        """
        n = len(df)
        providers: dict = {}

        high = df['high'].to_numpy(dtype=float)
        low = df['low'].to_numpy(dtype=float)
        main_draws = list(self._layer_builtin)
        if self.cb_formula.isChecked():
            main_draws += self._layer_formula.get('main', [])
        overlay_lo, overlay_hi = overlay_extent(main_draws, n)
        providers['main'] = (lambda i0, i1, _lo=np.fmin(low, overlay_lo),
                             _hi=np.fmax(high, overlay_hi): slice_span(_lo, _hi, i0, i1))

        if self.cb_vol.isChecked():
            volume = df['volume'].to_numpy(dtype=float)
            baseline = np.zeros(n, dtype=float)
            providers['vol'] = (lambda i0, i1, _lo=baseline, _hi=volume:
                                slice_span(_lo, _hi, i0, i1))

        if self.cb_macd.isChecked():
            arrays = [df[column].to_numpy(dtype=float)
                      for column in ('MACD_line', 'MACD_signal', 'MACD_hist')
                      if column in df.columns]
            if arrays:
                macd_lo = np.fmin(np.fmin.reduce(arrays), 0.0)
                macd_hi = np.fmax(np.fmax.reduce(arrays), 0.0)
                providers['macd'] = (lambda i0, i1, _lo=macd_lo, _hi=macd_hi:
                                     slice_span(_lo, _hi, i0, i1))

        if self.cb_formula.isChecked():
            for target in self.formula_plots:
                draws = self._layer_formula.get(target, [])
                if not draws:
                    continue
                span_lo, span_hi = overlay_extent(draws, n)
                providers[target] = (lambda i0, i1, _lo=span_lo, _hi=span_hi:
                                     slice_span(_lo, _hi, i0, i1))
        return providers

    # ==========================================
    # 统一图层（v6.6 · §7-B3 P4）
    # ==========================================
    def edit_formula(self):
        dialog = FormulaOverlayDialog(self, segments=self._formula_segments,
                                      params_text=self._formula_params_text)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._formula_segments = dialog.result_segments()
        self._formula_params_text = dialog.params_text()
        self._compile_formula()
        self.render_charts()

    def _compile_formula(self):
        """把 (函数文本, 目标窗格) 编译成 programs（顺序与 `_formula_segments` 一一对应）。"""
        self._formula_programs = []
        self._formula_error = ""
        if not self._formula_segments:
            self._set_formula_status(True, "未设置")
            return
        for index, (text, _target) in enumerate(self._formula_segments, start=1):
            try:
                self._formula_programs.append(parse_program(text))
            except FormulaProgramError as e:
                self._formula_error = f"函数段 {index}: {e}"
                return

    def _formula_layers(self, df) -> dict:
        """按目标窗格分组求值。**失败不打断整页渲染**，只把原因写进面板状态。

        ⚠ 各段共用**同一个变量池**（后段引用前段变量）—— 所以引擎**只求值一次**，
        再按段归位（`execute_programs_with_draws_grouped`）。
        """
        targets: dict = {}
        if not self._formula_programs:
            if self._formula_error:
                self._set_formula_status(False, f"❌ {self._formula_error}")
            return targets
        params = parse_params_text(self._formula_params_text)
        try:
            _variables, groups = execute_programs_with_draws_grouped(
                self._formula_programs, df, params)
        except FormulaProgramError as e:
            self._set_formula_status(False, f"❌ 执行失败: {e}")
            return targets
        for (_text, target), draws in zip(self._formula_segments, groups):
            targets.setdefault(target, []).extend(draws)
        return targets

    def _paint_layers(self):
        """把「内置指标 + 用户公式」画到各自窗格 —— 全 app 唯一渲染器（§10-11）。

        两者在渲染层**没有任何区别**（都是 DrawData → OverlayPainter），
        这正是 §7-B3 D4「像 MA 一样显示用户函数」的架构事实。
        """
        x = np.arange(self._layer_bars)
        items: list = []

        main_pane = self.host.main_pane
        main_pane.clear_overlays()
        OverlayPainter(main_pane, x).render(self._layer_builtin)
        if self.cb_formula.isChecked():
            OverlayPainter(main_pane, x).render(self._layer_formula.get('main', []))
        items += main_pane.overlay_items

        if self.cb_formula.isChecked():
            for target, plot_item in self.formula_plots.items():
                pane = ChartPane.wrap(plot_item, name=target, role='sub')
                pane.clear_overlays()
                OverlayPainter(pane, x).render(self._layer_formula.get(target, []))
                items += pane.overlay_items

        self._layer_items = items

    def _report_formula_status(self, df):
        """写面板状态：图层数 + 落点分布，必要时补一句"该放副图"的引导。"""
        if not self._formula_programs:
            return
        if not any(self._layer_formula.values()):
            return          # 已由 _formula_layers 写过 ❌，不覆盖
        main_count = len(self._layer_formula.get('main', []))
        sub_targets = sorted(t for t in self._layer_formula
                             if t != 'main' and self._layer_formula[t])
        message = (f"✓ {sum(len(v) for v in self._layer_formula.values())} 个图层 · "
                   f"主图 {main_count} · 副图 {len(sub_targets)} 格")
        hint = None
        if main_count and not df.empty:
            hint = scale_mismatch_hint(self._layer_formula.get('main', []),
                                       float(df['low'].min()), float(df['high'].max()))
        if hint:
            self._set_formula_status(
                True, message + "\n⚠ 主图部分与股价量级相差很大 · 建议改用副图", warn=True)
            self.lbl_formula_status.setToolTip(hint)
        else:
            self._set_formula_status(True, message)

    def _set_formula_status(self, ok: bool, message: str, *, warn: bool = False):
        self.lbl_formula_status.setText(message)
        self.lbl_formula_status.setToolTip(message)   # 窄面板会截断，完整内容进 tooltip
        color = '#E65100' if warn else ('#4CAF50' if ok else '#F44336')
        self.lbl_formula_status.setStyleSheet(f"font-size: 11px; color: {color};")

    # ==========================================
    # 公式资产化 + 互送（P7 · §7-B3 P7）
    # ==========================================
    def save_formula_as(self):
        if not self._formula_segments:
            QMessageBox.information(
                self, "暂无公式",
                "先在「✏️ 编辑公式…」里粘贴并应用一段函数，再保存为配方。")
            return
        name, ok = QInputDialog.getText(self, "保存为配方", "配方名称（同名即覆盖）：")
        if not ok:
            return
        try:
            formula = make_formula(name, self._formula_segments,
                                   params_text=self._formula_params_text,
                                   source=SOURCE_MARKET)
        except ValueError as e:
            QMessageBox.warning(self, "无法保存", str(e))
            return
        saved = self._formula_store.upsert(formula)
        self._set_formula_status(True, f"✓ 已存入配方库：{saved['name']}")

    def open_formula_library(self):
        dialog = FormulaLibraryDialog(self._formula_store, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        formula = dialog.selected_formula()
        if not formula:
            return
        self.receive_formula(segments_as_tuples(formula), formula.get("params_text", ""),
                             source_label=f"配方库「{formula['name']}」")

    def send_formula_to_backtest(self) -> int:
        """行情页 → 回测页（由主窗口转交，两个页面互不 import）；返回送过去的段数。"""
        if not self._formula_segments:
            QMessageBox.information(
                self, "暂无公式", "先在「✏️ 编辑公式…」里写好函数，再送去回测。")
            return 0
        count = self.main_win.send_formula_to_backtest(
            self._formula_segments, self._formula_params_text)
        if count:
            self._set_formula_status(True, f"✓ 已把 {count} 段函数送到「📐 市场回测」")
        return count

    def receive_formula(self, segments, params_text: str = "",
                        source_label: str = "外部") -> int:
        """接收外来配方（回测页 / 配方库）并立即生效。

        :return: 实际载入的段数（0 = 内容为空，什么都没做）
        """
        pairs = [(str(text), str(target)) for text, target in (segments or [])
                 if str(text or "").strip()]
        if not pairs:
            return 0
        self._formula_segments = pairs
        self._formula_params_text = str(params_text or "")
        self.cb_formula.setChecked(True)     # 刚送来的公式就该看得见
        self._compile_formula()
        self.render_charts()
        # 回执写在渲染**之后**：否则会被 `_report_formula_status` 的图层统计覆盖
        self._set_formula_status(True, f"✓ 已从{source_label}载入 {len(pairs)} 段函数")
        return len(pairs)

    def _restore_last_formula(self):
        """开机自动恢复"上次用过的配方" —— §7-B3 P7 要解决的"公式重启就丢"。"""
        formula = self._formula_store.last_used()
        if not formula:
            return
        pairs = segments_as_tuples(formula)
        if not pairs:
            return
        self._formula_segments = pairs
        self._formula_params_text = formula.get("params_text", "")
        self._compile_formula()
        self._set_formula_status(True, f"✓ 已自动载入上次配方「{formula['name']}」"
                                       f"（{len(pairs)} 段）")

    # ==========================================
    # 用户标注（P6 · 管线 B）
    # ==========================================
    def _on_tool_changed(self, *_):
        """切换画线工具（构造期填充下拉会触发，需容忍 layer 尚未就绪）"""
        if self._annotations is None:
            return
        self._annotations.set_tool(self.cmb_tool.currentData() or "")
        self._refresh_annotation_status()

    def _reset_tool(self):
        """Esc：回到浏览模式（避免误触在图上画出线）"""
        self.cmb_tool.setCurrentIndex(0)

    def add_annotation(self):
        """按当前工具在可视窗口放一条标注；拖好后**松手自动保存**。"""
        if self._annotations is None:
            return
        tool = self._annotations.tool
        if not tool:
            QMessageBox.information(
                self, "先选择类型",
                "请在左侧「🛠 标注工具」里选择要画的类型"
                "（趋势线 / 水平线 / 垂直线 / 斐波那契 / 文字），再点「➕ 添加标注」。")
            return
        text = ""
        if tool == KIND_TEXT:
            text, ok = QInputDialog.getText(self, "文字标注", "要显示的文字：")
            if not ok:
                return
            if not str(text or "").strip():
                QMessageBox.information(self, "内容为空", "文字标注需要填写内容。")
                return
        if self._annotations.create_default(tool, text=text) is None:
            QMessageBox.information(self, "无法添加",
                                    "请先查阅一个标的并加载出 K 线，再添加标注。")
            return
        self._refresh_annotation_status()

    def delete_selected_annotation(self):
        """删除**当前选中**的那一条（逐个独立删除是管线 B 的硬要求）。"""
        if self._annotations is None:
            return
        if not self._annotations.selected_id:
            self._refresh_annotation_status(hint="先在图上点一下要删除的线（变橙色=已选中）")
            return
        self._annotations.delete_selected()
        self._refresh_annotation_status()

    def clear_annotations(self):
        """清空当前 (标的, 周期) 的全部标注 —— 不可逆，先二次确认（§10-10）。"""
        if self._annotations is None:
            return
        total = self._annotations.count()
        if not total:
            self._refresh_annotation_status()
            return
        answer = QMessageBox.question(
            self, "清空标注",
            f"确定删除 {self.current_symbol}（{period_label(self.current_period)}）"
            f"的全部 {total} 条标注吗？\n"
            f"此操作不可撤销（其它标的/周期的标注不受影响）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._annotations.clear_all()
            self._refresh_annotation_status()

    def _refresh_annotation_status(self, hint: str = ""):
        """面板回执：当前工具 + 本周期已存条数 + 下一步该干嘛（也是 layer 的 on_changed）"""
        if self._annotations is None:
            return
        total = self._annotations.count()
        tool = self._annotations.tool_label()
        period = period_label(self.current_period)
        if hint:
            text = hint
        elif tool:
            text = f"工具：{tool} · {period} 已存 {total} 条\n拖线调整，松手自动保存"
        elif total:
            text = f"{period} 已存 {total} 条标注\n点线条选中（变橙），Delete 删除"
        else:
            text = f"{period} 暂无标注"
        self.lbl_annotation_status.setText(text)
        self.lbl_annotation_status.setToolTip(
            "标注按「标的 + 周期」保存在 ~/.jian_data/annotations.json；\n"
            "每条独立可删，重渲染/切换标的都不会丢。")
        self.btn_delete_annotation.setEnabled(bool(self._annotations.selected_id))
