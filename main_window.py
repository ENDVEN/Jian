import sys
import os
import shutil
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import calendar
import pyqtgraph as pg
from pyqtgraph import QtCore, QtGui
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, 
                             QVBoxLayout, QPushButton, QLabel, QFrame, QStackedWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView, QGridLayout,
                             QTabWidget, QDialog, QFileDialog, QComboBox, QMessageBox, 
                             QFormLayout, QScrollArea, QListWidget, QListWidgetItem, 
                             QTextEdit, QSplitter, QLineEdit, QDateTimeEdit, QDoubleSpinBox, 
                             QSpinBox, QButtonGroup)
from PyQt6.QtCore import Qt, QDate, QDateTime, QSize
from PyQt6.QtGui import QColor, QFont, QKeySequence

if not os.path.exists("screenshots"): os.makedirs("screenshots")

def generate_extreme_mock_data(num_trades=150):
    trades = []
    # 设定基准时间为当前月份，方便测试日历
    base_time = datetime.now().replace(day=1, hour=9, minute=0) 
    accounts = ['国内长线账户', '国内短线账户', '外盘IBKR']
    strategies = ['均线突破', '震荡网格', 'MACD背离', '裸K情绪']

    for i in range(num_trades):
        # 随机分布在这个月内
        trade_time = base_time + timedelta(days=random.randint(0, 27), hours=random.randint(1, 10))
        net_profit = random.uniform(1000, 8000) if random.random() < 0.45 else random.uniform(-4000, -500)
        
        trades.append({
            "trade_id": f"M{i:04d}", 
            "account": random.choice(accounts),
            "symbol": random.choice(['IF2310', 'RB2401', 'AU2312', 'NQ100']),
            "direction": random.choice(['LONG', 'SHORT']),
            "entry_time": trade_time, "exit_time": trade_time + timedelta(hours=random.randint(1, 48)),
            "lots": random.randint(1, 5), "net_profit": net_profit,
            "commission": random.uniform(10, 30), 
            "strategy_tag": random.choice(strategies),
            "entry_reason": "", "reflection": "" 
        })
    return pd.DataFrame(trades)



# ==========================================
# 0. 基础组件 (解析引擎、Hover列表等，保持不变)
# ==========================================
class HoverDeleteListWidget(QListWidget):
    def __init__(self, delete_callback, parent=None):
        super().__init__(parent); self.delete_callback = delete_callback; self.setViewMode(QListWidget.ViewMode.IconMode); self.setIconSize(QSize(100, 100)); self.setResizeMode(QListWidget.ResizeMode.Adjust); self.setFixedHeight(130)
        self.setStyleSheet("QListWidget { border: 2px dashed #E0E0E0; border-radius: 6px; background: #FAFAFA; padding: 5px;} QListWidget::item:selected { border: 2px solid #1976D2; background: transparent; border-radius: 4px;}")
        self.setMouseTracking(True); self.btn_delete = QPushButton("🗑️", self)
        self.btn_delete.setStyleSheet("QPushButton { background-color: rgba(244, 67, 54, 0.85); color: white; border: none; border-radius: 12px; font-size: 12px; font-weight: bold;} QPushButton:hover { background-color: rgba(211, 47, 47, 1); }")
        self.btn_delete.resize(24, 24); self.btn_delete.hide(); self.btn_delete.clicked.connect(self._on_delete_clicked); self.hovered_item = None
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event); item = self.itemAt(event.pos())
        if item: self.hovered_item = item; rect = self.visualItemRect(item); self.btn_delete.move(rect.right() - 26, rect.top() + 2); self.btn_delete.show()
        else: self.hovered_item = None; self.btn_delete.hide()
    def leaveEvent(self, event): super().leaveEvent(event); self.btn_delete.hide()
    def _on_delete_clicked(self):
        if self.hovered_item: filepath = self.hovered_item.data(Qt.ItemDataRole.UserRole); self.btn_delete.hide(); self.delete_callback(self.hovered_item, filepath)

def parse_cfmmc_excel(file_path):
    xls = pd.ExcelFile(file_path); account_name = "CFMMC真实账户"
    try:
        if '客户交易结算月报' in xls.sheet_names:
            df_info = pd.read_excel(xls, sheet_name='客户交易结算月报'); client_row = df_info[df_info.iloc[:, 0] == '客户名称']
            if not client_row.empty: account_name = str(client_row.iloc[0, 2]).strip()
    except Exception: pass
    df_raw = pd.read_excel(xls, sheet_name='成交明细'); header_idx = df_raw[df_raw.iloc[:, 0] == '交易日期'].index[0]
    df_trades = pd.read_excel(xls, sheet_name='成交明细', header=header_idx + 1); df_trades = df_trades[df_trades['交易日期'].notna() & (df_trades['交易日期'] != '合计')]
    open_positions = {}; matched_trades = []
    for _, row in df_trades.iterrows():
        symbol, action, direction = str(row['合约']).strip(), str(row['开/平']).strip(), str(row['买/卖']).strip()
        dt_str = str(row['交易日期']).split(' ')[0] + " " + str(row['成交时间']).strip()
        try: trade_time = pd.to_datetime(dt_str)
        except: trade_time = datetime.now()
        try: lots = int(float(row['手数']))
        except: lots = 0
        if lots == 0: continue
        if action == '开':
            if symbol not in open_positions: open_positions[symbol] = {'买': [], '卖': []}
            open_positions[symbol][direction].append({'entry_time': trade_time, 'lots': lots, 'commission': float(row['手续费']) if not pd.isna(row['手续费']) else 0.0})
        elif action in ['平', '平今', '平昨']:
            opposite_dir = '卖' if direction == '买' else '买'; lots_to_close = lots
            profit = pd.to_numeric(row['平仓盈亏'], errors='coerce'); profit = profit if not pd.isna(profit) else 0.0
            close_commission = float(row['手续费']) if not pd.isna(row['手续费']) else 0.0
            if symbol in open_positions and open_positions[symbol][opposite_dir]:
                while lots_to_close > 0 and open_positions[symbol][opposite_dir]:
                    open_trade = open_positions[symbol][opposite_dir][0]; matched_lots = min(lots_to_close, open_trade['lots'])
                    matched_trades.append({'trade_id': str(row['成交序号']), 'account': account_name, 'symbol': symbol, 'direction': 'LONG' if opposite_dir == '买' else 'SHORT', 'entry_time': open_trade['entry_time'], 'exit_time': trade_time, 'lots': matched_lots, 'net_profit': profit * (matched_lots / lots), 'commission': close_commission * (matched_lots / lots) + open_trade['commission'] * (matched_lots / open_trade['lots']), 'strategy_tag': '未分类', 'entry_reason': '', 'reflection': '', 'screenshot_paths': ''})
                    lots_to_close -= matched_lots; open_trade['lots'] -= matched_lots
                    if open_trade['lots'] == 0: open_positions[symbol][opposite_dir].pop(0)
            if lots_to_close > 0: matched_trades.append({'trade_id': str(row['成交序号']), 'account': account_name, 'symbol': symbol, 'direction': 'LONG' if opposite_dir == '买' else 'SHORT', 'entry_time': trade_time, 'exit_time': trade_time, 'lots': lots_to_close, 'net_profit': profit * (lots_to_close / lots), 'commission': close_commission * (lots_to_close / lots), 'strategy_tag': '未分类', 'entry_reason': '', 'reflection': '', 'screenshot_paths': ''})
    return pd.DataFrame(matched_trades)

class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        pg.GraphicsObject.__init__(self); self.data = data; self.generatePicture()
    def generatePicture(self):
        self.picture = QtGui.QPicture(); p = QtGui.QPainter(self.picture)
        w = (self.data[1][0] - self.data[0][0]) / 3.0 if len(self.data) > 1 else 0.3
        for (t, open_p, close_p, min_p, max_p) in self.data:
            if close_p >= open_p: p.setPen(pg.mkPen('#4CAF50', width=1.5)); p.setBrush(pg.mkBrush('#4CAF50'))
            else: p.setPen(pg.mkPen('#F44336', width=1.5)); p.setBrush(pg.mkBrush('#F44336'))
            p.drawLine(QtCore.QPointF(t, min_p), QtCore.QPointF(t, max_p)); p.drawRect(QtCore.QRectF(t - w, open_p, w * 2, close_p - open_p))
        p.end()
    def paint(self, p, *args): p.drawPicture(0, 0, self.picture)
    def boundingRect(self): return QtCore.QRectF(self.picture.boundingRect())

