# ui/dialogs/manual_entry.py
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QComboBox, QMessageBox, QFormLayout, QLineEdit,
                             QDateTimeEdit, QDoubleSpinBox, QSpinBox, QLabel)
from PyQt6.QtCore import QDateTime
from models.trade import TradeRecord
from core.preferences import TIME_SOURCE_DATE_ONLY, TIME_SOURCE_MANUAL
from config import settings

# 输入控件样式说明：
#  - QLineEdit/QComboBox/QDateTimeEdit 用 QSS 统一圆角边框。
#  - QSpinBox/QDoubleSpinBox 刻意【不写任何样式规则】：
#    一旦给微调框父控件写 border/padding 或只写一半子控件规则，Qt 就会切换到
#    "样式化绘制"路径，导致 up/down 箭头丢失、背景/边框异常（透明+只剩分隔线）。
#    不写规则则保持系统原生渲染：白底、清晰箭头、整块可点，最稳妥。
_INPUT_QSS = """
QDialog { background-color: #FAFAFA; font-family: -apple-system, sans-serif; }
QLabel { font-weight: bold; color: #424242; }

QLineEdit, QComboBox, QDateTimeEdit {
    border: 1px solid #E0E0E0; border-radius: 6px;
    padding: 6px; background: white; font-size: 14px;
}

QComboBox::drop-down, QDateTimeEdit::drop-down {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 26px; border: none; border-left: 1px solid #E0E0E0;
}
"""


