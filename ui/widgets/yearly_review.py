# ui/widgets/yearly_review.py
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFrame,
                             QGridLayout, QSplitter)
from PyQt6.QtCore import Qt

from config import settings
from ui.widgets.chart_style import apply_pokorny_style, plot_equity_curve


class YearlyReviewPanel(QWidget):
    """
    年度复盘面板 (SRP 拆分自 ReviewView)。

    职责单一：给定某一年全部交易的 DataFrame，渲染
      - 12 个月盈亏强度卡片
      - 策略净额贡献条形图
      - 年度资金净值曲线

    【口径】以上三者一律使用净额 (net_profit − commission)，与复盘页月视图、
    `core/analyzer`、Dashboard 保持完全一致（§5.3-B 净额铁律）。
    内部状态 (month_cards / 图表对象) 全部自持，宿主只负责喂数据。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.month_cards = []
        self._build_ui()

    # ==========================================
    # UI 构建
    # ==========================================
    def _apply_pokorny_style(self, chart: pg.PlotWidget, title: str = ""):
        """委托给 ui/widgets/chart_style.py —— 全 app 图表轴样式唯一来源 (v5.12 · §9-O7)"""
        return apply_pokorny_style(chart, title)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- 上区：月度盈亏卡片 2x6 ----
        cal_card = QFrame()
        cal_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        cal_layout = QVBoxLayout(cal_card)

        cal_title = QLabel("📅 年度各月盈亏概览")
        cal_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #424242; margin-bottom: 5px;")
        cal_layout.addWidget(cal_title)

        card_grid = QGridLayout()
        card_grid.setSpacing(10)
        for i in range(12):
            card = QLabel(f"{i+1}月\n无数据")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setStyleSheet("background: #F5F5F5; border-radius: 6px; font-size: 14px; font-weight:bold; color: #9E9E9E;")
            card.setMinimumSize(80, 80)
            self.month_cards.append(card)
            card_grid.addWidget(card, i // 6, i % 6)

        cal_layout.addLayout(card_grid)
        layout.addWidget(cal_card, 2)

        # ---- 下区：策略贡献 + 资金净值 ----
        charts_splitter = QSplitter(Qt.Orientation.Horizontal)

        bar_card = QFrame()
        bar_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        bar_layout = QVBoxLayout(bar_card)
        self.yearly_bar_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.yearly_bar_chart, title="🏆 年度策略净额贡献度 (已扣手续费)")
        self.yearly_bar_chart.showGrid(x=False, y=False)
        bar_layout.addWidget(self.yearly_bar_chart)
        charts_splitter.addWidget(bar_card)

        curve_card = QFrame()
        curve_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        curve_layout = QVBoxLayout(curve_card)
        self.yearly_curve_chart = pg.PlotWidget()
        self._apply_pokorny_style(self.yearly_curve_chart, title="📈 年度资金净值曲线 (已扣手续费)")
        curve_layout.addWidget(self.yearly_curve_chart)
        charts_splitter.addWidget(curve_card)

        charts_splitter.setSizes([500, 500])
        layout.addWidget(charts_splitter, 5)

    # ==========================================
    # 对外渲染接口
    # ==========================================
    def render(self, df: pd.DataFrame):
        """依据全年已平仓记录刷新月度卡片与全部图表。空 DataFrame 时安全地清空画面。"""
        df = df.copy()  # 【防御】绝不修改宿主传入的 DataFrame

        # 【v5.7 净额口径统一】真实到手 = 平仓盈亏 − 手续费。
        # 修复前本面板三处直接用 net_profit，导致"年视图资金曲线比月视图系统性偏高"
        # （差额恰好等于全年手续费），与 §5.3-B 净额铁律冲突。
        if 'net_amount' not in df.columns:
            profit = df['net_profit'] if 'net_profit' in df.columns else 0.0
            fee = df['commission'].fillna(0) if 'commission' in df.columns else 0.0
            df['net_amount'] = profit - fee

        self._render_month_cards(df)
        self._render_charts(df)

    def _render_month_cards(self, df: pd.DataFrame):
        monthly_stats = {}
        if not df.empty:
            df['month'] = df['trade_time'].dt.month
            monthly_stats = df.groupby('month')['net_amount'].sum().to_dict()

        for i in range(12):
            m = i + 1
            card = self.month_cards[i]
            if m not in monthly_stats:
                card.setStyleSheet("background: #F5F5F5; border-radius: 6px; font-size: 14px; font-weight:bold; color: #9E9E9E;")
                card.setText(f"{m}月\n无交易")
                continue

            net = monthly_stats[m]
            if net > 0:
                card.setStyleSheet(f"background: #E8F5E9; border-radius: 6px; font-size: 16px; font-weight:bold; color: {settings.COLOR_PROFIT_TEXT};")
                card.setText(f"{m}月\n+{net:,.0f}")
            else:
                card.setStyleSheet(f"background: #FFEBEE; border-radius: 6px; font-size: 16px; font-weight:bold; color: {settings.COLOR_LOSS_TEXT};")
                card.setText(f"{m}月\n{net:,.0f}")

    def _render_charts(self, df: pd.DataFrame):
        self.yearly_bar_chart.clear()
        self.yearly_curve_chart.clear()
        if df.empty:
            return

        df_sorted = df.sort_values(by='trade_time')
        equity_curve = [0.0] + df_sorted['net_amount'].cumsum().tolist()
        # 年度资金净值曲线：统一走 chart_style (v5.12 · §9-O7)，基准线 0
        plot_equity_curve(self.yearly_curve_chart, equity_curve, fill_base=0.0, width=3)

        strategy_pnl = df.groupby('strategy_tag')['net_amount'].sum().sort_values()
        if strategy_pnl.empty:
            return

        y_pos = list(range(len(strategy_pnl)))
        x_vals = strategy_pnl.values.tolist()
        brushes = [pg.mkBrush(settings.COLOR_PROFIT) if x > 0 else pg.mkBrush(settings.COLOR_LOSS) for x in x_vals]
        pens = [pg.mkPen(settings.COLOR_PROFIT) if x > 0 else pg.mkPen(settings.COLOR_LOSS) for x in x_vals]
        bar_item = pg.BarGraphItem(x0=0, y=y_pos, width=x_vals, height=0.5, brushes=brushes, pens=pens)
        self.yearly_bar_chart.addItem(bar_item)

        axis = self.yearly_bar_chart.getAxis('left')
        axis.setTicks([list(zip(y_pos, strategy_pnl.index.tolist()))])
        self.yearly_bar_chart.addLine(x=0, pen=pg.mkPen(color='#9E9E9E'))
