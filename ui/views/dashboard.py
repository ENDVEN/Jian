# ui/views/dashboard.py
import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel
from PyQt6.QtCore import Qt

class DashboardView(QWidget):
    """
    【资金与表现】页面组件。
    只负责渲染图表和统计指标，不包含任何外部数据获取逻辑。
    """
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win # 保存对主窗口的引用，方便以后需要时通信
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
        self.metric_keys = [
            ("净利润", "net_profit"), ("收益率", "return_rate"), ("胜率", "win_rate"), 
            ("盈亏比", "pl_ratio"), ("最大回撤", "max_drawdown"), ("交易次数", "total_trades"), 
            ("盈利次数", "winning_trades"), ("亏损次数", "losing_trades"), ("初始资金", "initial_capital"), 
            ("总手续费", "total_commission"), ("平均盈利", "avg_win"), ("平均亏损", "avg_loss"), 
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
        self.equity_chart = pg.PlotWidget(title="资金净值曲线")
        self.equity_chart.showGrid(x=True, y=True, alpha=0.3)
        self.distribution_chart = pg.PlotWidget(title="盈亏分布直方图")
        self.distribution_chart.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.equity_chart, 2)
        layout.addWidget(self.distribution_chart, 1)
        return panel

    def set_metric_style(self, widget, formatted_text, raw_value=None, force_neutral=False, reverse_color=False):
        widget.setText(formatted_text)
        if force_neutral: color, bg_color = "#424242", "#F5F5F5"
        elif raw_value is not None:
            if raw_value == 0: color, bg_color = "#757575", "#F5F5F5"
            elif (raw_value > 0 and not reverse_color) or (raw_value < 0 and reverse_color): color, bg_color = "#4CAF50", "rgba(76, 175, 80, 0.1)"
            else: color, bg_color = "#F44336", "rgba(244, 67, 54, 0.1)"
        else: color, bg_color = "#757575", "#F5F5F5"
        widget.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color}; padding: 5px; background-color: {bg_color}; border-radius: 4px;")

    def clear_view(self):
        """当没有数据时，清空面板"""
        self.equity_chart.clear()
        self.distribution_chart.clear()
        for widget in self.metric_widgets.values():
            self.set_metric_style(widget, "-", force_neutral=True)

    def update_view(self, r, df):
        """统一的对外更新接口"""
        # 1. 更新指标文本
        m = self.metric_widgets
        self.set_metric_style(m["net_profit"], f"￥{r['net_profit']:,.2f}", r['net_profit'])
        self.set_metric_style(m["avg_win"], f"￥{r['avg_win']:,.2f}", r['avg_win'])
        self.set_metric_style(m["avg_loss"], f"￥{r['avg_loss']:,.2f}", r['avg_loss'])
        self.set_metric_style(m["max_profit"], f"￥{r['max_profit']:,.2f}", r['max_profit'])
        self.set_metric_style(m["max_loss"], f"￥{r['max_loss']:,.2f}", r['max_loss'])
        self.set_metric_style(m["return_rate"], f"{r['return_rate']*100:.2f}%", r['return_rate'])
        self.set_metric_style(m["win_rate"], f"{r['win_rate']*100:.2f}%", r['win_rate'] - 0.5)
        self.set_metric_style(m["max_drawdown"], f"{r['max_drawdown']*100:.2f}%", r['max_drawdown'], reverse_color=True)
        self.set_metric_style(m["initial_capital"], f"￥{r['initial_capital']:,.2f}", force_neutral=True)
        self.set_metric_style(m["total_commission"], f"￥{r['total_commission']:,.2f}", force_neutral=True)
        self.set_metric_style(m["pl_ratio"], f"{r['pl_ratio']:.2f}", force_neutral=True)
        self.set_metric_style(m["total_trades"], str(r['total_trades']), force_neutral=True)
        self.set_metric_style(m["winning_trades"], str(r['winning_trades']), force_neutral=True)
        self.set_metric_style(m["losing_trades"], str(r['losing_trades']), force_neutral=True)

        # 2. 更新资金曲线
        equity_data = df['equity'].tolist()
        x_data = list(range(len(equity_data)))
        self.equity_chart.clear()
        if equity_data:
            is_prof = equity_data[-1] >= equity_data[0]
            col = (76, 175, 80) if is_prof else (244, 67, 54)
            fill = (76, 175, 80, 50) if is_prof else (244, 67, 54, 50)
            self.equity_chart.plot(x_data, equity_data, pen=pg.mkPen(color=col, width=2.5), fillLevel=equity_data[0], fillBrush=fill)

        # 3. 更新分布图
        profits = df['net_profit'].values
        self.distribution_chart.clear()
        if len(profits) > 0:
            hist, bin_edges = np.histogram(profits, bins=25)
            x_vals, y_vals = [], []
            for i in range(len(bin_edges)-1): 
                x_vals.extend([bin_edges[i], bin_edges[i+1]])
                y_vals.extend([hist[i], hist[i]])
            self.distribution_chart.plot(x_vals, y_vals, pen=pg.mkPen(color=(33, 150, 243), width=2), fillLevel=0, fillBrush=pg.mkBrush((33, 150, 243, 100)))