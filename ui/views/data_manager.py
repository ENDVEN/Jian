# ui/views/data_manager.py
"""
🗄 数据管理 (v5.8 · §7-A3；v5.10 UX 加固；v5.11 勾选重设计)

把过去"只能写、看不见、删不掉"的数据湖，变成：
  可清点（按分区列出条目 / 行数 / 日期范围 / 体积）
  可更新到最新（增量补齐，合并去重后落盘）/ 可重新全量下载
  可按需删除（单条 / 批量 / 清空分区，均二次确认 + 高危需键入确认）
  可批量预下载（交给 ui/dialogs/bulk_download.py）

【按钮层级设计 · 防呆原则】(v5.10)
  日常高频操作排在同一行、视觉连续：更新到最新 → 重新全量下载 → 删除选中；
  "清空该分区"属于大面积不可逆破坏，**刻意孤立**到左侧分区栏底部的低调链接，
  点击后必须键入「清空」二字才执行 —— 做得越费事，误操作率越低。

【文案原则】面向用户一律说人话：
  "增量更新" = 用户语言「更新到最新」（只下载缺失的最新几天）；
  "强制全量重拉" = 「重新全量下载」（丢弃本地从 2010 重拉，慢，日常不需要）。
  绝不把内部术语直接丢给用户。

【架构纪律】本页只做展示与 QThread 调度：
  真实的文件读写在 data/market_db.py，真实的网络与合并在 data/sync_service.py。
  这里绝不发网络请求、绝不直接 os.remove —— 与 §10-3 保持一致。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QSplitter, QListWidget, QTableWidget,
                             QTableWidgetItem, QHeaderView, QPushButton,
                             QLineEdit, QMessageBox, QInputDialog)
from PyQt6.QtGui import QColor, QFont

from data.market_db import DataLakeManager
from data.sync_service import (MarketSyncService, ThrottlePolicy,
                               ZONE_KLINE, ZONE_INDEX)
from ui.dialogs.bulk_download import BulkDownloadDialog
from ui.widgets.custom_widgets import NoWheelDoubleSpinBox
from ui.workers import ScanWorker, SyncWorker

# 分区中文名（顺序即左侧清单顺序）
ZONE_ORDER = ["kline_daily", "index_daily", "kline_min", "macro_eco",
              "fin_report", "valuation", "sentiment", "hot_topic"]
ZONE_LABELS = {
    "kline_daily": "日线行情",
    "index_daily": "大盘/行业指数",
    "kline_min": "分钟行情 (预留)",
    "macro_eco": "宏观经济",
    "fin_report": "财务报表",
    "valuation": "每日估值",
    "sentiment": "市场情绪",
    "hot_topic": "热门题材",
}
# 只有这两个区当前具备"联网同步"能力
SYNCABLE = (ZONE_KLINE, ZONE_INDEX)

_COLUMNS = ["☑", "标的", "行数", "起始", "结束", "大小", "更新时间"]
_COL_CHECK, _COL_NAME = 0, 1

_CARD_QSS = "QFrame { background: white; border: 1px solid #E7EAF0; border-radius: 10px; }"
_FLAT_QSS = ("QPushButton { color:#1976D2; background:transparent; border:none; "
             "padding:0 10px; font-weight:bold; border-radius:6px; }"
             "QPushButton:hover { background:#EEF4FD; }"
             "QPushButton:disabled { color:#B4BECB; }")


def _fmt_bytes(num) -> str:
    """人类可读的体积"""
    try:
        value = float(num)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


class DataManagerView(QWidget):
    """数据湖管理页：左分区 / 右明细 / 底部操作"""

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        self.lake = DataLakeManager()
        self.service = MarketSyncService()

        self._items: list[dict] = []      # 当前分区的清单
        self._current_zone = ZONE_KLINE
        self._checked: set[str] = set()   # 当前已勾选的标的名（跨过滤搜索保留勾选）
        self._scan_worker = None
        self._sync_worker = None

        self._setup_ui()
        self._refresh_zones()
        self._scan_current_zone()

    # ==========================================
    # UI
    # ==========================================
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 6, 0)
        root.setSpacing(10)

        # ---------- 顶部 ----------
        head = QHBoxLayout()
        title = QLabel("🗄 数据管理")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #212121;")
        head.addWidget(title)
        head.addSpacing(10)
        self.lbl_root = QLabel("")
        self.lbl_root.setStyleSheet("font-size: 12px; color: #8A94A6;")
        head.addWidget(self.lbl_root)
        head.addStretch()

        self.btn_rescan = QPushButton("🔄 重新扫描")
        self.btn_rescan.setStyleSheet(_FLAT_QSS)
        self.btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rescan.clicked.connect(self._rescan)
        head.addWidget(self.btn_rescan)

        self.btn_bulk = QPushButton("⬇ 批量预下载…")
        self.btn_bulk.setStyleSheet(
            "QPushButton { background:#1976D2; color:white; font-weight:bold; "
            "padding:8px 18px; border:none; border-radius:8px; }"
            "QPushButton:hover { background:#1565C0; }")
        self.btn_bulk.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bulk.clicked.connect(self._open_bulk)
        head.addWidget(self.btn_bulk)
        root.addLayout(head)

        # ---------- 主体：左分区 / 右明细 ----------
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- 左：分区清单（底部放孤立的"清空分区"危险入口，刻意远离主操作）----
        left = QFrame()
        left.setStyleSheet(_CARD_QSS)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(10, 10, 10, 10)
        left_lay.setSpacing(6)
        left_lay.addWidget(self._minor("数据分区"))
        self.zone_list = QListWidget()
        self.zone_list.setStyleSheet(
            "QListWidget { border:none; background:transparent; font-size:13px; }"
            "QListWidget::item { padding:8px 10px; border-radius:6px; }"
            "QListWidget::item:selected { background:#E3F2FD; color:#1976D2; }")
        self.zone_list.currentRowChanged.connect(self._on_zone_changed)
        left_lay.addWidget(self.zone_list, 1)

        # 危险动作孤立放这里：低调小字链接，须键入确认
        self.btn_clear = QPushButton("清空当前分区…")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setStyleSheet(
            "QPushButton { color:#B0B8C4; background:transparent; border:none; "
            "padding:6px 4px; font-size:12px; font-weight:bold; text-align:left; }"
            "QPushButton:hover { color:#C62828; background:#FDECEA; border-radius:6px; }")
        self.btn_clear.setToolTip(
            "【高危·不可逆】删除当前分区下的全部缓存。\n"
            "日常完全用不到；确需清空时必须输入「清空」二字才会执行。")
        self.btn_clear.clicked.connect(self._clear_zone)
        left_lay.addWidget(self.btn_clear)
        splitter.addWidget(left)

        # ---- 右：明细 ----
        right = QFrame()
        right.setStyleSheet(_CARD_QSS)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(12, 10, 12, 10)
        right_lay.setSpacing(8)

        tools = QHBoxLayout()
        self.lbl_zone_title = QLabel("—")
        self.lbl_zone_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1F2430;")
        tools.addWidget(self.lbl_zone_title)
        tools.addStretch()
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("过滤代码…")
        self.txt_filter.setFixedWidth(160)
        self.txt_filter.setFixedHeight(28)
        self.txt_filter.setStyleSheet(
            "QLineEdit { padding:0 10px; border:1px solid #E0E4EC; border-radius:8px; "
            "background:white; font-size:12px; }")
        self.txt_filter.textChanged.connect(self._render_items)
        tools.addWidget(self.txt_filter)
        self.btn_select_all = QPushButton("全选")
        self.btn_select_all.setStyleSheet(_FLAT_QSS)
        self.btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        tools.addWidget(self.btn_select_all)
        self.btn_select_none = QPushButton("取消")
        self.btn_select_none.setStyleSheet(_FLAT_QSS)
        self.btn_select_none.clicked.connect(lambda: self._set_all_checked(False))
        tools.addWidget(self.btn_select_none)
        right_lay.addLayout(tools)

        self.table = QTableWidget()
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setAlternatingRowColors(True)
        # 【v5.11】勾选不依赖 Qt 原生 checkbox / 行选中：
        #   · setSelectionMode(NoSelection) —— 点击不再高亮整行（上一版蓝色底太难看了）；
        #   · 第 0 列自绘 ☐/☑ 字符，点击整格切换，见 _on_cell_clicked。
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(
            "QTableWidget { background:white; alternate-background-color:#F7F9FC; "
            "border:none; gridline-color:#EEF1F6; }"
            "QTableWidget::item:focus { outline: none; }"
            "QHeaderView::section { background:#F4F6FA; color:#5B6472; font-weight:bold; "
            "border:none; padding:8px; }")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(_COL_CHECK, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(_COL_CHECK, 44)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.cellClicked.connect(self._on_cell_clicked)
        right_lay.addWidget(self.table, 1)

        # ---- 底部：日常操作行（更新/全量/删除 视觉连续，间隔控件归左）----
        ops = QHBoxLayout()
        ops.setSpacing(8)
        self.lbl_selected = QLabel("已选 0 项")
        self.lbl_selected.setStyleSheet("font-size: 12px; color: #5B6472;")
        ops.addWidget(self.lbl_selected)
        ops.addSpacing(10)
        ops.addWidget(self._minor("同步间隔(秒)"))
        self.spin_interval = NoWheelDoubleSpinBox()
        self.spin_interval.setRange(0.0, 10.0)
        self.spin_interval.setDecimals(1)
        self.spin_interval.setSingleStep(0.1)
        self.spin_interval.setValue(0.6)
        # 宽度留足：0.6~10.0 小数 + 上下箭头都要完整显示，不能被挤压成"…"
        self.spin_interval.setFixedWidth(82)
        self.spin_interval.setFixedHeight(28)
        self.spin_interval.setToolTip("批量操作时每只之间的等待时间。\n"
                                      "越大越不容易被行情源限流（防封 IP）。")
        ops.addWidget(self.spin_interval)
        ops.addStretch()

        self.btn_sync = QPushButton("🔄 更新到最新")
        self.btn_sync.setStyleSheet(_FLAT_QSS)
        self.btn_sync.setToolTip(
            "只下载本地缺失的最新几天数据，速度很快，是日常更新方式。\n"
            "已是最新的标的自动跳过；休市/未开盘时按「已是最新」处理，不算失败。")
        self.btn_sync.clicked.connect(lambda: self._sync_selected(force_full=False))
        ops.addWidget(self.btn_sync)

        self.btn_force = QPushButton("⟳ 重新全量下载")
        self.btn_force.setStyleSheet(_FLAT_QSS)
        self.btn_force.setToolTip(
            "丢弃本地已有数据，从 2010-01-01 起整段重新下载，耗时较长，日常不需要。\n"
            "仅在怀疑数据被「前复权修正」搞坏、或本地数据异常时才用 —— "
            "增量更新永远修不回历史价格。")
        self.btn_force.clicked.connect(lambda: self._sync_selected(force_full=True))
        ops.addWidget(self.btn_force)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#E3E7EF;")
        sep.setFixedHeight(20)
        ops.addWidget(sep)

        self.btn_delete = QPushButton("🗑 删除选中")
        self.btn_delete.setStyleSheet(
            "QPushButton { color:#C62828; background:transparent; border:none; padding:0 10px; "
            "font-weight:bold; border-radius:6px; } QPushButton:hover { background:#FDECEA; }"
            "QPushButton:disabled { color:#B4BECB; }")
        self.btn_delete.setToolTip("删除勾选的缓存文件（删除前会二次确认，且再次用到会重新下载）")
        self.btn_delete.clicked.connect(self._delete_selected)
        ops.addWidget(self.btn_delete)
        right_lay.addLayout(ops)

        splitter.addWidget(right)
        splitter.setSizes([235, 900])
        root.addWidget(splitter, 1)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #1976D2;")
        root.addWidget(self.lbl_status)

    @staticmethod
    def _minor(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #5B6472;")
        return lbl

    # ==========================================
    # 分区清单
    # ==========================================
    def _refresh_zones(self):
        stats = self.lake.zone_stats()
        self.zone_list.blockSignals(True)
        self.zone_list.clear()
        for zone in ZONE_ORDER:
            info = stats.get(zone, {"count": 0, "bytes": 0})
            label = ZONE_LABELS.get(zone, zone)
            self.zone_list.addItem(f"{label}  ({zone})\n{info['count']} 项 · {_fmt_bytes(info['bytes'])}")
        self.zone_list.blockSignals(False)
        self.zone_list.setCurrentRow(ZONE_ORDER.index(self._current_zone))
        total = sum(v["bytes"] for v in stats.values())
        self.lbl_root.setText(f"{self.lake.lake_root}　·　总占用 {_fmt_bytes(total)}")

    def _on_zone_changed(self, row: int):
        if row < 0 or row >= len(ZONE_ORDER):
            return
        self._current_zone = ZONE_ORDER[row]
        self._scan_current_zone()

    def _rescan(self):
        self._refresh_zones()
        self._scan_current_zone()

    def _scan_current_zone(self):
        zone = self._current_zone
        self.lbl_zone_title.setText(f"{ZONE_LABELS.get(zone, zone)}  ({zone})")
        self.lbl_status.setText("正在扫描…")
        self._scan_worker = ScanWorker(zone, lake=self.lake, parent=self)
        self._scan_worker.result.connect(self._on_scanned)
        self._scan_worker.start()

    def _on_scanned(self, zone: str, items: list):
        # 【竞态防护】快速切换分区时，迟到的旧扫描结果必须丢弃
        if zone != self._current_zone:
            return
        self._items = items or []
        # 勾选集合只保留仍存在于当前分区的标的
        self._checked &= {item["name"] for item in self._items}
        self._render_items()
        total_bytes = sum(i["bytes"] for i in self._items)
        self.lbl_status.setText(
            f"{len(self._items)} 项 · 合计 {_fmt_bytes(total_bytes)}"
            + ("" if self._current_zone in SYNCABLE else "　（该分区暂不支持联网同步）"))
        self._sync_ops_enabled()

    # ==========================================
    # 明细表
    # ==========================================
    def _visible_items(self) -> list[dict]:
        keyword = (self.txt_filter.text() or "").strip().lower()
        return [item for item in self._items
                if not keyword or keyword in str(item["name"]).lower()]

    def _render_items(self):
        """按当前过滤条件整表重建。

        【v5.10 修正】此前用"enumerate(self._items) + 跳过不匹配项"来定位行号，
        一旦开了过滤，行号会与 setRowCount 的真实行错位，单元格填错/漏填。
        现在直接对过滤后的可见列表按 0..n-1 顺序铺行，杜绝错位。
        """
        visible = self._visible_items()
        self.table.blockSignals(True)
        self.table.setRowCount(len(visible))

        for row, item in enumerate(visible):
            name = str(item["name"])

            # 【v5.11】自绘勾选符号：☐ 未选 / ☑ 已选。
            # 不用 Qt 原生 checkbox —— 原生指示器的命中区域/双重触发/行高亮都不可控。
            check = QTableWidgetItem("☑" if name in self._checked else "☐")
            check.setFlags(Qt.ItemFlag.ItemIsEnabled)   # 只读样式：禁止编辑/选中/原生勾选
            check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            check.setForeground(QColor("#1976D2") if name in self._checked
                                else QColor("#C9CFD9"))
            check.setToolTip("点击本格切换勾选")
            self.table.setItem(row, _COL_CHECK, check)

            name_cell = QTableWidgetItem(name)
            name_cell.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            self.table.setItem(row, _COL_NAME, name_cell)

            values = [
                f"{item['rows']:,}" if item["rows"] else "—",
                item["first_date"] or "—",
                item["last_date"] or "—",
                _fmt_bytes(item["bytes"]),
                item["modified"],
            ]
            for col, text in enumerate(values, start=2):
                cell = QTableWidgetItem(text)
                if col in (2, 3, 4):   # 行数 / 起始 / 结束 用弱化色
                    cell.setForeground(QColor("#5B6472"))
                self.table.setItem(row, col, cell)

        self.table.blockSignals(False)
        self._update_selected_count()

    def _checked_names(self) -> list[str]:
        """当前勾选且仍存在于本分区的标的名（勾选集合以 _checked 为唯一真相源）"""
        valid = {item["name"] for item in self._items}
        return sorted(self._checked & valid)

    def _set_all_checked(self, checked: bool):
        """全选/取消当前可见项（配合过滤搜索的直觉）"""
        for item in self._visible_items():
            name = str(item["name"])
            if checked:
                self._checked.add(name)
            else:
                self._checked.discard(name)
        self._render_items()

    def _on_cell_clicked(self, row: int, column: int):
        """勾选列整格可点：☐ → ☑（唯一切换入口，杜绝双重触发）"""
        if column != _COL_CHECK:
            return
        mark = self.table.item(row, _COL_CHECK)
        name_cell = self.table.item(row, _COL_NAME)
        if mark is None or name_cell is None:
            return
        name = name_cell.text()
        if name in self._checked:
            self._checked.discard(name)
        else:
            self._checked.add(name)
        self._refresh_row_mark(row)
        self._update_selected_count()

    def _refresh_row_mark(self, row: int):
        """按当前勾选集合刷新某一行的 ☐/☑（只改一格，不重建整表）"""
        mark = self.table.item(row, _COL_CHECK)
        name_cell = self.table.item(row, _COL_NAME)
        if mark is None or name_cell is None:
            return
        checked = name_cell.text() in self._checked
        mark.setText("☑" if checked else "☐")
        mark.setForeground(QColor("#1976D2") if checked else QColor("#C9CFD9"))

    def _update_selected_count(self):
        count = len(self._checked_names())
        self.lbl_selected.setText(f"已选 {count} 项")
        for btn in (self.btn_delete, self.btn_sync, self.btn_force):
            btn.setEnabled(count > 0)

    def _sync_ops_enabled(self):
        available = self._current_zone in SYNCABLE
        for btn in (self.btn_sync, self.btn_force):
            btn.setVisible(available)
        # 非空分区才允许"清空"；不可同步的分区（如财报）也能清
        self.btn_clear.setEnabled(bool(self._items))

    # ==========================================
    # 删除（单条/批量）
    # ==========================================
    def _delete_selected(self):
        names = self._checked_names()
        if not names:
            return
        bytes_ = sum(i["bytes"] for i in self._items if i["name"] in set(names))
        reply = QMessageBox.question(
            self, "删除确认",
            f"即将从【{ZONE_LABELS.get(self._current_zone, self._current_zone)}】"
            f"删除 {len(names)} 项缓存，释放约 {_fmt_bytes(bytes_)}。\n\n"
            f"⚠️ 此操作不可撤销；删除后再次用到会重新联网下载。\n\n确定删除吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        failed = [n for n in names if not self.lake.delete_data(self._current_zone, n)]
        self._rescan()
        if failed:
            QMessageBox.warning(
                self, "部分删除失败",
                f"{len(failed)} 项未能删除。\n\n"
                f"常见原因：文件正被其它程序占用（Windows 句柄未释放）。\n"
                f"请稍后重试：{', '.join(failed[:10])}"
                f"{' …' if len(failed) > 10 else ''}")
        else:
            self.lbl_status.setText(f"已删除 {len(names)} 项")

    def _clear_zone(self):
        """清空当前分区 —— 危险入口已被孤立，仍要求键入「清空」确认，双重防呆"""
        zone = self._current_zone
        zone_label = ZONE_LABELS.get(zone, zone)
        count = len(self._items)
        if count == 0:
            QMessageBox.information(self, "提示", "该分区当前为空，无需清空。")
            return
        total_bytes = _fmt_bytes(sum(i["bytes"] for i in self._items))

        # 第一道闸：说明后果
        QMessageBox.warning(
            self, "高危操作",
            f"你即将清空【{zone_label}】分区的全部 {count} 项缓存（约 {total_bytes}）。\n\n"
            f"⚠️ 这会同时影响「市场行情」「市场回测」的本地命中，且不可恢复；\n"
            f"    若确实需要，下一步还要输入「清空」二字才会真正执行。")
        # 第二道闸：必须键入「清空」
        typed, ok = QInputDialog.getText(
            self, "最终确认",
            f"请输入「清空」二字，以确认清空【{zone_label}】分区：")
        if not ok or (typed or "").strip() != "清空":
            self.lbl_status.setText("已取消清空")
            return

        ok_count, total = self.lake.clear_zone(zone)
        self._rescan()
        self.lbl_status.setText(f"已清空 {ok_count}/{total} 项")
        if ok_count < total:
            QMessageBox.warning(self, "部分失败", f"{total - ok_count} 项未能删除（可能被占用），请稍后重试。")

    # ==========================================
    # 同步（更新到最新 / 重新全量下载）
    # ==========================================
    def _sync_selected(self, force_full: bool):
        names = self._checked_names()
        if not names:
            return
        if self._current_zone not in SYNCABLE:
            QMessageBox.information(self, "提示", "该分区暂不支持联网同步。")
            return
        action = "重新全量下载" if force_full else "更新到最新"
        if force_full and len(names) > 20:
            reply = QMessageBox.question(
                self, "确认",
                f"「{action}」会忽略本地已有数据、从 2010 年重新整段下载，"
                f"耗时较长，仅在怀疑数据异常时才需要。\n\n对勾选的 {len(names)} 只继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._set_busy(True, f"正在{action} {len(names)} 只…")
        self._sync_worker = SyncWorker(
            names, zone=self._current_zone, force_full=force_full,
            policy=ThrottlePolicy(interval=float(self.spin_interval.value())),
            parent=self)
        self._sync_worker.finished.connect(self._on_sync_finished)
        self._sync_worker.start()

    def _on_sync_finished(self, stats: dict):
        self._set_busy(False, "")
        tail = "（已中断）" if stats.get("aborted") else ""
        self.lbl_status.setText(
            f"{tail}完成：成功 {stats.get('ok', 0)} · 跳过 {stats.get('skipped', 0)} · "
            f"失败 {stats.get('fail', 0)} · 新增 {stats.get('added', 0)} 行")
        self._rescan()
        if stats.get("fail"):
            QMessageBox.warning(
                self, "部分失败",
                f"{stats['fail']} 只未能同步。常见原因：\n"
                f"① 代码输入有误；② 该股已退市/长期停牌，行情源不再提供（属正常现象）；\n"
                f"③ 网络抖动或触发限流。\n\n"
                f"失败标的：{', '.join(stats.get('symbols_failed', [])[:10])}"
                f"{' …' if len(stats.get('symbols_failed', [])) > 10 else ''}")
        self._sync_worker = None

    def _set_busy(self, busy: bool, text: str):
        for btn in (self.btn_sync, self.btn_force, self.btn_delete,
                    self.btn_clear, self.btn_bulk, self.btn_rescan,
                    self.btn_select_all, self.btn_select_none):
            btn.setEnabled(not busy)
        if text:
            self.lbl_status.setText(text)

    # ==========================================
    # 预下载
    # ==========================================
    def _open_bulk(self):
        dialog = BulkDownloadDialog(self.main_win, self)
        dialog.exec()
        self._rescan()
