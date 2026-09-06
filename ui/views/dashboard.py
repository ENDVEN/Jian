# ui/views/dashboard.py
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel
from PyQt6.QtCore import Qt

from config import settings

class DashboardView(QWidget):
    # 中性态配色 (无数据 / 不参与盈亏着色的指标)
    NEUTRAL_TEXT = "#757575"
    NEUTRAL_BG = "#F5F5F5"

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win 
        self.metric_widgets = {}
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
            ("最大单笔赚", "max_profit"), ("最大单笔亏", "max_loss")
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
        # v1.2：净值曲线已改为按"净额（扣手续费后）"累计，标题如实标注口径
        self.equity_chart = pg.PlotWidget(title="资金净值曲线 (已扣手续费)")
        self.equity_chart.showGrid(x=True, y=True, alpha=0.3)
        self.distribution_chart = pg.PlotWidget(title="单笔净额分布直方图")
        self.distribution_chart.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.equity_chart, 2)
        layout.addWidget(self.distribution_chart, 1)
        return panel

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