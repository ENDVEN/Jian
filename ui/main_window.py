# ui/main_window.py
import pandas as pd
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QFrame, QStackedWidget,
                             QDialog, QMessageBox)

# ========= 核心模块 =========
from core.analyzer import TradeAnalyzer
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
    只负责核心数据的持有、视图模块的调度以及全局弹窗的触发。
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jian - 专业交易复盘系统")
        self.resize(1500, 950) 
        self.setStyleSheet("""
            QMainWindow { background-color: #FAFAFA; font-family: -apple-system, sans-serif; }
            QFrame#Sidebar { background-color: #FFFFFF; border-right: 1px solid #E0E0E0; }
            QPushButton.NavBtn { background-color: transparent; color: #424242; text-align: left; padding: 15px 20px; border-radius: 8px; font-size: 15px; font-weight: bold; border: none; margin: 2px 10px;}
            QPushButton.NavBtn:hover { background-color: #F5F5F5; }
            QPushButton.NavBtn:checked { background-color: #E3F2FD; color: #1976D2; }
        """)
        
        # 【应用级全局状态数据中心】
        self.global_df = pd.DataFrame() 
        self.global_strategies = ["未分类"] 

        # 构建主布局骨架
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 左侧导航栏
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
        
        # 右侧内容区（栈管理器）
        self.content_area = QStackedWidget()
        self.content_area.setContentsMargins(20, 20, 20, 20)
        
        # 实例化页面组件 (将 main_win 实例传入，允许组件访问数据和方法)
        self.page_overview = DashboardView(self)
        self.page_records = RecordsView(self)
        self.page_review = ReviewView(self) 
        
        self.content_area.addWidget(self.page_overview)
        self.content_area.addWidget(self.page_records)
        self.content_area.addWidget(self.page_review) 
        
        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.content_area)
        
        # 绑定导航切换事件
        self.btn_overview.clicked.connect(lambda: self.content_area.setCurrentIndex(0))
        self.btn_records.clicked.connect(lambda: self.content_area.setCurrentIndex(1))
        self.btn_review.clicked.connect(lambda: self.content_area.setCurrentIndex(2))
        
        # 注入假数据测试 (未来接入真实数据库后可删除此处)
        try:
            self.global_df = generate_extreme_mock_data(50)
            self.global_strategies += self.global_df['strategy_tag'].unique().tolist()
        except: pass
        
        # 启动时执行第一次全量数据渲染
        self.render_all_data()

    def render_all_data(self):
        """
        核心数据流驱动中心：
        只要 global_df 发生改变，就调用这个方法刷新所有视图
        """
        if self.global_df.empty: 
            self.page_overview.clear_view()
            self.page_records.clear_view()
            self.page_review.refresh_review_filters()
            return

        analyzer = TradeAnalyzer(self.global_df)
        raw_report = analyzer.generate_raw_report()
        
        if raw_report:
            # 优雅地通知各个子组件更新它们自己的界面
            self.page_overview.update_view(raw_report, analyzer.df)
            self.page_records.populate_table(analyzer.df)
            self.page_review.refresh_review_filters()
            self.page_review.update_review_view()

    # ==========================================
    # 全局弹窗控制器逻辑 (修改数据并触发 render_all_data)
    # ==========================================
    def open_import_wizard(self):
        dialog = ImportWizardDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.final_df is not None:
            if self.global_df.empty: self.global_df = dialog.final_df
            else: self.global_df = pd.concat([self.global_df, dialog.final_df], ignore_index=True)
            for st in dialog.final_df['strategy_tag'].dropna().unique():
                if st not in self.global_strategies: self.global_strategies.append(st)
            self.render_all_data()

    def open_manual_entry(self):
        dialog = ManualEntryDialog(self.global_strategies, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.new_trade_data is not None:
            if self.global_df.empty: self.global_df = dialog.new_trade_data
            else: self.global_df = pd.concat([self.global_df, dialog.new_trade_data], ignore_index=True)
            new_st = dialog.new_trade_data.iloc[0]['strategy_tag']
            if new_st not in self.global_strategies: self.global_strategies.append(new_st)
            self.render_all_data()

    def manage_accounts(self):
        if self.global_df.empty: return
        accounts = self.global_df['account'].dropna().unique().tolist()
        dialog = ListManagerDialog("管理账户", accounts, self._delete_account_action, self); dialog.exec()

    def _delete_account_action(self, acc_name):
        reply = QMessageBox.question(self, "危险", f"确定清空【{acc_name}】？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.global_df = self.global_df[self.global_df['account'] != acc_name].reset_index(drop=True)
            self.render_all_data(); return True
        return False

    def manage_strategies(self):
        strats = [s for s in self.global_strategies if s != "未分类"]
        if not strats: return
        dialog = ListManagerDialog("管理策略", strats, self._delete_strategy_action, self); dialog.exec()

    def _delete_strategy_action(self, st_name):
        reply = QMessageBox.question(self, "删除", f"确定删除策略【{st_name}】？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.global_df.loc[self.global_df['strategy_tag'] == st_name, 'strategy_tag'] = "未分类"
            if st_name in self.global_strategies: self.global_strategies.remove(st_name)
            self.render_all_data(); return True
        return False