# ui/main_window.py
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QFrame, QStackedWidget,
                             QDialog, QMessageBox, QFileDialog)

from config import settings
from core.analyzer import TradeAnalyzer
from core.engine import DataEngine

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
            self.page_records.populate_table(analyzer.df)
            self.page_review.refresh_review_filters()
            self.page_review.update_review_view()

    # ==========================================
    # 全局弹窗与数据导出控制器
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
            
    def export_data(self):
        """【新增】一键导出全量业务数据"""
        if self.engine.df.empty:
            QMessageBox.warning(self, "提示", "当前没有任何数据可以导出！")
            return

        # 默认生成带时间戳的文件名
        default_name = f"Jian_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(self, "导出数据备份", default_name, "CSV 数据表 (*.csv)")
        
        if file_path:
            try:
                export_df = self.engine.df.copy()
                
                # 剔除底层的 internal_id，防止用户看了迷惑
                if 'internal_id' in export_df.columns:
                    export_df = export_df.drop(columns=['internal_id'])
                
                # 重新排列顺眼的列名顺序
                cols_order = ['trade_id', 'account', 'symbol', 'direction', 'entry_time', 'exit_time', 
                              'lots', 'net_profit', 'commission', 'strategy_tag', 'entry_reason', 'reflection', 'screenshot_paths']
                export_cols = [c for c in cols_order if c in export_df.columns]
                export_df = export_df[export_cols]
                
                # 使用 utf-8-sig 编码保存，在 Windows 下用 Excel 打开绝不乱码
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