import sys
import random
import pandas as pd
from datetime import datetime, timedelta
import pyqtgraph as pg
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QLabel, QFrame, QStackedWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
                             QGridLayout, QGroupBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPalette
import numpy as np  # 需要导入numpy用于直方图计算

# ==========================================
# 1. 模拟数据生成器 (故意制造极端数据)
# ==========================================
def generate_extreme_mock_data(num_trades=1000):
    trades = []
    current_time = datetime(2023, 1, 1, 9, 0)
    symbols = ['黄金2310', '螺纹钢2401', '纯碱2405', '原油2403']

    for i in range(num_trades):
        # 制造随机的时间跨度
        current_time += timedelta(hours=random.randint(1, 24), minutes=random.randint(0, 60))
        exit_time = current_time + timedelta(hours=random.randint(1, 4))

        # 核心：制造极端数据！90%普通震荡，10%极端单边行情
        if random.random() < 0.1:
            # 极端黑天鹅：要么暴富，要么爆仓（测试资金曲线的剧烈波动）
            net_profit = random.choice([random.uniform(-80000, -30000), random.uniform(50000, 150000)])
        else:
            # 普通交易：胜率故意调低一点，模拟真实的频繁止损 (亏多赚少，但亏损额度小)
            if random.random() < 0.35: # 35% 胜率
                net_profit = random.uniform(1000, 8000)
            else:
                net_profit = random.uniform(-4000, -500)

        trade = {
            "trade_id": f"T{i:04d}",
            "trader_name": "我",
            "entry_time": current_time,
            "exit_time": exit_time,
            "symbol": random.choice(symbols),
            "direction": random.choice(['LONG', 'SHORT']),
            "lots": random.randint(1, 10),
            "entry_price": 0.0, 
            "exit_price": 0.0,
            "commission": random.uniform(10, 50),
            "slippage": random.uniform(0, 20),
            "net_profit": net_profit,
            "strategy_tag": "随机压力测试"
        }
        trades.append(trade)
        current_time = exit_time 
    
    return pd.DataFrame(trades)

# ==========================================
# 2. 我们之前写的分析大脑 (核心 Controller)
# ==========================================
class TradeAnalyzer:
    def __init__(self, df: pd.DataFrame, initial_capital: float = 1000000):
        self.df = df
        self.initial_capital = initial_capital
        self.df = self.df.sort_values(by='exit_time').reset_index(drop=True)
        # 提前算好资金曲线数据，供图表调用
        self.df['equity'] = self.initial_capital + self.df['net_profit'].cumsum()

    def generate_report(self):
        df = self.df
        winning_trades = df[df['net_profit'] > 0]
        losing_trades = df[df['net_profit'] <= 0] 
        
        # 保护机制：防止除以 0 导致崩溃 (这就是应对极端数据的防守)
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        total_count = len(df)
        win_rate = win_count / total_count if total_count > 0 else 0
        
        total_win_amount = winning_trades['net_profit'].sum()
        total_loss_amount = losing_trades['net_profit'].sum()
        avg_win = total_win_amount / win_count if win_count > 0 else 0
        avg_loss = total_loss_amount / loss_count if loss_count > 0 else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        df['peak'] = df['equity'].cummax()
        df['drawdown_pct'] = (df['peak'] - df['equity']) / df['peak']
        max_drawdown = df['drawdown_pct'].max()
        
        # 组装返回字典 (24个指标)
        return {
            "初始资金": f"￥{self.initial_capital:,.2f}", "收益率": f"{(df['equity'].iloc[-1]-self.initial_capital)/self.initial_capital * 100:.2f}%",
            "净利润": f"￥{df['net_profit'].sum():,.2f}", "总手续费": f"￥{df['commission'].sum():,.2f}",
            "平仓盈亏": f"￥{(df['net_profit'].sum() + df['commission'].sum() + df['slippage'].sum()):,.2f}", "总手数": df['lots'].sum(),
            "盈利手数": winning_trades['lots'].sum(), "亏损手数": losing_trades['lots'].sum(),
            "交易次数": total_count, "盈利次数": win_count,
            "亏损次数": loss_count, "胜率": f"{win_rate * 100:.2f}%",
            "盈亏比": f"{pl_ratio:.2f}", "盈利金额": f"￥{total_win_amount:,.2f}",
            "亏损金额": f"￥{total_loss_amount:,.2f}", "平均盈利": f"￥{avg_win:,.2f}",
            "平均亏损": f"￥{avg_loss:,.2f}", "最大单笔赚": f"￥{df['net_profit'].max():,.2f}",
            "最大单笔亏": f"￥{df['net_profit'].min():,.2f}", "最大回撤": f"{max_drawdown * 100:.2f}%"
        }

