# ui/widgets/download_queue_panel.py
"""下载队列面板 (v1.43 · §7-B11) —— **主窗口内的浮层**，不是独立窗口。

【形态为什么是浮层，而不是 QDialog】（v1.43 收口 · 按样板返工）
  样板 `design/1.43-bg-download/index.html` 定的是 `position:absolute; right:18px;
  bottom:52px` 的**窗口内浮层卡片**（圆角 + 阴影）。第一版按施工规格写成了
  `QDialog(setModal(False))` —— 它虽然不阻塞操作，但仍是**独立顶层窗口**：
  有标题栏、会进任务栏、还能被拖到主窗口外面，且不会随主窗口移动。
  用户一眼就看出"跟样板完全是两回事"（样板 → 规格 这一步把视觉语言丢了）。
  ⇒ 现在改回浮层：`QFrame` 挂在主窗口的内容区，位置由主窗口在显示/缩放时算。

【纪律】面板**不存任务数据**：每次 `refresh()` 都从 `hub.snapshot()` 现取，
  所以任何入口（批量弹窗 / 数据管理 / M2 / M3）提交的任务都在这里看到同一份真相。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect,
                             QHBoxLayout, QHeaderView, QLabel, QProgressBar,
                             QPushButton, QSizePolicy, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ui.dialogs.download_settings import DownloadSettingsDialog
from ui.download_hub import (STATUS_CANCELLED, STATUS_DONE, STATUS_LABELS,
                             STATUS_QUEUED, STATUS_RUNNING)
from ui.widgets.custom_widgets import FLAT_QSS   # ★v6.70 §9-F③ 样式唯一出口

PANEL_WIDTH = 490                    # 与样板一致（490px）
DOWNLOAD_PANEL_GAP_RIGHT = 18        # 右边距（样板 right:18px）
DOWNLOAD_PANEL_GAP_BOTTOM = 64       # 底边距（正好落在**浮动下载条**上方，条高 50 + 14 余量）

_ROW_H = 40
_HEAD_H = 42
_THEAD_H = 28
_FOOT_H = 46

_PANEL_QSS = (
    "QFrame#QueuePanel { background:#FFFFFF; border:1px solid #E4E9F0; border-radius:12px; }"
    "QLabel#QueueTitle { font-size:13.5px; font-weight:bold; color:#1F2430; }"
    "QLabel#QueueSum { font-size:12px; color:#5B6472; }"
    "QLabel#QueueX { color:#8A94A6; font-size:14px; }"
    "QLabel#QueueX:hover { color:#1F2430; }"
    "QTableWidget { font-size:12.5px; border:none; background:transparent; }"
    "QTableWidget::item:selected { background:#F2F7FE; color:#1F2430; }"
    "QHeaderView::section { background:#FFFFFF; border:none;"
    " border-bottom:1px solid #F0F3F7; padding:5px 8px; font-size:11.5px; color:#8A94A6; }"
    "QProgressBar#MiniProg { border:none; border-radius:3px; background:#EDF1F6; }"
    "QProgressBar#MiniProg::chunk { background:#1976D2; border-radius:3px; }"
)

# 状态胶囊配色（与样板 `.st.run / .st.queue / .st.ok / .st.part` 同源）
_PILL = {
    STATUS_RUNNING: ("#E3F2FD", "#1976D2"),
    STATUS_QUEUED: ("#F0F2F5", "#8A94A6"),
    STATUS_DONE: ("#E8F5E9", "#2E7D32"),
    STATUS_CANCELLED: ("#FFF3E0", "#E65100"),
}


def pill_qss(status: str) -> str:
    """状态胶囊样式（**唯一出口** —— 别在各处手写配色）。

    ⚠ 形状是**圆角气泡**（radius ≥ 半高 ⇒ 两端成圆弧），不是"整格色块"：
      只要把它直接 `setCellWidget` 就会撑满整格、看起来像色块填充（用户实测吐槽），
      ⇒ 必须套一层容器让它保持"只有内容那么大"（见 `_cell`）。
    """
    bg, fg = _PILL.get(status, ("#F0F2F5", "#8A94A6"))
    return (f"background:{bg}; color:{fg}; border-radius:10px;"
            f"padding:2px 10px; font-size:11.5px;")


class _ClickableLabel(QLabel):
    """能点的小标签（✕ 用）。

    ⚠ 不能靠"给实例赋 `mousePressEvent`"来接管点击 —— Qt 的事件派发走的是 C++ 虚函数，
      实例上的 Python 属性不参与；必须子类覆写（本批踩到）。
    """

    def __init__(self, text: str, on_click, parent=None):
        super().__init__(text, parent)
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):  # noqa: N802 —— Qt 命名
        if callable(self._on_click):
            self._on_click()
        event.accept()


def _state_of(job: dict) -> tuple:
    """`(状态键, 展示文案)`：完成但有失败 ⇒ 「部分失败」（橙，与样板一致）。"""
    status = str(job.get("status") or "")
    if status == STATUS_DONE and int(job.get("failed") or 0) > 0:
        return STATUS_CANCELLED, "部分失败"        # 复用橙色档
    return status, STATUS_LABELS.get(status, status)


class DownloadQueuePanel(QFrame):
    """浮层：任务表（任务 / 进度 / 状态 / 操作）+ 汇总行 + 三个动作。"""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self._hub = hub
        self.setObjectName("QueuePanel")
        self.setStyleSheet(_PANEL_QSS)
        self.setFixedWidth(PANEL_WIDTH)
        # 浮层质感（样板 `box-shadow: 0 10px 30px rgba(31,36,48,.16)`）
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(31, 36, 48, 40))
        self.setGraphicsEffect(shadow)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 头部：标题 + 运行中/排队胶囊 + ✕ ----------
        head = QFrame()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(14, 10, 12, 10)
        head_lay.setSpacing(8)
        self.lbl_title = QLabel("⬇ 下载队列")
        self.lbl_title.setObjectName("QueueTitle")
        head_lay.addWidget(self.lbl_title)
        self.lbl_run = QLabel("运行中 0")
        self.lbl_run.setStyleSheet(pill_qss(STATUS_RUNNING))
        head_lay.addWidget(self.lbl_run)
        self.lbl_queued = QLabel("排队 0")
        self.lbl_queued.setStyleSheet(pill_qss(STATUS_QUEUED))
        head_lay.addWidget(self.lbl_queued)
        head_lay.addStretch()
        self.btn_settings = _ClickableLabel("⚙", self._open_settings, parent=head)
        self.btn_settings.setObjectName("QueueX")
        self.btn_settings.setToolTip(
            "全局下载设置：间隔 / 抖动 / 熍断 / 跳过 / 并发（一处调、处处生效）")
        head_lay.addWidget(self.btn_settings)
        self.btn_close = _ClickableLabel("✕", self.hide, parent=head)
        self.btn_close.setObjectName("QueueX")
        self.btn_close.setToolTip("收起面板（不会停止下载）")
        head_lay.addWidget(self.btn_close)
        head.setFixedHeight(_HEAD_H)
        root.addWidget(head)

        # ---------- 任务表（进度=迷你条 / 状态=胶囊 / 操作=每行按钮）----------
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["任务", "进度", "状态", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # ⚠ 不用 ResizeToContents（§11.5-69：动态测宽 × 逐格 setItem = 平方级冻死 UI）
        for col, w in ((1, 120), (2, 104), (3, 96)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, w)
        self.table.horizontalHeader().setFixedHeight(_THEAD_H)
        root.addWidget(self.table)

        # ---------- 汇总 + 三个动作 ----------
        foot = QFrame()
        foot_lay = QHBoxLayout(foot)
        foot_lay.setContentsMargins(12, 8, 12, 8)
        foot_lay.setSpacing(8)
        self.lbl_sum = QLabel("队列为空 —— 任何入口提交的下载都会出现在这里。")
        self.lbl_sum.setObjectName("QueueSum")
        # 窄屏不撑窗（§11.5-73）：单行标签可缩不可撑，长文案走 tooltip
        self.lbl_sum.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        foot_lay.addWidget(self.lbl_sum, 1)
        self.btn_retry = QPushButton("只重试失败")
        self.btn_copy = QPushButton("复制失败清单")
        self.btn_stop = QPushButton("全部中断")
        for btn in (self.btn_retry, self.btn_copy, self.btn_stop):
            btn.setStyleSheet(FLAT_QSS)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setEnabled(False)
            foot_lay.addWidget(btn)
        foot.setFixedHeight(_FOOT_H)
        root.addWidget(foot)

        self.btn_retry.clicked.connect(self._retry_selected)
        self.btn_copy.clicked.connect(self._copy_selected)
        self.btn_stop.clicked.connect(self._stop_all)
        self.table.itemSelectionChanged.connect(self._sync_buttons)

        hub.jobs_changed.connect(self.refresh)
        hub.job_progress.connect(lambda *_: self.refresh())
        hub.job_finished.connect(lambda *_: self.refresh())
        self.refresh()

    # ==========================================
    # 布局：高度随行数（1~4 行）
    # ==========================================
    def preferred_height(self) -> int:
        rows = max(1, min(4, max(1, self.table.rowCount())))
        return _HEAD_H + _THEAD_H + rows * _ROW_H + _FOOT_H

    def _fit_height(self) -> None:
        self.setFixedHeight(self.preferred_height())

    # ==========================================
    def _selected_id(self) -> int | None:
        """当前行的任务 id（没行 / 未选 ⇒ None）。"""
        row = self.table.currentRow()
        item = self.table.item(row, 0) if 0 <= row < self.table.rowCount() else None
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def refresh(self) -> None:
        """从 `hub.snapshot()` 现取并重画（面板不存任何任务数据）。"""
        jobs = self._hub.snapshot()
        keep = self._selected_id()
        self.table.blockSignals(True)
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self._fill_row(row, job)
        self.table.blockSignals(False)
        if keep is not None:
            for row, job in enumerate(jobs):
                if job["id"] == keep:
                    self.table.selectRow(row)
                    break
        running = sum(1 for j in jobs if j["status"] == STATUS_RUNNING)
        queued = sum(1 for j in jobs if j["status"] == STATUS_QUEUED)
        self.lbl_run.setText(f"运行中 {running}")
        self.lbl_queued.setText(f"排队 {queued}")
        self._fit_height()
        self._sync_buttons()

    def _cell(self, widget: QWidget, *, left: int = 10, right: int = 10,
              trailing: bool = True) -> QWidget:
        """把单元格内容**竖直居中**（并做小幅水平内缩）后放进容器。

        ⚠ 【为什么不直接 `setCellWidget(控件)`】那样控件会被撑满整格：
          进度条变成"贴顶的直条"、状态胶囊变成"整格色块" —— 用户实测就是这个观感
          （样板里两者都是"竖直居中 + 两端圆角 / 圆角气泡"）。⇒ 一律套容器 + 上下 stretch。
        """
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.setContentsMargins(left, 0, right, 0)
        row.setSpacing(0)
        row.addWidget(widget)
        if trailing:
            row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        return holder

    def _fill_row(self, row: int, job: dict) -> None:
        status, label = _state_of(job)

        name = QTableWidgetItem(str(job.get("label") or ""))
        name.setData(Qt.ItemDataRole.UserRole, job["id"])
        name.setToolTip(f"#{job['id']} · 来源 {job.get('origin') or '—'}\n"
                        f"{job.get('receipt') or job.get('text') or ''}")
        self.table.setItem(row, 0, name)

        bar = QProgressBar()
        bar.setObjectName("MiniProg")
        bar.setTextVisible(False)
        bar.setFixedHeight(6)              # 高 6 + 半径 3 ⇒ 两端成圆弧（样板观感）
        bar.setFixedWidth(100)             # 列宽 120 − 左右各 10 ⇒ 视觉上铺满但有小内缩
        bar.setRange(0, 100)
        bar.setValue(int(job.get("percent") or 0))
        bar.setToolTip(f"{job.get('done', 0)}/{job.get('total', 0)}"
                       f"（{job.get('percent', 0)}%）")
        self.table.setCellWidget(row, 1, self._cell(bar, trailing=False))

        pill = QLabel(label)
        pill.setStyleSheet(pill_qss(status))
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setToolTip(job.get("receipt") or job.get("text") or label)
        self.table.setCellWidget(row, 2, self._cell(pill))

        self.table.setCellWidget(row, 3, self._cell(self._row_action(job, status)))
        self.table.setRowHeight(row, _ROW_H)

    def _row_action(self, job: dict, status: str) -> QWidget:
        """每行的操作（样板：运行中/排队中 = 中断；有失败 = 只重试失败）。

        ★v6.70 / §9-F② 多一档：**已中断且还有没轮到的标的** ⇒ 给「继续 N 只」。
        ⚠ 判据用**原始状态** `job["status"]`，不用传进来的 `status` —— 后者会把
          “完成但有失败”映射成同一个橙色档（`_state_of`），拿它判“被中断”就误判了。
        ⚠ 优先级“继续”在“只重试失败”之前：失败那批仍可由底部「只重试失败」处理，
          而“没轮到的那批”**只在**这个入口能拿到（它们不在失败清单里）。
        """
        jid = int(job["id"])
        if status in (STATUS_RUNNING, STATUS_QUEUED):
            btn = QPushButton("中断")
            btn.setStyleSheet(FLAT_QSS)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=jid: (self._hub.cancel(i), self.refresh()))
            return btn
        rest = int(job.get("rest") or 0)
        if str(job.get("status") or "") == STATUS_CANCELLED and rest > 0:
            # ★v6.70 加固（二次修改）：这条的"没轮到的"已经续传过 ⇒ 收成**不可点**的回执。
            #   否则旧行会一直挂着「继续 N 只」，用户再点一次 = 同范围重投
            #   （续传任务已结束 + `force_full` 时就是整段重下）；接着该看续传那一行。
            if job.get("continued"):
                btn = QPushButton("已续传")
                btn.setStyleSheet(FLAT_QSS)
                btn.setEnabled(False)
                btn.setToolTip(
                    "这批『没轮到的』已经用**同一份参数**续传过（一条单独的任务）。\n"
                    "接着看下面那条「继续未完成 · …」；它若也被中断，那一行会再给「继续」。")
                return btn
            btn = QPushButton(f"继续 {rest} 只")
            btn.setStyleSheet(FLAT_QSS)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(
                f"这批被中断时还有 {rest} 只一次都没抓到（所以不在失败清单里）。\n"
                "点这里：按**同一份参数**只补这些，已抓过的不重抓、已最新的自动跳过。")
            btn.clicked.connect(lambda _=False, i=jid: (self._hub.continue_unfinished(i),
                                                        self.refresh()))
            return btn
        if int(job.get("failed") or 0) > 0:
            btn = QPushButton("只重试失败")
            btn.setStyleSheet(FLAT_QSS)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=jid: (self._hub.retry_failures(i), self.refresh()))
            return btn
        return QLabel("")

    def _current_job(self) -> dict | None:
        """要操作的那一条：选中行优先；没选中就取最近一条（用户要动的多数是它）。"""
        jobs = self._hub.snapshot()
        if not jobs:
            return None
        jid = self._selected_id()
        for job in jobs:
            if job["id"] == jid:
                return job
        return jobs[-1]

    def _sync_buttons(self) -> None:
        job = self._current_job() if self.table.rowCount() else None
        if job is None:
            self.lbl_sum.setText("队列为空 —— 任何入口提交的下载都会出现在这里。")
            for btn in (self.btn_retry, self.btn_copy, self.btn_stop):
                btn.setEnabled(False)
            return
        failed = int(job.get("failed") or 0)
        self.lbl_sum.setText(f"{job['label']} · {job.get('receipt') or job.get('text') or ''}"
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

    def _stop_all(self) -> None:
        self._hub.cancel(None)
        self.refresh()

    def _open_settings(self) -> None:
        """打开全局下载设置对话框（挂到主窗口，避免面板隐藏时变孤儿）。"""
        DownloadSettingsDialog(self.window()).exec()
