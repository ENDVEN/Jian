# ui/views/backtest_module.py
"""
📐 市场回测 —— 模块容器（三个子页全部上线）：

  · 📈 单股回测   M1: 已实现 (SingleStockBacktestView)
  · 🌐 全市场筛选 M2: 已实现 (ScanView · §7-B1/B2 STEP 4：某日全市场横截面选股)
  · 📊 广度统计   M3: 已实现 (BreadthView · §7-B1/B2 STEP 5：逐日广度折线 + 指数副图联动)

容器只负责顶部子页导航与页面切换，具体逻辑均在各子页内实现。
"""
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ui.views.backtest import SingleStockBacktestView
from ui.views.backtest_history import BacktestHistoryView
from ui.views.breadth_view import BreadthView
from ui.views.scan_view import ScanView

_TAB_QSS = """
QTabWidget::pane { border: none; background: transparent; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: #8A94A6; font-size: 14px;
               font-weight: bold; padding: 10px 22px; border: none;
               border-bottom: 2px solid transparent; margin-right: 4px; }
QTabBar::tab:hover { color: #1976D2; }
QTabBar::tab:selected { color: #1976D2; border-bottom: 2px solid #1976D2; }
"""


class BacktestModule(QWidget):
    """市场回测模块：顶部子页切换 + 当前子页"""

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win

        self.single_view = SingleStockBacktestView(main_win)
        # ★§7-B1/B2 STEP 4（v6.37）：M2 从 `_ComingSoonPage` 占位换成真页面。
        #   版式 / 行为 / 渲染分居 `ui/widgets/scan_layout.py` / `scan_flow.py` / `scan_result.py`
        #   （"状态留页面、行为搬模块 + 同名薄壳"，与 1.22/1.23/1.26 同款）。
        self.page_scan = ScanView(main_win)
        # ★§7-B1/B2 STEP 5（1.29）：M3 从 `_ComingSoonPage` 占位换成真页面（占位类就此退役）。
        #   版式 / 流程 / 空态 / 图表分居 `breadth_layout` / `breadth_flow` / `breadth_result`
        #   / `breadth_chart`；与 M2 共用同一个内核 + 会话缓存（一个引擎两种视图，C 节）。
        self.page_breadth = BreadthView(main_win)
        # ★§7-A4（v1.37）：运行历史子页——历次回测的不可变快照列表 + 预览（载入/复用/重跑）。
        self.page_history = BacktestHistoryView(main_win)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 6, 0)
        layout.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(_TAB_QSS)
        self.tabs.addTab(self.single_view, "📈 单股回测")
        self.tabs.addTab(self.page_scan, "🌐 全市场筛选")
        self.tabs.addTab(self.page_breadth, "📊 广度统计")
        self.tabs.addTab(self.page_history, "🗂 运行历史")
        layout.addWidget(self.tabs, 1)

    # 供测试/其它模块快速访问单股页
    @property
    def backtest_single(self):
        return self.single_view