# ==========================================
# 3. Michael Pokorny 风格 UI 界面及数据绑定
# ==========================================
pg.setConfigOption('background', '#FFFFFF') 
pg.setConfigOption('foreground', '#000000') 
pg.setConfigOptions(antialias=True)

class TradingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("交易分析仪表板 - Michael Pokorny风格")
        self.resize(1400, 900) 
        self.setStyleSheet("""
            QMainWindow { 
                background-color: #FAFAFA;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #E0E0E0;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #424242;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧：关键指标面板
        left_panel = self.create_metrics_panel()
        
        # 右侧：图表区域
        right_panel = self.create_charts_panel()
        
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 2)
        
        # 启动模拟
        self.run_simulation()

    def create_metrics_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("交易绩效摘要")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #212121;
                padding: 10px;
                border-bottom: 2px solid #E0E0E0;
            }
        """)
        layout.addWidget(title_label)
        
        # 创建指标网格
        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(10)
        metrics_grid.setContentsMargins(10, 10, 10, 10)
        
        # 定义指标布局
        metrics_layout = [
            ("净利润", "net_profit"),
            ("收益率", "return_rate"),
            ("胜率", "win_rate"),
            ("盈亏比", "profit_loss_ratio"),
            ("最大回撤", "max_drawdown"),
            ("总交易次数", "total_trades"),
            ("盈利次数", "winning_trades"),
            ("亏损次数", "losing_trades"),
            ("初始资金", "initial_capital"),
            ("平均盈利", "avg_profit"),
            ("平均亏损", "avg_loss"),
            ("最大单笔盈利", "max_profit"),
            ("最大单笔亏损", "max_loss"),
            ("总手续费", "total_commission"),
            ("盈利手数", "winning_lots"),
            ("亏损手数", "losing_lots")
        ]
        
        self.metric_widgets = {}
        for i, (label_text, metric_key) in enumerate(metrics_layout):
            row = i // 2
            col = (i % 2) * 2  # 0 or 2
            
            label = QLabel(label_text)
            label.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    color: #757575;
                    font-weight: normal;
                }
            """)
            
            value_label = QLabel("待计算...")
            value_label.setObjectName(f"value_{metric_key}")  # 用于后续更新
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #212121;
                    padding: 5px;
                    background-color: #F5F5F5;
                    border-radius: 4px;
                }
            """)
            
            metrics_grid.addWidget(label, row, col)
            metrics_grid.addWidget(value_label, row, col + 1)
            self.metric_widgets[metric_key] = value_label
        
        layout.addLayout(metrics_grid)
        
        # 添加一些空白空间
        layout.addStretch()
        
        return panel

    def create_charts_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # 资金曲线图表
        self.equity_chart = pg.PlotWidget(title="资金曲线分析")
        self.equity_chart.showGrid(x=True, y=True, alpha=0.3)
        self.equity_chart.setLabel('left', '资金价值')
        self.equity_chart.setLabel('bottom', '交易序号')
        
        # 交易分布图表
        self.distribution_chart = pg.PlotWidget(title="盈亏分布直方图")
        self.distribution_chart.showGrid(x=True, y=True, alpha=0.3)
        self.distribution_chart.setLabel('left', '频次')
        self.distribution_chart.setLabel('bottom', '盈亏金额区间')
        
        layout.addWidget(self.equity_chart, 2)
        layout.addWidget(self.distribution_chart, 1)
        
        return panel

    def run_simulation(self):
        mock_df = generate_extreme_mock_data(1000)
        analyzer = TradeAnalyzer(mock_df)
        report = analyzer.generate_report()
        
        # 更新指标面板
        self.update_metrics(report)
        
        # 更新图表
        self.update_equity_chart(analyzer.df)
        self.update_distribution_chart(analyzer.df)

    def update_metrics(self, report):
        """更新指标面板，只对数值进行颜色编码"""
        # 净利润
        net_profit_value = float(report["净利润"].replace("￥", "").replace(",", ""))
        self.metric_widgets["net_profit"].setText(str(report["净利润"]))
        if net_profit_value >= 0:
            self.metric_widgets["net_profit"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            self.metric_widgets["net_profit"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #F44336;
                    padding: 5px;
                    background-color: rgba(244, 67, 54, 0.1);
                    border-radius: 4px;
                }
            """)

        # 收益率
        return_rate_value = float(report["收益率"].replace("%", ""))
        self.metric_widgets["return_rate"].setText(str(report["收益率"]))
        if return_rate_value >= 0:
            self.metric_widgets["return_rate"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            self.metric_widgets["return_rate"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #F44336;
                    padding: 5px;
                    background-color: rgba(244, 67, 54, 0.1);
                    border-radius: 4px;
                }
            """)

        # 胜率
        win_rate_value = float(report["胜率"].replace("%", ""))
        self.metric_widgets["win_rate"].setText(str(report["胜率"]))
        if win_rate_value >= 50:
            self.metric_widgets["win_rate"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            self.metric_widgets["win_rate"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #FF9800;
                    padding: 5px;
                    background-color: rgba(255, 152, 0, 0.1);
                    border-radius: 4px;
                }
            """)

        # 盈亏比
        pl_ratio_value = float(report["盈亏比"])
        self.metric_widgets["profit_loss_ratio"].setText(str(report["盈亏比"]))
        if pl_ratio_value >= 1:
            self.metric_widgets["profit_loss_ratio"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            self.metric_widgets["profit_loss_ratio"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #FF9800;
                    padding: 5px;
                    background-color: rgba(255, 152, 0, 0.1);
                    border-radius: 4px;
                }
            """)

        # 最大回撤
        max_drawdown_value = float(report["最大回撤"].replace("%", ""))
        self.metric_widgets["max_drawdown"].setText(str(report["最大回撤"]))
        if max_drawdown_value <= 10:
            self.metric_widgets["max_drawdown"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            self.metric_widgets["max_drawdown"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #F44336;
                    padding: 5px;
                    background-color: rgba(244, 67, 54, 0.1);
                    border-radius: 4px;
                }
            """)

        # 平均盈利
        avg_profit_str = report["平均盈利"]
        avg_profit_value = float(avg_profit_str.replace("￥", "").replace(",", ""))
        self.metric_widgets["avg_profit"].setText(str(avg_profit_str))
        if avg_profit_value >= 0:
            self.metric_widgets["avg_profit"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            self.metric_widgets["avg_profit"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #F44336;
                    padding: 5px;
                    background-color: rgba(244, 67, 54, 0.1);
                    border-radius: 4px;
                }
            """)

        # 平均亏损
        avg_loss_str = report["平均亏损"]
        avg_loss_value = float(avg_loss_str.replace("￥", "").replace(",", ""))
        self.metric_widgets["avg_loss"].setText(str(avg_loss_str))
        if avg_loss_value >= 0:  # 注意：平均亏损通常是负数，如果变成正数说明有问题
            self.metric_widgets["avg_loss"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:  # 正常情况，平均亏损是负数，显示红色
            self.metric_widgets["avg_loss"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #F44336;
                    padding: 5px;
                    background-color: rgba(244, 67, 54, 0.1);
                    border-radius: 4px;
                }
            """)

        # 最大单笔盈利
        max_profit_str = report["最大单笔赚"]
        max_profit_value = float(max_profit_str.replace("￥", "").replace(",", ""))
        self.metric_widgets["max_profit"].setText(str(max_profit_str))
        if max_profit_value >= 0:
            self.metric_widgets["max_profit"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:
            self.metric_widgets["max_profit"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #F44336;
                    padding: 5px;
                    background-color: rgba(244, 67, 54, 0.1);
                    border-radius: 4px;
                }
            """)

        # 最大单笔亏损
        max_loss_str = report["最大单笔亏"]
        max_loss_value = float(max_loss_str.replace("￥", "").replace(",", ""))
        self.metric_widgets["max_loss"].setText(str(max_loss_str))
        if max_loss_value >= 0:  # 正常情况，最大单笔亏损是负数，如果是正数说明有问题
            self.metric_widgets["max_loss"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #4CAF50;
                    padding: 5px;
                    background-color: rgba(76, 175, 80, 0.1);
                    border-radius: 4px;
                }
            """)
        else:  # 正常情况，最大单笔亏损是负数，显示红色
            self.metric_widgets["max_loss"].setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-weight: bold;
                    color: #F44336;
                    padding: 5px;
                    background-color: rgba(244, 67, 54, 0.1);
                    border-radius: 4px;
                }
            """)

        # 其他指标保持默认样式，确保转换为字符串
        self.metric_widgets["total_trades"].setText(str(report["交易次数"]))
        self.metric_widgets["winning_trades"].setText(str(report["盈利次数"]))
        self.metric_widgets["losing_trades"].setText(str(report["亏损次数"]))
        self.metric_widgets["initial_capital"].setText(str(report["初始资金"]))
        self.metric_widgets["total_commission"].setText(str(report["总手续费"]))
        self.metric_widgets["winning_lots"].setText(str(report["盈利手数"]))
        self.metric_widgets["losing_lots"].setText(str(report["亏损手数"]))

    def update_equity_chart(self, df):
        """更新资金曲线图表"""
        equity_data = df['equity'].tolist()
        x_data = list(range(len(equity_data)))
        
        # 清空现有图形
        self.equity_chart.clear()
        
        # 设置颜色
        if equity_data[-1] >= equity_data[0]:
            color = (0, 150, 136)  # 青绿色
            fill_color = (0, 150, 136, 50)
        else:
            color = (244, 67, 54)  # 红色
            fill_color = (244, 67, 54, 50)
        
        pen = pg.mkPen(color=color, width=2.5) 
        self.equity_chart.plot(x_data, equity_data, pen=pen, fillLevel=equity_data[0], fillBrush=fill_color)
        
        # 添加起始和结束标记
        self.equity_chart.plot([0], [equity_data[0]], pen=None, symbol='o', symbolSize=8, symbolBrush=(0, 150, 136))
        self.equity_chart.plot([len(equity_data)-1], [equity_data[-1]], pen=None, symbol='o', symbolSize=8, symbolBrush=(244, 67, 54))

    def update_distribution_chart(self, df):
        """更新盈亏分布直方图"""
        profits = df['net_profit'].values
        
        # 清空现有图形
        self.distribution_chart.clear()
        
        # 创建直方图
        if len(profits) > 0:
            hist, bin_edges = np.histogram(profits, bins=50)
            
            # 使用阶梯图绘制直方图
            x_vals = []
            y_vals = []
            for i in range(len(bin_edges)-1):
                x_vals.extend([bin_edges[i], bin_edges[i+1]])
                y_vals.extend([hist[i], hist[i]])
            
            pen = pg.mkPen(color=(33, 150, 243), width=2)
            brush = pg.mkBrush((33, 150, 243, 100))
            self.distribution_chart.plot(x_vals, y_vals, pen=pen, fillLevel=0, fillBrush=brush)
        
        self.distribution_chart.setTitle("盈亏分布直方图")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TradingApp()
    window.show()
    sys.exit(app.exec())