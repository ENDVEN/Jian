# ui/widgets/portfolio_parts.py
"""🧺 组合页的**零件**（★1.90 从 `ui/views/portfolio_view.py` 拆出：那页已 1391 行）。

【为什么拆】§4 红黑榜：`portfolio_view.py` 早越 400 线三倍，`_build`(353) / `_render_p1`(238)
  两个方法把"列表卡 + 环形图 + 版式 + 计算装配"全塞在一处。本文件只放**与业务无关的显示件**：
  · `PfCard`      —— 左栏一张组合卡（名称 / 来源组 / 累计·日·净值）
  · `RingChart`   —— 极简环形图（QPainter 自绘，不引第三方）
  · `overview_qss` / `dot_title` —— 概览数值配色、卡头彩色圆点
  ⚠ 拆件纪律（§4）：**只搬代码不改行为**；行数/断言仍按原口径。

【纪律】本文件是**纯显示**：不读存储、不算统计、不联网。颜色取 `ui/widgets/styles.py` 的同族色值
  （组合页当前仍以本页内联 QSS 为主，统一到 styles 属另一轮视觉变更，别在拆件里顺手改观感）。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

__all__ = ["PfCard", "RingChart", "overview_qss", "dot_title"]


def overview_qss(tone: str) -> str:
    """概览数值的配色（正绿 / 负红 / 中性灰）—— 用户要求"按具体数值显示不同颜色"。"""
    _c = {"up": "#2E7D32", "down": "#C62828"}.get(tone, "#1F2A37")
    return f"font-size:16px;font-weight:700;color:{_c};background:transparent;"


def dot_title(title: str, color: str) -> str:
    """卡头标题前加彩色圆点（样板做法；只影响本页，不动全局 QSS）。"""
    return f'<span style="color:{color}">●</span> {title}'


class PfCard(QFrame):
    """左栏的一张组合卡（样板样式）：名称 + 累计/日/净值 + 来源组。

    ⚠ 与列表项的关系：卡是**显示层**，`QListWidgetItem` 仍保留文本（断言与 tooltip 用）。
    """

    QSS = (
        "QFrame#pfCard { background:#FFFFFF; border:1px solid #E7ECF3; border-radius:10px; }"
        "QFrame#pfCard[sel=\"true\"] { background:#EAF3FE; border:1px solid #B6D4F7; }"
        "QLabel { background: transparent; }")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pfCard")
        self.setStyleSheet(self.QSS)
        self._sel = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.lbl_name = QLabel("")
        self.lbl_name.setStyleSheet("font-size:13px;font-weight:700;color:#1F2A37;")
        top.addWidget(self.lbl_name, 1)
        self.lbl_group = QLabel("")
        self.lbl_group.setStyleSheet("font-size:11px;color:#8A94A6;")
        top.addWidget(self.lbl_group, 0)
        lay.addLayout(top)

        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setStyleSheet("font-size:11.5px;")
        lay.addWidget(self.lbl_metrics)

        self.lbl_sub = QLabel("")
        self.lbl_sub.setStyleSheet("font-size:11px;color:#9AA6B8;")
        lay.addWidget(self.lbl_sub)

    def fill(self, name: str, group: str, ret, day) -> None:
        self.lbl_name.setText(name)
        self.lbl_group.setText(f"自选组：{group}" if group else "自选组：未指定")
        parts = []
        if ret is None:
            parts.append('<span style="color:#9AA6B8">累计 —</span>')
        else:
            _c = "#2E7D32" if ret >= 0 else "#C62828"
            parts.append(f'<span style="color:{_c}">累计 {ret:+.2f}%</span>')
        if day is not None:
            _c = "#2E7D32" if day >= 0 else "#C62828"
            parts.append(f'<span style="color:{_c}">日 {day:+.2f}%</span>')
        if ret is not None:
            parts.append(f'<span style="color:#5A6577">净值 {1 + ret / 100.0:.4f}</span>')
        self.lbl_metrics.setText("　".join(parts))

    def set_selected(self, sel: bool) -> None:
        self._sel = bool(sel)
        self.setProperty("sel", "true" if sel else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class RingChart(QWidget):
    """极简环形图（QPainter 自绘，不引第三方）。

    ⚠ 只画"占比"；**没有数据就不画**（空列表 ⇒ 只留灰底），绝不画一个假的 100% 圆。
    """

    COLORS = ("#1976D2", "#26A69A", "#7E57C2", "#FB8C00", "#8D6E63", "#78909C")

    def __init__(self, parent=None, palette_offset: int = 0):
        super().__init__(parent)
        self._offset = int(palette_offset or 0)   # ★1.87：单段时两环不要撞色
        self._data = []
        self.setMinimumSize(118, 118)
        self.setMaximumSize(150, 150)

    def set_data(self, data) -> None:
        self._data = [(str(k), float(v)) for k, v in (data or []) if float(v) > 1e-9]
        self.update()

    def paintEvent(self, _event) -> None:      # noqa: N802 —— Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#EDF1F7"))           # 底色（无数据时就是它）
        p.drawEllipse(rect)
        total = sum(v for _k, v in self._data)
        if total > 0:
            start = 90 * 16
            for i, (_k, v) in enumerate(self._data):
                span = int(-360 * 16 * v / total)
                p.setBrush(QColor(self.COLORS[(i + self._offset) % len(self.COLORS)]))
                p.drawPie(rect, start, span)
                start += span
        # 挖个白心 ⇒ 环
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(rect.adjusted(26, 26, -26, -26))
