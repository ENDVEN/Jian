# ui/widgets/history_parts.py
"""运行历史页的**纯显示小件**（★2.04 / P2 拆件）。

从 `backtest_history_ui.py` 抽出：迷你净值图 / 四态占比条 / 带标题卡片。
只做"给定数据画出来"，不碰存档、筛选、线程；样式常量跟着小件走（唯一定义处）。
"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                             QVBoxLayout, QWidget)

from config import settings
from ui.widgets.chart_style import apply_pokorny_style

__all__ = ['MiniEquityChart', 'ScanStatBar', 'SectionCard',
           'SCAN_SEGMENTS', '_TEXT', '_ACCENT', '_CENTER',
           '_STATBAR_QSS', '_SECT_QSS']

# ---- 配色（与全站一致的语义色；文字色取"可读版"，避免高饱和）----
_TEXT = "#1F2430"
_ACCENT = "#1976D2"
_CENTER = Qt.AlignmentFlag.AlignCenter

_SECT_QSS = (
    "QFrame#HistSect{background:#FFFFFF;border:1px solid #EDF0F5;border-radius:8px;}"
    "QFrame#HistSectHead{background:#FAFBFD;border:none;"
    " border-top-left-radius:7px;border-top-right-radius:7px;}"
    "QLabel#HistSectTitle{font-size:12.5px;font-weight:bold;color:#3A4250;"
    " border:none;background:transparent;}"
    "QLabel#HistSectMeta{font-size:11.5px;color:#8A94A6;border:none;background:transparent;}")
_STATBAR_QSS = ("QFrame#HistStatBar{background:#F5F6F8;border:1px solid #EDF0F5;"
                "border-radius:6px;}")

# 四态占比条的段（顺序 = 画法顺序；颜色 = 语义色，与结果表 KPI 同源）
SCAN_SEGMENTS = (
    ('hit', '命中', '#2E7D32'),
    ('miss', '未命中', '#9AA3B2'),
    ('insufficient', '数据不足', '#FB8C00'),
    ('filtered', '被粗筛剔除', '#C9D2DE'),
)


class MiniEquityChart(pg.PlotWidget):
    """迷你净值曲线 + 买卖点（点落在曲线上 —— 成交日净值定位）。**只有 M1 用。**"""

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_pokorny_style(self, background="w", margins=0)
        self.setFixedHeight(132)
        self.setMouseEnabled(False, False)       # 预览小图：不缩放不拖动
        self.getPlotItem().setLabel('left', '净值')
        self.getPlotItem().showAxis('bottom', False)
        self._empty()

    def _empty(self, text: str = "选中一份存档查看净值曲线"):
        self.clear()
        self.getPlotItem().setTitle(text, color="#9AA3B2", size="10pt")

    def set_series(self, rows: list) -> None:
        """画一次净值序列（含买卖点）。⚠ 方法名不能叫 `plot` —— 会遮蔽 `PlotWidget.plot`。"""
        rows = rows or []
        if not rows:
            self._empty("该存档没有净值序列")
            return
        self.clear()
        self.getPlotItem().setTitle("")
        ys = [float(r.get("equity") or 0.0) for r in rows]
        # ⚠ `PlotWidget` 的 `plot` 是 `__getattr__` 转发到 PlotItem 的，不在 MRO 里 ⇒
        # `super().plot(...)` 会 AttributeError；必须显式走 `getPlotItem().plot(...)`。
        self.getPlotItem().plot(list(range(len(ys))), ys, pen=pg.mkPen(_ACCENT, width=2))
        self.addLine(y=1.0, pen=pg.mkPen('#BDBDBD', style=Qt.PenStyle.DashLine))
        for key, symbol, color in (("buy_at", 't', settings.COLOR_PROFIT),
                                   ("sell_at", 'd', settings.COLOR_LOSS)):
            xs = [i for i, r in enumerate(rows) if r.get(key) is not None]
            if xs:
                self.addItem(pg.ScatterPlotItem(
                    x=xs, y=[float(rows[i][key]) for i in xs], symbol=symbol,
                    size=9, brush=pg.mkBrush(color), pen='w'))


class ScanStatBar(QWidget):
    """横截面快照的**四态占比条**（★v1.46 替代旧版 4 个 M1 语义的胶囊）。

    【为什么是"条"而不是 4 个数字】横截面最要紧的信息是**比例** ——
    "300 只里 256 只没数据"用四个孤立数字看不出来，用一条占比条一眼就是压倒性的橙色。
    段宽按只数比例分；太窄的段不写字（数字进 tooltip 与图例），绝不撑宽面板（§11.5-73）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.lbl_head = QLabel("—")
        self.lbl_head.setStyleSheet(f"font-size:12px;color:{_TEXT};")
        self.lbl_head.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.lbl_head)

        self.bar = QFrame()
        self.bar.setObjectName("HistStatBar")
        self.bar.setStyleSheet(_STATBAR_QSS)
        self.bar.setFixedHeight(22)
        self._bar_lay = QHBoxLayout(self.bar)
        self._bar_lay.setContentsMargins(0, 0, 0, 0)
        self._bar_lay.setSpacing(0)
        lay.addWidget(self.bar)

        self._segs = {}
        for key, _name, color in SCAN_SEGMENTS:
            seg = QLabel("")
            seg.setAlignment(_CENTER)
            seg.setMinimumWidth(0)
            seg.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            seg.setStyleSheet(f"background:{color};color:#fff;font-size:11px;font-weight:bold;")
            seg.hide()
            self._bar_lay.addWidget(seg)
            self._segs[key] = seg

        self.lbl_legend = QLabel("")
        self.lbl_legend.setWordWrap(True)
        self.lbl_legend.setStyleSheet(f"font-size:11.5px;color:{_TEXT};")
        lay.addWidget(self.lbl_legend)

    def clear(self) -> None:
        self.lbl_head.setText("—")
        for seg in self._segs.values():
            seg.hide()
            seg.setText("")
        self.lbl_legend.setText("")

    def render(self, counts: dict, elapsed_ms=None) -> None:
        counts = counts or {}
        total = int(counts.get('total') or 0) or 1
        valid = int(counts.get('valid') or 0)
        rate = counts.get('hit_rate')
        head = f"有效样本 {valid} / {total}"
        if rate is not None:
            head += f"      命中率 {float(rate) * 100:.1f}%"
        if elapsed_ms:
            head += f"      用时 {float(elapsed_ms) / 1000:.2f} s"
        self.lbl_head.setText(head)

        legend = []
        for key, name, color in SCAN_SEGMENTS:
            value = int(counts.get(key) or 0)
            seg = self._segs[key]
            idx = self._bar_lay.indexOf(seg)
            if value <= 0:
                seg.hide()
                self._bar_lay.setStretch(idx, 0)
                continue
            seg.show()
            seg.setText(str(value) if value / total >= 0.10 else "")
            seg.setToolTip(f"{name} {value} 只（{value / total * 100:.1f}%）")
            self._bar_lay.setStretch(idx, max(1, value))
            legend.append(f'<span style="color:{color}">■</span> {name} {value}')
        self.lbl_legend.setText("&nbsp;&nbsp;&nbsp;".join(legend))


class SectionCard(QFrame):
    """带标题行的小卡片（标题 + 右侧 meta / 动作 + 正文）。

    用于「筛选条件」「粗筛漏斗」等 —— 样式收敛在本文件（§10-9），业务页面不许就地写。
    """

    def __init__(self, title: str, meta: str = '', action: QWidget = None, parent=None):
        super().__init__(parent)
        self.setObjectName("HistSect")
        self.setStyleSheet(_SECT_QSS)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        head = QFrame()
        head.setObjectName("HistSectHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 7, 10, 7)
        hl.setSpacing(8)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName("HistSectTitle")
        self.lbl_meta = QLabel(meta)
        self.lbl_meta.setObjectName("HistSectMeta")
        hl.addWidget(self.lbl_title)
        hl.addWidget(self.lbl_meta)
        hl.addStretch(1)
        if action is not None:
            hl.addWidget(action)
        box.addWidget(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(10, 8, 10, 10)
        self.body.setSpacing(6)
        box.addLayout(self.body)

    def set_meta(self, text: str) -> None:
        self.lbl_meta.setText(text or "")