class ManualEntryDialog(QDialog):
    """
    手工录入一笔已闭环交易。

    v1.1 起只保留单一"交易时间"：现实中交易记录只存在一个成交/结算时间点。
    v1.2.1 改进：
      - 归属账户只列出"已经存在的账户"（来自已导入数据），可继续输入新名称创建；
        不再预置"国内长线/国内短线"这类空洞的虚构账户。
      - 手工录入是用户主动填写的结果记录，不存在"开仓腿配对"概念，
        因此不受孤儿（待缝合）语义约束 —— 价格可留空显示为「—」即可。
    """
    def __init__(self, current_strategies, existing_accounts=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✍️ 手工录入交易")
        self.resize(420, 500)
        self.setStyleSheet(_INPUT_QSS)

        existing_accounts = [
            str(a) for a in (existing_accounts or []) if str(a).strip()
        ]

        self.new_trades = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(14)

        # ---- 归属账户：仅列出现有账户，可自由输入新账户名 ----
        self.inp_account = QComboBox()
        self.inp_account.setEditable(True)
        self.inp_account.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.inp_account.addItems(existing_accounts)
        self.inp_account.lineEdit().setPlaceholderText(
            "从下拉选择已有账户，或直接输入新账户名")
        form.addRow("归属账户*:", self.inp_account)

        # 新用户引导：没有账户时明确告知可直接输入名称创建
        self.lbl_account_hint = QLabel()
        self.lbl_account_hint.setWordWrap(True)
        self.lbl_account_hint.setStyleSheet(
            "font-size: 11px; font-weight: normal; color: #1976D2; "
            "background: #E3F2FD; border-radius: 4px; padding: 5px 8px;")
        form.addRow("", self.lbl_account_hint)
        if existing_accounts:
            self.lbl_account_hint.setText(
                f"已找到 {len(existing_accounts)} 个账户：点右侧 ▾ 下拉选择即可；"
                "如果要新建账户，直接输入新名称，保存后会自动创建。")
        else:
            self.lbl_account_hint.setText(
                "还没有任何账户：直接在上方输入一个账户名（例如：我的期货账户），"
                "保存后系统会自动创建该账户。")

        self.inp_symbol = QLineEdit()
        self.inp_symbol.setPlaceholderText("例如: RB2401")
        form.addRow("交易品种*:", self.inp_symbol)

        self.inp_direction = QComboBox()
        self.inp_direction.addItems(["做多 (LONG)", "做空 (SHORT)"])
        form.addRow("买卖方向:", self.inp_direction)

        self.inp_strategy = QComboBox()
        self.inp_strategy.setEditable(True)
        self.inp_strategy.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        strategy_options = current_strategies if current_strategies else [settings.DEFAULT_STRATEGY]
        self.inp_strategy.addItems(strategy_options)
        if strategy_options:
            self.inp_strategy.setCurrentText(strategy_options[0])
        form.addRow("策略分类:", self.inp_strategy)

        self.inp_time = QDateTimeEdit(QDateTime.currentDateTime())
        self.inp_time.setCalendarPopup(True)
        self.inp_time.setDisplayFormat("yyyy-MM-dd HH:mm")
        form.addRow("交易时间:", self.inp_time)

        # v1.2：价格属选填项。填了就能计算点数盈亏，留空按"无价格"显示。
        # 手工录入是直接填写结果，不是开平仓配对，因此不产生孤儿标记。
        self.inp_entry_price = QDoubleSpinBox()
        self.inp_entry_price.setRange(0, 99999999)
        self.inp_entry_price.setDecimals(2)
        self.inp_entry_price.setSpecialValueText("留空")
        form.addRow("开仓价 (选填):", self.inp_entry_price)

        self.inp_exit_price = QDoubleSpinBox()
        self.inp_exit_price.setRange(0, 99999999)
        self.inp_exit_price.setDecimals(2)
        self.inp_exit_price.setSpecialValueText("留空")
        form.addRow("平仓价 (选填):", self.inp_exit_price)

        self.inp_lots = QSpinBox()
        self.inp_lots.setRange(1, 100000)
        self.inp_lots.setValue(1)
        form.addRow("数量(手/股):", self.inp_lots)

        self.inp_pnl = QDoubleSpinBox()
        self.inp_pnl.setRange(-999999999, 999999999)
        self.inp_pnl.setDecimals(2)
        form.addRow("净盈亏*:", self.inp_pnl)

        self.inp_comm = QDoubleSpinBox()
        self.inp_comm.setRange(0, 99999999)
        self.inp_comm.setDecimals(2)
        form.addRow("手续费:", self.inp_comm)

        layout.addLayout(form)
        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("padding: 10px 18px;")
        btn_cancel.clicked.connect(self.reject)

        btn_submit = QPushButton("确认添加")
        btn_submit.setStyleSheet(
            f"background-color: {settings.COLOR_PROFIT}; color: white; "
            f"padding: 10px 18px; font-weight: bold; border-radius: 6px;")
        btn_submit.clicked.connect(self.submit_data)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_submit)
        layout.addLayout(btn_layout)

    def submit_data(self):
        account = self.inp_account.currentText().strip()
        symbol = self.inp_symbol.text().strip()
        if not account:
            QMessageBox.warning(self, "账户不能为空",
                                "请选择已有账户，或直接输入一个新的账户名。")
            return
        if not symbol:
            QMessageBox.warning(self, "错误", "品种不能为空！")
            return

        # 价格为 0 即代表"未填写"（控件上显示为「留空」），落库为 NULL
        entry_price = self.inp_entry_price.value() or None
        exit_price = self.inp_exit_price.value() or None

        # 用户若在时间控件里填了具体时分，那属于本人填写的真实信息（非程序虚构），
        # 如实记录为 MANUAL 来源；停留在零点则按纯日期处理。
        qtime = self.inp_time.time()
        has_clock = bool(qtime.hour() or qtime.minute() or qtime.second())
        fill_time = qtime.toString("HH:mm:ss") if has_clock else ""

        record = TradeRecord(
            account=account,
            symbol=symbol,
            direction='LONG' if '多' in self.inp_direction.currentText() else 'SHORT',
            trade_time=self.inp_time.dateTime().toPyDateTime(),
            lots=self.inp_lots.value(),
            net_profit=self.inp_pnl.value(),
            commission=self.inp_comm.value(),
            strategy_tag=self.inp_strategy.currentText().strip() or settings.DEFAULT_STRATEGY,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_fill_time=fill_time,
            time_source=TIME_SOURCE_MANUAL if has_clock else TIME_SOURCE_DATE_ONLY,
        )
        self.new_trades = [record]
        self.accept()
