# ui/dialogs/import_stocks.py
import os
import pandas as pd
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                             QWidget, QFileDialog, QComboBox, QMessageBox, QFormLayout, QScrollArea)
from models.trade import TradeRecord

# 未映射账户列时使用的兜底账户名
DEFAULT_ACCOUNT = "自定义股票/外部账户"

# 【数据完整性】品种/净盈亏/交易时间是复盘的地基，缺失则拒绝导入
REQUIRED_FIELDS = ('symbol', 'net_profit', 'trade_time')

PLACEHOLDER = "-- 请选择 / 留空 --"


class ImportWizardDialog(QDialog):
    """
    通用外部数据映射向导。
    把券商导出的任意表格字段，手动绑定到系统的标准交易契约上。
    """
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
            "trade_time": {"label": "交易时间 (必选)", "keywords": ["交易时间", "成交日期", "成交时间", "日期", "Time"]}, 
            "lots": {"label": "交易数量(股/手)", "keywords": ["手数", "成交量", "成交数量", "Qty"]}, 
            "net_profit": {"label": "净盈亏 (必选)", "keywords": ["平仓盈亏", "发生金额", "净盈亏", "PnL"]}, 
            "commission": {"label": "手续费", "keywords": ["手续费", "佣金", "印花税", "Commission"]},
            # v1.2 选填：映射后可计算点数盈亏；留空则如实标记为待补录
            "entry_price": {"label": "开仓价 (选填)", "keywords": ["开仓价", "买入价", "成本价", "Entry"]},
            "exit_price": {"label": "平仓价 (选填)", "keywords": ["平仓价", "卖出价", "成交价", "Exit"]}
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
            cb.addItem(PLACEHOLDER, None)
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
        # 使用 basename 而非手工切分，兼容 Windows 与 POSIX 两种路径分隔符
        self.lbl_file.setText(f"已选: {os.path.basename(file_path)}")
        
        try:
            if file_path.lower().endswith('.csv'):
                self.raw_df = pd.read_csv(file_path, encoding='utf-8-sig')
            else:
                self.raw_df = pd.read_excel(file_path)
        except Exception as e: 
            self.raw_df = None
            QMessageBox.critical(self, "错误", f"读取文件失败: {str(e)}")
            return
            
        for key, cb in self.comboboxes.items():
            cb.clear(); cb.addItem(PLACEHOLDER, None)
            best = 0
            for i, header in enumerate(self.raw_df.columns):
                cb.addItem(str(header), header)
                for kw in self.target_fields[key]["keywords"]:
                    if kw in str(header): best = i + 1; break
            cb.setCurrentIndex(best)
        
    def process_import(self):
        if self.raw_df is None:
            QMessageBox.warning(self, "提示", "请先选择要导入的数据文件。")
            return
        
        # 【必选校验】缺少品种或盈亏，复盘统计将失去意义
        missing = [
            self.target_fields[key]["label"]
            for key in REQUIRED_FIELDS
            if not self.comboboxes[key].currentData()
        ]
        if missing:
            QMessageBox.warning(self, "字段缺失", "以下必选字段尚未映射：\n· " + "\n· ".join(missing))
            return
        
        try:
            records, skipped = self._build_records()
        except Exception as e:
            QMessageBox.critical(self, "解析失败", f"映射过程中发生错误：\n{str(e)}")
            return
            
        if not records:
            QMessageBox.warning(self, "无有效数据", "未能从当前映射结果中解析出任何有效交易。")
            return
            
        if skipped:
            QMessageBox.information(
                self, "部分跳过",
                f"有 {skipped} 行因缺少有效交易时间而被跳过。\n"
                f"(复盘日历与交易回放都依赖交易时间，无时间的记录无法定位)"
            )
            
        self.final_trades = records
        self.accept()
        
    def _build_records(self):
        """按当前映射构建 TradeRecord 列表，返回 (记录列表, 被跳过的行数)"""
        mapped = {
            key: (self.raw_df[cb.currentData()] if cb.currentData() else None)
            for key, cb in self.comboboxes.items()
        }
        temp_df = pd.DataFrame(mapped)
        
        temp_df['account'] = temp_df['account'].fillna(DEFAULT_ACCOUNT)
        temp_df['net_profit'] = pd.to_numeric(temp_df['net_profit'], errors='coerce').fillna(0.0)
        temp_df['lots'] = pd.to_numeric(temp_df['lots'], errors='coerce').fillna(1).astype(int)
        temp_df['commission'] = pd.to_numeric(temp_df['commission'], errors='coerce').fillna(0.0)
        # v1.2 价格列：未映射 / 脏数据保持 NaN，绝不用 0 冒充真实成交价
        temp_df['entry_price'] = pd.to_numeric(temp_df['entry_price'], errors='coerce')
        temp_df['exit_price'] = pd.to_numeric(temp_df['exit_price'], errors='coerce')
        
        # v1.1：交割单只有单一"交易时间"，无需再做双时间互补
        temp_df['trade_time'] = pd.to_datetime(temp_df['trade_time'], errors='coerce')
        
        # 【关键防御】交易时间无效的行必须剔除，
        # 否则 TradeRecord 生成 internal_id 时调用 NaT.strftime() 会直接崩溃。
        has_valid_time = temp_df['trade_time'].notna()
        skipped = int((~has_valid_time).sum())
        temp_df = temp_df[has_valid_time]
        
        records = []
        for _, row in temp_df.iterrows():
            dir_str = str(row['direction']) if pd.notna(row['direction']) else ""
            direction = 'LONG' if ('买' in dir_str or '多' in dir_str) else 'SHORT'

            # v1.2 价格：NaN 视为"未提供"，显示为「—」。
            # 注意：孤儿(待缝合)是交割单开平配对的专属语义，映射导入不参与。
            entry_price = float(row['entry_price']) if pd.notna(row['entry_price']) else None
            exit_price = float(row['exit_price']) if pd.notna(row['exit_price']) else None

            tr = TradeRecord(
                account=str(row['account']),
                symbol=str(row['symbol']) if pd.notna(row['symbol']) else "Unknown",
                direction=direction,
                trade_time=row['trade_time'].to_pydatetime(),
                lots=int(row['lots']),
                net_profit=float(row['net_profit']),
                commission=float(row['commission']),
                entry_price=entry_price,
                exit_price=exit_price,
            )
            if pd.notna(row.get('trade_id')):
                tr.trade_id = str(row['trade_id'])
            records.append(tr)
            
        return records, skipped
