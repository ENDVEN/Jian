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
     ★v1.38/§7-E2：**代理类失败（ProxyError）另有更小的阈值**（3 连败即停）——
     代理瞬断时失败率是 100%，按 12 连败等下去只是白等十几次超时；
     且这类失败**必须直说"去查代理"**（中断原因文案 = `sync_service.abort_reason_text`）。
  另外「跳过已最新」实现断点续传：中断后重跑不会重复劳动。

本弹窗只做参数收集与进度展示；真正干活的线程在 `ui/workers.SyncWorker`，
而**任务归属**在主窗口的后台下载队列 `ui/download_hub.py`（v1.43 · §7-B11）。
⇒ 本弹窗是**非模态**的（`data_manager._open_bulk` 用 `show()`）：提交后下载照跑，
  窗口可以一直开着当监控器（进度是队列的**投影**），也可以直接关掉去做别的事。
"""
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QRadioButton, QButtonGroup, QPlainTextEdit,
                             QCheckBox, QProgressBar, QListWidget,
                             QPushButton, QMessageBox, QApplication, QFrame)

from data.akshare_feed import INDEX_PRESETS
from data.sync_service import (ZONE_KLINE, ZONE_KLINE_RAW, ZONE_INDEX,
                               abort_reason_text, estimate_seconds,
                               format_duration, friendly_constituent_message)
from ui.download_hub import download_policy_from_prefs
from ui.widgets.custom_widgets import (NoWheelComboBox, NoWheelDateEdit,
                                       mono_font_css)   # ★v1.46 §10-15 开源等宽栈
# 【架构纪律 v5.12 · §9-O2】线程一律用 ui/workers.py 的，弹窗不自造 QThread
from ui.workers import ConstituentsWorker, JobGuard

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


class BulkDownloadDialog(QDialog):
    """批量预下载：选来源 → 调参数 → 看进度 → 可中断"""

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.main_win = main_win
        self._symbols: list[str] = []
        self._failures: list[str] = []
        self._zone = ZONE_KLINE
        # ★v1.43 / §7-B11：线程不再属于本弹窗（旧版 `SyncWorker(parent=self)` ⇒
        #   “下载中不能关窗”与“关窗前硬等 15 秒”都是这一行带来的）。
        #   现在只记自己提交的任务号，进度与回执全部从队列订阅而来。
        self._job_id: int | None = None
        # ★v6.66：口径选「两个都下」会**提交两个任务** ⇒ 回包过滤与「停止本任务」都要认一组 id
        self._job_ids: list[int] = []
        self._cons_worker: ConstituentsWorker | None = None
        # ★v1.38/§7-E2（P4 顺手项）：成分股的"只认最后一次"改用**公共件** JobGuard
        #   （原先这里是手写的 `_cons_token` 计数器，与 §9-O5 的公共判据重复 ——
        #    `ui/workers.py` 的 JobGuard docstring 里早就挂账"择机改用它"，本次还清）。
        self._cons_guard = JobGuard()
        hub = main_win.downloads
        hub.job_progress.connect(self._on_hub_progress)
        hub.job_failed.connect(self._on_hub_failed)
        hub.job_finished.connect(self._on_hub_finished)

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
                      "建议在网络空闲时段执行。提交后任务在后台跑：界面照常可用，"
                      "随时可「停止本任务」——已下载的部分会保留，下次自动跳过。")
        warn.setWordWrap(True)
        warn.setStyleSheet("font-size: 12px; color: #E65100; background: #FFF8E1; "
                           "border: 1px solid #FFE082; border-radius: 6px; padding: 8px 10px;")
        root.addWidget(warn)

        # ★v6.74 S2-2（用户拍板 2026-09-27）：本弹窗的「⚙ 下载设置…」入口**直接删除**（不预留"跳设置页"）
        #   —— 节流参数是**全局**的，需要时去左栏「⚙ 设置 → 下载与取数」改；
        #   下载设置的入口**只保留下载列表面板那一处**（少一个按钮 = 少一处漂移面，§9-D）。
        #   ⚠ 本弹窗的**预估值**仍按当前全局偏好实时算（见 `_refresh_estimate`），不需要手动刷新入口。

        # ---------- ⚡ 预设（§7-B1/B2 D6-2）：一键填好"全市场扫描就绪"底座 ----------
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self.btn_preset_scan = QPushButton("⚡ 预设：全市场扫描就绪（全A · 2016起）")
        self.btn_preset_scan.setStyleSheet(_FLAT_BTN)
        self.btn_preset_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preset_scan.setToolTip(
            "为「🌐 全市场筛选 / 📊 广度统计」一次备齐全 A 日线底座：\n"
            "来源 = 全市场 A 股 · 起点 2016-01-01 · 勾「跳过已最新」（断点续传）。\n"
            "已下载过的会自动跳过，可分多次补齐。")
        self.btn_preset_scan.clicked.connect(self._apply_scan_ready_preset)
        preset_row.addWidget(self.btn_preset_scan)
        self.lbl_preset = QLabel("为全市场筛选 / 广度统计备底座（已下载的自动跳过）")
        self.lbl_preset.setStyleSheet("font-size: 11.5px; color: #8A94A6;")
        preset_row.addWidget(self.lbl_preset)
        preset_row.addStretch()
        root.addLayout(preset_row)

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
            "QPlainTextEdit { " + mono_font_css() + " "
            "font-size: 12px; border: 1px solid #E0E4EC; border-radius: 8px; "
            "background: white; padding: 6px; }")
        blay.addWidget(self.txt_paste)
        root.addWidget(box)

        # ---------- 复权口径（★v6.66 · **"不复权分区永远填不上"的根因修复**）----------
        # 【旧版】来源不是指数时一律写 `kline_daily`（前复权）⇒ 用户"预下载了几十轮"、
        #   `kline_daily_raw` 里仍只有当初手工下的那一只（用户 2026-09-25 截图实证：
        #   raw 分区 1 项 / 173KB，而且**没有任何入口**能往里加新的）。
        #   前复权与不复权是**两份独立数据**（互推不出来，见 market_db 的分区注释）⇒
        #   必须在这里让用户选，否则"点了预下载却永远补不上不复权那份"。
        adj_row = QHBoxLayout()
        adj_row.setSpacing(10)
        adj_row.addWidget(self._minor("复权口径"))
        self.cmb_adjust = NoWheelComboBox()
        self.cmb_adjust.setFixedHeight(28)
        for _key, _text in (("qfq", "前复权（默认）"),
                            ("raw", "不复权"),
                            ("both", "两个都下（各存一份）")):
            self.cmb_adjust.addItem(_text, _key)
        self.cmb_adjust.setToolTip(
            "**前复权**＝看长期趋势、算指标（随除权整体重算）；**不复权**＝看当年真实价位。\n"
            "两份数据各存一个分区、**互推不出来** ⇒ 选「两个都下」会提交**两个任务**。\n"
            "⚠ 指数预设来源没有复权概念，本项对它无效。")
        self.cmb_adjust.currentIndexChanged.connect(self._refresh_estimate)
        adj_row.addWidget(self.cmb_adjust)
        self.lbl_adjust_note = QLabel("不复权那份必须单独下 —— 否则行情页切过去只能现取")
        self.lbl_adjust_note.setStyleSheet("font-size: 11.5px; color: #8A94A6;")
        adj_row.addWidget(self.lbl_adjust_note)
        adj_row.addStretch()
        root.addLayout(adj_row)

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
        params.addStretch()
        root.addLayout(params)
        
        params2 = QHBoxLayout()
        params2.setSpacing(14)
        self.chk_force = QCheckBox("重新全量下载")
        self.chk_force.setToolTip(
            "忽略本地已有数据，从所选起点整段重新下载，耗时较长。\n"
            "仅在怀疑数据被前复权修正搞坏 / 本地数据异常时才用；日常默认「跳过已最新」即可。")
        params2.addWidget(self.chk_force)
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

        # ★v1.43：进度与失败清单已搬到全局队列面板（弹窗关了也不会丢），
        #   这里给一个入口，不让用户自己找。按钮名只引用不拼写（§11.5-80）。
        self.btn_queue = QPushButton("查看下载队列")
        self.btn_queue.setStyleSheet(_FLAT_BTN)
        self.btn_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_queue.clicked.connect(self._open_queue)
        btns.addWidget(self.btn_queue)
        btns.addStretch()

        self.btn_cancel = QPushButton("停止本任务")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("只停本弹窗刚提交的那个任务；要停全部请到下载队列面板点「全部中断」。\n"
                                   "已下载的部分会保留，下次重跑同范围会自动跳过。")
        self.btn_cancel.setStyleSheet(
            "QPushButton { color:#E65100; background:white; border:1px solid #FFB74D; "
            "border-radius:6px; padding:6px 18px; font-weight:bold; }"
            "QPushButton:hover { background:#FFF3E0; }")
        self.btn_cancel.clicked.connect(self._cancel)
        btns.addWidget(self.btn_cancel)

        self.btn_start = QPushButton("▶ 开始下载")
        self.btn_start.setToolTip("提交给后台下载队列（不占用界面），并排队逐个执行。")
        self.btn_start.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; font-weight:bold; "
            "padding:6px 22px; border:none; border-radius:6px; }"
            "QPushButton:hover { background:#1565C0; }"
            "QPushButton:disabled { background:#B8C6D8; }")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.clicked.connect(self._start)
        btns.addWidget(self.btn_start)

        self.btn_close = QPushButton("关闭")
        self.btn_close.setToolTip("关闭本窗口不会停止已提交的后台下载。")
        self.btn_close.setStyleSheet(_FLAT_BTN)
        self.btn_close.clicked.connect(self.close)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

        for radio in self._radios.values():
            radio.toggled.connect(self._sync_source_ui)

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
        # ★v6.66：指数预设走 `index_daily`，没有复权概念 ⇒ 口径选择对它无效（不是隐藏，是禁用 + 说明）
        _is_index = (key == "index_preset")
        self.cmb_adjust.setEnabled(not _is_index)
        self.lbl_adjust_note.setText(
            "指数只有一种口径（指数点位本身不复权），本项不适用"
            if _is_index else "不复权那份必须单独下 —— 否则行情页切过去只能现取")
        self._refresh_estimate()

    def _zones_to_download(self) -> list:
        """本次要写哪几个分区（★v6.66）：指数预设固定 `index_daily`；其它来源看**口径选择**。"""
        if self._current_source() == "index_preset":
            return [ZONE_INDEX]
        key = str(self.cmb_adjust.currentData() or "qfq")
        if key == "raw":
            return [ZONE_KLINE_RAW]
        if key == "both":
            return [ZONE_KLINE, ZONE_KLINE_RAW]
        return [ZONE_KLINE]

    @staticmethod
    def _zone_label(zone: str) -> str:
        return {ZONE_KLINE: "前复权", ZONE_KLINE_RAW: "不复权",
                ZONE_INDEX: "指数"}.get(zone, zone)

    def _apply_scan_ready_preset(self):
        """「全市场扫描就绪」预设（D6-2）：只**填控件**，不替用户点开始 —— 下载永远手动发起。"""
        self._radios["all"].setChecked(True)
        self.date_start.setDate(QDate(2016, 1, 1))
        self.chk_force.setChecked(False)
        self.lbl_status.setText("已按「全市场扫描就绪」填好参数 —— 确认后点「▶ 开始下载」")
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
        job = self._cons_guard.next()          # 取号 ⇒ 此前所有在途请求的回包作废
        worker = ConstituentsWorker(code, self)
        worker.finished_signal.connect(
            lambda result, t=job: self._on_constituents(result, t))
        self._cons_worker = worker
        worker.start()

    def _on_constituents(self, result, token: int):
        # 【竞态防护】只接受最新一次请求的结果，迟到的旧请求直接丢弃（§9-O5 · 公共件 JobGuard）
        if not self._cons_guard.accept(token):
            return
        self.btn_resolve.setEnabled(True)
        # v6.9：结果由 MarketSyncService 统一回包（dict），失败原因分类文案也由它给
        # （门面是联网抓取的唯一入口，§9-H 红线；此处只负责展示，§10-3）
        if not isinstance(result, dict):
            result = {"symbols": result or []}
        symbols = result.get("symbols") or []
        self._symbols = symbols
        if symbols:
            self.lbl_cons.setText(f"✅ 解析到 {len(symbols)} 只")
        else:
            self.lbl_cons.setText("❌ 解析失败，请改用其它来源")
            QMessageBox.warning(
                self, "解析失败",
                friendly_constituent_message(self.cmb_cons.currentData(), result))
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
            return "花名册为空 —— 请先运行 scripts/sync_roster.py 同步 A 股名册"
        return "请先粘贴至少一个代码"

    def _refresh_estimate(self, *_):
        symbols = self._collect_symbols()
        policy = download_policy_from_prefs()
        if not symbols:
            self.lbl_estimate.setText(f"待下载：—（{self._empty_source_hint()}）")
            return
        zones = self._zones_to_download()
        # ★v6.66：每个口径是**一个独立任务**（各发一轮请求）⇒ 预估按"只数 × 口径数"算，别少报
        seconds = estimate_seconds(len(symbols) * len(zones), policy)
        self.lbl_estimate.setText(
            f"待下载：{len(symbols)} 只　·　口径 "
            f"{' + '.join(self._zone_label(z) for z in zones)}　·　"
            f"最多约 {format_duration(seconds)}（间隔 {policy.interval:.1f}s"
            f"{' + 抖动' if policy.jitter else ''}）")
        # ★v1.40/§7-E5：这里**给不出**"真正要跑几只"（没体检过，逐只读 footer 反而要先花时间），
        # 所以数字只能是**上限**；把"已最新的会自动跳过"说清楚，用户才不会看到 50 分钟就放弃。
        self.lbl_estimate.setToolTip(
            "上限估算：按每只都发一次请求算。\n"
            "已是最新的标的（本地末日 >= 最近一个已收盘定稿的交易日）会被自动跳过、不发请求，\n"
            "所以实际通常明显更快 —— 周末 / 节假日 / 盘中批量同步几乎瞬时完成。")

    def _start(self):
        symbols = self._collect_symbols()
        if not symbols:
            QMessageBox.information(self, "提示", self._empty_source_hint())
            return
        if self._current_source() == "all" and len(symbols) > 1000:
            reply = QMessageBox.question(
                self, "确认",
                f"即将下载 {len(symbols)} 只标的，耗时可能达到数十分钟。\n"
                f"提交后**不占用界面**，随时可「停止本任务」，已下载部分会保留。\n\n确定提交吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.log.clear()
        self._failures = []
        self.btn_copy.setEnabled(False)
        self.progress.setMaximum(len(symbols))
        self.progress.setValue(0)

        # ★v1.43 / §7-B11：**提交给主窗口的后台队列**，本弹窗不再持有线程。
        #   ⇒ 窗口可以关、界面可以用，下载照在后台串行跑（一次只跑一批）。
        # ★v6.66：**一个口径一个任务**（前复权 / 不复权是两份独立数据）⇒ 循环提交、逐个记 id。
        hub = self.main_win.downloads
        force = bool(self.chk_force.isChecked())
        min_date = self.date_start.date().toString("yyyyMMdd")
        self._job_ids = []
        dup: list[str] = []
        for zone in self._zones_to_download():
            jid = hub.submit(f"批量预下载 · {self._source_label()} · {self._zone_label(zone)}",
                             symbols, zone=zone, force_full=force,
                             min_date=min_date, origin="bulk")
            if jid:
                self._job_ids.append(jid)
            else:
                dup.append(self._zone_label(zone))
        self._job_id = self._job_ids[-1] if self._job_ids else None
        if not self._job_ids:
            # 去重命中（同样的标的清单已在跑/已排队）⇒ 诚实说清楚，不假装修了新任务
            self.lbl_status.setText(
                "同样的任务已经在队列里了（含口径）—— 进度见底部下载条。")
            self.btn_cancel.setEnabled(False)
            return
        ahead = max(0, hub.pending_count() - len(self._job_ids))
        _dup_note = f"　⚠ {'、'.join(dup)} 已在队列里，未重复提交" if dup else ""
        self.btn_cancel.setEnabled(True)
        self.lbl_status.setText(
            f"已提交后台（任务 {'、#'.join(str(i) for i in self._job_ids)}）· {len(symbols)} 只"
            + (f" · 前面还排着 {ahead} 个" if ahead else "")
            + _dup_note
            + "。本窗口可以一直开着看进度，也可以直接关掉去做别的事。")

    def _source_label(self) -> str:
        """任务名（出现在下载条与队列面板里，必须让用户认得出是谁提交的）。"""
        return {"index_preset": "指数预设", "constituent": "指数成分股",
                "paste": "粘贴代码列表", "all": "全市场 A 股"}.get(self._current_source(),
                                                                    "批量")

    # ==========================================
    # 队列回包（本弹窗只是其中一个视图：只认自己提交的那个任务）
    # ==========================================
    def _on_hub_progress(self, job_id: int, done: int, total: int, symbol: str):
        if job_id not in self._job_ids:      # ★v6.66：本弹窗可能提交了**两个**口径的任务
            return
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        self.lbl_status.setText(f"({done}/{total}) 正在处理 {symbol} …")

    def _on_hub_failed(self, job_id: int, symbol: str, reason: str):
        if job_id not in self._job_ids:
            return
        self._failures.append(symbol)
        if self.log.count() < 500:
            self.log.addItem(f"✗ {symbol} —— {reason}")

    def _on_hub_finished(self, job_id: int, stats: dict):
        if job_id not in self._job_ids:
            return
        stats = stats or {}
        self.btn_cancel.setEnabled(False)
        self.btn_copy.setEnabled(bool(stats.get("symbols_failed")))
        # 中断原因必须说清（§7-E2）：代理全灭时只显示"已中断"，用户还是不知道该查代理
        _why = abort_reason_text(stats)
        tail = f"（{_why}）" if _why else ""
        self.lbl_status.setText(
            f"{tail}完成：成功 {stats.get('ok', 0)} · 跳过 {stats.get('skipped', 0)} · "
            f"失败 {stats.get('fail', 0)} · 新增 {stats.get('added', 0)} 行")
        if stats.get("fail"):
            # 后台任务的失败**不再弹窗打断**（用户可能正在别的页面做事）；
            # 原因与清单留在本弹窗与队列面板里（文案单出口 `failure_hint`）。
            job = self.main_win.downloads.get(job_id)
            hint = job.hint_text if job is not None else ""
            if hint:
                self.lbl_status.setToolTip(hint)
                self.log.addItem(f"—— {len(self._failures)} 只未下载成功。{hint}")

    # ==========================================
    # 其它
    # ==========================================
    def _cancel(self):
        """停掉**本弹窗刚提交的**任务（口径选「两个都下」时是两个）。"""
        if self._job_ids:
            for _jid in list(self._job_ids):
                self.main_win.downloads.cancel(_jid)
            self.lbl_status.setText("正在停止本任务…（等待当前这一只结束）")
            self.btn_cancel.setEnabled(False)

    def _open_queue(self):
        """打开主窗口的下载队列面板（多任务与失败清单都在那里）。"""
        self.main_win.show_download_queue()

    def _copy_failures(self):
        if not self._failures:
            return
        QApplication.clipboard().setText("\n".join(self._failures))

