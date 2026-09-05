# ui/views/backtest_module.py
"""
📐 市场回测 —— 模块容器 (预留三个子页，分步上线)：

  · 📈 单股回测   M1: 已实现 (SingleStockBacktestView)
  · 🌐 全市场筛选 M2: 预留 (某日全市场横截面选股)
  · 📊 广度统计   M3: 预留 (逐日符合条件家数折线 + 指数/板块叠加)

容器只负责顶部子页导航与页面切换，具体逻辑均在各子页内实现。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QLabel,
                             QFrame, QHBoxLayout)

from ui.views.backtest import SingleStockBacktestView

_TAB_QSS = """
QTabWidget::pane { border: none; background: transparent; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: #8A94A6; font-size: 14px;
               font-weight: bold; padding: 10px 22px; border: none;
               border-bottom: 2px solid transparent; margin-right: 4px; }
QTabBar::tab:hover { color: #1976D2; }
QTabBar::tab:selected { color: #1976D2; border-bottom: 2px solid #1976D2; }
"""


class _ComingSoonPage(QWidget):
    """M2 / M3 预留子页：空态占位，清晰告知即将上线的能力"""

    def __init__(self, icon: str, title: str, description: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 48, 40, 40)
        layout.setSpacing(14)

        head = QFrame()
        head.setStyleSheet("QFrame { background: white; border: 1px solid #E7EAF0; border-radius: 16px; }")
        head_lay = QVBoxLayout(head)
        head_lay.setContentsMargins(36, 34, 36, 34)
        head_lay.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size: 46px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head_lay.addWidget(icon_lbl)

        name_lbl = QLabel(title)
        name_lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #1F2430;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head_lay.addWidget(name_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setStyleSheet("font-size: 13px; color: #8A94A6;")
        desc_lbl.setWordWrap(True)
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head_lay.addWidget(desc_lbl)

        status = QLabel("该子页为预留模块 · 功能将分步迭代上线")
        status.setStyleSheet("font-size: 12px; color: #B4BECB;")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head_lay.addWidget(status)

        layout.addWidget(head)
        layout.addStretch()


class BacktestModule(QWidget):
    """市场回测模块：顶部子页切换 + 当前子页"""

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win

        self.single_view = SingleStockBacktestView(main_win)
        self.page_scan = _ComingSoonPage(
            "🌐",
            "全市场筛选 (M2)",
            "选某一天，让整段函数跑遍全市场，筛出符合自研条件的股票列表。\n"
            "能力规划：函数复用 · 并发求值 · 结果排序/导出/查看K线。",
        )
        self.page_breadth = _ComingSoonPage(
            "📊",
            "广度统计 (M3)",
            "逐日统计全市场符合函数条件的股票家数，形成折线并叠加指数/板块涨跌幅。\n"
            "能力规划：数据湖预下载 · 增量计算 · 双轴对比。",
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 6, 0)
        layout.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(_TAB_QSS)
        self.tabs.addTab(self.single_view, "📈 单股回测")
        self.tabs.addTab(self.page_scan, "🌐 全市场筛选")
        self.tabs.addTab(self.page_breadth, "📊 广度统计")
        layout.addWidget(self.tabs, 1)

    # 供测试/其它模块快速访问单股页
    @property
    def backtest_single(self):
        return self.single_view
