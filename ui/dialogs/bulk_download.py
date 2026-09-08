# ui/dialogs/bulk_download.py
"""
批量预下载弹窗 (v5.8 · §7-A3)。

【产品口径（用户明确要求）】
  大量数据下载会占用用户很长时间，因此**必须让用户自己选择范围**：
  既保留"秒出"的快速来源（指数预设 / 指数成分股 / 粘贴代码列表），
  也保留"全市场"的完整能力；同时抓取手段必须温柔，避免用户被封 IP 或触发限流。

【温柔抓取的三道保险】
  1. 可调间隔 + 随机抖动：打散"机器人固定频率"特征；
  2. 失败指数退避重试：偶发抖动自己扛过去；
  3. 连续失败熔断：达到阈值立即停手，判定"疑似被限流"，保护用户 IP。
  另外「跳过已最新」实现断点续传：中断后重跑不会重复劳动。

本弹窗只做参数收集与进度展示，真正干活的是 ui/workers.SyncWorker
→ data/sync_service.MarketSyncService。
"""
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QRadioButton, QButtonGroup, QPlainTextEdit,
                             QCheckBox, QProgressBar, QListWidget,
                             QPushButton, QMessageBox, QApplication, QFrame)

from data.akshare_feed import INDEX_PRESETS
from data.sync_service import (ThrottlePolicy, ZONE_KLINE, ZONE_INDEX,
                               estimate_seconds)
from ui.widgets.custom_widgets import (NoWheelComboBox, NoWheelDateEdit,
                                       NoWheelDoubleSpinBox, NoWheelSpinBox)
from ui.workers import SyncWorker

# 成分股可选指数（代码 -> 展示名）
CONSTITUENT_INDEXES = {
    "000300": "沪深300",
    "000905": "中证500",
    "000016": "上证50",
    "000852": "中证1000",
    "399006": "创业板指",
}

_FLAT_BTN = ("QPushButton { color:#1976D2; background:transparent; border:none; "
             "padding:0 10px; font-weight:bold; border-radius:6px; }"
             "QPushButton:hover { background:#EEF4FD; }"
             "QPushButton:disabled { color:#B4BECB; }")


class _ConstituentsWorker(QThread):
    """解析指数成分股（网络操作，必须后台执行）"""

    finished_signal = pyqtSignal(object)   # list[str]

    def __init__(self, index_code: str, parent=None):
        super().__init__(parent)
        self._code = index_code

    def run(self):
        from data.akshare_feed import AkShareFeed
        try:
            df = AkShareFeed.fetch_index_constituents(self._code)
        except Exception:
            df = None
        self.finished_signal.emit(
            [] if df is None or df.empty else df["symbol"].tolist())


