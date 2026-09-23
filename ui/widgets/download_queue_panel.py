# ui/widgets/download_queue_panel.py
"""
下载队列面板 (v1.43 · §7-B11) —— **非模态**，可以一直挂着当监控窗。

【为什么不是"回到弹窗里看进度"】旧版所有进度/失败清单/复制按钮都长在批量预下载弹窗里，
  弹窗一关就全没了 ⇒ 这些能力搬到这里，并且**不属于任何页面**：
  任务在 hub 里，面板只是它的一个视图（同 §11.5-11 单一状态源）。

【纪律】面板**不存任务数据**：每次 `refresh()` 都从 `hub.snapshot()` 现取，
  所以任何入口（弹窗 / 数据管理 / M2 / M3）提交的任务都在这里看到同一份真相。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QHeaderView,
                             QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                             QVBoxLayout)

from ui.download_hub import STATUS_LABELS
from ui.widgets.backtest_panes import FLAT_QSS

_TABLE_QSS = ("QTableWidget { font-size:12.5px; border:1px solid #E7EAF0;"
              " border-radius:8px; background:#fff; }"
              "QHeaderView::section { background:#FAFBFD; border:none;"
              " border-bottom:1px solid #E7EAF0; padding:6px 8px;"
              " font-size:11.5px; color:#8A94A6; }")


class DownloadQueuePanel(QDialog):
    """任务列表 + 进度 + 状态 + 「只重试失败 / 复制失败清单 / 全部中断」。"""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self._hub = hub
        self.setWindowTitle("⬇ 下载队列")
        self.setModal(False)                      # ★ 关键：开着它也能操作主界面
        self.resize(560, 300)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        head = QLabel("任务在后台串行执行（一次只跑一批，避免把行情源打急）。"
                      "关掉本窗口不会停止下载。")
        head.setStyleSheet("font-size:11.5px; color:#8A94A6;")
        head.setWordWrap(True)
        root.addWidget(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["任务", "进度", "状态", "失败"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(_TABLE_QSS)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 96)
        self.table.setColumnWidth(3, 52)
        root.addWidget(self.table, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.lbl_sum = QLabel("—")
        self.lbl_sum.setStyleSheet("font-size:12px; color:#5B6472;")
        foot.addWidget(self.lbl_sum, 1)
        self.btn_retry = QPushButton("只重试失败")
        self.btn_copy = QPushButton("复制失败清单")
        self.btn_stop = QPushButton("全部中断")
        for b in (self.btn_retry, self.btn_copy, self.btn_stop):
            b.setStyleSheet(FLAT_QSS)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setEnabled(False)
            foot.addWidget(b)
        root.addLayout(foot)

        self.btn_retry.clicked.connect(self._retry_selected)
        self.btn_copy.clicked.connect(self._copy_selected)
        self.btn_stop.clicked.connect(lambda: (self._hub.cancel(None), self.refresh()))

        hub.jobs_changed.connect(self.refresh)
        hub.job_progress.connect(lambda *_: self.refresh())
        hub.job_finished.connect(lambda *_: self.refresh())
        self.table.itemSelectionChanged.connect(self._sync_buttons)

    # ==========================================
    def _selected_id(self) -> int | None:
        """当前行的任务 id（没行 / 未选 ⇒ None）。"""
        row = self.table.currentRow()
        it = self.table.item(row, 0) if 0 <= row < self.table.rowCount() else None
        return int(it.data(Qt.ItemDataRole.UserRole)) if it is not None else None

    def refresh(self) -> None:
        jobs = self._hub.snapshot()
        keep = self._selected_id()
        self.table.blockSignals(True)
        self.table.setRowCount(len(jobs))
        for r, j in enumerate(jobs):
            it = QTableWidgetItem(j["label"])
            it.setData(Qt.ItemDataRole.UserRole, j["id"])
            it.setToolTip(f"#{j['id']} · 来源 {j['origin'] or '—'}\n{j['receipt'] or j['text']}")
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(f"{j['done']}/{j['total']}"
                                                       f"（{j['percent']}%）"))
            self.table.setItem(r, 2, QTableWidgetItem(STATUS_LABELS.get(j["status"], j["status"])))
            self.table.setItem(r, 3, QTableWidgetItem(str(j["failed"]) or ""))
        self.table.blockSignals(False)
        if keep is not None and any(j["id"] == keep for j in jobs):
            for r, j in enumerate(jobs):
                if j["id"] == keep:
                    self.table.selectRow(r)
                    break
        self._sync_buttons()

    def _current_job(self) -> dict | None:
        """要操作的那一条：选中行优先；没选中就取最近一条（用户要动的多数是它）。"""
        jobs = self._hub.snapshot()
        if not jobs:
            return None
        jid = self._selected_id()
        for j in jobs:
            if j["id"] == jid:
                return j
        return jobs[-1]

    def _sync_buttons(self) -> None:
        job = self._current_job() if self.table.rowCount() else None
        if job is None:
            self.lbl_sum.setText("队列为空 —— 任何入口提交的下载都会出现在这里。")
            for b in (self.btn_retry, self.btn_copy, self.btn_stop):
                b.setEnabled(False)
            return
        failed = int(job.get("failed") or 0)
        self.lbl_sum.setText(f"{job['label']} · {job['receipt'] or job['text']}"
                             + (f"（失败 {failed} 只）" if failed else ""))
        self.lbl_sum.setToolTip(self.lbl_sum.text())
        self.btn_retry.setEnabled(failed > 0)
        self.btn_copy.setEnabled(failed > 0)
        self.btn_stop.setEnabled(self._hub.pending_count() > 0)

    # ==========================================
    def _retry_selected(self) -> None:
        job = self._current_job()
        if job:
            self._hub.retry_failures(job["id"])
            self.refresh()

    def _copy_selected(self) -> None:
        job = self._current_job()
        if not job:
            return
        real = self._hub.get(job["id"])
        symbols = real.failures if real is not None else []
        if symbols:
            QApplication.clipboard().setText("\n".join(symbols))
            self.lbl_sum.setText(f"已复制 {len(symbols)} 只失败标的到剪贴板。")
