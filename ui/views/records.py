# ui/views/records.py
import pandas as pd
import re
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QTabWidget, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QComboBox)
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
        
        # ==========================================
        # 顶部操作栏
        # ==========================================
        top_bar_1 = QHBoxLayout()
        title = QLabel("交易流水明细")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        
        # 【修改点】将导入按钮升级为带下拉菜单的按钮
        from PyQt6.QtWidgets import QMenu # 请确保在文件顶部引入了 QMenu
        self.btn_import = QPushButton("📥 导入数据")
        self.btn_import.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; } QPushButton::menu-indicator { image: none; }")
        
        import_menu = QMenu(self.btn_import)
        import_menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #E0E0E0; border-radius: 4px; padding: 5px; } 
            QMenu::item { padding: 8px 25px; font-size: 14px; color: #333; } 
            QMenu::item:selected { background-color: #E3F2FD; color: #1976D2; border-radius: 4px;}
        """)
        
        action_futures = import_menu.addAction("📊 导入期货交割单")
        action_futures.triggered.connect(self.main_win.open_futures_import)
        
        action_stocks = import_menu.addAction("📈 导入股票交割单")
        action_stocks.triggered.connect(self.main_win.open_stock_import)
        
        self.btn_import.setMenu(import_menu)
        
        self.btn_manual = QPushButton("✍️ 录入")
        self.btn_manual.setStyleSheet(f"QPushButton {{ background-color: {settings.COLOR_PROFIT}; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }}")
        self.btn_manual.clicked.connect(self.main_win.open_manual_entry)
        
        self.btn_export = QPushButton("📤 导出")
        self.btn_export.setStyleSheet("QPushButton { background-color: #FF9800; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }")
        self.btn_export.clicked.connect(self.main_win.export_data)
        
        self.btn_manage_acc = QPushButton("🗑️ 清空账户")
        self.btn_manage_acc.setStyleSheet(f"QPushButton {{ background-color: white; color: {settings.COLOR_LOSS}; border: 1px solid {settings.COLOR_LOSS}; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }}")
        self.btn_manage_acc.clicked.connect(self.main_win.manage_accounts)
        
        top_bar_1.addWidget(title)
        top_bar_1.addStretch()
        top_bar_1.addWidget(self.btn_import)
        top_bar_1.addWidget(self.btn_manual)
        top_bar_1.addWidget(self.btn_export)
        top_bar_1.addWidget(self.btn_manage_acc)
        
        # ==========================================
        # 【新增】高级多条件过滤器 (Advanced Filters)
        # ==========================================
        top_bar_2 = QHBoxLayout()
        
        top_bar_2.addWidget(QLabel("账户:"))
        self.cb_acc = QComboBox(); self.cb_acc.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_acc)
        
        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("品种主体:"))
        self.cb_sym = QComboBox(); self.cb_sym.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_sym)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("方向:"))
        self.cb_dir = QComboBox()
        self.cb_dir.addItems(["全部", "做多 (LONG)", "做空 (SHORT)"])
        self.cb_dir.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_dir)

        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("盈亏结果:"))
        self.cb_res = QComboBox()
        self.cb_res.addItems(["全部", "仅盈利", "仅亏损"])
        self.cb_res.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_res)

        # 核心杀器：持仓时间过滤
        top_bar_2.addSpacing(15)
        top_bar_2.addWidget(QLabel("持仓时间:"))
        self.cb_dur = QComboBox()
        self.cb_dur.addItems(["全部时长", "日内 (<24h)", "隔夜 (1~2天)", "波段 (>2天)", "长线 (>5天)"])
        self.cb_dur.currentIndexChanged.connect(self.apply_filters)
        top_bar_2.addWidget(self.cb_dur)
        
        top_bar_2.addStretch()

        self.records_tab_widget = QTabWidget()
        self.records_tab_widget.setStyleSheet("QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 8px; background: white; top: -1px; } QTabBar::tab { background: #F5F5F5; color: #757575; padding: 10px 25px; border: 1px solid #E0E0E0; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; font-weight: bold; } QTabBar::tab:selected { background: white; color: #1976D2; border-bottom: 2px solid white; }")
        
        layout.addLayout(top_bar_1)
        layout.addLayout(top_bar_2)
        layout.addSpacing(10)
        layout.addWidget(self.records_tab_widget)

    def refresh_records_filters(self):
        """主窗口数据变动时，刷新这里的下拉框选项"""
        if self.main_win.engine.df.empty: 
            self.clear_view()
            return
            
        self.cb_acc.blockSignals(True)
        self.cb_sym.blockSignals(True)
        
        self.cb_acc.clear(); self.cb_acc.addItem("全账户", "ALL")
        for acc in self.main_win.engine.df['account'].dropna().unique(): 
            self.cb_acc.addItem(str(acc), str(acc))
            
        self.cb_sym.clear(); self.cb_sym.addItem("全品种", "ALL")
        roots = set()
        for sym in self.main_win.engine.df['symbol'].dropna().unique():
            match = re.match(r'^[A-Za-z]+', str(sym))
            if match: roots.add(match.group().upper())
            else: roots.add(str(sym).upper()) 
        for r in sorted(roots): self.cb_sym.addItem(r, r)
            
        self.cb_acc.blockSignals(False)
        self.cb_sym.blockSignals(False)
        
        self.apply_filters()

    def apply_filters(self):
        """执行高级多维过滤矩阵，并将结果输出给表格"""
        df = self.main_win.engine.df.copy()
        if df.empty:
            self.clear_view()
            return
            
        # 1. 账户过滤
        acc_sel = self.cb_acc.currentData()
        if acc_sel != "ALL" and acc_sel is not None: 
            df = df[df['account'] == acc_sel]
            
        # 2. 品种过滤
        sym_sel = self.cb_sym.currentData()
        if sym_sel != "ALL" and sym_sel is not None: 
            df['root_sym'] = df['symbol'].apply(lambda x: re.match(r'^[A-Za-z]+', str(x)).group().upper() if re.match(r'^[A-Za-z]+', str(x)) else str(x).upper())
            df = df[df['root_sym'] == sym_sel]
            
        # 3. 方向过滤
        dir_sel = self.cb_dir.currentText()
        if "做多" in dir_sel: df = df[df['direction'] == 'LONG']
        elif "做空" in dir_sel: df = df[df['direction'] == 'SHORT']
            
        # 4. 盈亏过滤
        res_sel = self.cb_res.currentText()
        if res_sel == "仅盈利": df = df[df['net_profit'] > 0]
        elif res_sel == "仅亏损": df = df[df['net_profit'] <= 0]
        
        # 5. 持仓时间过滤 (核心武器)
        if not df.empty:
            df['entry_time'] = pd.to_datetime(df['entry_time'])
            df['exit_time'] = pd.to_datetime(df['exit_time'])
            # 计算持仓小时数
            df['duration_h'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600.0
            
            dur_sel = self.cb_dur.currentText()
            if dur_sel == "日内 (<24h)": df = df[df['duration_h'] < 24]
            elif dur_sel == "隔夜 (1~2天)": df = df[(df['duration_h'] >= 24) & (df['duration_h'] <= 48)]
            elif dur_sel == "波段 (>2天)": df = df[df['duration_h'] > 48]
            elif dur_sel == "长线 (>5天)": df = df[df['duration_h'] > 120]

        self._populate_table_internal(df)

    def clear_view(self):
        self.records_tab_widget.clear()

    def _populate_table_internal(self, df):
        self.clear_view()
        if df.empty: return
        
        # 动态创建页签：第一个永远是符合筛选条件的总览
        self._create_table_for_tab(f"筛选结果 ({len(df)}笔)", df)
        
        # 如果没有按账户筛选，就额外生成每个账户的分类页签
        if self.cb_acc.currentData() == "ALL" or self.cb_acc.currentData() is None:
            for acc in df['account'].unique():
                if pd.notna(acc): 
                    acc_df = df[df['account'] == acc]
                    self._create_table_for_tab(f"{acc} ({len(acc_df)}笔)", acc_df)

    def _create_table_for_tab(self, tab_name, df_subset):
        table = QTableWidget()
        table.setColumnCount(10) # 增加了一列持仓时间
        table.setHorizontalHeaderLabels(["单号", "账户", "品种", "方向", "进场时间", "平仓时间", "持仓(h)", "手数", "盈亏", "手续费"])
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
            dur = f"{record.get('duration_h', 0):.1f}" if 'duration_h' in record else "-"
            
            items = [
                QTableWidgetItem(str(record.get('trade_id', '-'))), 
                QTableWidgetItem(str(record.get('account', '-'))), 
                QTableWidgetItem(str(record.get('symbol', '-'))), 
                QTableWidgetItem("做多" if record.get('direction') == 'LONG' else "做空"), 
                QTableWidgetItem(entry_t), 
                QTableWidgetItem(exit_t), 
                QTableWidgetItem(dur), # 新增的持仓时间列
                QTableWidgetItem(str(record.get('lots', 0))), 
                QTableWidgetItem(f"￥{record.get('net_profit', 0):,.2f}"), 
                QTableWidgetItem(f"￥{record.get('commission', 0):.2f}")
            ]
            
            pnl_color = settings.COLOR_PROFIT_TEXT if record.get('net_profit', 0) > 0 else settings.COLOR_LOSS_TEXT
            items[8].setForeground(QColor(pnl_color))
            items[8].setFont(QFont("Arial", 10, QFont.Weight.Bold))
            
            for col, item in enumerate(items): 
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row, col, item)
                
        self.records_tab_widget.addTab(table, tab_name)