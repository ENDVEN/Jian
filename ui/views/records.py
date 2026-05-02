# ui/views/records.py
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QTabWidget, QTableWidget, QTableWidgetItem, 
                             QHeaderView)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from config import settings

class RecordsView(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        top_bar = QHBoxLayout()
        title = QLabel("交易流水明细")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        
        self.btn_import = QPushButton("📥 导入")
        self.btn_import.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; }")
        self.btn_import.clicked.connect(self.main_win.open_import_wizard)
        
        self.btn_manual = QPushButton("✍️ 录入")
        self.btn_manual.setStyleSheet(f"QPushButton {{ background-color: {settings.COLOR_PROFIT}; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }}")
        self.btn_manual.clicked.connect(self.main_win.open_manual_entry)
        
        # 【新增】导出按钮，使用醒目的橘色
        self.btn_export = QPushButton("📤 导出")
        self.btn_export.setStyleSheet("QPushButton { background-color: #FF9800; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }")
        self.btn_export.clicked.connect(self.main_win.export_data)
        
        self.btn_manage_acc = QPushButton("🗑️ 清空账户")
        self.btn_manage_acc.setStyleSheet(f"QPushButton {{ background-color: white; color: {settings.COLOR_LOSS}; border: 1px solid {settings.COLOR_LOSS}; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }}")
        self.btn_manage_acc.clicked.connect(self.main_win.manage_accounts)
        
        top_bar.addWidget(title)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_import)
        top_bar.addWidget(self.btn_manual)
        top_bar.addWidget(self.btn_export)      # 【新增】挂载到布局
        top_bar.addWidget(self.btn_manage_acc)
        
        self.records_tab_widget = QTabWidget()
        self.records_tab_widget.setStyleSheet("QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 8px; background: white; top: -1px; } QTabBar::tab { background: #F5F5F5; color: #757575; padding: 10px 25px; border: 1px solid #E0E0E0; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; font-weight: bold; } QTabBar::tab:selected { background: white; color: #1976D2; border-bottom: 2px solid white; }")
        
        layout.addLayout(top_bar)
        layout.addSpacing(15)
        layout.addWidget(self.records_tab_widget)

    def clear_view(self):
        self.records_tab_widget.clear()

    def populate_table(self, df):
        self.clear_view()
        if df.empty: return
        
        self._create_table_for_tab("全部账户 (总览)", df)
        for acc in df['account'].unique():
            if pd.notna(acc): 
                self._create_table_for_tab(str(acc), df[df['account'] == acc])

    def _create_table_for_tab(self, tab_name, df_subset):
        table = QTableWidget()
        table.setColumnCount(9)
        table.setHorizontalHeaderLabels(["单号", "账户", "品种", "方向", "进场时间", "平仓时间", "手数", "盈亏", "手续费"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("QTableWidget { background-color: white; alternate-background-color: #FAFAFA; border: none; gridline-color: #EEEEEE; } QHeaderView::section { background-color: #F5F5F5; color: #757575; font-weight: bold; border: none; border-bottom: 1px solid #E0E0E0; padding: 10px; text-align: left; }")
        table.setRowCount(len(df_subset))
        
        df_reversed = df_subset.iloc[::-1].reset_index(drop=True) 
        for row in range(len(df_reversed)):
            record = df_reversed.iloc[row]
            entry_t = record['entry_time'].strftime('%m-%d %H:%M') if pd.notna(record.get('entry_time')) else "-"
            exit_t = record['exit_time'].strftime('%m-%d %H:%M') if pd.notna(record.get('exit_time')) else "-"
            
            items = [
                QTableWidgetItem(str(record.get('trade_id', '-'))), 
                QTableWidgetItem(str(record.get('account', '-'))), 
                QTableWidgetItem(str(record.get('symbol', '-'))), 
                QTableWidgetItem("做多" if record.get('direction') == 'LONG' else "做空"), 
                QTableWidgetItem(entry_t), 
                QTableWidgetItem(exit_t), 
                QTableWidgetItem(str(record.get('lots', 0))), 
                QTableWidgetItem(f"￥{record.get('net_profit', 0):,.2f}"), 
                QTableWidgetItem(f"￥{record.get('commission', 0):.2f}")
            ]
            
            pnl_color = settings.COLOR_PROFIT_TEXT if record.get('net_profit', 0) > 0 else settings.COLOR_LOSS_TEXT
            items[7].setForeground(QColor(pnl_color))
            items[7].setFont(QFont("Arial", 10, QFont.Weight.Bold))
            
            for col, item in enumerate(items): 
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, col, item)
                
        self.records_tab_widget.addTab(table, tab_name)