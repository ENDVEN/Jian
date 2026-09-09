"""
回测结果报告图 —— 单页 PNG「一图看懂」(v5.15 · §7-A2)。

【定位】
  专业投资者追求"可溯源、可核查"：CSV 明细承担逐笔/参数的确定性溯源；
  而这份 PNG 承担"打开图片就能看懂这次回测讲了什么"的可视化结论：
    标题(品种/区间/策略) + KPI 四卡 + 净值曲线 + 离场原因分布饼图 + 参数/风控简表。

【为什么放 ui/widgets 而不是 ui/views/backtest.py】
  §9-L 大文件拆分红线：回测页已有 1400+ 行。本模块与 chart_style 同级，属于
  "图表/图像产出"，可被回测页（现在）与未来的「结果历史存档」复用（§7-A4）。
  本模块只依赖 pyqtgraph / config.settings / core.backtest 的纯常量，不碰 SQL/网络。

【渲染方式】
  QWidget 按目标尺寸离屏排版 → processEvents → grab() 存 PNG。
  中文依赖系统字体（用户 Windows 自带微软雅黑，正常；CI/沙箱缺 CJK 字体会显示方框，
  属环境问题不是代码问题）。
"""
from __future__ import annotations

import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QFont
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QVBoxLayout, QWidget)

from config import settings
from core.backtest import EXIT_REASON_COLORS, EXIT_REASON_LABELS, risk_summary
from ui.widgets.chart_style import apply_pokorny_style, plot_equity_curve

# 报告图默认画布
REPORT_WIDTH = 1120
REPORT_HEIGHT = 660

_CARD_QSS = "QFrame { background:#F7F9FC; border:1px solid #E7EAF0; border-radius:10px; }"
_TEXT_SEC = "#8A94A6"
_TEXT_MAIN = "#1F2430"
_TEXT_DIM = "#5B6472"
_TEXT_FAINT = "#9AA3B2"
_FONT_LABEL = "12px"
_FONT_TITLE = "20px"


# ==========================================
# 离场原因饼图（QPainter 手绘，轻量无依赖）
# ==========================================
class _ReasonPie(QWidget):
    """绘制离场原因占比饼图。items: [(reason_key, count)]"""

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self._items = [(k, c) for k, c in items if c > 0]
        self.setFixedSize(160, 160)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))

        total = sum(c for _, c in self._items)
        if total <= 0:
            painter.setPen(QColor(_TEXT_FAINT))
            painter.setFont(QFont("Microsoft YaHei", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "无成交")
            return

        rect = QRectF(10, 10, 140, 140)
        start = 90 * 16  # 从 12 点方向开始，顺时针
        for key, count in self._items:
            span = -int(round(count / total * 360 * 16))
            color = QColor(EXIT_REASON_COLORS.get(key, "#9AA3B2"))
            painter.setBrush(color)
            painter.setPen(QColor("#FFFFFF"))  # 白描边分隔扇区
            painter.drawPie(rect, start, span)
            start += span


def _reason_items(result) -> list:
    """统计离场原因分布：按次数降序，返回 [(reason_key, count)]"""
    counts: dict[str, int] = {}
    for t in result.trades:
        key = getattr(t, "exit_reason", "signal") or "signal"
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


# ==========================================
# 小构件
# ==========================================
def _kpi_card(title: str, value: str, color: str = _TEXT_MAIN) -> QFrame:
    frame = QFrame()
    frame.setStyleSheet(_CARD_QSS)
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(2)
    cap = QLabel(title)
    cap.setStyleSheet(f"font-size: {_FONT_LABEL}; color: {_TEXT_SEC}; font-weight: bold;")
    lay.addWidget(cap)
    body = QLabel(value)
    body.setStyleSheet(f"font-size: 23px; font-weight: bold; color: {color};")
    body.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(body)
    return frame


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text).split())  # 压缩换行/连续空白
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clamp_segments(meta: dict, limit: int = 200) -> str:
    segs = meta.get("segments") or []
    joined = " | ".join(_truncate(s, 90) for s in segs)
    return _truncate(joined, limit) or "—"


