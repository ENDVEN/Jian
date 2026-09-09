# ui/dialogs/import_futures.py
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QFileDialog, QMessageBox, QRadioButton, QGroupBox)

from core.preferences import (
    TIME_PRECISION_DATE,
    TIME_PRECISION_FILL,
    preferences,
)
# 【架构纪律 v5.12 · §9-O2】线程一律用 ui/workers.py 的，弹窗不自造 QThread
from ui.workers import FuturesImportWorker

# 时间精度偏好的人类可读名称
_PRECISION_TITLE = {
    TIME_PRECISION_DATE: "日期优先（只显示到某一天）",
    TIME_PRECISION_FILL: "精确到时分（显示真实成交时刻）",
}


class FuturesImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_win = parent
        self.setWindowTitle("📥 导入期货交割单 (CFMMC)")
        self.resize(540, 470)
        self.setStyleSheet("QDialog { background-color: white; font-family: -apple-system, sans-serif; }")

        self.parsed_result = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        self.lbl_info = QLabel(
            "请选择由监控中心导出的 Excel 结算单。\n"
            "系统支持一次选择多月数据，并在后台按真实成交时间全局排序后缝合，"
            "因此分批导入与一次性导入的结果完全一致。"
        )
        self.lbl_info.setStyleSheet("color: #616161; font-size: 13px;")
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

        self._build_precision_block(layout)

        self.lbl_status = QLabel("等待选择文件...")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #1976D2;")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet("padding: 10px 18px;")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_select = QPushButton("浏览并解析文件")
        self.btn_select.setStyleSheet(
            "background-color: #1976D2; color: white; padding: 10px 18px; "
            "font-weight: bold; border-radius: 6px;"
        )
        self.btn_select.clicked.connect(self.select_and_process_file)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_select)
        layout.addLayout(btn_layout)

        self._sync_precision_state()

    # ==========================================
    # 时间精度选择区
    # ==========================================
    def _build_precision_block(self, layout):
        """
        【产品决策】不替用户预设默认值 —— 首次导入必须由其本人做出选择，
        同时保留"修改"入口，让高频用户随时能切换到精确时分（反之亦然）。

        两种选择都不影响任何盈亏数字，切换零成本（原始时刻始终完整入库），
        这一点在提示文案中明确告知，消除用户的选择焦虑。
        """
        summary_row = QHBoxLayout()
        self.lbl_precision = QLabel()
        self.lbl_precision.setStyleSheet("color: #424242; font-size: 13px;")

        self.btn_change = QPushButton("修改")
        self.btn_change.setStyleSheet(
            "QPushButton { border: 1px solid #BBDEFB; color: #1976D2; background: white; "
            "border-radius: 4px; padding: 4px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #E3F2FD; }"
        )
        self.btn_change.clicked.connect(self._expand_precision)

        summary_row.addWidget(self.lbl_precision)
        summary_row.addStretch()
        summary_row.addWidget(self.btn_change)
        layout.addLayout(summary_row)

        self.precision_box = QGroupBox("⏱ 时间精度（首次导入请选择，之后随时可改）")
        self.precision_box.setStyleSheet(
            "QGroupBox { border: 1px solid #E0E0E0; border-radius: 6px; margin-top: 8px; "
            "font-weight: bold; color: #424242; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }"
        )
        box = QVBoxLayout(self.precision_box)
        box.setContentsMargins(14, 14, 14, 12)

        self.rb_date = QRadioButton("日期优先　——　适合波段 / 长线")
        self.rb_fill = QRadioButton("精确到时分　——　适合日内 / 高频")
        for rb in (self.rb_date, self.rb_fill):
            rb.setStyleSheet("font-size: 13px; font-weight: normal; color: #212121; padding: 4px;")
        box.addWidget(self.rb_date)
        box.addWidget(self.rb_fill)

        tip = QLabel(
            "· 日期优先：交易只呈现到「某一天」，界面更清爽\n"
            "· 精确到时分：保留真实成交时刻 (如 10:34:51)，同日多笔按先后排序，"
            "并可统计持仓时长\n\n"
            "ℹ️ 该选择只影响时间的显示粒度，不改变任何盈亏数字。\n"
            "　 交割单的原始成交时刻始终完整保存在数据库中，\n"
            "　 之后可随时在「交易流水 → ⏱ 时刻」中切换，无需重新导入。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #9E9E9E; font-size: 12px; padding: 8px 2px 2px 2px;")
        box.addWidget(tip)

        layout.addWidget(self.precision_box)

        self.rb_date.toggled.connect(
            lambda on: on and self._choose_precision(TIME_PRECISION_DATE))
        self.rb_fill.toggled.connect(
            lambda on: on and self._choose_precision(TIME_PRECISION_FILL))

    def _sync_precision_state(self):
        first_time = preferences.needs_time_precision_choice()

        self.precision_box.setVisible(first_time)
        self.lbl_precision.setVisible(not first_time)
        self.btn_change.setVisible(not first_time)

        if not first_time:
            self.lbl_precision.setText(f"⏱ 时间精度：{_PRECISION_TITLE[preferences.time_precision]}")
            current = preferences.time_precision
            for rb in (self.rb_date, self.rb_fill):
                rb.blockSignals(True)
            self.rb_date.setChecked(current == TIME_PRECISION_DATE)
            self.rb_fill.setChecked(current == TIME_PRECISION_FILL)
            for rb in (self.rb_date, self.rb_fill):
                rb.blockSignals(False)

        # 【首次导入】禁用"浏览"按钮直到用户做出选择，确保这个决定不会被跳过
        self.btn_select.setEnabled(not first_time)
        if first_time:
            self.lbl_status.setText("👉 请先在上方的「时间精度」中做出选择，然后再选择文件。")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #FF9800;")

    def _choose_precision(self, value: str):
        preferences.set_time_precision(value)
        self.btn_select.setEnabled(True)
        if self.lbl_status.text().startswith("👉"):
            self.lbl_status.setText("等待选择文件...")
            self.lbl_status.setStyleSheet("font-weight: bold; color: #1976D2;")

    def _expand_precision(self):
        """点击「修改」重新展开选择区，给主流软件都具备的"反悔"机会"""
        self.precision_box.setVisible(True)
        self.btn_change.setVisible(False)

    # ==========================================
    # 文件选择与后台解析
    # ==========================================
    def select_and_process_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择交割单(可多选)", "", "Excel Files (*.xls *.xlsx)")
        if not file_paths: return

        self.btn_select.setEnabled(False)
        self.lbl_status.setText(f"⏳ 正在后台解析 {len(file_paths)} 个文件，请稍候...")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #FF9800;")

        self.worker = FuturesImportWorker(self.main_win.engine, file_paths, self)
        self.worker.finished.connect(self.on_process_success)
        self.worker.error.connect(self.on_process_error)
        self.worker.start()

    def on_process_success(self, result):
        self.parsed_result = result
        rep = result['report']

        msg = (f"成功解析并匹配了 {rep['closed_trades']} 笔闭环交易！\n\n"
               f"📅 覆盖月份：{', '.join(rep['months']) or '—'}\n"
               f"📄 成交明细：{rep['parsed_fills']} 行（跳过 {rep['skipped_rows']} 行无效数据）\n"
               f"📌 月末未平持仓：{rep['open_legs']} 条（已结转至下次导入）")

        if rep['orphan_closes']:
            msg += (f"\n\n⚠️ 有 {rep['orphan_closes']} 笔平仓在本机找不到对应开仓记录，"
                    f"已标记为「待缝合」，开仓价将显示为「—」。\n"
                    f"若这些仓位建于更早月份，请先导入更早的交割单，系统会自动补全。")

        QMessageBox.information(self, "解析成功", msg)
        self.accept()

    def on_process_error(self, error_msg):
        self.btn_select.setEnabled(True)
        self.lbl_status.setText("❌ 解析失败")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #F44336;")
        QMessageBox.critical(self, "数据解析错误", f"无法正确解析交割单格式，报错信息：\n{error_msg}")