# ==========================================
# 1. 管理与表单弹窗 (折叠省略)
# ==========================================
class ListManagerDialog(QDialog):
    def __init__(self, title, items, delete_callback, parent=None):
        super().__init__(parent); self.setWindowTitle(title); self.resize(350, 450); self.setStyleSheet("QDialog { background-color: #FAFAFA; font-family: -apple-system, sans-serif; } QListWidget { background: white; border: 1px solid #E0E0E0; border-radius: 8px; outline: none; } QListWidget::item { border-bottom: 1px solid #F5F5F5; }"); self.delete_callback = delete_callback
        layout = QVBoxLayout(self); lbl_desc = QLabel("⚠️ 注意：删除操作不可逆，请谨慎操作。"); lbl_desc.setStyleSheet("color: #F44336; font-weight: bold; margin-bottom: 10px;"); layout.addWidget(lbl_desc); self.list_widget = QListWidget(); layout.addWidget(self.list_widget)
        for item_text in items: self.add_item(item_text)
        btn_close = QPushButton("完成"); btn_close.setStyleSheet("background-color: #1976D2; color: white; padding: 10px; font-weight: bold; border-radius: 6px;"); btn_close.clicked.connect(self.accept); layout.addWidget(btn_close)
    def add_item(self, text):
        item = QListWidgetItem(); widget = QWidget(); h_layout = QHBoxLayout(widget); h_layout.setContentsMargins(15, 10, 15, 10); lbl = QLabel(text); lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #424242;")
        btn = QPushButton("🗑️"); btn.setStyleSheet("QPushButton { border: none; color: #F44336; font-size: 16px; padding: 5px; } QPushButton:hover { background: #FFEBEE; border-radius: 6px; }"); btn.clicked.connect(lambda checked, t=text, i=item: self.on_delete(t, i)); h_layout.addWidget(lbl); h_layout.addStretch(); h_layout.addWidget(btn); item.setSizeHint(widget.sizeHint()); self.list_widget.addItem(item); self.list_widget.setItemWidget(item, widget)
    def on_delete(self, text, item):
        if self.delete_callback(text): row = self.list_widget.row(item); self.list_widget.takeItem(row)

class ImportWizardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("数据导入映射向导"); self.resize(500, 600); self.setStyleSheet("QDialog { background-color: white; font-family: -apple-system, sans-serif; }"); self.raw_df, self.final_df = None, None
        self.target_fields = {"trade_id": {"label": "交易单号", "keywords": ["成交号", "单号", "Ticket"]}, "account": {"label": "所属账户", "keywords": ["账户", "Account"]}, "symbol": {"label": "交易品种 (必选)", "keywords": ["合约", "品种", "Symbol"]}, "direction": {"label": "多空方向", "keywords": ["买卖", "方向", "Action"]}, "entry_time": {"label": "开仓时间", "keywords": ["开仓时间", "成交时间"]}, "exit_time": {"label": "平仓时间", "keywords": ["平仓时间", "日期"]}, "lots": {"label": "交易手数", "keywords": ["手数", "成交量", "Qty"]}, "net_profit": {"label": "净盈亏 (必选)", "keywords": ["平仓盈亏", "净盈亏", "PnL"]}, "commission": {"label": "手续费", "keywords": ["手续费", "佣金", "Commission"]}}
        layout = QVBoxLayout(self); top_layout = QHBoxLayout(); self.lbl_file = QLabel("请选择交割单文件:"); self.btn_select = QPushButton("浏览文件"); self.btn_select.setStyleSheet("padding: 5px 15px; background: #EEEEEE; border-radius: 4px; font-weight: bold;"); self.btn_select.clicked.connect(self.select_file); top_layout.addWidget(self.lbl_file); top_layout.addStretch(); top_layout.addWidget(self.btn_select); layout.addLayout(top_layout); self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True); self.form_widget = QWidget(); self.form_layout = QFormLayout(self.form_widget)
        self.comboboxes = {}
        for key, config in self.target_fields.items(): cb = QComboBox(); cb.setMinimumWidth(200); cb.addItem("-- 请选择对应的列 --", None); self.comboboxes[key] = cb; self.form_layout.addRow(config["label"], cb)
        self.scroll_area.setWidget(self.form_widget); layout.addWidget(self.scroll_area); btn_layout = QHBoxLayout(); self.btn_cancel, self.btn_import = QPushButton("取消"), QPushButton("确认映射并导入"); self.btn_import.setStyleSheet("background-color: #1976D2; color: white; padding: 8px 20px; font-weight: bold; border-radius: 4px;"); self.btn_import.clicked.connect(self.process_import); self.btn_cancel.clicked.connect(self.reject); btn_layout.addStretch(); btn_layout.addWidget(self.btn_cancel); btn_layout.addWidget(self.btn_import); layout.addLayout(btn_layout)
    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择交割单", "", "Excel/CSV Files (*.csv *.xls *.xlsx)")
        if not file_path: return
        self.lbl_file.setText(f"已选: {file_path.split('/')[-1]}")
        try:
            if file_path.endswith(('.xls', '.xlsx')):
                xls = pd.ExcelFile(file_path)
                if '成交明细' in xls.sheet_names:
                    if QMessageBox.question(self, "极速解析", "检测到标准格式，是否自动提取？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                        self.final_df = parse_cfmmc_excel(file_path); self.accept(); return
            if file_path.endswith('.csv'): self.raw_df = pd.read_csv(file_path, encoding='utf-8-sig')
            else: self.raw_df = pd.read_excel(file_path)
            for key, cb in self.comboboxes.items():
                cb.clear(); cb.addItem("-- 请选择 / 留空 --", None); best = 0
                for i, header in enumerate(self.raw_df.columns):
                    cb.addItem(str(header), header)
                    for kw in self.target_fields[key]["keywords"]:
                        if kw in str(header): best = i + 1; break
                cb.setCurrentIndex(best)
        except Exception as e: QMessageBox.critical(self, "错误", f"读取失败: {str(e)}")
    def process_import(self):
        if self.raw_df is None: return
        mapped = {k: self.raw_df[cb.currentData()] if cb.currentData() else None for k, cb in self.comboboxes.items()}
        if mapped["account"] is None: mapped["account"] = "自定义导入"
        if mapped["net_profit"] is None: mapped["net_profit"] = 0.0
        if mapped["lots"] is None: mapped["lots"] = 1
        self.final_df = pd.DataFrame(mapped)
        for col in ['entry_reason', 'reflection', 'screenshot_paths']: self.final_df[col] = ""
        self.final_df['strategy_tag'] = "未分类"
        self.final_df['entry_time'] = pd.to_datetime(self.final_df['entry_time'], errors='coerce')
        self.final_df['exit_time'] = pd.to_datetime(self.final_df['exit_time'], errors='coerce')
        self.final_df['entry_time'] = self.final_df['entry_time'].fillna(self.final_df['exit_time'])
        self.accept()

class ManualEntryDialog(QDialog):
    def __init__(self, current_strategies, parent=None):
        super().__init__(parent); self.setWindowTitle("手工录入"); self.resize(400, 500); self.setStyleSheet("QDialog { background-color: #FAFAFA; font-family: -apple-system, sans-serif; } QLabel { font-weight: bold; color: #424242; } QLineEdit, QComboBox, QDateTimeEdit, QDoubleSpinBox, QSpinBox { border: 1px solid #E0E0E0; border-radius: 6px; padding: 6px; background: white; font-size: 14px; }")
        self.new_trade_data = None; layout = QVBoxLayout(self); form = QFormLayout(); form.setSpacing(15)
        self.inp_account = QComboBox(); self.inp_account.setEditable(True); self.inp_account.addItems(["默认手工账户", "国内长线", "国内短线"]); form.addRow("归属账户:", self.inp_account)
        self.inp_symbol = QLineEdit(); self.inp_symbol.setPlaceholderText("例如: RB2401"); form.addRow("交易品种:", self.inp_symbol)
        self.inp_direction = QComboBox(); self.inp_direction.addItems(["做多 (LONG)", "做空 (SHORT)"]); form.addRow("买卖方向:", self.inp_direction)
        self.inp_strategy = QComboBox(); self.inp_strategy.setEditable(True); self.inp_strategy.addItems(current_strategies if current_strategies else ["未分类"]); form.addRow("策略分类:", self.inp_strategy)
        self.inp_entry_time = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1)); self.inp_entry_time.setCalendarPopup(True); form.addRow("进场时间:", self.inp_entry_time)
        self.inp_exit_time = QDateTimeEdit(QDateTime.currentDateTime()); self.inp_exit_time.setCalendarPopup(True); form.addRow("平仓时间:", self.inp_exit_time)
        self.inp_lots = QSpinBox(); self.inp_lots.setRange(1, 1000); form.addRow("手数:", self.inp_lots)
        self.inp_pnl = QDoubleSpinBox(); self.inp_pnl.setRange(-9999999, 9999999); self.inp_pnl.setDecimals(2); form.addRow("净盈亏:", self.inp_pnl)
        self.inp_comm = QDoubleSpinBox(); self.inp_comm.setRange(0, 999999); self.inp_comm.setDecimals(2); form.addRow("手续费:", self.inp_comm)
        layout.addLayout(form); layout.addStretch(); btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消"); btn_cancel.clicked.connect(self.reject); btn_submit = QPushButton("确认添加"); btn_submit.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight: bold; border-radius: 6px;"); btn_submit.clicked.connect(self.submit_data)
        btn_layout.addWidget(btn_cancel); btn_layout.addWidget(btn_submit); layout.addLayout(btn_layout)
    def submit_data(self):
        if not self.inp_symbol.text().strip(): QMessageBox.warning(self, "错误", "品种不能为空！"); return
        self.new_trade_data = pd.DataFrame([{'trade_id': f"M_{int(datetime.now().timestamp())}", 'account': self.inp_account.currentText().strip(), 'symbol': self.inp_symbol.text().strip(), 'direction': 'LONG' if '多' in self.inp_direction.currentText() else 'SHORT', 'entry_time': self.inp_entry_time.dateTime().toPyDateTime(), 'exit_time': self.inp_exit_time.dateTime().toPyDateTime(), 'lots': self.inp_lots.value(), 'net_profit': self.inp_pnl.value(), 'commission': self.inp_comm.value(), 'strategy_tag': self.inp_strategy.currentText().strip(), 'entry_reason': '', 'reflection': '', 'screenshot_paths': ''}])
        self.accept()