# ==========================================
# 对外入口：渲染整张报告图到文件
# ==========================================
def render_result_png(meta: dict, result, file_path: str) -> bool:
    """把一次回测渲染成单页 PNG 报告图，保存到 file_path。成功返回 True。

    :param meta: 与 CSV 导出同源的参数快照（start_backtest 定格的那份）
    :param result: BacktestResult
    """
    app = QApplication.instance()
    if app is None:
        return False  # 没有 QApplication 无从渲染

    summary = result.summary() if result is not None else {}
    cum = float(summary.get("cumulative_return", 0.0))
    cum_col = settings.COLOR_PROFIT_TEXT if cum >= 0 else settings.COLOR_LOSS_TEXT
    symbol = meta.get("symbol") or ""
    name = meta.get("name") or symbol or "-"

    root = QWidget()
    root.resize(REPORT_WIDTH, REPORT_HEIGHT)
    root.setStyleSheet("QWidget { background: white; }")
    lay = QVBoxLayout(root)
    lay.setContentsMargins(26, 20, 26, 14)
    lay.setSpacing(10)

    # ---- 标题行 ----
    head = QHBoxLayout()
    title = QLabel("回测结果报告")
    title.setStyleSheet(f"font-size: {_FONT_TITLE}; font-weight: bold; color: {_TEXT_MAIN};")
    head.addWidget(title)
    head.addSpacing(16)
    meta_lbl = QLabel(
        f"{name} ({symbol})　·　{meta.get('start_date', '-')} ~ {meta.get('end_date', '-')}"
        f"　·　策略: {meta.get('strategy_name') or '（未保存）'}"
    )
    meta_lbl.setStyleSheet(f"font-size: 13px; color: {_TEXT_DIM};")
    head.addWidget(meta_lbl)
    head.addStretch()
    head.addWidget(QLabel(f"共 {summary.get('total_trades', 0)} 笔成交"))
    head.itemAt(head.count() - 1).widget().setStyleSheet(
        f"font-size: 13px; font-weight: bold; color: {_TEXT_SEC};")
    lay.addLayout(head)

    # ---- KPI 行 ----
    kpi = QHBoxLayout()
    kpi.setSpacing(12)
    kpi.addWidget(_kpi_card("总成交", f"{summary.get('total_trades', 0)} 笔"))
    kpi.addWidget(_kpi_card("胜率", f"{float(summary.get('win_rate', 0)) * 100:.1f}%"))
    kpi.addWidget(_kpi_card("累计收益", f"{cum * 100:+.1f}%", cum_col))
    kpi.addWidget(_kpi_card("平均单笔", f"{float(summary.get('avg_return_pct', 0)) * 100:+.2f}%"))
    lay.addLayout(kpi)

    # ---- 中部：左 净值曲线 / 右 离场原因分布 ----
    mid = QHBoxLayout()
    mid.setSpacing(16)

    chart = pg.PlotWidget()
    chart.setBackground("w")
    if result is not None and result.equity is not None and not result.equity.empty:
        plot_equity_curve(chart, result.equity["equity"], fill_base=1.0, width=2)
        chart.addLine(y=1.0, pen=pg.mkPen(color="#BDBDBD", style=Qt.PenStyle.DashLine))
        last_eq = float(result.equity["equity"].iloc[-1])
        last_date = pd.Timestamp(result.equity["date"].iloc[-1]).strftime("%Y-%m-%d")
        end_note = pg.TextItem(
            f"期末 {last_eq:.3f}（{cum * 100:+.1f}%） @ {last_date}",
            color=settings.COLOR_PROFIT_TEXT if last_eq >= 1 else settings.COLOR_LOSS_TEXT,
            anchor=(1, 0))
        end_note.setPos(len(result.equity) - 1, last_eq)
        chart.addItem(end_note)
        apply_pokorny_style(chart, background=None, margins=0)
        chart.getAxis("left").setLabel("单位净值（初始 = 1.0）")
        chart.getPlotItem().setTitle(
            f"净值曲线 · 区间 {meta.get('start_date', '-')} ~ {meta.get('end_date', '-')}",
            color=_TEXT_SEC, size="11pt")
    else:
        chart.setStyleSheet("background: white;")
        chart.getPlotItem().hideAxis("left")
        chart.getPlotItem().hideAxis("bottom")
        chart.getPlotItem().setTitle("区间内无成交 / 无净值数据", color=_TEXT_FAINT, size="12pt")
    mid.addWidget(chart, 1)

    # 右侧：离场原因饼图
    right = QFrame()
    right.setStyleSheet(_CARD_QSS)
    right.setFixedWidth(248)
    rlay = QVBoxLayout(right)
    rlay.setContentsMargins(14, 12, 14, 12)
    rlay.setSpacing(6)
    rcap = QLabel("离场原因分布")
    rcap.setStyleSheet(f"font-size: {_FONT_LABEL}; color: {_TEXT_SEC}; font-weight: bold;")
    rlay.addWidget(rcap)

    items = _reason_items(result)
    pie = _ReasonPie(items)
    rlay.addWidget(pie, 0, Qt.AlignmentFlag.AlignHCenter)

    if items:
        total = sum(c for _, c in items)
        for key, count in items:
            hex_color = EXIT_REASON_COLORS.get(key, "#9AA3B2")
            label = EXIT_REASON_LABELS.get(key, key)
            seg = QLabel(
                f"<span style='color:{hex_color};'>&#9679;</span>&nbsp; "
                f"{label} × {count}（{count / total * 100:.0f}%）")
            seg.setStyleSheet(f"font-size: 12px; color: {_TEXT_DIM};")
            seg.setTextFormat(Qt.TextFormat.RichText)
            rlay.addWidget(seg)
    else:
        empty = QLabel("本次回测无成交")
        empty.setStyleSheet(f"font-size: 12px; color: {_TEXT_FAINT};")
        rlay.addWidget(empty)
    rlay.addStretch()
    mid.addWidget(right)
    lay.addLayout(mid, 1)

    # ---- 参数简表（两行内放完，超长截断）----
    params_text = meta.get("params_text") or "（无）"
    index = meta.get("index")
    index_txt = (f"启用 {index.get('symbol')}"
                 f"（买 {index.get('expr_buy') or '—'} | 卖 {index.get('expr_sell') or '—'}）"
                 if index else "未启用")
    risk_txt = risk_summary(meta.get("risk") or {})

    note1 = QLabel(
        f"函数: {_clamp_segments(meta, 130)}　|　参数: {params_text}")
    note1.setStyleSheet(f"font-size: 12px; color: {_TEXT_DIM};")
    note1.setWordWrap(True)
    lay.addWidget(note1)
    note2 = QLabel(
        f"买入: {_truncate(meta.get('buy_expr') or '—', 90)}　|　"
        f"卖出: {_truncate(meta.get('sell_expr') or '—', 90)}")
    note2.setStyleSheet(f"font-size: 12px; color: {_TEXT_DIM};")
    note2.setWordWrap(True)
    lay.addWidget(note2)
    note3 = QLabel(f"风控: {risk_txt}　|　指数门控: {index_txt}")
    note3.setStyleSheet(f"font-size: 12px; color: {_TEXT_DIM};")
    note3.setWordWrap(True)
    lay.addWidget(note3)

    foot = QLabel("逐笔成交明细与参数全文请「导出 CSV 明细」留档核查。")
    foot.setStyleSheet(f"font-size: 11px; color: {_TEXT_FAINT};")
    lay.addWidget(foot)

    # ---- 离屏排版 + 抓图 ----
    root.show()
    app.processEvents()
    root.resize(REPORT_WIDTH, REPORT_HEIGHT)
    app.processEvents()
    pixmap = root.grab()
    if pixmap.isNull():
        return False
    return pixmap.save(file_path, "PNG")
