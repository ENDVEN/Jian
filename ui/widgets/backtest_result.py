# ui/widgets/backtest_result.py
"""
📐 回测「结果区」（L0 主角 · 1.22 自 `ui/views/backtest.py` 拆出 · §9-L 第二批）。

【它管什么】把**已经算好**的结果画出来：
  · KPI 四卡（总成交 / 胜率 / 累计收益 / 平均单笔）；
  · 结果页签 4 个：净值曲线 · K线买卖点（含公式叠层）· 策略对比 · 成交明细表；
  · 两个图表的**日期轴与量程自适应**（刻度算法一律走公共件 `adaptive_axis`，§7-B4）。
【它不管什么】回测流程、数据抓取、策略存取、导出 —— 那些仍归页面（`ui/views/backtest.py`）。
【为什么拆】页面已 1400+ 行，而结果区是**最高频、长停留**的那一块（§10-14 的 L0）：
单独成模块它才能继续长（加页签 / 加指标）而不再把页面撑大。

【与页面的契约】
  · 页面通过 `render_result(...)` / `render_kline(...)` / `render_compare_chart(...)` 喂结果；
  · 页面通过属性读取控件（`tabs` / `kline_chart` / `chk_overlay` …）以保持既有断言口径；
  · `df` / `draws`（整段行情 + 引擎绘图 IR）**由页面持有**（它们是"本次运行"的状态），
    每次渲染显式传进来 —— 结果区不做任何"记住上次数据"的隐式行为。
"""
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from config import settings
from core.backtest import EXIT_REASON_COLORS, EXIT_REASON_LABELS
from ui.widgets.adaptive_axis import axis_px, compute_ticks, slice_span, visible_span
from ui.widgets.chart_pane import ChartPane
from ui.widgets.chart_style import apply_pokorny_style, plot_equity_curve
from ui.widgets.custom_widgets import CandlestickItem
from ui.widgets.draw_overlay import OverlayPainter, overlay_extent, slice_draws

PLACEHOLDER = "-"
MARKER_MARGIN = 0.03     # 买卖三角/菱形相对当根最低/最高价的偏移（防压住影线）
RECENT_BARS = 150        # 「最近150日」按钮的窗口

_CARD_QSS = ("QFrame { background: white; border: 1px solid #E7EAF0; border-radius: 12px; }")
_TABS_QSS = ("QTabWidget::pane { border:1px solid #E7EAF0; border-radius:10px; background:white;"
             " top:-1px;} QTabBar::tab { background:transparent; color:#8A94A6; padding:8px 18px;"
             " font-weight:bold; } QTabBar::tab:selected { color:#1976D2;"
             " border-bottom:3px solid #1976D2; }")
_TABLE_QSS = ("QTableWidget { background: white; alternate-background-color: #F7F9FC; border:none;"
              " gridline-color:#EEF1F6;} QHeaderView::section { background:#F4F6FA; color:#5B6472;"
              " font-weight:bold; border:none; padding:8px; }")