# ==========================================
# 3. 核心分析大脑 
# ==========================================
class TradeAnalyzer:
    def __init__(self, df: pd.DataFrame, initial_capital: float = 1000000):
        self.df = df.copy(); self.initial_capital = initial_capital
        self.df['entry_time'] = pd.to_datetime(self.df['entry_time'], errors='coerce')
        self.df['exit_time'] = pd.to_datetime(self.df['exit_time'], errors='coerce')
        for col in ['net_profit', 'commission', 'lots']:
            if self.df[col].dtype == object: self.df[col] = pd.to_numeric(self.df[col].astype(str).str.replace(',', ''), errors='coerce')
        self.df = self.df.sort_values(by='exit_time').reset_index(drop=True)
        self.df['equity'] = self.initial_capital + self.df['net_profit'].cumsum()

    def generate_raw_report(self):
        df = self.df
        if len(df) == 0: return None 
        winning_trades, losing_trades = df[df['net_profit'] > 0], df[df['net_profit'] <= 0]
        win_count, total_count = len(winning_trades), len(df)
        avg_win = winning_trades['net_profit'].sum() / win_count if win_count > 0 else 0
        avg_loss = losing_trades['net_profit'].sum() / len(losing_trades) if len(losing_trades) > 0 else 0
        pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        df['peak'] = df['equity'].cummax()
        df['drawdown_pct'] = (df['peak'] - df['equity']) / df['peak']
        return {"initial_capital": self.initial_capital, "net_profit": df['net_profit'].sum(), "return_rate": (df['equity'].iloc[-1] - self.initial_capital) / self.initial_capital, "total_commission": df['commission'].sum(), "total_trades": total_count, "win_rate": win_count / total_count if total_count > 0 else 0, "pl_ratio": pl_ratio, "winning_trades": win_count, "losing_trades": total_count - win_count, "max_drawdown": df['drawdown_pct'].max(), "avg_win": avg_win, "avg_loss": avg_loss, "max_profit": df['net_profit'].max(), "max_loss": df['net_profit'].min()}

# ==========================================
# 4. GUI 主程序
# ==========================================
pg.setConfigOption('background', '#FFFFFF'); pg.setConfigOption('foreground', '#424242'); pg.setConfigOptions(antialias=True)

class TradingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("量化交易分析仪表板 - 专业版")
        self.resize(1500, 950) 
        self.setStyleSheet("""
            QMainWindow { background-color: #FAFAFA; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
            QFrame#Sidebar { background-color: #FFFFFF; border-right: 1px solid #E0E0E0; }
            QPushButton.NavBtn { background-color: transparent; color: #424242; text-align: left; padding: 15px 20px; border-radius: 8px; font-size: 15px; font-weight: bold; border: none; margin: 2px 10px;}
            QPushButton.NavBtn:hover { background-color: #F5F5F5; }
            QPushButton.NavBtn:checked { background-color: #E3F2FD; color: #1976D2; }
            QComboBox { border: 1px solid #E0E0E0; border-radius: 6px; padding: 5px 10px; background: white; font-weight: bold; color: #424242;}
            QComboBox::drop-down { border: none; }
        """)
        self.global_df = pd.DataFrame() 
        self.global_strategies = ["未分类"] 

        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget); main_layout.setContentsMargins(0, 0, 0, 0); main_layout.setSpacing(0)
        
        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(sidebar); sidebar_layout.setContentsMargins(0, 20, 0, 20)
        self.btn_overview, self.btn_records, self.btn_review = QPushButton("📊 资金与表现"), QPushButton("📝 交易流水"), QPushButton("💡 深度复盘")
        for btn in [self.btn_overview, self.btn_records, self.btn_review]:
            btn.setProperty("class", "NavBtn"); btn.setCheckable(True); btn.setAutoExclusive(True); sidebar_layout.addWidget(btn)
        self.btn_overview.setChecked(True); sidebar_layout.addStretch()
        
        self.content_area = QStackedWidget(); self.content_area.setContentsMargins(20, 20, 20, 20)
        self.page_overview = self.build_dashboard_page() 
        self.page_records = self.build_records_page()    
        self.page_review = self.build_review_page() 
        
        self.content_area.addWidget(self.page_overview); self.content_area.addWidget(self.page_records); self.content_area.addWidget(self.page_review) 
        main_layout.addWidget(sidebar); main_layout.addWidget(self.content_area)
        self.btn_overview.clicked.connect(lambda: self.content_area.setCurrentIndex(0))
        self.btn_records.clicked.connect(lambda: self.content_area.setCurrentIndex(1))
        self.btn_review.clicked.connect(lambda: self.content_area.setCurrentIndex(2))
        
        self.current_review_date = datetime.now()
        # 初始视图状态：默认月视图
        self.is_yearly_view = False
        
        # 为了演示，加入少量假数据
        from main_window import generate_extreme_mock_data # 偷懒调用一下以前写的
        try:
            self.global_df = generate_extreme_mock_data(50)
            self.global_strategies += self.global_df['strategy_tag'].unique().tolist()
        except: pass
        self.render_all_data()

    def render_all_data(self):
        if self.global_df.empty: 
            self.records_tab_widget.clear()
            self.day_trades_list.clear(); self.review_calendar.clearContents()
            self.review_pnl_chart.clear(); self.review_kline_chart.clear(); self.review_duration_chart.clear()
            self.refresh_review_filters()
            return

        analyzer = TradeAnalyzer(self.global_df)
        raw_report = analyzer.generate_raw_report()
        if raw_report:
            self.update_metrics(raw_report)
            self.update_equity_chart(analyzer.df)
            self.update_distribution_chart(analyzer.df)
            self.populate_records_table(analyzer.df)
            self.refresh_review_filters()
            self.update_review_view()

    # ==========================================
    # UI: Dash/Records (不变)
    # ==========================================
    def build_dashboard_page(self):
        page = QWidget(); layout = QHBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.create_metrics_panel(), 1); layout.addWidget(self.create_charts_panel(), 2); return page

    def build_records_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0)
        top_bar = QHBoxLayout(); title = QLabel("交易流水明细"); title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        self.btn_import = QPushButton("📥 导入"); self.btn_import.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; }"); self.btn_import.clicked.connect(self.open_import_wizard)
        self.btn_manual = QPushButton("✍️ 录入"); self.btn_manual.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }"); self.btn_manual.clicked.connect(self.open_manual_entry)
        self.btn_manage_acc = QPushButton("🗑️ 清空账户"); self.btn_manage_acc.setStyleSheet("QPushButton { background-color: white; color: #F44336; border: 1px solid #F44336; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; margin-left:10px; }"); self.btn_manage_acc.clicked.connect(self.manage_accounts)
        top_bar.addWidget(title); top_bar.addStretch(); top_bar.addWidget(self.btn_import); top_bar.addWidget(self.btn_manual); top_bar.addWidget(self.btn_manage_acc)
        self.records_tab_widget = QTabWidget(); self.records_tab_widget.setStyleSheet("QTabWidget::pane { border: 1px solid #E0E0E0; border-radius: 8px; background: white; top: -1px; } QTabBar::tab { background: #F5F5F5; color: #757575; padding: 10px 25px; border: 1px solid #E0E0E0; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; font-weight: bold; } QTabBar::tab:selected { background: white; color: #1976D2; border-bottom: 2px solid white; }")
        layout.addLayout(top_bar); layout.addSpacing(15); layout.addWidget(self.records_tab_widget); return page

    # ==========================================
    # 深度复盘：【双模态架构】
    # ==========================================
    def build_review_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(15)
        
        # === 顶部控制栏 ===
        top_bar = QHBoxLayout()
        title = QLabel("复盘工作台"); title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        top_bar.addWidget(title); top_bar.addSpacing(30)

        top_bar.addWidget(QLabel("账户:")); self.cb_rev_account = QComboBox(); self.cb_rev_account.currentIndexChanged.connect(self.update_review_view); top_bar.addWidget(self.cb_rev_account); top_bar.addSpacing(15)
        top_bar.addWidget(QLabel("策略:")); self.cb_rev_strategy = QComboBox(); self.cb_rev_strategy.currentIndexChanged.connect(self.update_review_view); top_bar.addWidget(self.cb_rev_strategy)
        self.btn_manage_str = QPushButton("🏷️ 管理策略"); self.btn_manage_str.setStyleSheet("QPushButton { border: none; color: #1976D2; font-weight:bold; font-size:14px; margin-left: 5px;} QPushButton:hover { text-decoration: underline; }"); self.btn_manage_str.clicked.connect(self.manage_strategies)
        top_bar.addWidget(self.btn_manage_str); top_bar.addStretch()

        # 【核心修改 1】加入年月双模态切换按钮
        self.btn_mode_toggle = QPushButton("切换年视图 📅")
        self.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
        self.btn_mode_toggle.clicked.connect(self.toggle_review_mode)
        top_bar.addWidget(self.btn_mode_toggle)

        # 极速时间导航栏 (复用，根据模态动态改变行为)
        nav_layout = QHBoxLayout()
        self.btn_prev_time = QPushButton("◀")
        self.btn_next_time = QPushButton("▶")
        for btn in [self.btn_prev_time, self.btn_next_time]: btn.setStyleSheet("QPushButton { border: none; font-size: 18px; color: #9E9E9E;} QPushButton:hover { color: #1976D2; }")
        self.btn_prev_time.clicked.connect(lambda: self.change_review_time(-1))
        self.btn_next_time.clicked.connect(lambda: self.change_review_time(1))
        
        self.cb_time_picker = QComboBox()
        self.cb_time_picker.setStyleSheet("QComboBox { font-size: 16px; font-weight: bold; color: #1976D2; padding: 5px 15px; border: 1px solid #E0E0E0; border-radius: 6px; background: white;} QComboBox::drop-down { border: none; width: 20px;} QComboBox:hover { background: #F5F5F5; }")
        self.cb_time_picker.activated.connect(self.quick_jump_time)

        nav_layout.addWidget(self.btn_prev_time); nav_layout.addWidget(self.cb_time_picker); nav_layout.addWidget(self.btn_next_time)
        top_bar.addLayout(nav_layout)
        layout.addLayout(top_bar)

        # === 动态核心区：使用 QStackedWidget 承载两个模态 ===
        self.review_stack = QStackedWidget()
        
        # 模态A：月视图 (Micro Mode)
        self.review_monthly_widget = self._build_monthly_mode()
        # 模态B：年视图 (Macro Mode)
        self.review_yearly_widget = self._build_yearly_mode()
        
        self.review_stack.addWidget(self.review_monthly_widget) # Index 0
        self.review_stack.addWidget(self.review_yearly_widget)  # Index 1
        
        layout.addWidget(self.review_stack)
        return page

    def _build_monthly_mode(self):
        """原有的左上日历、右上图表、下方明细编辑器"""
        widget = QWidget()
        layout = QVBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)
        
        macro_splitter = QSplitter(Qt.Orientation.Horizontal)
        cal_card = QFrame(); cal_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); cal_layout = QVBoxLayout(cal_card); cal_layout.setContentsMargins(10, 10, 10, 10)
        self.review_calendar = QTableWidget(6, 7); self.review_calendar.setHorizontalHeaderLabels(["一", "二", "三", "四", "五", "六", "日"]); self.review_calendar.verticalHeader().setVisible(False)
        self.review_calendar.setStyleSheet("QTableWidget { border: none; background: white; gridline-color: transparent; } QHeaderView::section { background: white; color: #9E9E9E; border: none; font-weight: bold; font-size: 13px; } QTableWidget::item { border-radius: 6px; margin: 2px; } QTableWidget::item:selected { border: 2px solid #1976D2; background: transparent; color: black;}")
        self.review_calendar.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.review_calendar.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.review_calendar.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.review_calendar.setFocusPolicy(Qt.FocusPolicy.NoFocus); self.review_calendar.setSelectionMode(QTableWidget.SelectionMode.SingleSelection); self.review_calendar.cellClicked.connect(self.on_calendar_day_clicked)
        cal_layout.addWidget(self.review_calendar)
        
        chart_card = QFrame(); chart_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); chart_layout = QVBoxLayout(chart_card); chart_layout.setContentsMargins(5, 5, 5, 5)
        self.review_chart_tabs = QTabWidget(); self.review_chart_tabs.setStyleSheet("QTabWidget::pane { border: none; } QTabBar::tab { background: transparent; color: #757575; padding: 8px 15px; font-weight: bold; font-size: 14px;} QTabBar::tab:selected { color: #1976D2; border-bottom: 3px solid #1976D2; }")
        self.review_pnl_chart = pg.PlotWidget(); self.review_pnl_chart.setBackground('w'); self.review_pnl_chart.showGrid(x=True, y=True, alpha=0.2)
        self.review_kline_chart = pg.PlotWidget(); self.review_kline_chart.setBackground('w'); self.review_kline_chart.showGrid(x=True, y=True, alpha=0.2) 
        self.review_duration_chart = pg.PlotWidget(); self.review_duration_chart.setBackground('w'); self.review_duration_chart.showGrid(x=True, y=True, alpha=0.3); self.review_duration_chart.setLabel('left', '单笔盈亏'); self.review_duration_chart.setLabel('bottom', '时长(H)')
        self.review_chart_tabs.addTab(self.review_pnl_chart, "📈 累计盈亏"); self.review_chart_tabs.addTab(self.review_kline_chart, "📊 资金 K线"); self.review_chart_tabs.addTab(self.review_duration_chart, "⏳ 时长分析")
        chart_layout.addWidget(self.review_chart_tabs)
        macro_splitter.addWidget(cal_card); macro_splitter.addWidget(chart_card); macro_splitter.setSizes([450, 600])
        layout.addWidget(macro_splitter, 5)

        micro_splitter = QSplitter(Qt.Orientation.Horizontal)
        list_card = QFrame(); list_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); list_layout = QVBoxLayout(list_card); self.lbl_selected_date = QLabel("选定日期: 无"); self.lbl_selected_date.setStyleSheet("font-weight: bold; color: #757575; font-size: 14px;")
        self.day_trades_list = QListWidget(); self.day_trades_list.setStyleSheet("QListWidget { border: none; font-size: 13px; } QListWidget::item { padding: 12px; border-bottom: 1px solid #F5F5F5; } QListWidget::item:selected { background: #E3F2FD; color: #1976D2; border-radius: 4px;}")
        self.day_trades_list.currentItemChanged.connect(self.on_review_trade_selected)
        list_layout.addWidget(self.lbl_selected_date); list_layout.addWidget(self.day_trades_list)
        
        editor_card = QFrame(); editor_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }"); editor_layout = QVBoxLayout(editor_card)
        header_layout = QHBoxLayout(); self.lbl_trade_detail = QLabel("请选择交易..."); self.lbl_trade_detail.setStyleSheet("font-size: 14px; font-weight: bold; color: #424242;"); header_layout.addWidget(self.lbl_trade_detail); header_layout.addStretch()
        header_layout.addWidget(QLabel("分类至: ")); self.cb_edit_strategy = QComboBox(); self.cb_edit_strategy.setEditable(True); self.cb_edit_strategy.setMinimumWidth(150); self.cb_edit_strategy.setStyleSheet("QComboBox { border: 1px solid #1976D2; border-radius: 4px; background: #F3E5F5; }"); self.cb_edit_strategy.lineEdit().editingFinished.connect(self.silent_update_strategy); self.cb_edit_strategy.activated.connect(self.silent_update_strategy); header_layout.addWidget(self.cb_edit_strategy)
        editor_layout.addLayout(header_layout)

        text_layout = QHBoxLayout(); v1, v2 = QVBoxLayout(), QVBoxLayout()
        v1.addWidget(QLabel("💡 进场逻辑:")); self.txt_reason = QTextEdit(); self.txt_reason.setStyleSheet("QTextEdit { border: 1px solid #EEEEEE; border-radius: 4px; background: #FAFAFA; padding: 5px;}"); v1.addWidget(self.txt_reason)
        v2.addWidget(QLabel("🔍 离场反思:")); self.txt_reflection = QTextEdit(); self.txt_reflection.setStyleSheet("QTextEdit { border: 1px solid #EEEEEE; border-radius: 4px; background: #FAFAFA; padding: 5px;}"); v2.addWidget(self.txt_reflection)
        text_layout.addLayout(v1); text_layout.addLayout(v2); editor_layout.addLayout(text_layout)
        
        img_layout = QVBoxLayout(); img_header = QHBoxLayout(); lbl_img = QLabel("📸 画廊:"); lbl_img.setStyleSheet("font-weight: bold; color: #424242;"); img_header.addWidget(lbl_img); img_header.addStretch()
        self.btn_paste_img = QPushButton("📋 粘贴"); self.btn_import_img = QPushButton("📁 导入")
        for btn in [self.btn_paste_img, self.btn_import_img]: btn.setStyleSheet("QPushButton { background-color: #F5F5F5; color: #424242; border: 1px solid #E0E0E0; border-radius: 4px; padding: 4px 10px; font-weight: bold; } QPushButton:hover { background-color: #EEEEEE; }")
        self.btn_paste_img.clicked.connect(self.paste_image); self.btn_import_img.clicked.connect(self.import_image); img_header.addWidget(self.btn_paste_img); img_header.addWidget(self.btn_import_img); img_layout.addLayout(img_header)
        self.list_screenshots = HoverDeleteListWidget(self.delete_image, self); self.list_screenshots.itemDoubleClicked.connect(self.view_full_image); shortcut = QtGui.QShortcut(QKeySequence("Ctrl+V"), self.list_screenshots); shortcut.activated.connect(self.paste_image); img_layout.addWidget(self.list_screenshots); editor_layout.addLayout(img_layout)
        
        action_layout = QHBoxLayout(); self.btn_del_trade = QPushButton("🗑️ 删除此单"); self.btn_del_trade.setStyleSheet("QPushButton { background-color: white; color: #F44336; border: 1px solid #F44336; border-radius: 6px; padding: 10px; font-weight: bold; } QPushButton:hover { background-color: #FFEBEE; }"); self.btn_del_trade.clicked.connect(self.delete_current_trade)
        self.btn_save_review = QPushButton("💾 保存复盘文字与截图"); self.btn_save_review.setStyleSheet("QPushButton { background-color: #1976D2; color: white; border: none; border-radius: 6px; padding: 10px; font-weight: bold; } QPushButton:hover { background-color: #1565C0; }"); self.btn_save_review.clicked.connect(self.save_review_text)
        action_layout.addWidget(self.btn_del_trade); action_layout.addStretch(); action_layout.addWidget(self.btn_save_review); editor_layout.addLayout(action_layout)
        
        micro_splitter.addWidget(list_card); micro_splitter.addWidget(editor_card); micro_splitter.setSizes([350, 700])
        layout.addWidget(micro_splitter, 4)
        return widget

    def _build_yearly_mode(self):
        """【全新模块】年度复盘面板"""
        widget = QWidget()
        layout = QVBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. 年度热力日历 (宏观)
        cal_card = QFrame()
        cal_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        cal_layout = QVBoxLayout(cal_card)
        cal_title = QLabel("📅 年度各月盈亏概览")
        cal_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #424242; margin-bottom: 5px;")
        cal_layout.addWidget(cal_title)
        
        # 12个月份的卡片网格
        self.yearly_grid = QGridLayout()
        self.yearly_grid.setSpacing(10)
        self.month_cards = []
        
        for i in range(12):
            card = QLabel(f"{i+1}月\n无数据")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card.setStyleSheet("background: #F5F5F5; border-radius: 6px; font-size: 14px; font-weight:bold; color: #9E9E9E;")
            # 设为固定大小的方块
            card.setMinimumSize(80, 80)
            self.month_cards.append(card)
            # 布局为 2行6列
            self.yearly_grid.addWidget(card, i // 6, i % 6)
            
        cal_layout.addLayout(self.yearly_grid)
        layout.addWidget(cal_card, 2)
        
        # 2. 下方：年度洞察雷达 (Insights Radar)
        radar_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：策略贡献柱状图
        bar_card = QFrame()
        bar_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        bar_layout = QVBoxLayout(bar_card)
        self.yearly_bar_chart = pg.PlotWidget(title="🏆 年度策略利润贡献度")
        self.yearly_bar_chart.setBackground('w'); self.yearly_bar_chart.showGrid(x=False, y=True, alpha=0.2)
        bar_layout.addWidget(self.yearly_bar_chart)
        radar_splitter.addWidget(bar_card)
        
        # 右侧：年度盈亏散点图 (或者大盘曲线)
        curve_card = QFrame()
        curve_card.setStyleSheet("QFrame { background: white; border: 1px solid #E0E0E0; border-radius: 8px; }")
        curve_layout = QVBoxLayout(curve_card)
        self.yearly_curve_chart = pg.PlotWidget(title="📈 年度资金净值曲线")
        self.yearly_curve_chart.setBackground('w'); self.yearly_curve_chart.showGrid(x=True, y=True, alpha=0.2)
        curve_layout.addWidget(self.yearly_curve_chart)
        radar_splitter.addWidget(curve_card)
        
        radar_splitter.setSizes([500, 500])
        layout.addWidget(radar_splitter, 5)
        return widget

    # ==========================================
    # 交互：图库管理 & 通用弹窗
    # ==========================================
    def paste_image(self):
        if getattr(self, 'current_editing_idx', None) is None: QMessageBox.warning(self, "提示", "请先选择交易！"); return
        clipboard = QApplication.clipboard(); mime_data = clipboard.mimeData()
        if mime_data.hasImage():
            image = clipboard.image()
            trade_id = str(self.global_df.at[self.current_editing_idx, 'trade_id']).replace(" ", "_")
            timestamp = int(datetime.now().timestamp() * 1000)
            filename = f"screenshots/{trade_id}_{timestamp}.png"
            image.save(filename); self.add_thumbnail(filename); self._save_image_paths_to_df() 
        else: QMessageBox.warning(self, "提示", "剪贴板无图片！")

    def import_image(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择截图", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        trade_id = str(self.global_df.at[self.current_editing_idx, 'trade_id']).replace(" ", "_")
        for path in file_paths:
            timestamp = int(datetime.now().timestamp() * 1000); ext = path.split('.')[-1]
            filename = f"screenshots/{trade_id}_{timestamp}.{ext}"
            shutil.copy(path, filename); self.add_thumbnail(filename)
        self._save_image_paths_to_df()

    def add_thumbnail(self, filepath):
        icon = QtGui.QIcon(filepath); item = QListWidgetItem(icon, "")
        item.setData(Qt.ItemDataRole.UserRole, filepath); self.list_screenshots.addItem(item)

    def delete_image(self, item, filepath):
        reply = QMessageBox.question(self, "删除截图", "确定要永久删除截图吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(filepath): os.remove(filepath)
            except Exception as e: QMessageBox.warning(self, "错误", str(e))
            row = self.list_screenshots.row(item); self.list_screenshots.takeItem(row); self._save_image_paths_to_df()

    def _save_image_paths_to_df(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        paths = [self.list_screenshots.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_screenshots.count())]
        self.global_df.at[self.current_editing_idx, 'screenshot_paths'] = ";".join(paths)

    def view_full_image(self, item):
        filepath = item.data(Qt.ItemDataRole.UserRole); 
        if not os.path.exists(filepath): return
        dialog = QDialog(self); dialog.setWindowTitle("查看截图"); dialog.setStyleSheet("QDialog { background-color: #212121; }"); layout = QVBoxLayout(dialog); layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(); pixmap = QtGui.QPixmap(filepath)
        screen = QApplication.primaryScreen().geometry()
        if pixmap.width() > screen.width() * 0.8 or pixmap.height() > screen.height() * 0.8:
            pixmap = pixmap.scaled(int(screen.width() * 0.8), int(screen.height() * 0.8), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap); label.setAlignment(Qt.AlignmentFlag.AlignCenter); layout.addWidget(label); dialog.exec()

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

    def delete_current_trade(self):
        if getattr(self, 'current_editing_idx', None) is None: return
        if QMessageBox.question(self, "危险操作", "永久删除此交易记录？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.global_df = self.global_df.drop(self.current_editing_idx).reset_index(drop=True)
            self.current_editing_idx = None; self.render_all_data()

    # ==========================================
    # 复盘核心：双模态联动机制
    # ==========================================
    def toggle_review_mode(self):
        """核心按钮：切换年/月视图"""
        self.is_yearly_view = not self.is_yearly_view
        if self.is_yearly_view:
            self.btn_mode_toggle.setText("切换月视图 🔍")
            self.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #4CAF50; padding: 5px 15px; border: 1px solid #A5D6A7; border-radius: 6px; background: #E8F5E9; margin-right: 15px;} QPushButton:hover { background: #C8E6C9; }")
            self.review_stack.setCurrentIndex(1) # 切换到年图
            self.refresh_time_picker(is_year=True)
        else:
            self.btn_mode_toggle.setText("切换年视图 📅")
            self.btn_mode_toggle.setStyleSheet("QPushButton { font-size: 14px; font-weight: bold; color: #FF9800; padding: 5px 15px; border: 1px solid #FFCC80; border-radius: 6px; background: #FFF3E0; margin-right: 15px;} QPushButton:hover { background: #FFE0B2; }")
            self.review_stack.setCurrentIndex(0) # 切换回月图
            self.refresh_time_picker(is_year=False)
            
        self.update_review_view()

    def refresh_review_filters(self):
        if self.global_df.empty: return
        self.cb_rev_account.blockSignals(True); self.cb_rev_strategy.blockSignals(True); self.cb_edit_strategy.blockSignals(True)
        
        self.cb_rev_account.clear(); self.cb_rev_account.addItem("全账户汇总", "ALL")
        for acc in self.global_df['account'].dropna().unique(): self.cb_rev_account.addItem(str(acc), str(acc))
            
        self.cb_rev_strategy.clear(); self.cb_rev_strategy.addItem("全策略分类", "ALL")
        all_st = list(set(self.global_strategies + self.global_df['strategy_tag'].dropna().unique().tolist()))
        self.cb_edit_strategy.clear()
        for st in all_st: 
            self.cb_rev_strategy.addItem(str(st), str(st))
            self.cb_edit_strategy.addItem(str(st))
            
        self.refresh_time_picker(self.is_yearly_view)
        
        self.cb_rev_account.blockSignals(False); self.cb_rev_strategy.blockSignals(False); self.cb_edit_strategy.blockSignals(False)

    def refresh_time_picker(self, is_year=False):
        self.cb_time_picker.blockSignals(True)
        self.cb_time_picker.clear()
        if self.global_df.empty: return
        
        dates = pd.to_datetime(self.global_df['exit_time'])
        if is_year:
            # 提取所有年份
            years = sorted(dates.dt.year.unique().tolist(), reverse=True)
            for y in years:
                # 存入该年 1 月 1 日作为锚点
                self.cb_time_picker.addItem(f"{y}年", datetime(y, 1, 1))
        else:
            # 提取所有月份
            months = sorted([d.to_timestamp() for d in dates.dt.to_period('M').unique()], reverse=True)
            for dt in months:
                self.cb_time_picker.addItem(dt.strftime("%Y年 %m月"), dt)
                
        self.cb_time_picker.blockSignals(False)

    def quick_jump_time(self):
        selected_dt = self.cb_time_picker.currentData()
        if selected_dt:
            self.current_review_date = selected_dt
            self.update_review_view()

    def change_review_time(self, delta):
        if self.is_yearly_view:
            # 加减年
            y = self.current_review_date.year + delta
            self.current_review_date = self.current_review_date.replace(year=y, month=1, day=1)
        else:
            # 加减月
            m = self.current_review_date.month - 1 + delta; y = self.current_review_date.year + m // 12; m = m % 12 + 1
            self.current_review_date = self.current_review_date.replace(year=y, month=m, day=1)
        self.update_review_view()

    def update_review_view(self):
        if self.global_df.empty: return
        
        # 更新时间导航栏文本
        display_text = f"{self.current_review_date.year}年" if self.is_yearly_view else self.current_review_date.strftime("%Y年 %m月")
        idx = self.cb_time_picker.findText(display_text)
        if idx >= 0: self.cb_time_picker.setCurrentIndex(idx)
        
        df = self.global_df.copy()
        acc_sel = self.cb_rev_account.currentData()
        if acc_sel != "ALL" and acc_sel is not None: df = df[df['account'] == acc_sel]
        str_sel = self.cb_rev_strategy.currentData()
        if str_sel != "ALL" and str_sel is not None: df = df[df['strategy_tag'] == str_sel]
            
        df['exit_time'] = pd.to_datetime(df['exit_time']); df['entry_time'] = pd.to_datetime(df['entry_time'])
        
        y = self.current_review_date.year
        if self.is_yearly_view:
            self.current_view_df = df[df['exit_time'].dt.year == y]
            self._render_yearly_view()
        else:
            m = self.current_review_date.month
            self.current_view_df = df[(df['exit_time'].dt.year == y) & (df['exit_time'].dt.month == m)]
            # 清理月视图底层
            self.day_trades_list.clear(); self.txt_reason.clear(); self.txt_reflection.clear(); self.list_screenshots.clear()
            self.lbl_trade_detail.setText("请在左侧列表选择一笔特定交易..."); self.current_editing_idx = None
            self._render_calendar(); self._render_monthly_charts() 

    # --- 月视图渲染逻辑 (保持不变) ---
    def _render_calendar(self):
        self.review_calendar.clearContents()
        y, m = self.current_review_date.year, self.current_review_date.month
        cal = calendar.monthcalendar(y, m); df = self.current_view_df; daily_stats = {}
        if not df.empty:
            df['day'] = df['exit_time'].dt.day
            for day, group in df.groupby('day'):
                daily_stats[day] = {'net': group['net_profit'].sum(), 'reviewed': any((pd.notna(group['reflection']) & (group['reflection'].str.strip() != '')))}
        for row, week in enumerate(cal):
            for col, day in enumerate(week):
                if day == 0: continue 
                item = QTableWidgetItem(str(day))
                if day in daily_stats:
                    net = daily_stats[day]['net']
                    if net > 0: item.setBackground(QColor("#E8F5E9")); item.setForeground(QColor("#2E7D32")); item.setText(f"{day}\n+{net:,.0f}")
                    elif net < 0: item.setBackground(QColor("#FFEBEE")); item.setForeground(QColor("#C62828")); item.setText(f"{day}\n{net:,.0f}")
                    if daily_stats[day]['reviewed']: item.setText(item.text() + "\n📝")
                else: item.setForeground(QColor("#BDBDBD"))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter); font = QFont(); font.setBold(day in daily_stats); item.setFont(font); item.setData(Qt.ItemDataRole.UserRole, QDate(y, m, day))
                self.review_calendar.setItem(row, col, item)

    def _render_monthly_charts(self):
        self.review_pnl_chart.clear(); self.review_kline_chart.clear(); self.review_duration_chart.clear()
        df = self.current_view_df.copy(); 
        if df.empty: return
        df_sorted = df.sort_values(by='exit_time')
        equity_curve = [0.0] + df_sorted['net_profit'].cumsum().tolist(); x_data = list(range(len(equity_curve)))
        is_prof = equity_curve[-1] >= 0; pen = pg.mkPen(color=(46, 125, 50) if is_prof else (198, 40, 40), width=3); fill = (76, 175, 80, 50) if is_prof else (244, 67, 54, 50)
        self.review_pnl_chart.plot(x_data, equity_curve, pen=pen, fillLevel=0, fillBrush=fill)
        df_sorted['day'] = df_sorted['exit_time'].dt.day; k_data = []; current_equity = 0.0
        for i, (day, group) in enumerate(df_sorted.groupby('day')):
            open_eq = current_equity; high_eq = current_equity; low_eq = current_equity
            for pnl in group['net_profit']:
                current_equity += pnl; high_eq = max(high_eq, current_equity); low_eq = min(low_eq, current_equity)
            k_data.append((i, open_eq, current_equity, low_eq, high_eq))
        if k_data:
            self.review_kline_chart.addItem(CandlestickItem(k_data)); axis = self.review_kline_chart.getAxis('bottom'); axis.setTicks([[(i, f"{day}日") for i, day in enumerate(df_sorted['day'].unique())]])
        durations = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600.0; profits = df['net_profit'].values; spots = []
        for h, p in zip(durations, profits):
            h = max(h, 0); brush = pg.mkBrush(color=(76, 175, 80, 150)) if p > 0 else pg.mkBrush(color=(244, 67, 54, 150))
            spots.append({'pos': (h, p), 'brush': brush, 'pen': None, 'size': 12})
        self.review_duration_chart.addItem(pg.ScatterPlotItem(spots=spots)); self.review_duration_chart.addLine(y=0, pen=pg.mkPen(color='#9E9E9E', style=Qt.PenStyle.DashLine))

    def on_calendar_day_clicked(self, row, col):
        item = self.review_calendar.item(row, col)
        if not item or not item.data(Qt.ItemDataRole.UserRole): return
        qdate = item.data(Qt.ItemDataRole.UserRole); self.lbl_selected_date.setText(f"选定日期: {qdate.toString('yyyy-MM-dd')}")
        self.day_trades_list.clear(); self.txt_reason.clear(); self.txt_reflection.clear(); self.list_screenshots.clear(); self.lbl_trade_detail.setText("请在左侧列表选择一笔特定交易..."); self.current_editing_idx = None
        day_df = self.current_view_df[self.current_view_df['exit_time'].dt.day == qdate.day()]
        for idx, record in day_df.iterrows():
            pnl, sym = record['net_profit'], record['symbol']
            txt = f"{sym} | ￥{'+' if pnl>0 else ''}{pnl:,.2f}" + (" 📝" if pd.notna(record.get('reflection')) and str(record.get('reflection')).strip()!="" else "")
            list_item = QListWidgetItem(txt); list_item.setData(Qt.ItemDataRole.UserRole, idx); list_item.setForeground(QColor("#2E7D32") if pnl > 0 else QColor("#C62828")); self.day_trades_list.addItem(list_item)

    def on_review_trade_selected(self, current, previous):
        if not current: return
        df_idx = current.data(Qt.ItemDataRole.UserRole); record = self.global_df.loc[df_idx]; self.current_editing_idx = df_idx
        pnl = record['net_profit']; duration = (record['exit_time'] - record['entry_time']).total_seconds() / 3600; col_hex = "#2E7D32" if pnl > 0 else "#C62828"
        self.lbl_trade_detail.setText(f"""<span style="font-size:16px;">{record['symbol']}</span><br><span style="color:#757575;">进场: {pd.to_datetime(record['entry_time']).strftime('%m-%d %H:%M')} <br>出场: {pd.to_datetime(record['exit_time']).strftime('%m-%d %H:%M')} (持仓 {duration:.1f} h)</span><br>结果: <b style="color:{col_hex}; font-size:16px;">￥{pnl:,.2f}</b>""")
        self.txt_reason.setPlainText(str(record.get('entry_reason', ''))); self.txt_reflection.setPlainText(str(record.get('reflection', '')))
        self.cb_edit_strategy.blockSignals(True); self.cb_edit_strategy.setCurrentText(str(record.get('strategy_tag', '未分类'))); self.cb_edit_strategy.blockSignals(False)
        self.list_screenshots.clear()
        paths_str = str(record.get('screenshot_paths', ''))
        if paths_str and paths_str != 'nan':
            for p in paths_str.split(';'):
                if os.path.exists(p): self.add_thumbnail(p)

    def silent_update_strategy(self, *args):
        if getattr(self, 'current_editing_idx', None) is None: return
        new_st = self.cb_edit_strategy.currentText().strip(); new_st = "未分类" if new_st == "" else new_st
        old_st = str(self.global_df.at[self.current_editing_idx, 'strategy_tag']).strip()
        if new_st == old_st: return
        self.global_df.at[self.current_editing_idx, 'strategy_tag'] = new_st
        if new_st not in self.global_strategies: self.global_strategies.append(new_st); self.refresh_review_filters()
        self.update_review_view()

    def save_review_text(self):
        if getattr(self, 'current_editing_idx', None) is None: QMessageBox.warning(self, "提示", "请先选择一笔交易！"); return
        self.global_df.at[self.current_editing_idx, 'entry_reason'] = self.txt_reason.toPlainText()
        self.global_df.at[self.current_editing_idx, 'reflection'] = self.txt_reflection.toPlainText()
        self._save_image_paths_to_df(); self.update_review_view(); QMessageBox.information(self, "保存成功", "复盘文字及截图状态已保存。")

    # --- 全新：年视图渲染逻辑 ---
    def _render_yearly_view(self):
        """渲染宏观的年度数据"""
        df = self.current_view_df
        
        # 1. 渲染 12 个月卡片
        monthly_stats = {}
        if not df.empty:
            df['month'] = df['exit_time'].dt.month
            for m, group in df.groupby('month'):
                monthly_stats[m] = group['net_profit'].sum()

        for i in range(12):
            m = i + 1
            card = self.month_cards[i]
            if m in monthly_stats:
                net = monthly_stats[m]
                if net > 0:
                    card.setStyleSheet("background: #E8F5E9; border-radius: 6px; font-size: 16px; font-weight:bold; color: #2E7D32;")
                    card.setText(f"{m}月\n+{net:,.0f}")
                else:
                    card.setStyleSheet("background: #FFEBEE; border-radius: 6px; font-size: 16px; font-weight:bold; color: #C62828;")
                    card.setText(f"{m}月\n{net:,.0f}")
            else:
                card.setStyleSheet("background: #F5F5F5; border-radius: 6px; font-size: 14px; font-weight:bold; color: #9E9E9E;")
                card.setText(f"{m}月\n无交易")

        # 2. 渲染雷达图表
        self.yearly_bar_chart.clear(); self.yearly_curve_chart.clear()
        if df.empty: return
        
        # 右侧：年度净值曲线
        df_sorted = df.sort_values(by='exit_time')
        equity_curve = [0.0] + df_sorted['net_profit'].cumsum().tolist(); x_data = list(range(len(equity_curve)))
        is_prof = equity_curve[-1] >= 0; pen = pg.mkPen(color=(46, 125, 50) if is_prof else (198, 40, 40), width=3); fill = (76, 175, 80, 50) if is_prof else (244, 67, 54, 50)
        self.yearly_curve_chart.plot(x_data, equity_curve, pen=pen, fillLevel=0, fillBrush=fill)
        
        # 左侧：策略利润条形图 (Bar Chart)
        strategy_pnl = df.groupby('strategy_tag')['net_profit'].sum().sort_values()
        y_pos = list(range(len(strategy_pnl)))
        x_vals = strategy_pnl.values.tolist()
        
        # 给大于0和小于0的策略分配不同的颜色
        brushes = [pg.mkBrush('#4CAF50') if x > 0 else pg.mkBrush('#F44336') for x in x_vals]
        
        bar_item = pg.BarGraphItem(x0=0, y=y_pos, width=x_vals, height=0.6, brushes=brushes)
        self.yearly_bar_chart.addItem(bar_item)
        
        # 设置 Y 轴文字标签为策略名称
        ax = self.yearly_bar_chart.getAxis('left')
        ticks = [list(zip(y_pos, strategy_pnl.index.tolist()))]
        ax.setTicks(ticks)
        
        # 加一条 0 轴分界线
        self.yearly_bar_chart.addLine(x=0, pen=pg.mkPen(color='#9E9E9E'))


    # ==========================================
    # 其他冗余代码折叠 (仪表板组件等，保持不变)
    # ==========================================
    def create_metrics_panel(self):
        panel = QWidget(); layout = QVBoxLayout(panel); title_label = QLabel("交易绩效摘要"); title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121; padding: 10px; border-bottom: 2px solid #E0E0E0;"); layout.addWidget(title_label)
        metrics_grid = QGridLayout(); metrics_grid.setSpacing(10)
        self.metric_keys = [("净利润", "net_profit"), ("收益率", "return_rate"), ("胜率", "win_rate"), ("盈亏比", "pl_ratio"), ("最大回撤", "max_drawdown"), ("交易次数", "total_trades"), ("盈利次数", "winning_trades"), ("亏损次数", "losing_trades"), ("初始资金", "initial_capital"), ("总手续费", "total_commission"), ("平均盈利", "avg_win"), ("平均亏损", "avg_loss"), ("最大单笔赚", "max_profit"), ("最大单笔亏", "max_loss")]
        self.metric_widgets = {}
        for i, (label_text, key) in enumerate(self.metric_keys):
            row, col = i // 2, (i % 2) * 2; lbl_name = QLabel(label_text); lbl_name.setStyleSheet("font-size: 12px; color: #757575;"); lbl_value = QLabel("-"); lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            metrics_grid.addWidget(lbl_name, row, col); metrics_grid.addWidget(lbl_value, row, col + 1); self.metric_widgets[key] = lbl_value
        layout.addLayout(metrics_grid); layout.addStretch(); return panel

    def create_charts_panel(self):
        panel = QWidget(); layout = QVBoxLayout(panel); self.equity_chart = pg.PlotWidget(title="资金净值曲线"); self.equity_chart.showGrid(x=True, y=True, alpha=0.3); self.distribution_chart = pg.PlotWidget(title="盈亏分布直方图"); self.distribution_chart.showGrid(x=True, y=True, alpha=0.3); layout.addWidget(self.equity_chart, 2); layout.addWidget(self.distribution_chart, 1); return panel

    def set_metric_style(self, widget, formatted_text, raw_value=None, force_neutral=False, reverse_color=False):
        widget.setText(formatted_text)
        if force_neutral: color, bg_color = "#424242", "#F5F5F5"
        elif raw_value is not None:
            if raw_value == 0: color, bg_color = "#757575", "#F5F5F5"
            elif (raw_value > 0 and not reverse_color) or (raw_value < 0 and reverse_color): color, bg_color = "#4CAF50", "rgba(76, 175, 80, 0.1)"
            else: color, bg_color = "#F44336", "rgba(244, 67, 54, 0.1)"
        else: color, bg_color = "#757575", "#F5F5F5"
        widget.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color}; padding: 5px; background-color: {bg_color}; border-radius: 4px;")

    def update_metrics(self, r):
        m = self.metric_widgets; self.set_metric_style(m["net_profit"], f"￥{r['net_profit']:,.2f}", r['net_profit']); self.set_metric_style(m["avg_win"], f"￥{r['avg_win']:,.2f}", r['avg_win']); self.set_metric_style(m["avg_loss"], f"￥{r['avg_loss']:,.2f}", r['avg_loss']); self.set_metric_style(m["max_profit"], f"￥{r['max_profit']:,.2f}", r['max_profit']); self.set_metric_style(m["max_loss"], f"￥{r['max_loss']:,.2f}", r['max_loss']); self.set_metric_style(m["return_rate"], f"{r['return_rate']*100:.2f}%", r['return_rate']); self.set_metric_style(m["win_rate"], f"{r['win_rate']*100:.2f}%", r['win_rate'] - 0.5); self.set_metric_style(m["max_drawdown"], f"{r['max_drawdown']*100:.2f}%", r['max_drawdown'], reverse_color=True); self.set_metric_style(m["initial_capital"], f"￥{r['initial_capital']:,.2f}", force_neutral=True); self.set_metric_style(m["total_commission"], f"￥{r['total_commission']:,.2f}", force_neutral=True); self.set_metric_style(m["pl_ratio"], f"{r['pl_ratio']:.2f}", force_neutral=True); self.set_metric_style(m["total_trades"], str(r['total_trades']), force_neutral=True); self.set_metric_style(m["winning_trades"], str(r['winning_trades']), force_neutral=True); self.set_metric_style(m["losing_trades"], str(r['losing_trades']), force_neutral=True)

    def update_equity_chart(self, df):
        equity_data = df['equity'].tolist(); x_data = list(range(len(equity_data))); self.equity_chart.clear()
        if not equity_data: return
        is_prof = equity_data[-1] >= equity_data[0]; col = (76, 175, 80) if is_prof else (244, 67, 54); fill = (76, 175, 80, 50) if is_prof else (244, 67, 54, 50)
        self.equity_chart.plot(x_data, equity_data, pen=pg.mkPen(color=col, width=2.5), fillLevel=equity_data[0], fillBrush=fill)

    def update_distribution_chart(self, df):
        profits = df['net_profit'].values; self.distribution_chart.clear()
        if len(profits) > 0:
            hist, bin_edges = np.histogram(profits, bins=25); x_vals, y_vals = [], []
            for i in range(len(bin_edges)-1): x_vals.extend([bin_edges[i], bin_edges[i+1]]); y_vals.extend([hist[i], hist[i]])
            self.distribution_chart.plot(x_vals, y_vals, pen=pg.mkPen(color=(33, 150, 243), width=2), fillLevel=0, fillBrush=pg.mkBrush((33, 150, 243, 100)))

    def populate_records_table(self, df):
        while self.records_tab_widget.count() > 0: self.records_tab_widget.removeTab(0)
        self._create_table_for_tab("全部账户 (总览)", df)
        for acc in df['account'].unique():
            if pd.notna(acc): self._create_table_for_tab(str(acc), df[df['account'] == acc])

    def _create_table_for_tab(self, tab_name, df_subset):
        table = QTableWidget(); table.setColumnCount(9); table.setHorizontalHeaderLabels(["单号", "账户", "品种", "方向", "进场时间", "平仓时间", "手数", "盈亏", "手续费"]); table.horizontalHeader().setStretchLastSection(True); table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); table.setAlternatingRowColors(True); table.setStyleSheet("QTableWidget { background-color: white; alternate-background-color: #FAFAFA; border: none; gridline-color: #EEEEEE; } QHeaderView::section { background-color: #F5F5F5; color: #757575; font-weight: bold; border: none; border-bottom: 1px solid #E0E0E0; padding: 10px; text-align: left; }")
        table.setRowCount(len(df_subset)); df_reversed = df_subset.iloc[::-1].reset_index(drop=True) 
        for row in range(len(df_reversed)):
            record = df_reversed.iloc[row]
            entry_t = record['entry_time'].strftime('%m-%d %H:%M') if pd.notna(record.get('entry_time')) else "-"; exit_t = record['exit_time'].strftime('%m-%d %H:%M') if pd.notna(record.get('exit_time')) else "-"
            items = [QTableWidgetItem(str(record.get('trade_id', '-'))), QTableWidgetItem(str(record.get('account', '-'))), QTableWidgetItem(str(record.get('symbol', '-'))), QTableWidgetItem("做多" if record.get('direction') == 'LONG' else "做空"), QTableWidgetItem(entry_t), QTableWidgetItem(exit_t), QTableWidgetItem(str(record.get('lots', 0))), QTableWidgetItem(f"￥{record.get('net_profit', 0):,.2f}"), QTableWidgetItem(f"￥{record.get('commission', 0):.2f}")]
            items[7].setForeground(QColor("#4CAF50") if record.get('net_profit', 0) > 0 else QColor("#F44336")); items[7].setFont(QFont("Arial", 10, QFont.Weight.Bold))
            for col, item in enumerate(items): item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter); table.setItem(row, col, item)
        self.records_tab_widget.addTab(table, tab_name)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TradingApp()
    window.show()
    sys.exit(app.exec())