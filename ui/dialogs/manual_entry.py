from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QComboBox, QMessageBox, QFormLayout, QLineEdit, 
                             QDateTimeEdit, QDoubleSpinBox, QSpinBox)
from PyQt6.QtCore import QDateTime
from models.trade import TradeRecord
from config import settings

class ManualEntryDialog(QDialog):
    def __init__(self, current_strategies, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✍️ 手工录入交易")
        self.resize(400, 500)
        self.setStyleSheet("QDialog { background-color: #FAFAFA; font-family: -apple-system, sans-serif; } QLabel { font-weight: bold; color: #424242; } QLineEdit, QComboBox, QDateTimeEdit, QDoubleSpinBox, QSpinBox { border: 1px solid #E0E0E0; border-radius: 6px; padding: 6px; background: white; font-size: 14px; }")
        
        self.new_trades = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(15)
        
        self.inp_account = QComboBox()
        self.inp_account.setEditable(True)
        self.inp_account.addItems(settings.DEFAULT_ACCOUNTS)
        form.addRow("归属账户:", self.inp_account)
        
        self.inp_symbol = QLineEdit()
        self.inp_symbol.setPlaceholderText("例如: RB2401")
        form.addRow("交易品种:", self.inp_symbol)
        
        self.inp_direction = QComboBox()
        self.inp_direction.addItems(["做多 (LONG)", "做空 (SHORT)"])
        form.addRow("买卖方向:", self.inp_direction)
        
        self.inp_strategy = QComboBox()
        self.inp_strategy.setEditable(True)
        self.inp_strategy.addItems(current_strategies if current_strategies else [settings.DEFAULT_STRATEGY])
        form.addRow("策略分类:", self.inp_strategy)
        
        self.inp_entry_time = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self.inp_entry_time.setCalendarPopup(True)
        form.addRow("进场时间:", self.inp_entry_time)
        
        self.inp_exit_time = QDateTimeEdit(QDateTime.currentDateTime())
        self.inp_exit_time.setCalendarPopup(True)
        form.addRow("平仓时间:", self.inp_exit_time)
        
        self.inp_lots = QSpinBox()
        self.inp_lots.setRange(1, 100000)
        form.addRow("数量(手/股):", self.inp_lots)
        
        self.inp_pnl = QDoubleSpinBox()
        self.inp_pnl.setRange(-9999999, 9999999)
        self.inp_pnl.setDecimals(2)
        form.addRow("净盈亏:", self.inp_pnl)
        
        self.inp_comm = QDoubleSpinBox()
        self.inp_comm.setRange(0, 999999)
        self.inp_comm.setDecimals(2)
        form.addRow("手续费:", self.inp_comm)
        
        layout.addLayout(form)
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_submit = QPushButton("确认添加")
        btn_submit.setStyleSheet(f"background-color: {settings.COLOR_PROFIT}; color: white; padding: 10px; font-weight: bold; border-radius: 6px;")
        btn_submit.clicked.connect(self.submit_data)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_submit)
        layout.addLayout(btn_layout)
        
    def submit_data(self):
        if not self.inp_symbol.text().strip(): 
            QMessageBox.warning(self, "错误", "品种不能为空！")
            return
            
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