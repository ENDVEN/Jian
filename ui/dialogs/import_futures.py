from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal
from data.data_feed import parse_cfmmc_excel

class FuturesImportWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths

    def run(self):
        try:
            all_trades = []
            for file_path in self.file_paths:
                trades = parse_cfmmc_excel(file_path)
                all_trades.extend(trades)
            self.finished.emit(all_trades)
        except Exception as e:
            self.error.emit(str(e))

class FuturesImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📥 导入期货交割单 (CFMMC)")
        self.resize(450, 200)
        self.setStyleSheet("QDialog { background-color: white; font-family: -apple-system, sans-serif; }")
        
        self.final_trades = None
        layout = QVBoxLayout(self)
        
        self.lbl_info = QLabel("请选择由监控中心导出的 Excel 结算单。\n系统支持一次性选择多月的数据，并在后台自动进行缝合并拆单去重。")
        self.lbl_info.setStyleSheet("color: #616161; font-size: 13px; margin-bottom: 15px;")
        layout.addWidget(self.lbl_info)
        
        self.lbl_status = QLabel("等待选择文件...")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #1976D2;")
        layout.addWidget(self.lbl_status)
        
        layout.addStretch()
        
        btn_layout = QHBoxLayout()
        self.btn_select = QPushButton("浏览并解析文件")
        self.btn_select.setStyleSheet("background-color: #1976D2; color: white; padding: 10px; font-weight: bold; border-radius: 6px;")
        self.btn_select.clicked.connect(self.select_and_process_file)
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_select)
        layout.addLayout(btn_layout)

    def select_and_process_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "选择交割单(可多选)", "", "Excel Files (*.xls *.xlsx)")
        if not file_paths: return
            
        self.btn_select.setEnabled(False)
        self.lbl_status.setText(f"⏳ 正在后台解析 {len(file_paths)} 个文件，请稍候...")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #FF9800;")
        
        self.worker = FuturesImportWorker(file_paths)
        self.worker.finished.connect(self.on_process_success)
        self.worker.error.connect(self.on_process_error)
        self.worker.start()

    def on_process_success(self, trades):
        self.final_trades = trades
        QMessageBox.information(self, "解析成功", f"成功解析并匹配了 {len(trades)} 笔闭环交易记录！\n(如果有过月历史持仓，多次导入也绝不会重复)")
        self.accept()

    def on_process_error(self, error_msg):
        self.btn_select.setEnabled(True)
        self.lbl_status.setText("❌ 解析失败")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #F44336;")
        QMessageBox.critical(self, "数据解析错误", f"无法正确解析交割单格式，报错信息：\n{error_msg}")