# ui/dialogs/dialogs.py
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                             QListWidget, QListWidgetItem, QWidget, QFileDialog, 
                             QComboBox, QMessageBox, QFormLayout, QScrollArea, 
                             QLineEdit, QDateTimeEdit, QDoubleSpinBox, QSpinBox)
from PyQt6.QtCore import Qt, QDateTime

from data.data_feed import parse_cfmmc_excel
from models.trade import TradeRecord
from config import settings

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
        super().__init__(parent); self.setWindowTitle("数据导入映射向导"); self.resize(500, 600); self.setStyleSheet("QDialog { background-color: white; font-family: -apple-system, sans-serif; }"); self.raw_df = None; self.final_trades = None
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
                        self.final_trades = parse_cfmmc_excel(file_path); self.accept(); return
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
        temp_df = pd.DataFrame(mapped)
        
        temp_df['account'] = temp_df['account'].fillna("自定义导入")
        temp_df['net_profit'] = pd.to_numeric(temp_df['net_profit'], errors='coerce').fillna(0.0)
        temp_df['lots'] = pd.to_numeric(temp_df['lots'], errors='coerce').fillna(1).astype(int)
        temp_df['commission'] = pd.to_numeric(temp_df['commission'], errors='coerce').fillna(0.0)
        
        temp_df['entry_time'] = pd.to_datetime(temp_df['entry_time'], errors='coerce')
        temp_df['exit_time'] = pd.to_datetime(temp_df['exit_time'], errors='coerce')
        temp_df['entry_time'] = temp_df['entry_time'].fillna(temp_df['exit_time'])
        temp_df['exit_time'] = temp_df['exit_time'].fillna(temp_df['entry_time'])

        records = []
        for idx, row in temp_df.iterrows():
            tr = TradeRecord(
                account=str(row['account']),
                symbol=str(row['symbol']) if pd.notna(row['symbol']) else "Unknown",
                direction=str(row['direction']) if pd.notna(row['direction']) else "LONG",
                entry_time=row['entry_time'],
                exit_time=row['exit_time'],
                lots=int(row['lots']),
                net_profit=float(row['net_profit']),
                commission=float(row['commission'])
            )
            if pd.notna(row.get('trade_id')):
                tr.trade_id = str(row['trade_id'])
            records.append(tr)
            
        self.final_trades = records
        self.accept()

class ManualEntryDialog(QDialog):
    def __init__(self, current_strategies, parent=None):
        super().__init__(parent); self.setWindowTitle("手工录入"); self.resize(400, 500); self.setStyleSheet("QDialog { background-color: #FAFAFA; font-family: -apple-system, sans-serif; } QLabel { font-weight: bold; color: #424242; } QLineEdit, QComboBox, QDateTimeEdit, QDoubleSpinBox, QSpinBox { border: 1px solid #E0E0E0; border-radius: 6px; padding: 6px; background: white; font-size: 14px; }")
        self.new_trades = None; layout = QVBoxLayout(self); form = QFormLayout(); form.setSpacing(15)
        self.inp_account = QComboBox(); self.inp_account.setEditable(True); 
        # 【进化】使用配置中心的默认账户
        self.inp_account.addItems(settings.DEFAULT_ACCOUNTS); form.addRow("归属账户:", self.inp_account)
        self.inp_symbol = QLineEdit(); self.inp_symbol.setPlaceholderText("例如: RB2401"); form.addRow("交易品种:", self.inp_symbol)
        self.inp_direction = QComboBox(); self.inp_direction.addItems(["做多 (LONG)", "做空 (SHORT)"]); form.addRow("买卖方向:", self.inp_direction)
        self.inp_strategy = QComboBox(); self.inp_strategy.setEditable(True); 
        # 【进化】使用配置中心的默认策略
        self.inp_strategy.addItems(current_strategies if current_strategies else [settings.DEFAULT_STRATEGY]); form.addRow("策略分类:", self.inp_strategy)
        self.inp_entry_time = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1)); self.inp_entry_time.setCalendarPopup(True); form.addRow("进场时间:", self.inp_entry_time)
        self.inp_exit_time = QDateTimeEdit(QDateTime.currentDateTime()); self.inp_exit_time.setCalendarPopup(True); form.addRow("平仓时间:", self.inp_exit_time)
        self.inp_lots = QSpinBox(); self.inp_lots.setRange(1, 1000); form.addRow("手数:", self.inp_lots)
        self.inp_pnl = QDoubleSpinBox(); self.inp_pnl.setRange(-9999999, 9999999); self.inp_pnl.setDecimals(2); form.addRow("净盈亏:", self.inp_pnl)
        self.inp_comm = QDoubleSpinBox(); self.inp_comm.setRange(0, 999999); self.inp_comm.setDecimals(2); form.addRow("手续费:", self.inp_comm)
        layout.addLayout(form); layout.addStretch(); btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消"); btn_cancel.clicked.connect(self.reject); btn_submit = QPushButton("确认添加"); btn_submit.setStyleSheet(f"background-color: {settings.COLOR_PROFIT}; color: white; padding: 10px; font-weight: bold; border-radius: 6px;"); btn_submit.clicked.connect(self.submit_data)
        btn_layout.addWidget(btn_cancel); btn_layout.addWidget(btn_submit); layout.addLayout(btn_layout)
        
    def submit_data(self):
        if not self.inp_symbol.text().strip(): QMessageBox.warning(self, "错误", "品种不能为空！"); return
        record = TradeRecord(
            account=self.inp_account.currentText().strip(),
            symbol=self.inp_symbol.text().strip(),
            direction='LONG' if '多' in self.inp_direction.currentText() else 'SHORT',
            entry_time=self.inp_entry_time.dateTime().toPyDateTime(),
            exit_time=self.inp_exit_time.dateTime().toPyDateTime(),
            lots=self.inp_lots.value(),
            net_profit=self.inp_pnl.value(),
            commission=self.inp_comm.value(),
            strategy_tag=self.inp_strategy.currentText().strip()
        )
        self.new_trades = [record]
        self.accept()