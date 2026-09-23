# ui/dialogs/download_settings.py
"""下载设置对话框 (v1.45 · §7-B11 后续 · 续) —— 批量下载节流参数的**唯一编辑面**。

【为什么要单独一个对话框】
  之前「间隔 / 抖动 / 熔断 / 跳过已最新」散在批量预下载弹窗与数据管理页各自的旋钮里，
  M2/M3 干脆没有入口 —— 于是「在预下载调的间隔，不会带到 M2/M3」（用户实测的困惑）。
  ⇒ 收成**一份全局偏好** `preferences.download_prefs`（唯一真源，见 §9-D）：
    · 所有批量下载（数据管理 / 预下载弹窗 / M2/M3）经 `DownloadHub.submit` 读**同一份**；
    · 只有本对话框能改它（「一处调、处处生效」、重启记住）；各页不再放各自的旋钮。

【入口】同一份对话框、多处打开（都是它，不各存一份）：
  数据管理页工具栏 / 批量预下载弹窗头部 / 下载队列面板，三处「⚙ 下载设置…」均 `exec()` 本类。

【字段边界】并发上限 4（K≤4，与「宁可慢也不封 IP」一致）；间隔/熔断等沿用既有默认。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                             QLabel, QVBoxLayout)

from core.preferences import preferences
from ui.widgets.custom_widgets import double_spin, int_spin

# 与 preferences.DEFAULTS["download_prefs"] 对齐的默认（恢复默认按钮用）
_DEFAULTS = {"interval": 0.6, "jitter": True, "circuit_breaker": 12,
             "skip_fresh": True, "concurrency": 3}

_HINT = ("这些参数对**所有**批量下载生效（数据管理 / 预下载 / 全市场筛选 / 广度统计），\n"
         "改动会记住；force_full、下载起点、分区属于「每次任务」，在各自页面单独选。")


class DownloadSettingsDialog(QDialog):
    """全局下载偏好编辑面：间隔 / 抖动 / 熔断 / 跳过已最新 / 并发。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙ 下载设置")
        cur = dict(_DEFAULTS)
        saved = preferences.get("download_prefs")
        if isinstance(saved, dict):
            cur.update({k: saved[k] for k in _DEFAULTS if k in saved})

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QLabel("⚙ 全局下载设置")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1F2430;")
        root.addWidget(title)

        hint = QLabel(_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #5B6472;")
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        # 间隔：复用全站工厂（宽度只给下限不钉死，§10-9）
        self.spin_interval = double_spin(
            value=float(cur["interval"]), lo=0.0, hi=10.0, decimals=1, step=0.1,
            tooltip="每次请求前的等待时间（并发时是全局发起节奏）。越慢越安全，建议不低于 0.4 秒。")
        form.addRow("间隔(秒)", self.spin_interval)

        self.chk_jitter = QCheckBox("随机抖动（±30%）")
        self.chk_jitter.setChecked(bool(cur["jitter"]))
        self.chk_jitter.setToolTip(
            "让间隔随机浮动，打散「机器人固定频率」特征，降低被识别/限流风险。")
        form.addRow("抖动", self.chk_jitter)

        self.spin_breaker = int_spin(
            value=int(cur["circuit_breaker"]), lo=1, hi=50,
            tooltip="连续失败达到该数量即判定「疑似被限流」并自动停手，保护用户 IP。")
        form.addRow("连续失败熔断", self.spin_breaker)

        self.chk_skip_fresh = QCheckBox("跳过已最新（断点续传）")
        self.chk_skip_fresh.setChecked(bool(cur["skip_fresh"]))
        self.chk_skip_fresh.setToolTip(
            "本地已最新（末日 >= 最近一个已收盘定稿交易日）的标的自动跳过、不发请求。")
        form.addRow("跳过", self.chk_skip_fresh)

        self.spin_concurrency = int_spin(
            value=int(cur["concurrency"]), lo=1, hi=4,
            tooltip="同时抓取几条线。提速只靠「等待与网络往返重叠」、不改总请求频率（不额外封 IP）。\n"
                    "1=纯串行（最保守/回滚）；3=均衡（默认）；上限 4，更高有封 IP 风险。")
        form.addRow("并发数", self.spin_concurrency)
        root.addLayout(form)

        self.lbl_reset = QLabel("恢复默认")
        self.lbl_reset.setStyleSheet("font-size: 12px; color: #1976D2;")
        self.lbl_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_reset.mousePressEvent = lambda _e: self._load_into_widgets(_DEFAULTS)
        root.addWidget(self.lbl_reset)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load_into_widgets(self, d: dict) -> None:
        """把一组值灌回控件（「恢复默认」只动控件，仍要点确定才落盘）。"""
        self.spin_interval.setValue(float(d["interval"]))
        self.chk_jitter.setChecked(bool(d["jitter"]))
        self.spin_breaker.setValue(int(d["circuit_breaker"]))
        self.chk_skip_fresh.setChecked(bool(d["skip_fresh"]))
        self.spin_concurrency.setValue(int(d["concurrency"]))

    def _on_ok(self) -> None:
        prefs = {
            "interval": float(self.spin_interval.value()),
            "jitter": self.chk_jitter.isChecked(),
            "circuit_breaker": int(self.spin_breaker.value()),
            "skip_fresh": self.chk_skip_fresh.isChecked(),
            "concurrency": int(self.spin_concurrency.value()),
        }
        preferences.set("download_prefs", prefs)   # 原子落盘，下次启动与所有入口都读到
        self.accept()
