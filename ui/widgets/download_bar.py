# ui/widgets/download_bar.py
"""
主窗口底部的**下载状态条** (v1.43 · §7-B11) —— 后台下载时的唯一全局可见出口。

【为什么放在主窗口而不是各页面】
  下载是**跨页面**的长任务（几十分钟），而页面级回执有三个天生缺陷：
  ① 用户切走页面就看不见了；② 页面销毁时进度跟着没了；③ 每个页面各画一条 = 三套进度真源。
  ⇒ 真源在 `ui/download_hub.py`，本条只是它的一个**投影**（同 §11.5-11 单一状态源）。

【版式纪律】
  · **空闲时整条 `hide()`** ⇒ 不占高度，界面回到今天的样子（不新增常驻"皮"）。
  · 单行标签**只放短状态**，长说明进 tooltip，且水平策略 `Ignored` ——
    否则一条不换行的 `QLabel` 会把窗口的**最小宽度**顶大（§11.5-73 用户明令）。
  · 文案不自己拼：任务名 / 进度 / 预计剩余 / 完成回执全部来自 `DownloadJob`。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QSizePolicy, QWidget)

from ui.download_hub import STATUS_CANCELLED, STATUS_QUEUED, STATUS_RUNNING
from ui.widgets.backtest_panes import FLAT_QSS
from ui.widgets.custom_widgets import SYNC_ACTION_LABEL

_BAR_QSS = ("QWidget#DownloadBar { background:#FFFFFF; border-top:1px solid #E4E9F0; }"
            "QLabel#BarIco { font-size:13px; font-weight:bold; color:#1976D2; }"
            "QLabel#BarName { font-size:12.5px; font-weight:bold; color:#1F2430; }"
            "QLabel#BarTxt { font-size:12px; color:#5B6472; }"
            "QLabel#BarEta { font-size:12px; font-weight:bold; color:#1F2430; }"
            "QLabel#BarQueue { font-size:11.5px; color:#8A94A6; }"
            "QProgressBar#BarProg { border:none; border-radius:3px; background:#EDF1F6; }"
            "QProgressBar#BarProg::chunk { background:#1976D2; border-radius:3px; }")
_STOP_QSS = ("QPushButton { color:#E65100; background:transparent; border:none; "
             "padding:0 10px; font-weight:bold; border-radius:6px; }"
             "QPushButton:hover { background:#FFF3E0; }")
# 三种状态图标（与全站"蓝=进行中、绿=成功、橙=需要注意"一致）
_ICO_RUN, _ICO_OK, _ICO_WARN = "⬇", "✅", "⚠"


class DownloadBar(QWidget):
    """一行：`⬇ 任务名 ▮▮▮▮ 223/5849 · 000622  约剩 31 分钟  · 排队 2  [详情] [中断]`"""

    sig_detail = pyqtSignal()          # 打开队列面板（面板由主窗口持有）

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self._hub = hub
        self.setObjectName("DownloadBar")
        self.setStyleSheet(_BAR_QSS)
        self.setFixedHeight(32)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 10, 0)
        lay.setSpacing(8)
        self.lbl_ico = QLabel(_ICO_RUN)
        self.lbl_ico.setObjectName("BarIco")
        self.lbl_name = QLabel(SYNC_ACTION_LABEL)
        self.lbl_name.setObjectName("BarName")
        self.bar = QProgressBar()
        self.bar.setObjectName("BarProg")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setFixedHeight(6)
        self.bar.setFixedWidth(140)
        self.lbl_txt = QLabel("")
        self.lbl_txt.setObjectName("BarTxt")
        # ★ 可缩不可撑：长文本一律进 tooltip，别让单行 QLabel 顶大窗口最小宽度（§11.5-73）
        self.lbl_txt.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Preferred)
        self.lbl_eta = QLabel("")
        self.lbl_eta.setObjectName("BarEta")
        self.lbl_queue = QLabel("")
        self.lbl_queue.setObjectName("BarQueue")

        self.btn_detail = QPushButton("详情")
        self.btn_detail.setStyleSheet(FLAT_QSS)
        self.btn_detail.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detail.clicked.connect(self.sig_detail.emit)
        self.btn_stop = QPushButton("中断")
        self.btn_stop.setStyleSheet(_STOP_QSS)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setToolTip("停止当前任务（已下载的部分会保留，下次自动跳过）")
        self.btn_stop.clicked.connect(self._stop)
        self.btn_close = QPushButton("✕")
        self.btn_close.setStyleSheet(FLAT_QSS)
        self.btn_close.setFixedWidth(28)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setToolTip("收起这条回执（不会停止下载；要停请点「中断」）")
        self.btn_close.clicked.connect(self.dismiss)

        for w in (self.lbl_ico, self.lbl_name, self.bar, self.lbl_txt, self.lbl_eta,
                  self.lbl_queue, self.btn_detail, self.btn_stop, self.btn_close):
            lay.addWidget(w)

        self._shown_id: int | None = None      # 当前显示的是哪条任务（收起判据）
        self._dismissed_id: int | None = None  # 用户✕掉的那条（不再重复弹出来）
        self.hide()
        hub.jobs_changed.connect(self.refresh)
        hub.job_progress.connect(lambda *_: self.refresh())
        hub.job_finished.connect(lambda *_: self.refresh())
        hub.activity_changed.connect(lambda *_: self.refresh())

    # ==========================================
    def _stop(self) -> None:
        """中断**当前这一条**任务。

        ⚠ 这里**不能**用 `cancel(None)`：那是"停当前 + 清空排队"，会把用户还排着的任务
          一起静默取消；而按钮文案/tooltip 说的是"停止当前任务"（§11.5-82）。
          要全停请到队列面板点「全部中断」。
        """
        job = self._hub.current
        if job is not None:
            self._hub.cancel(job.id)
        self.refresh()

    def dismiss(self) -> None:
        """用户✕掉当前这条（主要是“已经看到完成了”的回执）⇒ 不再重复弹出来。"""
        self._dismissed_id = self._shown_id
        self.hide()

    def refresh(self) -> None:
        """投影 hub 的状态。真源全在 hub，这里不存任何任务数据。"""
        hub = self._hub
        job = hub.current or hub.next_queued()
        if job is None:
            job = hub.last_finished()          # 全跑完了 ⇒ 留一条可点的回执
            if job is None or job.id == self._dismissed_id:
                self.hide()
                return
        self._shown_id = job.id
        running = job.status == STATUS_RUNNING
        queued = max(0, hub.pending_count() - (1 if running else 0))
        self.lbl_ico.setText(_ICO_RUN if running or job.status == STATUS_QUEUED
                             else (_ICO_WARN if job.status == STATUS_CANCELLED else _ICO_OK))
        self.lbl_name.setText(job.label)
        self.bar.setValue(job.percent)
        self.lbl_txt.setText(job.progress_text())
        self.lbl_txt.setToolTip(
            f"#{job.id} {job.label}\n{job.progress_text()}\n"
            + (f"预计：{job.eta_text()}" if running else job.receipt_text()))
        self.lbl_eta.setText(job.eta_text())
        self.lbl_queue.setText(f"· 排队 {queued}" if queued and running else "")
        live = running or job.status == STATUS_QUEUED or queued > 0
        self.btn_stop.setVisible(live)
        self.btn_stop.setEnabled(live)
        # ✕ 只在"回执态"给：任务在跑时它按了也收不起来（下一次投影会立刻把条弹回来，
        #   因为运行中的任务不走 `_dismissed_id` 分支）⇒ 给了等于骗用户。
        #   要收起请到队列面板；要停请按「中断」。
        self.btn_close.setVisible(not live)
        self.show()
