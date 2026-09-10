# ui/widgets/indicator_panes.py
"""
行情页「内置副图」的内容构建（v6.8 从 `ui/views/market.py` 搬出，SRP）。

【为什么搬】market.py 已 463 行、连续越线（§9-L）。窗格的**编排**交给
`ui/widgets/chart_host.py`，**内容构建**搬到这里，页面只剩"开关 + 组装"。

【纪律】
  · 本模块只往**给定的 PlotItem** 上画图元：不创建窗格、不读数据、不发网络。
  · 量柱 / MACD 仍用 pyqtgraph 原生 `BarGraphItem`（逐柱配色是它的强项），
    **尚未**并入图层协议 —— 这是 §7-B3 P5 明确保留的例外（不为架构一致性
    去改两张已经好用的图，等 P8 重做时一并统一）。
"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from pyqtgraph import QtGui

from config import settings


def fill_volume_pane(plot_item, df, x_data) -> None:
    """成交量副图：涨绿跌红的柱状图（与 K 线同色约定）。"""
    colors = [settings.COLOR_PROFIT if close >= open_ else settings.COLOR_LOSS
              for open_, close in zip(df['open'], df['close'])]
    brushes = [pg.mkBrush(color) for color in colors]
    pens = [pg.mkPen(color) for color in colors]
    plot_item.addItem(pg.BarGraphItem(x=x_data, height=df['volume'], width=0.6,
                                      brushes=brushes, pens=pens))


def fill_macd_pane(plot_item, df, x_data) -> None:
    """MACD 副图：DIF / DEA 两条线 + 红绿柱（国内习惯把柱子放大 2 倍）。"""
    plot_item.addLine(y=0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
    plot_item.plot(x_data, df['MACD_line'], pen=pg.mkPen(color='#212121', width=1.5))
    plot_item.plot(x_data, df['MACD_signal'], pen=pg.mkPen(color='#FF9800', width=1.5))

    hist = df['MACD_hist']
    hist_colors = [settings.COLOR_PROFIT if value > 0 else settings.COLOR_LOSS for value in hist]
    hist_brushes = [pg.mkBrush(QtGui.QColor(color).lighter(120)) for color in hist_colors]
    hist_pens = [pg.mkPen(color) for color in hist_colors]
    plot_item.addItem(pg.BarGraphItem(x=x_data, height=hist, width=0.5,
                                      brushes=hist_brushes, pens=hist_pens))
