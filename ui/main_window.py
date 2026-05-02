# ui/main_window.py
import pandas as pd
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QFrame, QStackedWidget,
                             QDialog, QMessageBox)

# 引入全局配置
from config import settings

# ========= 核心模块 =========
from core.analyzer import TradeAnalyzer
from core.engine import DataEngine
from data.data_feed import generate_extreme_mock_data

# ========= 弹窗控制器 =========
from ui.dialogs.dialogs import ListManagerDialog, ImportWizardDialog, ManualEntryDialog

# ========= 页面视图组件 =========
from ui.views.dashboard import DashboardView
from ui.views.records import RecordsView
from ui.views.review import ReviewView

class JianMainWindow(QMainWindow):
    """
    Jian 主窗口控制器。
    """
    def __init__(self):
        super().__init__()
        
        # 【核心进化】：使用配置中心参数
        self.setWindowTitle(settings.APP_NAME)
        self.resize(settings.MAIN_WINDOW_WIDTH, settings.MAIN_WINDOW_HEIGHT) 
        
        self.setStyleSheet("""
            QMainWindow { background-color: #FAFAFA; font-family: -apple-system, sans-serif; }
            QFrame#Sidebar { background-color: #FFFFFF; border-right: 1px solid #E0E0E0; }
            QPushButton.NavBtn { background-color: transparent; color: #424242; text-align: left; padding: 15px 20px; border-radius: 8px; font-size: 15px; font-weight: bold; border: none; margin: 2px 10px;}
            QPushButton.NavBtn:hover { background-color: #F5F5F5; }
            QPushButton.NavBtn:checked { background-color: #E3F2FD; color: #1976D2; }
        """)
        
        self.engine = DataEngine()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        
        self.btn_overview = QPushButton("📊 资金与表现")
        self.btn_records = QPushButton("📝 交易流水")
        self.btn_review = QPushButton("💡 深度复盘")
        
        for btn in [self.btn_overview, self.btn_records, self.btn_review]:
            btn.setProperty("class", "NavBtn")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            sidebar_layout.addWidget(btn)
        self.btn_overview.setChecked(True)
        sidebar_layout.addStretch()
        
        self.content_area = QStackedWidget()
        self.content_area.setContentsMargins(20, 20, 20, 20)
        
        self.page_overview = DashboardView(self)
        self.page_records = RecordsView(self)
        self.page_review = ReviewView(self) 
        
        self.content_area.addWidget(self.page_overview)
        self.content_area.addWidget(self.page_records)
        self.content_area.addWidget(self.page_review) 
        
        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.content_area)
        
        self.btn_overview.clicked.connect(lambda: self.content_area.setCurrentIndex(0))
        self.btn_records.clicked.connect(lambda: self.content_area.setCurrentIndex(1))
        self.btn_review.clicked.connect(lambda: self.content_area.setCurrentIndex(2))
        
        self.engine.load_initial_mock(generate_extreme_mock_data)
        self.render_all_data()

    def render_all_data(self):
        """核心数据流驱动中心"""
        if self.engine.df.empty: 
            self.page_overview.clear_view()
            self.page_records.clear_view()
            self.page_review.refresh_review_filters()
            return

        analyzer = TradeAnalyzer(self.engine.df)
        raw_report = analyzer.generate_raw_report()
        
        if raw_report:
            self.page_overview.update_view(raw_report, analyzer.df)
            self.page_records.populate_table(analyzer.df)
            self.page_review.refresh_review_filters()
            self.page_review.update_review_view()

    # ==========================================
    # 全局弹窗控制器
    # ==========================================
    def open_import_wizard(self):
        dialog = ImportWizardDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and getattr(dialog, 'final_trades', None):
            self.engine.add_trades(dialog.final_trades)
            self.render_all_data()

    def open_manual_entry(self):
        dialog = ManualEntryDialog(self.engine.strategies, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and getattr(dialog, 'new_trades', None):
            self.engine.add_trades(dialog.new_trades)
            self.render_all_data()

    def manage_accounts(self):
        if self.engine.df.empty: return
        accounts = self.engine.df['account'].dropna().unique().tolist()
        dialog = ListManagerDialog("管理账户", accounts, self._delete_account_action, self)
        dialog.exec()

    def _delete_account_action(self, acc_name):
        reply = QMessageBox.question(self, "危险", f"确定清空【{acc_name}】？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.engine.clear_account(acc_name):
                self.render_all_data()
            return True
        return False

    def manage_strategies(self):
        strats = [s for s in self.engine.strategies if s != settings.DEFAULT_STRATEGY]
        if not strats: return
        dialog = ListManagerDialog("管理策略", strats, self._delete_strategy_action, self)
        dialog.exec()

    def _delete_strategy_action(self, st_name):
        reply = QMessageBox.question(self, "删除", f"确定删除策略【{st_name}】？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self.engine.delete_strategy(st_name):
                self.render_all_data()
            return True
        return False