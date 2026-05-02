# ui/main_window.py
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QFrame, QStackedWidget,
                             QDialog, QMessageBox, QFileDialog)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl

from config import settings
from core.analyzer import TradeAnalyzer
from core.engine import DataEngine
from core.updater import UpdateCheckerThread  # 【引入异步侦察兵】

from ui.dialogs.dialogs import ListManagerDialog, ImportWizardDialog, ManualEntryDialog
from ui.views.dashboard import DashboardView
from ui.views.records import RecordsView
from ui.views.review import ReviewView

class JianMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
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
        
        self.render_all_data()
        
        # 【新增】软件启动后，静默触发云端更新检测
        self.check_for_updates()

    # ==========================================
    # 版本更新检测模块
    # ==========================================
    def check_for_updates(self):
        """启动后台线程检测更新，防止主界面卡顿"""
        self.updater_thread = UpdateCheckerThread()
        # 信号接通：一旦侦察兵发现新版本，立刻调用 show_update_dialog
        self.updater_thread.update_available.connect(self.show_update_dialog)
        self.updater_thread.start()

    def show_update_dialog(self, version: str, notes: str, download_url: str):
        """弹出优美的更新提示框"""
        msg = f"当前版本: {settings.APP_VERSION}\n最新版本: {version}\n\n更新说明:\n{notes}\n\n是否立即前往浏览器下载新版本？"
        reply = QMessageBox.question(
            self, 
            "✨ 发现新版本", 
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes and download_url:
            # 调用操作系统的默认浏览器打开下载链接
            QDesktopServices.openUrl(QUrl(download_url))

    # ==========================================
    # 数据流与弹窗控制器 (保持不变)
    # ==========================================
    def render_all_data(self):
        if self.engine.df.empty: 
            self.page_overview.clear_view()
            self.page_records.clear_view()
            self.page_review.refresh_review_filters()
            return

        analyzer = TradeAnalyzer(self.engine.df)
        raw_report = analyzer.generate_raw_report()
        
        if raw_report:
            self.page_overview.update_view(raw_report, analyzer.df)
            
            # 【核心修改点】这里不再是无脑塞数据，而是让流水页面去刷新它自己的高级过滤器！
            self.page_records.refresh_records_filters()
            
            self.page_review.refresh_review_filters()
            self.page_review.update_review_view()

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
            
    def export_data(self):
        if self.engine.df.empty:
            QMessageBox.warning(self, "提示", "当前没有任何数据可以导出！")
            return

        default_name = f"Jian_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(self, "导出数据备份", default_name, "CSV 数据表 (*.csv)")
        
        if file_path:
            try:
                export_df = self.engine.df.copy()
                if 'internal_id' in export_df.columns:
                    export_df = export_df.drop(columns=['internal_id'])
                
                cols_order = ['trade_id', 'account', 'symbol', 'direction', 'entry_time', 'exit_time', 
                              'lots', 'net_profit', 'commission', 'strategy_tag', 'entry_reason', 'reflection', 'screenshot_paths']
                export_cols = [c for c in cols_order if c in export_df.columns]
                export_df = export_df[export_cols]
                
                export_df.to_csv(file_path, index=False, encoding='utf-8-sig')
                QMessageBox.information(self, "导出成功", f"恭喜！所有复盘数据已成功导出至：\n\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"文件保存时发生错误：\n{str(e)}")

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