class _MetricCard(QFrame):
    """大号 KPI 卡片：上标题下数值，数值越大越醒目"""

    def __init__(self, title: str, accent: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_CARD_QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        head = QLabel(title)
        head.setStyleSheet("font-size: 12px; color: #8A94A6; font-weight: bold;")
        lay.addWidget(head)
        self.value = QLabel(PLACEHOLDER)
        self.value.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {accent};")
        lay.addWidget(self.value)


class BacktestResultArea(QWidget):
    """结果区整块（KPI + K线控制 + 4 结果页签 + 图表渲染）。

    :param export_button: 页面的「导出结果 ▾」按钮（菜单动作是页面职责，故由页面建好后传进来）
    """

    def __init__(self, export_button=None, parent=None):
        super().__init__(parent)

        # 本次渲染的输入（由页面在每次 render_* 时传入）
        self._df = pd.DataFrame()
        self._draws: list = []
        self._equity_state = None
        self._kline_state = None
        self._kline_win_draws: list = []   # 按 K 线窗口切片后的叠层
        self._overlay_items: list = []     # 已渲染的叠层图元（供"显示公式叠层"开关切换）
        self._kline_hint_text: str = ""    # K 线空态提示文案（§7-A4 只读回放要用自定义文案）

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addLayout(self._build_kpi_row())
        root.addLayout(self._build_kline_controls(export_button))
        root.addWidget(self._build_tabs(), 1)

    # ==========================================
    # 构建
    # ==========================================
    def _build_kpi_row(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        self.card_total = _MetricCard("总成交", "#1F2430")
        self.card_win = _MetricCard("胜率", settings.COLOR_PROFIT_TEXT)
        self.card_cum = _MetricCard("累计收益", settings.COLOR_PROFIT_TEXT)
        self.card_avg = _MetricCard("平均单笔", settings.COLOR_TEXT_PRIMARY)
        for card in (self.card_total, self.card_win, self.card_cum, self.card_avg):
            card.setMinimumWidth(150)
            row.addWidget(card, 1)
        return row

    def _build_kline_controls(self, export_button):
        """K 线显示控制行 + 导出入口（L4 附属：贴着结果区头部）。"""
        row = QHBoxLayout()

        def mini(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #5B6472;")
            return lbl

        row.addWidget(mini("K线:"))
        self.chk_follow = QCheckBox("价格轴跟随可视区间")
        self.chk_follow.setChecked(True)
        self.chk_follow.setToolTip("只按**可视窗口内**的价格重算纵轴（放大后不会被全量极值压扁）")
        self.chk_follow.toggled.connect(self._refresh_kline_view)
        row.addWidget(self.chk_follow)

        self.chk_log = QCheckBox("对数价格")
        self.chk_log.toggled.connect(self._on_log_toggled)
        row.addWidget(self.chk_log)

        # v6.4 / §7-B3 P3：公式叠层开关（默认开）。切换只改可见性，不重置缩放。
        self.chk_overlay = QCheckBox("显示公式叠层")
        self.chk_overlay.setChecked(True)
        self.chk_overlay.setToolTip("叠加函数里的公式线 / STICKLINE 状态柱 / DRAWICON 图标")
        self.chk_overlay.toggled.connect(self._on_overlay_toggled)
        row.addWidget(self.chk_overlay)

        self.btn_fit_full = QPushButton("适应全量")
        self.btn_fit_full.clicked.connect(self._fit_kline_full)
        row.addWidget(self.btn_fit_full)

        self.btn_fit_last = QPushButton("最近150日")
        self.btn_fit_last.clicked.connect(self._fit_kline_recent)
        row.addWidget(self.btn_fit_last)

        row.addStretch()
        if export_button is not None:
            self.btn_export_result = export_button
            row.addWidget(export_button)
        return row

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(_TABS_QSS)

        self.equity_chart = pg.PlotWidget()
        self._style_chart(self.equity_chart)
        # 空态先给一句话，别让用户对着一块"默认 0~1 坐标轴"发懵（渲染时会被清掉）
        self.equity_chart.getPlotItem().setTitle(
            "回测后在这里看净值曲线", color="#9AA3B2", size="11pt")
        self.tabs.addTab(self.equity_chart, "📈 净值曲线")

        self.kline_chart = pg.PlotWidget()
        self._style_chart(self.kline_chart)
        self.tabs.addTab(self.kline_chart, "🕯️ K线买卖点")

        self.compare_tab = QWidget()
        self._build_compare_tab()
        self.tabs.addTab(self.compare_tab, "🧭 策略对比")

        self.trades_table = QTableWidget()
        self.trades_table.setColumnCount(9)
        self.trades_table.setHorizontalHeaderLabels(
            ["#", "买入日期", "买入价", "卖出日期", "卖出价", "持有天数", "盈亏", "收益率", "离场原因"])
        self.trades_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.trades_table.setAlternatingRowColors(True)
        self.trades_table.setStyleSheet(_TABLE_QSS)
        self.tabs.addTab(self.trades_table, "🧾 成交明细")

        # 图表轴/量程自适应：监听缩放，刻度随可视区间重算（§7-B4）
        self.kline_chart.getViewBox().sigXRangeChanged.connect(self._on_kline_zoom)
        self.equity_chart.getViewBox().sigXRangeChanged.connect(self._on_equity_zoom)
        return self.tabs

    def _build_compare_tab(self):
        lay = QVBoxLayout(self.compare_tab)
        lay.setContentsMargins(10, 10, 10, 10)
        title = QLabel("🧭 当前标的下，已保存策略的回测表现对比")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2430;")
        lay.addWidget(title)
        desc = QLabel("运行某个已选用策略并完成回测后，指标会自动归档。"
                      "横向比较可快速判断该股票更适合哪套策略。")
        desc.setStyleSheet("font-size: 12px; color: #8A94A6;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        self.compare_chart = pg.PlotWidget()
        self._style_chart(self.compare_chart)
        self.compare_chart.getPlotItem().setLabel('left', '累计收益')
        lay.addWidget(self.compare_chart, 1)

        self.compare_table = QTableWidget()
        self.compare_table.setColumnCount(5)
        self.compare_table.setHorizontalHeaderLabels(
            ["策略", "总成交", "胜率", "累计收益", "归档时间"])
        self.compare_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.compare_table.setAlternatingRowColors(True)
        self.compare_table.setStyleSheet(
            "QTableWidget { background: white; alternate-background-color:#F7F9FC;"
            " border:1px solid #E7EAF0; border-radius:8px; }"
            " QHeaderView::section { background:#F4F6FA; color:#5B6472; font-weight:bold;"
            " padding:6px; border:none; }")
        lay.addWidget(self.compare_table, 1)

    # NOTE(v5.12 · §9-O7)：图表轴样式统一下沉到 ui/widgets/chart_style.py。
    # 这里图表嵌在白色卡片里，故 background=None（不重刷背景）、margins=0（不设内边距）。
    @staticmethod
    def _style_chart(chart):
        return apply_pokorny_style(chart, background=None, margins=0)

    # ==========================================
    # 对外：渲染
    # ==========================================
    def render_result(self, result, name: str, symbol: str,
                      df=None, draws=None, kline_hint: str = None) -> dict:
        """渲染一次完整结果（KPI + 净值 + 明细 + K线），返回引擎 summary 供页面写回执。

        页面负责用返回的 summary 拼"运行回执"文字（那里才有 current_name/symbol 的语境）。
        :param kline_hint: K 线画不出时标题上的说明（如"历史存档不含逐日 K 线"）；
                           为 None 时用默认文案。
        """
        if df is not None:
            self._df = df
        if draws is not None:
            self._draws = draws

        summary = result.summary()
        self._render_kpi(summary)
        self._render_equity(result)
        self._render_trades(result)
        self._render_kline(result, hint=kline_hint)
        return summary

    def render_kline(self, result, df=None, draws=None, name: str = "", symbol: str = ""):
        """只重画 K 线买卖点（叠层开关/窗口切换/测试断言都会走它）。"""
        if df is not None:
            self._df = df
        if draws is not None:
            self._draws = draws
        self._kline_name = name
        self._kline_symbol = symbol
        self._render_kline(result)

    def render_compare_chart(self, snapshots):
        """策略对比柱图（数据从策略库来，由页面取好后喂进来）。"""
        self.compare_chart.clear()
        if not snapshots:
            self.compare_chart.getPlotItem().setTitle(
                "暂无该标的的归档结果：选用策略并完成回测后会自动出现在这里",
                color="#9AA3B2", size="10pt")
            return
        names = [str(s["strategy"].get("name", "?"))[:12] for s in snapshots]
        cums = [float(s["metrics"].get("cumulative_return", 0.0)) for s in snapshots]
        x = list(range(len(cums)))
        brushes = [pg.mkBrush(settings.COLOR_PROFIT if c >= 0 else settings.COLOR_LOSS)
                   for c in cums]
        pens = [pg.mkPen(settings.COLOR_PROFIT if c >= 0 else settings.COLOR_LOSS)
                for c in cums]
        self.compare_chart.addItem(
            pg.BarGraphItem(x=x, height=cums, width=0.6, brushes=brushes, pens=pens))
        self.compare_chart.addLine(
            y=0, pen=pg.mkPen(color='#C3CAD6', style=Qt.PenStyle.DashLine))
        axis = self.compare_chart.getAxis('bottom')
        axis.setTicks([[(i, one_name) for i, one_name in enumerate(names)]])

    # ==========================================
    # 内部：KPI / 净值 / 明细
    # ==========================================
    def _render_kpi(self, summary: dict):
        self.card_total.value.setText(str(summary["total_trades"]))
        win_rate = summary["win_rate"]
        cum = summary["cumulative_return"]
        self.card_win.value.setText(f"{win_rate * 100:.1f}%")
        self.card_cum.value.setText(f"{cum * 100:+.1f}%")
        color = settings.COLOR_PROFIT_TEXT if cum >= 0 else settings.COLOR_LOSS_TEXT
        self.card_cum.value.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {color};")
        self.card_avg.value.setText(f"{summary['avg_return_pct'] * 100:+.2f}%")

    def _render_equity(self, result):
        self.equity_chart.clear()
        self._equity_state = None
        if result.equity.empty:
            self.equity_chart.getPlotItem().setTitle(
                "本次回测没有净值序列（一笔成交都没有）", color="#9AA3B2", size="11pt")
            return
        self.equity_chart.getPlotItem().setTitle("")   # 有数据就撤掉空态提示
        eq = result.equity
        dates = pd.to_datetime(eq['date'])
        # 净值曲线基准线 = 1.0（归一化起点），绘制统一走 chart_style（v5.12 · §9-O7）
        plot_equity_curve(self.equity_chart, eq['equity'], fill_base=1.0, width=2)
        self.equity_chart.addLine(
            y=1.0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
        # §7-A4：历史存档回放的净值序列带 buy_at / sell_at（成交日**净值**）⇒
        # 买卖点直接落在净值曲线上（不用成交价 —— 与净值不同量纲，画上去会跑出坐标轴）。
        for col, symbol, color in (("buy_at", 't', settings.COLOR_PROFIT),
                                   ("sell_at", 'd', settings.COLOR_LOSS)):
            if col not in eq.columns:
                continue
            xs = [i for i, ok in enumerate(eq[col].notna().tolist()) if ok]
            if xs:
                self.equity_chart.addItem(pg.ScatterPlotItem(
                    x=xs, y=[float(eq[col].iloc[i]) for i in xs], symbol=symbol,
                    size=12, brush=pg.mkBrush(color), pen='w'))
        self._equity_state = {'dates': dates.tolist()}
        self._refresh_equity_axis()

    def _render_trades(self, result):
        self.trades_table.setRowCount(len(result.trades))
        for row, t in enumerate(result.trades):
            entry = pd.Timestamp(t.entry_date)
            exit_ = pd.Timestamp(t.exit_date)
            reason = EXIT_REASON_LABELS.get(getattr(t, 'exit_reason', 'signal'), "卖出信号")
            if getattr(t, 'deferred_t1', False):
                # v6.17：该笔是"进场当根被 T+1 拦下、顺延到最早可卖根开盘价成交"的
                reason += "（T+1 顺延）"
            values = [
                str(row + 1), entry.strftime('%Y-%m-%d'), f"{t.entry_price:.2f}",
                exit_.strftime('%Y-%m-%d'), f"{t.exit_price:.2f}",
                str(t.days_held if t.days_held is not None else "-"),
                f"￥{t.pnl:+,.2f}", f"{t.return_pct * 100:+.2f}%",
                reason,
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col in (6, 7):
                    item_color = (settings.COLOR_PROFIT_TEXT if t.pnl > 0
                                  else settings.COLOR_LOSS_TEXT)
                    item.setForeground(QColor(item_color))
                    item.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                if col == 8:
                    item_color = EXIT_REASON_COLORS.get(
                        getattr(t, 'exit_reason', 'signal'), "#212121")
                    item.setForeground(QColor(item_color))
                    item.setToolTip(f"离场来源：{reason}")
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self.trades_table.setItem(row, col, item)

    # ==========================================
    # 内部：K 线 + 公式叠层
    # ==========================================
    def _render_kline(self, result, hint: str = None):
        self.kline_chart.clear()
        self._kline_state = None
        self._overlay_items = []
        self._kline_win_draws = []
        self._kline_hint_text = ""            # 空态提示文案（验收断言读它，不依赖 pyqtgraph 内部）

        df = self._df
        if df is None or df.empty or not result.trades:
            self._kline_hint_text = hint or "请回测后查看买卖点标注"
            self.kline_chart.getPlotItem().setTitle(
                self._kline_hint_text, color="#9AA3B2", size="11pt")
            return
        data = df.copy()
        data['date'] = pd.to_datetime(data['date'])
        # 【v6.4 关键】叠层是在**整段 df 的原行序**上求值的，而这里为稳妥会按日期重排；
        # 因此必须记下"排序后位置 → 原始行号"的映射，否则公式线会整体错位
        # （就是 §7-B3 强调的"跨窗口漂移"）。restore 后仍与 _df 行序严格对应。
        order = np.argsort(data['date'].to_numpy(), kind='stable')
        data = data.iloc[order].reset_index(drop=True)

        first_entry = pd.Timestamp(result.trades[0].entry_date)
        last_exit = pd.Timestamp(result.trades[-1].exit_date)
        mask = ((data['date'] >= first_entry - pd.Timedelta(days=90))
                & (data['date'] <= last_exit + pd.Timedelta(days=30))).to_numpy()
        win_pos = np.nonzero(mask)[0]
        if win_pos.size == 0:
            return
        window = data.iloc[win_pos].reset_index(drop=True)
        src_rows = order[win_pos]
        date_index = {d: i for i, d in enumerate(window['date'])}

        name = getattr(self, "_kline_name", "") or ""
        symbol = getattr(self, "_kline_symbol", "") or ""
        title = (f"<span style='color:#1F2430; font-size:15px; font-weight:bold;'>{name} "
                 f"({symbol})</span> <span style='color:#8A94A6; font-size:12px;'>买卖点标注</span>")
        self.kline_chart.getPlotItem().setTitle(title)
        k_data = [(i, row['open'], row['close'], row['low'], row['high'])
                  for i, row in window.iterrows()]
        self.kline_chart.addItem(CandlestickItem(k_data))

        # ---- 公式叠层：K线之后、买卖点之前（§7-B3 P3 堆叠顺序）----
        self._paint_overlays(src_rows, len(window))

        buy_x, buy_y, sell_x, sell_y = [], [], [], []
        for t in result.trades:
            e_date, x_date = pd.Timestamp(t.entry_date), pd.Timestamp(t.exit_date)
            if e_date in date_index:
                idx = date_index[e_date]
                buy_x.append(idx)
                buy_y.append(window['low'].iloc[idx] * (1 - MARKER_MARGIN))
            if x_date in date_index:
                idx = date_index[x_date]
                sell_x.append(idx)
                sell_y.append(window['high'].iloc[idx] * (1 + MARKER_MARGIN))
        if buy_x:
            self.kline_chart.addItem(pg.ScatterPlotItem(
                x=buy_x, y=buy_y, symbol='t', size=15,
                brush=pg.mkBrush(settings.COLOR_PROFIT), pen='w'))
        if sell_x:
            self.kline_chart.addItem(pg.ScatterPlotItem(
                x=sell_x, y=sell_y, symbol='d', size=15,
                brush=pg.mkBrush(settings.COLOR_LOSS), pen='w'))

        ov_lo = ov_hi = None
        if self._kline_win_draws and self.chk_overlay.isChecked():
            ov_lo, ov_hi = overlay_extent(self._kline_win_draws, len(window))
        self._kline_state = {
            'dates': window['date'].tolist(),
            'high': window['high'].to_numpy(dtype=float),
            'low': window['low'].to_numpy(dtype=float),
            'overlay_lo': ov_lo,
            'overlay_hi': ov_hi,
        }
        lo = max(0, date_index.get(first_entry, 0) - 60)
        hi = min(len(window) - 1, date_index.get(last_exit, len(window) - 1) + 10)
        self.kline_chart.getPlotItem().setXRange(lo, hi, padding=0.02)
        self._on_log_toggled()
        self._refresh_kline_view()

    def _paint_overlays(self, src_rows, bar_count: int):
        """把引擎绘图 IR（整段）按 K 线窗口切片后渲染到 K 线窗格上。

        宿主只做三件事（§7-B3 B③）：**切窗口 / 喂 x 数组 / 把 y 范围扩到盖住叠层**；
        "IR → 图元" 全部在 `ui/widgets/draw_overlay.py`（全 app 唯一渲染器），
        本模块**不得**自己写任何绘图逻辑（§10-11）。
        """
        self._kline_win_draws = []
        if not self._draws or bar_count <= 0:
            return
        win_draws = slice_draws(self._draws, src_rows)
        self._kline_win_draws = win_draws
        if not self.chk_overlay.isChecked():
            return
        painter = OverlayPainter(
            ChartPane.wrap(self.kline_chart, name="kline", role="main"),
            np.arange(bar_count))
        self._overlay_items = painter.render(win_draws)

    def _on_overlay_toggled(self):
        """「显示公式叠层」开关：只切可见性 + 重算 y 范围，**不重置用户的缩放**。"""
        visible = self.chk_overlay.isChecked()
        for item in self._overlay_items:
            item.setVisible(visible)
        state = self._kline_state
        if state is None:
            return
        if visible and self._kline_win_draws:
            lo, hi = overlay_extent(self._kline_win_draws, len(state['dates']))
        else:
            lo = hi = None
        state['overlay_lo'], state['overlay_hi'] = lo, hi
        self._refresh_kline_view()

    # ==========================================
    # 内部：日期轴 / 量程自适应（§7-B4）
    # ==========================================
    def _on_equity_zoom(self, *_args):
        if self._equity_state is not None:
            self._refresh_equity_axis()

    def _refresh_equity_axis(self):
        state = self._equity_state
        if state is None:
            return
        # 刻度算法收敛到公共件（§7-B4）：不再自己写"按可视 bar 重算 + 自适应格式"，
        # 与行情页/复盘页共用同一份口径（这正是当年"改一处漏三处"的病根）。
        dates = state['dates']
        view_box = self.equity_chart.getViewBox()
        axis = self.equity_chart.getAxis('bottom')
        i0, i1 = visible_span(view_box, len(dates))
        ticks = compute_ticks(dates, i0, i1, width_px=axis_px(axis))
        axis.setTicks([ticks] if ticks else [])

    def _on_kline_zoom(self, *_args):
        if self._kline_state is not None:
            self._refresh_kline_view()

    def _fit_kline_full(self):
        if self._kline_state is None:
            return
        n = len(self._kline_state['dates'])
        self.kline_chart.setXRange(0, max(1, n - 1), padding=0.02)
        self._refresh_kline_view()

    def _fit_kline_recent(self):
        if self._kline_state is None:
            return
        n = len(self._kline_state['dates'])
        lo = max(0, n - RECENT_BARS)
        self.kline_chart.setXRange(lo, max(lo + 1, n - 1), padding=0.02)
        self._refresh_kline_view()

    def _on_log_toggled(self):
        self.kline_chart.setLogMode(x=False, y=self.chk_log.isChecked())
        self._refresh_kline_view()

    def _refresh_kline_view(self, *_args):
        state = self._kline_state
        if state is None:
            return
        dates = state['dates']
        view_box = self.kline_chart.getViewBox()
        n = len(dates)
        # 刻度算法收敛到公共件（§7-B4）：横轴密度/格式全 app 一份口径
        axis = self.kline_chart.getAxis('bottom')
        i0, i1 = visible_span(view_box, n)
        ticks = compute_ticks(dates, i0, i1, width_px=axis_px(axis))
        axis.setTicks([ticks] if ticks else [])

        if self.chk_follow.isChecked():
            # 「价格轴跟随可视区间」开关语义保留（用户可以关，§7-B4 边界）：
            # 极值只在**可视窗口内**取，并沿用 v6.4 的"叠层也纳入视口"（§7-B3 B③）。
            low = np.asarray(state['low'], dtype=float)
            high = np.asarray(state['high'], dtype=float)
            ov_lo = state.get('overlay_lo')
            ov_hi = state.get('overlay_hi')
            if ov_lo is not None and np.asarray(ov_lo).size == n:
                low = np.fmin(low, np.asarray(ov_lo, dtype=float))
            if ov_hi is not None and np.asarray(ov_hi).size == n:
                high = np.fmax(high, np.asarray(ov_hi, dtype=float))
            span = slice_span(low, high, i0, i1)
            if span is not None:
                lo_p, hi_p = span
                pad = (hi_p - lo_p) * 0.06 or (abs(hi_p) * 0.01 or 1.0)
                # padding=0：pyqtgraph 会在我们给的范围上再叠一层自己的 padding（§11.5-21），
                # 那会让"价格轴跟随可视区间"的实际留白变成不可预期的数值。
                view_box.setYRange(lo_p - pad, hi_p + pad, padding=0)
