# ui/views/dashboard.py
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QFrame)
from PyQt6.QtCore import Qt

from config import settings
from core.utils import format_duration
from ui.widgets.calendar_heatmap import CalendarHeatmap
from ui.widgets.custom_widgets import NoWheelComboBox

class DashboardView(QWidget):
    # 中性态配色 (无数据 / 不参与盈亏着色的指标)
    NEUTRAL_TEXT = "#757575"
    NEUTRAL_BG = "#F5F5F5"

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win 
        self.metric_widgets = {}
        # C1 日历热力图数据源：{年份: ({日期: 当日净额}, {日期: 当日笔数})}
        self._calendar_data = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.create_metrics_panel(), 1)
        layout.addWidget(self.create_charts_panel(), 2)

    def create_metrics_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        title_label = QLabel("交易绩效摘要")
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121; padding: 10px; border-bottom: 2px solid #E0E0E0;")
        layout.addWidget(title_label)
        
        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(10)
        # v1.2：把"净额（真实到手）"提到首位，并拆出毛利与手续费供对照。
        # 胜率/盈亏比/单笔极值等结果类指标均已按净额口径计算（见 analyzer）。
        self.metric_keys = [
            ("净额 (真实到手)", "net_amount"), ("平仓盈亏 (毛利)", "gross_profit"),
            ("总手续费", "total_commission"), ("收益率", "return_rate"),
            ("胜率", "win_rate"), ("盈亏比", "pl_ratio"), ("最大回撤", "max_drawdown"),
            ("交易次数", "total_trades"), ("盈利次数", "winning_trades"),
            ("亏损次数", "losing_trades"), ("初始资金", "initial_capital"),
            ("平均盈利", "avg_win"), ("平均亏损", "avg_loss"),
            ("最大单笔赚", "max_profit"), ("最大单笔亏", "max_loss"),
            # v1.3 持仓时长（先加法：先展示，观察后不需要再减）
            ("平均持仓", "avg_holding_seconds"), ("最长持仓", "max_holding_seconds")
        ]
        
        for i, (label_text, key) in enumerate(self.metric_keys):
            row, col = i // 2, (i % 2) * 2
            lbl_name = QLabel(label_text)
            lbl_name.setStyleSheet("font-size: 12px; color: #757575;")
            lbl_value = QLabel("-")
            lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            metrics_grid.addWidget(lbl_name, row, col)
            metrics_grid.addWidget(lbl_value, row, col + 1)
            self.metric_widgets[key] = lbl_value
            
        layout.addLayout(metrics_grid)
        layout.addStretch()
        return panel

    def create_charts_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # C1：整年节奏总览（GitHub 风格每日净额日历）
        layout.addWidget(self.create_calendar_panel())

        # v1.2：净值曲线已改为按"净额（扣手续费后）"累计，标题如实标注口径
        self.equity_chart = pg.PlotWidget(title="资金净值曲线 (已扣手续费)")
        self.equity_chart.showGrid(x=True, y=True, alpha=0.3)
        self.distribution_chart = pg.PlotWidget(title="单笔净额分布直方图")
        self.distribution_chart.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.equity_chart, 2)
        layout.addWidget(self.distribution_chart, 1)
        return panel

    def create_calendar_panel(self):
        """C1：每日净额日历热力图 + 年份切换 + 年度摘要"""
        panel = QFrame()
        panel.setStyleSheet("QFrame { background: white; border: 1px solid #E7EAF0; border-radius: 10px; }")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("🗓 每日净额日历")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #5B6472;")
        head.addWidget(title)
        head.addSpacing(8)

        self.cb_year = NoWheelComboBox()
        self.cb_year.setFixedHeight(26)
        self.cb_year.setMinimumWidth(96)
        self.cb_year.setStyleSheet(
            "QComboBox { padding: 0 8px; border: 1px solid #E0E4EC; border-radius: 8px; "
            "background: white; font-size: 12px; color: #1F2430; }"
            "QComboBox:focus { border: 1px solid #1976D2; }")
        self.cb_year.currentIndexChanged.connect(self._render_calendar)
        head.addWidget(self.cb_year)
        head.addSpacing(12)

        self.lbl_cal_summary = QLabel("—")
        self.lbl_cal_summary.setStyleSheet("font-size: 12px; color: #8A94A6;")
        head.addWidget(self.lbl_cal_summary)
        head.addStretch()
        head.addWidget(self._hint_icon(
            "颜色 = 当日净额（已扣手续费），绿盈红亏，绝对值越大颜色越深；"
            "灰色 = 当日无交易或净额为 0。鼠标悬停任意格子可看当日净额与成交笔数。"))
        lay.addLayout(head)

        self.heatmap = CalendarHeatmap()
        lay.addWidget(self.heatmap)
        return panel

    @staticmethod
    def _hint_icon(tooltip: str) -> QLabel:
        """「?」小角标承载说明，避免长灰字占版面（与回测页同一手法）"""
        icon = QLabel("?")
        icon.setFixedSize(15, 15)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("QLabel { background:#E3E7EF; color:#7A8392; border-radius:7px;"
                           " font-size:10px; font-weight:bold; }")
        icon.setToolTip(tooltip)
        return icon

    @staticmethod
    def _rgba_bg(rgb: tuple, alpha: float = 0.1) -> str:
        """将配置中心的 RGB 元组转换为带透明度的背景色"""
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"

    def set_metric_style(self, widget, formatted_text, raw_value=None, threshold=0.0,
                         force_neutral=False, reverse_color=False):
        """
        统一的指标着色策略。
        :param threshold: 好坏判定基准线，默认 0；胜率这类“过半才算好”的指标传 0.5
        :param reverse_color: 数值越大越糟糕的指标 (如最大回撤) 置为 True
        """
        widget.setText(formatted_text)

        if force_neutral:
            color, bg_color = settings.COLOR_TEXT_PRIMARY, self.NEUTRAL_BG
        elif raw_value is None:
            color, bg_color = self.NEUTRAL_TEXT, self.NEUTRAL_BG
        else:
            diff = raw_value - threshold
            if diff == 0:
                color, bg_color = self.NEUTRAL_TEXT, self.NEUTRAL_BG
            elif (diff > 0) != reverse_color:
                color, bg_color = settings.COLOR_PROFIT, self._rgba_bg(settings.RGB_PROFIT)
            else:
                color, bg_color = settings.COLOR_LOSS, self._rgba_bg(settings.RGB_LOSS)

        widget.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {color}; "
            f"padding: 5px; background-color: {bg_color}; border-radius: 4px;"
        )

    def clear_view(self):
        self.equity_chart.clear()
        self.distribution_chart.clear()
        for widget in self.metric_widgets.values():
            self.set_metric_style(widget, "-", force_neutral=True)
        self._calendar_data = {}
        self.cb_year.blockSignals(True)
        self.cb_year.clear()
        self.cb_year.blockSignals(False)
        self.heatmap.clear()
        self.lbl_cal_summary.setText("—")

    # ==========================================
    # C1 每日净额日历热力图
    # ==========================================
    def _prepare_calendar(self, df):
        """把日级净额聚合成 {年份: ({日期: 净额}, {日期: 笔数})}，供日历按年渲染。

        【口径】与全站一致使用 net_amount = net_profit − commission（§5.3-B）。
        """
        self._calendar_data = {}
        if df is None or df.empty or 'trade_time' not in df.columns:
            return
        work = df.copy()
        work['trade_time'] = pd.to_datetime(work['trade_time'], errors='coerce')
        work = work.dropna(subset=['trade_time'])
        if work.empty or 'net_amount' not in work.columns:
            return

        grouped = work.groupby(work['trade_time'].dt.date)['net_amount'].agg(['sum', 'count'])
        for day, row in grouped.iterrows():
            values, counts = self._calendar_data.setdefault(day.year, ({}, {}))
            values[day] = float(row['sum'])
            counts[day] = int(row['count'])

    def _refresh_calendar_years(self):
        """重建年份下拉（倒序，默认停在最近有数据的年份）"""
        years = sorted(self._calendar_data.keys(), reverse=True)
        self.cb_year.blockSignals(True)
        self.cb_year.clear()
        for year in years:
            self.cb_year.addItem(f"{year} 年", year)
        if years:
            self.cb_year.setCurrentIndex(0)
        self.cb_year.blockSignals(False)
        self._render_calendar()

    def _render_calendar(self, *_args):
        """按当前选中年份渲染热力图 + 年度摘要"""
        year = self.cb_year.currentData()
        if year is None:
            self.heatmap.clear()
            self.lbl_cal_summary.setText("—")
            return
        year = int(year)
        values, counts = self._calendar_data.get(year, ({}, {}))
        self.heatmap.set_year_data(year, values, counts)

        wins = sum(1 for v in values.values() if v > 0)
        losses = sum(1 for v in values.values() if v < 0)
        total = sum(values.values())
        tone = settings.COLOR_PROFIT_TEXT if total >= 0 else settings.COLOR_LOSS_TEXT
        self.lbl_cal_summary.setText(
            f"共 {len(values)} 个交易日　盈利 <b style='color:{settings.COLOR_PROFIT_TEXT};'>"
            f"{wins}</b> 天　亏损 <b style='color:{settings.COLOR_LOSS_TEXT};'>{losses}</b> 天　"
            f"年度净额 <b style='color:{tone};'>￥{total:+,.2f}</b>")

    def update_view(self, r, df):
        m = self.metric_widgets
        # 净额是主推指标；毛利与手续费并列展示，让用户一眼看清成本占比
        self.set_metric_style(m["net_amount"], f"￥{r['net_amount']:,.2f}", r['net_amount'])
        self.set_metric_style(m["gross_profit"], f"￥{r['gross_profit']:,.2f}", r['gross_profit'])
        self.set_metric_style(m["avg_win"], f"￥{r['avg_win']:,.2f}", r['avg_win'])
        self.set_metric_style(m["avg_loss"], f"￥{r['avg_loss']:,.2f}", r['avg_loss'])
        self.set_metric_style(m["max_profit"], f"￥{r['max_profit']:,.2f}", r['max_profit'])
        self.set_metric_style(m["max_loss"], f"￥{r['max_loss']:,.2f}", r['max_loss'])
        self.set_metric_style(m["return_rate"], f"{r['return_rate']*100:.2f}%", r['return_rate'])
        self.set_metric_style(m["win_rate"], f"{r['win_rate']*100:.2f}%", r['win_rate'], threshold=0.5)
        self.set_metric_style(m["max_drawdown"], f"{r['max_drawdown']*100:.2f}%", r['max_drawdown'], reverse_color=True)
        self.set_metric_style(m["initial_capital"], f"￥{r['initial_capital']:,.2f}", force_neutral=True)
        self.set_metric_style(m["total_commission"], f"￥{r['total_commission']:,.2f}", force_neutral=True)
        self.set_metric_style(m["pl_ratio"], f"{r['pl_ratio']:.2f}", force_neutral=True)
        self.set_metric_style(m["total_trades"], str(r['total_trades']), force_neutral=True)
        self.set_metric_style(m["winning_trades"], str(r['winning_trades']), force_neutral=True)
        self.set_metric_style(m["losing_trades"], str(r['losing_trades']), force_neutral=True)

        # v1.3 持仓时长卡片 —— 诚实标注样本覆盖，绝不假装全量
        covered = r.get('holding_covered', 0)
        total = r.get('holding_total', 0)
        date_only = r.get('date_only_holds', 0)
        tip = (f"基于开仓带时分的 {covered}/{total} 笔精确计时；"
               f"{date_only} 笔开仓仅日期（按交易日口径，见深度复盘页）。")
        for key in ('avg_holding_seconds', 'max_holding_seconds'):
            hs = r.get(key)
            self.set_metric_style(m[key],
                                  format_duration(hs) if hs is not None else "—",
                                  force_neutral=True)
            m[key].setToolTip(tip)

        equity_data = df['equity'].tolist()
        x_data = list(range(len(equity_data)))
        self.equity_chart.clear()
        if equity_data:
            is_prof = equity_data[-1] >= equity_data[0]
            # 【进化】使用配置中心的 RGB 元组
            col = settings.RGB_PROFIT if is_prof else settings.RGB_LOSS
            fill = settings.RGB_PROFIT_FILL if is_prof else settings.RGB_LOSS_FILL
            self.equity_chart.plot(x_data, equity_data, pen=pg.mkPen(color=col, width=2.5), fillLevel=equity_data[0], fillBrush=fill)

        # 分布图同样改用净额，直方图形态才与真实到手盈亏一致
        profits = df['net_amount'].values
        self.distribution_chart.clear()
        if len(profits) > 0:
            hist, bin_edges = np.histogram(profits, bins=25)
            x_vals, y_vals = [], []
            for i in range(len(bin_edges)-1): 
                x_vals.extend([bin_edges[i], bin_edges[i+1]])
                y_vals.extend([hist[i], hist[i]])
            self.distribution_chart.plot(x_vals, y_vals, pen=pg.mkPen(color=(33, 150, 243), width=2), fillLevel=0, fillBrush=pg.mkBrush((33, 150, 243, 100)))

        # C1：日级净额聚合 -> 年度日历热力图（放在最后，与图表同一次刷新完成）
        self._prepare_calendar(df)
        self._refresh_calendar_years()