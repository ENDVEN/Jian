import pandas as pd
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                             QWidget, QFileDialog, QComboBox, QMessageBox, QFormLayout, QScrollArea)
from models.trade import TradeRecord

class ImportWizardDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📈 股票 / 通用数据映射向导")
        self.resize(500, 600)
        self.setStyleSheet("QDialog { background-color: white; font-family: -apple-system, sans-serif; }")
        
        self.raw_df = None
        self.final_trades = None
        
        self.target_fields = {
            "trade_id": {"label": "交易单号", "keywords": ["成交号", "单号", "编号", "Ticket"]}, 
            "account": {"label": "所属账户", "keywords": ["账户", "Account", "资金账号"]}, 
            "symbol": {"label": "交易品种 (必选)", "keywords": ["证券名称", "股票", "合约", "品种", "Symbol"]}, 
            "direction": {"label": "多空方向", "keywords": ["买卖", "操作", "方向", "Action"]}, 
            "entry_time": {"label": "开仓时间", "keywords": ["开仓时间", "买入时间", "成交时间"]}, 
            "exit_time": {"label": "平仓时间", "keywords": ["平仓时间", "卖出时间", "日期", "成交日期"]}, 
            "lots": {"label": "交易数量(股/手)", "keywords": ["手数", "成交量", "成交数量", "Qty"]}, 
            "net_profit": {"label": "净盈亏 (必选)", "keywords": ["平仓盈亏", "发生金额", "净盈亏", "PnL"]}, 
            "commission": {"label": "手续费", "keywords": ["手续费", "佣金", "印花税", "Commission"]}
        }
        
        layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        self.lbl_file = QLabel("请选择包含交易记录的数据表:")
        self.btn_select = QPushButton("浏览文件")
        self.btn_select.setStyleSheet("padding: 5px 15px; background: #EEEEEE; border-radius: 4px; font-weight: bold;")
        self.btn_select.clicked.connect(self.select_file)
        
        top_layout.addWidget(self.lbl_file)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_select)
        layout.addLayout(top_layout)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.form_widget = QWidget()
        self.form_layout = QFormLayout(self.form_widget)
        
        self.comboboxes = {}
        for key, config in self.target_fields.items(): 
            cb = QComboBox()
            cb.setMinimumWidth(200)
            cb.addItem("-- 请选择对应的列 --", None)
            self.comboboxes[key] = cb
            self.form_layout.addRow(config["label"], cb)
            
        self.scroll_area.setWidget(self.form_widget)
        layout.addWidget(self.scroll_area)
        
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_import = QPushButton("确认映射并导入")
        self.btn_import.setStyleSheet("background-color: #1976D2; color: white; padding: 8px 20px; font-weight: bold; border-radius: 4px;")
        self.btn_import.clicked.connect(self.process_import)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_import)
        layout.addLayout(btn_layout)
        
    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择数据文件", "", "Excel/CSV Files (*.csv *.xls *.xlsx)")
        if not file_path: return
        self.lbl_file.setText(f"已选: {file_path.split('/')[-1]}")
        
        try:
            if file_path.endswith('.csv'): self.raw_df = pd.read_csv(file_path, encoding='utf-8-sig')
            else: self.raw_df = pd.read_excel(file_path)
                
            for key, cb in self.comboboxes.items():
                cb.clear(); cb.addItem("-- 请选择 / 留空 --", None)
                best = 0
                for i, header in enumerate(self.raw_df.columns):
                    cb.addItem(str(header), header)
                    for kw in self.target_fields[key]["keywords"]:
                        if kw in str(header): best = i + 1; break
                cb.setCurrentIndex(best)
        except Exception as e: 
            QMessageBox.critical(self, "错误", f"读取文件失败: {str(e)}")
        
    def process_import(self):
        if self.raw_df is None: return
        
        mapped = {k: self.raw_df[cb.currentData()] if cb.currentData() else None for k, cb in self.comboboxes.items()}
        temp_df = pd.DataFrame(mapped)
        
        temp_df['account'] = temp_df['account'].fillna("自定义股票/外部账户")
        temp_df['net_profit'] = pd.to_numeric(temp_df['net_profit'], errors='coerce').fillna(0.0)
        temp_df['lots'] = pd.to_numeric(temp_df['lots'], errors='coerce').fillna(1).astype(int)
        temp_df['commission'] = pd.to_numeric(temp_df['commission'], errors='coerce').fillna(0.0)
        
        temp_df['entry_time'] = pd.to_datetime(temp_df['entry_time'], errors='coerce')
        temp_df['exit_time'] = pd.to_datetime(temp_df['exit_time'], errors='coerce')
        temp_df['entry_time'] = temp_df['entry_time'].fillna(temp_df['exit_time'])
        temp_df['exit_time'] = temp_df['exit_time'].fillna(temp_df['entry_time'])

        records = []
        for idx, row in temp_df.iterrows():
            dir_str = str(row['direction']) if pd.notna(row['direction']) else ""
            direction = 'LONG' if '买' in dir_str or '多' in dir_str else 'SHORT'
            
            tr = TradeRecord(
                account=str(row['account']), symbol=str(row['symbol']) if pd.notna(row['symbol']) else "Unknown",
                direction=direction, entry_time=row['entry_time'], exit_time=row['exit_time'],
                lots=int(row['lots']), net_profit=float(row['net_profit']), commission=float(row['commission'])
            )
            if pd.notna(row.get('trade_id')): tr.trade_id = str(row['trade_id'])
            records.append(tr)
            
        self.final_trades = records
        self.accept()