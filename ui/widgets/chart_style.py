"""
图表外观与常用绘制的唯一收敛点 (v5.12 · §9-O7)。

【为什么要有这个文件】
  Michael Pokorny 准则（§10-1）要求的"抗锯齿 / 去描边 / 单色高对比"轴样式，
  此前被复制成了**四份**几乎一样的实现：
      ui/views/review.py          ReviewView._apply_pokorny_style
      ui/widgets/yearly_review.py YearlyReviewPanel._apply_pokorny_style
      ui/views/backtest.py        SingleStockBacktestView._apply_pokorny_axis
      ui/views/market.py          MarketView._apply_pokorny_axis
  而"资金/净值曲线"（排序 → cumsum → 按盈亏选色 → plot + fillLevel）更是重复了四份
  （review / yearly_review / backtest / dashboard）。
  **改一处漏两处是迟早的事**，这里统一收口。

【纪律】
  · 新增/调整任何图表外观，一律改本文件；业务页面禁止就地写轴样式与曲线绘制。
  · 本模块只依赖 pyqtgraph + config.settings，不碰业务状态，可被任意页面复用。
"""

import pyqtgraph as pg

from config import settings

# 网格线与轴文字的弱化配色（Pokorny 准则：让数据本身成为唯一的视觉焦点）
GRID_ALPHA = 0.15
AXIS_PEN_COLOR = '#E0E0E0'
AXIS_TEXT_COLOR = '#9E9E9E'
TITLE_COLOR = '#424242'


def apply_pokorny_style(chart, title: str = "", background='w',
                        grid_alpha: float = GRID_ALPHA, margins=15):
    """
    把一张 pyqtgraph 图表收拾成 Pokorny 风格。

    :param chart:      pg.PlotWidget **或** pg.PlotItem 都行 ——
                       回测页/复盘页传的是 PlotWidget，而行情页的
                       `GraphicsLayoutWidget.addPlot()` 直接返回 PlotItem，
                       这里统一兼容，免得调用方纠结类型。
    :param title:      标题文本；空串表示不设置
    :param background: 背景色；传 None 表示"沿用现有背景，不改动"
                       （回测页的图表嵌在白色卡片里，不需要再刷一次背景）
    :param grid_alpha: 网格透明度
    :param margins:    ViewBox 内边距；传 0 表示不设置
    """
    if background and hasattr(chart, 'setBackground'):
        chart.setBackground(background)
    if title:
        chart.setTitle(title, color=TITLE_COLOR, size="11pt", bold=True)

    # PlotWidget 需要下沉一层拿 PlotItem；PlotItem 本身就是目标
    plot_item = chart.getPlotItem() if hasattr(chart, 'getPlotItem') else chart
    plot_item.hideAxis('top')
    plot_item.hideAxis('right')
    chart.showGrid(x=True, y=True, alpha=grid_alpha)

    pen = pg.mkPen(color=AXIS_PEN_COLOR, width=1)
    text_pen = pg.mkPen(color=AXIS_TEXT_COLOR)
    for axis_name in ('left', 'bottom'):
        axis = plot_item.getAxis(axis_name)
        axis.setPen(pen)
        axis.setTextPen(text_pen)

    if margins:
        plot_item.getViewBox().setContentsMargins(margins, margins, margins, margins)
    return chart


def plot_equity_curve(chart, values, fill_base: float = 0.0, width: float = 2,
                      positive: bool = None):
    """
    绘制累计资金 / 净值曲线：盈绿亏红 + 同色半透明填充（§10-1 单色高对比）。

    :param values:    纵轴序列（已按时间排序的累计值）
    :param fill_base: 填充基准线 —— 资金曲线传 0，净值曲线传 1.0（归一化起点），
                      Dashboard 传"初始资金"（equity_data[0]）
    :param positive:  手动指定盈亏方向；None = 按"末值 >= 基准线"自动判定
    :return:          该曲线的 PlotDataItem（无数据时返回 None）
    """
    y = list(values)
    if not y:
        return None

    if positive is None:
        positive = y[-1] >= fill_base
    color = settings.RGB_PROFIT if positive else settings.RGB_LOSS
    fill = settings.RGB_PROFIT_FILL if positive else settings.RGB_LOSS_FILL

    return chart.plot(
        list(range(len(y))), y,
        pen=pg.mkPen(color=color, width=width),
        fillLevel=fill_base,
        fillBrush=fill,
    )
