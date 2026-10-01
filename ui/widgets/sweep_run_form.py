# ui/widgets/sweep_run_form.py
"""
🧪 参数研究 —— **运行面板**（★R2 拆件；左栏第 ⑤ 步「交易次数门槛」+ 第 ⑥ 步「运行」）。

【为什么单独成件】`sweep_form.py` 一度 488 行（§4 越线）：它同时管"口径/网格/区间"的编排
**和**"门槛滑块 + 分布图 + 三颗按钮 + 进度 + 回执"。后者是独立的一块（只跟运行有关），
拆出来两边都能长：表单回到"研究设置"，本件专管"跑"。

【公共面不变】`SweepForm` 仍然暴露 `sl_gate / btn_run_is / btn_run_oos / btn_cancel /
progress / lbl_receipt / lbl_gate_hint / dist_chart` 与
`run_is_requested / run_oos_requested / cancel_requested` 信号、以及
`min_trades() / set_distribution() / set_running() / set_oos_enabled() / set_progress() /
set_receipt()` —— 由 `SweepForm` 用**别名**转发到本件（页面与既有断言一行都不用改）。

【口径】门槛"只筛不排"（它只决定候选成员，不参与排序键）—— 文案必须说出这件事。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QSlider, QVBoxLayout, QWidget)

from ui.widgets.styles import FLAT_QSS_DANGER, SUMMARY_RUN_QSS
from ui.widgets.sweep_chart import TradesDistribution
from ui.widgets.sweep_parts import _hint, _sep, _step_title, _warn

GATE_MIN = 5            # 门槛滑块下限（方案书 §2：滑块 5~120）
GATE_MAX = 120
GATE_DEFAULT = 30       # 默认门槛（方案书：默认停在 30）


class SweepRunPanel(QWidget):
    """⑤ 交易次数门槛 + ⑥ 运行（含进度与回执）。"""

    run_is_requested = pyqtSignal()
    run_oos_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        bl = QVBoxLayout(self)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)

        # ---- ⑤ 门槛 ----
        bl.addWidget(_sep())
        bl.addWidget(_step_title(5, "交易次数门槛"))
        row = QHBoxLayout()
        self.sl_gate = QSlider(Qt.Orientation.Horizontal)
        self.sl_gate.setRange(GATE_MIN, GATE_MAX)
        self.sl_gate.setValue(GATE_DEFAULT)
        self.lbl_gate = QLabel(str(GATE_DEFAULT))
        row.addWidget(self.sl_gate, 1)
        row.addWidget(self.lbl_gate)
        bl.addLayout(row)
        self.dist_chart = TradesDistribution()
        self.dist_chart.setMinimumHeight(120)
        bl.addWidget(self.dist_chart)
        self.lbl_gate_hint = _hint()
        self.lbl_gate_hint.setText(
            "门槛是什么：每个参数组合在样本里进出场的次数。次数太少 ⇒ 年化收益全靠运气。"
            "门槛只筛掉样本太少的组合，不参与排名。")
        bl.addWidget(self.lbl_gate_hint)

        # ---- ⑥ 运行 ----
        bl.addWidget(_sep())
        bl.addWidget(_step_title(6, "运行"))
        # ★用户 2026-10-01：闸门拦住时必须**看得见**（橙字一行 + 按钮禁用），
        #   否则"点了没反应"看起来就像坏了（旧版原因只在小灰字里）。
        self.blk_reason = _warn()
        bl.addWidget(self.blk_reason)
        row2 = QHBoxLayout()
        self.btn_run_is = QPushButton("▶ 跑样本内")
        self.btn_run_is.setStyleSheet(SUMMARY_RUN_QSS)
        self.btn_run_oos = QPushButton("▶ 跑样本外")
        self.btn_run_oos.setStyleSheet(SUMMARY_RUN_QSS)
        self.btn_run_oos.setEnabled(False)
        self.btn_cancel = QPushButton("中断")
        self.btn_cancel.setStyleSheet(FLAT_QSS_DANGER)
        self.btn_cancel.setVisible(False)
        row2.addWidget(self.btn_run_is, 1)
        row2.addWidget(self.btn_run_oos, 1)
        row2.addWidget(self.btn_cancel)
        bl.addLayout(row2)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        bl.addWidget(self.progress)
        self.lbl_receipt = _hint()
        bl.addWidget(self.lbl_receipt)
        self._blocked = ""      # 闸门原因（非空 ⇒ 跑按钮保持禁用，见 `set_blocked`）

        # ---- 接线（原 sweep_form 的同名四行，随控件一起搬来）----
        self.sl_gate.valueChanged.connect(lambda v: self.lbl_gate.setText(str(v)))
        self.btn_run_is.clicked.connect(self.run_is_requested)
        self.btn_run_oos.clicked.connect(self.run_oos_requested)
        self.btn_cancel.clicked.connect(self.cancel_requested)

    # ================= 公共面（SweepForm 直接别名转发）=================
    def min_trades(self) -> int:
        """当前门槛（= 交易次数下限）——**只筛不排**，不参与排序键。"""
        return int(self.sl_gate.value())

    def set_distribution(self, trades: list[int], gate: int) -> None:
        """画分布并回一句"建议门槛"（引导卡文案由 `TradesDistribution` 一起给）。"""
        self.lbl_gate_hint.setText(self.dist_chart.set_trades(trades, gate))

    def set_blocked(self, reason: str) -> None:
        """★用户实测：网格/区间不合规时按钮照样能点 ⇒ 像"坏了"。现在**禁用 + 写原因**。

        `reason` 非空 = 拦住（按钮禁用、原因进橙字行与 tooltip）；空 = 放行。
        """
        self._blocked = str(reason or "").strip()
        self.blk_reason.setText(self._blocked)
        self.blk_reason.setVisible(bool(self._blocked))
        self.btn_run_is.setEnabled(not self._blocked)
        self.btn_run_is.setToolTip(("现在跑不了：" + self._blocked) if self._blocked else "")

    def set_running(self, running: bool) -> None:
        # ⚠ 跑完**不能无脑重新启用**：若此刻仍被闸门拦着（`_blocked` 非空），要保持禁用
        self.btn_run_is.setEnabled((not running) and not self._blocked)
        self.btn_cancel.setVisible(running)
        self.progress.setVisible(running)

    def set_oos_enabled(self, enabled: bool) -> None:
        """样本外按钮的解锁（红线①：先跑样本内才给跑样本外）。"""
        self.btn_run_oos.setEnabled(enabled)

    def set_progress(self, done: int, total: int, note: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.lbl_receipt.setText(f"[{done}/{total}] {note}")

    def set_receipt(self, text: str) -> None:
        self.lbl_receipt.setText(text)