class BulkDownloadDialog(QDialog):
    """批量预下载：选来源 → 调参数 → 看进度 → 可中断"""

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self._symbols: list[str] = []
        self._failures: list[str] = []
        self._zone = ZONE_KLINE
        self._worker: SyncWorker | None = None
        self._cons_worker: _ConstituentsWorker | None = None
        self._cons_token = 0   # 成分股请求序号：快速连点时只接受最后一次的结果

        self.setWindowTitle("⬇ 批量预下载")
        self.resize(640, 620)
        self._setup_ui()
        self._sync_source_ui()

    # ==========================================
    # UI
    # ==========================================
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel("⬇ 批量预下载到本地数据湖")
        title.setStyleSheet("font-size: 17px; font-weight: bold; color: #1F2430;")
        root.addWidget(title)

        warn = QLabel("⚠️ 全市场下载会持续很久（默认间隔下约 50 分钟）。"
                      "建议在网络空闲时段执行，随时可「中断」——已下载的部分会保留，下次自动跳过。")
        warn.setWordWrap(True)
        warn.setStyleSheet("font-size: 12px; color: #E65100; background: #FFF8E1; "
                           "border: 1px solid #FFE082; border-radius: 6px; padding: 8px 10px;")
        root.addWidget(warn)

        # ---------- 来源 ----------
        box = QFrame()
        box.setStyleSheet("QFrame { background:#FAFBFD; border:1px solid #E7EAF0; border-radius:10px; }")
        blay = QVBoxLayout(box)
        blay.setContentsMargins(12, 10, 12, 10)
        blay.setSpacing(6)

        blay.addWidget(self._minor("数据来源"))
        self._radio_group = QButtonGroup(self)
        self._radios = {}
        sources = [
            ("index_preset", "指数预设（29 个大盘/行业指数 · 秒级完成）"),
            ("constituent", "指数成分股"),
            ("paste", "粘贴代码列表"),
            ("all", "全市场 A 股（来自花名册 · 数量最多）"),
        ]
        for key, text in sources:
            radio = QRadioButton(text)
            radio.setStyleSheet("font-size: 13px; color: #1F2430;")
            self._radio_group.addButton(radio)
            self._radios[key] = radio
            blay.addWidget(radio)
        self._radios["index_preset"].setChecked(True)

        # 成分股行
        row_cons = QHBoxLayout()
        row_cons.addSpacing(22)
        row_cons.addWidget(self._minor("指数"))
        self.cmb_cons = NoWheelComboBox()
        self.cmb_cons.setFixedHeight(28)
        for code, name in CONSTITUENT_INDEXES.items():
            self.cmb_cons.addItem(f"{name} ({code})", code)
        row_cons.addWidget(self.cmb_cons)
        self.btn_resolve = QPushButton("解析成分股")
        self.btn_resolve.setStyleSheet(_FLAT_BTN)
        self.btn_resolve.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_resolve.clicked.connect(self._resolve_constituents)
        row_cons.addWidget(self.btn_resolve)
        self.lbl_cons = QLabel("")
        self.lbl_cons.setStyleSheet("font-size: 12px; color: #8A94A6;")
        row_cons.addWidget(self.lbl_cons)
        row_cons.addStretch()
        blay.addLayout(row_cons)

        # 粘贴行
        self.txt_paste = QPlainTextEdit()
        self.txt_paste.setPlaceholderText(
            "每行一个，或用空格/逗号/分号分隔。例：\n600519 000001, 300750\n（指数请填 sh000001 / sz399001 这类带前缀的代码）")
        self.txt_paste.setFixedHeight(80)
        self.txt_paste.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas, 'Microsoft YaHei', monospace; "
            "font-size: 12px; border: 1px solid #E0E4EC; border-radius: 8px; "
            "background: white; padding: 6px; }")
        blay.addWidget(self.txt_paste)
        root.addWidget(box)

        # ---------- 参数 ----------
        params = QHBoxLayout()
        params.setSpacing(14)
        params.addWidget(self._minor("起点"))
        self.date_start = NoWheelDateEdit(QDate(2016, 1, 1))
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        # 起点下沿放宽到 2010（个股全历史），默认仍给 2016 平衡下载量，用户可自行调早
        self.date_start.setMinimumDate(QDate(2010, 1, 1))
        self.date_start.setFixedHeight(28)
        self.date_start.setToolTip("首次拉取的起点；默认 2016（够回测评估窗）。"
                                   "如需更早历史（个股可到 2010）可手动调早；"
                                   "已存在的数据按增量更新，不受此值影响")
        params.addWidget(self.date_start)

        params.addWidget(self._minor("间隔(秒)"))
        self.spin_interval = NoWheelDoubleSpinBox()
        self.spin_interval.setRange(0.0, 10.0)
        self.spin_interval.setDecimals(1)
        self.spin_interval.setSingleStep(0.1)
        self.spin_interval.setValue(0.6)
        self.spin_interval.setFixedWidth(64)
        self.spin_interval.setFixedHeight(28)
        self.spin_interval.setToolTip("每次请求前的等待时间。越慢越安全，建议不低于 0.4 秒")
        params.addWidget(self.spin_interval)

        self.chk_jitter = QCheckBox("随机抖动")
        self.chk_jitter.setChecked(True)
        self.chk_jitter.setToolTip("让间隔在 ±30% 内随机浮动，打散固定频率特征，降低被识别为机器人的风险")
        params.addWidget(self.chk_jitter)
        params.addStretch()
        root.addLayout(params)

        params2 = QHBoxLayout()
        params2.setSpacing(14)
        self.chk_skip_fresh = QCheckBox("跳过已最新（断点续传）")
        self.chk_skip_fresh.setChecked(True)
        params2.addWidget(self.chk_skip_fresh)

        self.chk_force = QCheckBox("重新全量下载")
        self.chk_force.setToolTip(
            "忽略本地已有数据，从所选起点整段重新下载，耗时较长。\n"
            "仅在怀疑数据被前复权修正搞坏 / 本地数据异常时才用；日常勾「跳过已最新」即可。")
        params2.addWidget(self.chk_force)

        params2.addWidget(self._minor("连续失败熔断"))
        self.spin_breaker = NoWheelSpinBox()
        self.spin_breaker.setRange(3, 999)
        self.spin_breaker.setValue(12)
        self.spin_breaker.setFixedWidth(64)
        self.spin_breaker.setFixedHeight(28)
        self.spin_breaker.setToolTip("连续失败达到该数量即认定为「疑似被限流」并自动停手，保护用户 IP")
        params2.addWidget(self.spin_breaker)
        params2.addStretch()
        root.addLayout(params2)

        # ---------- 预估 ----------
        self.lbl_estimate = QLabel("—")
        self.lbl_estimate.setStyleSheet("font-size: 12px; color: #5B6472;")
        root.addWidget(self.lbl_estimate)

        # ---------- 进度 ----------
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(20)
        root.addWidget(self.progress)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #1976D2;")
        root.addWidget(self.lbl_status)

        self.log = QListWidget()
        self.log.setFixedHeight(110)
        self.log.setStyleSheet("QListWidget { font-size: 12px; background:#FAFBFD; "
                               "border:1px solid #E7EAF0; border-radius:8px; }")
        root.addWidget(self.log)

        # ---------- 按钮 ----------
        btns = QHBoxLayout()
        self.btn_copy = QPushButton("复制失败清单")
        self.btn_copy.setStyleSheet(_FLAT_BTN)
        self.btn_copy.clicked.connect(self._copy_failures)
        self.btn_copy.setEnabled(False)
        btns.addWidget(self.btn_copy)
        btns.addStretch()

        self.btn_cancel = QPushButton("中断")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet(
            "QPushButton { color:#E65100; background:white; border:1px solid #FFB74D; "
            "border-radius:6px; padding:6px 18px; font-weight:bold; }"
            "QPushButton:hover { background:#FFF3E0; }")
        self.btn_cancel.clicked.connect(self._cancel)
        btns.addWidget(self.btn_cancel)

        self.btn_start = QPushButton("▶ 开始下载")
        self.btn_start.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; font-weight:bold; "
            "padding:6px 22px; border:none; border-radius:6px; }"
            "QPushButton:hover { background:#1565C0; }"
            "QPushButton:disabled { background:#B8C6D8; }")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self._start)
        btns.addWidget(self.btn_start)

        self.btn_close = QPushButton("关闭")
        self.btn_close.setStyleSheet(_FLAT_BTN)
        self.btn_close.clicked.connect(self._on_close_clicked)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        for radio in self._radios.values():
            radio.toggled.connect(self._sync_source_ui)
        for widget in (self.spin_interval, self.spin_breaker):
            widget.valueChanged.connect(self._refresh_estimate)

    @staticmethod
    def _minor(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #5B6472;")
        return lbl

    def _sync_source_ui(self, *_):
        """按来源切换可用控件"""
        key = self._current_source()
        self.cmb_cons.setEnabled(key == "constituent")
        self.btn_resolve.setEnabled(key == "constituent")
        self.lbl_cons.setVisible(key == "constituent")
        self.txt_paste.setVisible(key == "paste")
        self._refresh_estimate()

    def _current_source(self) -> str:
        for key, radio in self._radios.items():
            if radio.isChecked():
                return key
        return "index_preset"

    # ==========================================
    # 解析待下载列表
    # ==========================================
    def _collect_symbols(self) -> list[str]:
        """按来源收集待下载代码；返回空列表表示需要用户补充"""
        key = self._current_source()
        if key == "index_preset":
            self._zone = ZONE_INDEX
            return list(INDEX_PRESETS.keys())

        self._zone = ZONE_KLINE
        if key == "constituent":
            return list(self._symbols)   # 由「解析成分股」预先填好
        if key == "paste":
            raw = self.txt_paste.toPlainText()
            parts = []
            for chunk in raw.replace(",", " ").replace(";", " ").replace("\n", " ").split():
                chunk = chunk.strip()
                if chunk:
                    parts.append(chunk.upper() if not chunk.isdigit() else chunk)
            return sorted(set(parts))
        if key == "all":
            return self.main_win.engine.list_stock_symbols()
        return []

    def _resolve_constituents(self):
        code = self.cmb_cons.currentData()
        if not code:
            return
        self.btn_resolve.setEnabled(False)
        self.lbl_cons.setText("解析中…")
        self._cons_token += 1
        worker = _ConstituentsWorker(code, self)
        token = self._cons_token
        worker.finished_signal.connect(
            lambda symbols, t=token: self._on_constituents(symbols, t))
        self._cons_worker = worker
        worker.start()

    def _on_constituents(self, symbols: list, token: int):
        # 【竞态防护】只接受最新一次请求的结果，迟到的旧请求直接丢弃
        if token != self._cons_token:
            return
        self.btn_resolve.setEnabled(True)
        self._symbols = symbols
        if symbols:
            self.lbl_cons.setText(f"✅ 解析到 {len(symbols)} 只")
        else:
            self.lbl_cons.setText("❌ 解析失败，请改用其它来源")
            QMessageBox.warning(
                self, "解析失败",
                "未能获取该指数的成分股列表（接口不可用或网络异常）。\n\n"
                "建议：① 稍后重试；② 改用「粘贴代码列表」或「全市场 A 股」。")
        self._refresh_estimate()

    # ==========================================
    # 预估 / 进度
    # ==========================================
    def _empty_source_hint(self) -> str:
        """列表为空时给用户针对性的下一步指引"""
        key = self._current_source()
        if key == "constituent":
            return "请先点击「解析成分股」"
        if key == "all":
            return "花名册为空 —— 请先运行 sync_roster.py 同步 A 股名册"
        return "请先粘贴至少一个代码"

    def _refresh_estimate(self, *_):
        symbols = self._collect_symbols()
        policy = self._build_policy()
        if not symbols:
            self.lbl_estimate.setText(f"待下载：—（{self._empty_source_hint()}）")
            return
        seconds = estimate_seconds(len(symbols), policy)
        minutes = seconds / 60
        when = f"{minutes:.0f} 分钟" if minutes >= 1 else f"{seconds} 秒"
        if minutes >= 60:
            when = f"{minutes / 60:.1f} 小时"
        self.lbl_estimate.setText(
            f"待下载：{len(symbols)} 只　·　区间 {self._zone}　·　"
            f"预计约 {when}（间隔 {policy.interval:.1f}s"
            f"{' + 抖动' if self.chk_jitter.isChecked() else ''}）")

    def _build_policy(self) -> ThrottlePolicy:
        return ThrottlePolicy(
            interval=float(self.spin_interval.value()),
            jitter=0.3 if self.chk_jitter.isChecked() else 0.0,
            circuit_breaker=int(self.spin_breaker.value()),
            skip_fresh=bool(self.chk_skip_fresh.isChecked()),
        )

    def _start(self):
        symbols = self._collect_symbols()
        if not symbols:
            QMessageBox.information(self, "提示", self._empty_source_hint())
            return
        if self._current_source() == "all" and len(symbols) > 1000:
            reply = QMessageBox.question(
                self, "确认",
                f"即将下载 {len(symbols)} 只标的，耗时可能达到数十分钟。\n"
                f"过程中可随时「中断」，已下载部分会保留。\n\n确定开始吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.log.clear()
        self._failures = []
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_copy.setEnabled(False)
        self.progress.setMaximum(len(symbols))
        self.progress.setValue(0)

        self._worker = SyncWorker(
            symbols, zone=self._zone,
            force_full=bool(self.chk_force.isChecked()),
            min_date=self.date_start.date().toString("yyyyMMdd"),
            policy=self._build_policy(), parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done, total, symbol):
        self.progress.setValue(done)
        self.lbl_status.setText(f"({done}/{total}) 正在处理 {symbol} …")

    def _on_failed(self, symbol, reason):
        self._failures.append(symbol)
        if self.log.count() < 500:
            self.log.addItem(f"✗ {symbol} —— {reason}")

    def _on_finished(self, stats: dict):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_copy.setEnabled(bool(stats.get("symbols_failed")))
        tail = "（已中断）" if stats.get("aborted") else ""
        self.lbl_status.setText(
            f"{tail}完成：成功 {stats.get('ok', 0)} · 跳过 {stats.get('skipped', 0)} · "
            f"失败 {stats.get('fail', 0)} · 新增 {stats.get('added', 0)} 行")
        if stats.get("fail"):
            QMessageBox.warning(
                self, "部分失败",
                f"{stats['fail']} 只未下载成功。常见原因：\n"
                f"① 代码输入有误；② 该股已退市 / 长期停牌，行情源不再提供（属正常现象）；\n"
                f"③ 网络抖动或被限流。\n\n"
                f"失败清单可用左下角「复制失败清单」取出，稍后重试即可（已完成的不重复）。")
        self._worker = None

    # ==========================================
    # 其它
    # ==========================================
    def _cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.lbl_status.setText("正在中断…（等待当前这一只结束）")
            self.btn_cancel.setEnabled(False)

    def _copy_failures(self):
        if not self._failures:
            return
        QApplication.clipboard().setText("\n".join(self._failures))

    def _try_stop_worker(self) -> bool:
        """中断并等待线程结束；返回是否已安全停止。

        【为什么宁可等也不强关】QThread 若在销毁时仍在运行会导致程序崩溃，
        而"正在下载时把窗口关掉"绝不应该把整个 App 带走。
        等 15 秒后仍没停（网络挂死），就保持窗口存活并提示，等线程自己结束。
        """
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(15000)
        return not (self._worker is not None and self._worker.isRunning())

    def _on_close_clicked(self):
        if self._try_stop_worker():
            self.accept()

    def closeEvent(self, event):  # noqa: N802
        """右上角 X 同样走安全停线程逻辑，绝不带着活线程销毁对话框"""
        if self._try_stop_worker():
            event.accept()
        else:
            event.ignore()
            QMessageBox.warning(
                self, "下载仍在进行",
                "有一个网络请求迟迟没有结束（可能网络挂起）。\n"
                "已请求中断，请稍候片刻再点「关闭」；也可以点「中断」后等待。")
