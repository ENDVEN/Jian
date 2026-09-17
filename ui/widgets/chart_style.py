"""
图表外观与常用绘制的唯一收敛点 (v5.12 · §9-O7)。

【为什么要有这个文件】
  Michael Pokorny 准则（§10-1）要求的"抗锯齿 / 去描边 / 单色高对比"轴样式，
  此前被复制成了**四份**几乎一样的实现：
      ui/views/review.py          ReviewView._apply_pokorny_style
      ui/widgets/yearly_review.py YearlyReviewPanel._apply_pokorny_style
      ui/views/backtest.py        SingleStockBacktestView._apply_pokorny_axis
      ui/views/market.py          MarketView._apply_pokorny_axis
                                  （`market.py` v6.12 已删除，现为 trading_desk.py；上面是当时的现场）
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
# 十字光标（§7-B3 P2）：与轴同源的弱化灰，避免抢走数据焦点
CROSSHAIR_COLOR = '#9E9E9E'
# 公式叠层的默认线色（函数里没写 COLORxxx 时用）—— 与 K 线红/绿明确区分。
# 取深蓝，使其**无需**再经 ensure_contrast 压暗即达到可见标准（默认色不该被改样子）。
DEFAULT_OVERLAY_COLOR = '#0D47A1'
# 图表背景的两种基准（供 ensure_contrast 判定"相对谁来看得见"）
LIGHT_BACKGROUND = '#FFFFFF'
DARK_BACKGROUND = '#000000'
# 内置主图指标的配色（**唯一来源**，§7-B3 D4）。MA 序列需与 core/indicators
# TAEngine.add_ma 的默认窗口 (5/20/60) 对齐；行情页与用户公式共用同一套图层协议。
MA_SERIES = (
    ('MA_5', '#2196F3'),
    ('MA_20', '#FF9800'),
    ('MA_60', '#9C27B0'),
)
BOLL_LINE_COLOR = '#90CAF9'


def style_axis(plot_item, axis_name: str, pen_color: str = AXIS_PEN_COLOR,
               text_color: str = AXIS_TEXT_COLOR):
    """把某一根轴收拾成 Pokorny 风格（**唯一来源**，v6.3/P2 抽出）。

    ⚠ 图表宿主「换轴」后（如切换 `pg.DateAxisItem`）**必须**重新调用本函数 ——
    新轴会退回 Qt 默认的黑色粗线外观，与其它轴不一致（§10-9 同类问题）。
    """
    axis = plot_item.getAxis(axis_name)
    axis.setPen(pg.mkPen(color=pen_color, width=1))
    axis.setTextPen(pg.mkPen(color=text_color))
    return axis


# ==========================================
# 纵轴"固定左槽"（§7-B8 R8）：让多窗格的绘图区左边缘对齐
# ==========================================
# 纵轴预留的**刻度文本**宽度（px）。它是**布局常量**（与 SUB_PLOT_HEIGHT 同类）：
#   所有窗格共用它 ⇒ 绘图区左边缘必然对齐；
#   同时它**足够小** ⇒ 不会像第一版那样"把窄标签窗格也撑到最宽那个"而留下一大片空白。
AXIS_TEXT_WIDTH = 52
AXIS_MIN_TEXT_WIDTH = 40      # 下限（防止调用方传入过小值把标签挤到只剩一两个刻度）


def unify_axis_width(plot_items, axis_name: str = 'left',
                     text_width: int = AXIS_TEXT_WIDTH) -> float:
    """★ §7-B8 R8 修法：让一组窗格的同一根轴**共用同一个固定宽度**
    —— 既让绘图区左边缘对齐，又**不留空白**。

    【治什么】用户实测（原话）："随着副图的变多，左侧的坐标轴还会出现对不齐的情况，
    有些坐标大数字长，有些坐标小数字就小，这也导致两者的缩进完全不一致。"
    根因 = pyqtgraph 的 `AxisItem` 宽度按**自己**的刻度文本算 ⇒
    主图（`35` / `5`）、量柱（`4e+08`）、MACD（`100`）三种标签长度不同，左槽宽度就不同。
    离屏实测：轴宽 `[41, 65, 89]`、绘图区左边缘 `[51, 75, 99]` ⇒ **错位 48px**。

    【为什么**不能**用 setWidth(最宽的那根)】（第一版就是这么写的，**被用户截图推翻**）
    那等于"把窄标签的窗格也撑到最宽那个"：实测 `[41,65,89] → [89,89,89]`，
    主图凭空多出 **48px 空白**。用户原话："坐标轴占据了大量的空间，
    并且造成了比较大的一个空白，请你重新设计一个可以规避这种情况的方案。"

    【第二版做法：改用 pyqtgraph 自己为此准备的三个开关】
      · `tickTextWidth = 固定值` —— 所有窗格预留**同样的**文本宽度（这才是"预留宽度"的正主）；
      · `autoExpandTextSpace = False` —— **禁止**它再按自己的标签把轴撑开
        （实测留着 True 就会被最长的撑回去、对齐立刻失效：`41/65/89`）；
      · `autoReduceTextSpace = True` —— 标签真的超宽时，让 pyqtgraph **自动减少刻度条数 /
        降低刻度精度**去适配（`textFillLimits` 就是干这个的），而**不是**把数字裁掉。
    【实测（同一组三窗格）】改后轴宽 `[57, 57, 57]`、左边缘 `[67, 67, 67]` ⇒ **错位 0**，
    且只比最窄的那根多 **16px**（对比第一版的 +48px）。

    【安全性】整体 try/except + 失败返回 0.0 ⇒ 这类"装饰性"逻辑绝不许连累图表（§10-2 同精神）。
    :param text_width: 预留的刻度文本宽度。太小会让 pyqtgraph 减少刻度条数、
                       太大就退化成第一版的空白。默认 52 是按本项目标签形态（≤6 字符）定的。
    :return: 实际使用的文本宽度；**0.0 = 没做任何事**（空列表 / 失败），供断言区分"跳过"与"成功"
    """
    items = [it for it in (plot_items or []) if it is not None]
    if not items:
        return 0.0
    try:
        width = max(AXIS_MIN_TEXT_WIDTH, int(text_width))
        for it in items:
            axis = it.getAxis(axis_name)
            axis.setWidth(None)          # 清掉任何历史钉死值，回到"由 tickTextWidth 决定"
            axis.setStyle(tickTextWidth=width,
                          autoExpandTextSpace=False,    # 不许按自己的标签撑开（否则对齐全废）
                          autoReduceTextSpace=True)     # 超宽时减刻度，而不是裁字
        return float(width)
    except Exception:  # noqa: BLE001
        return 0.0


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

    for axis_name in ('left', 'bottom'):
        style_axis(plot_item, axis_name)

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


# ==========================================
# 叠层配色与对比度（§7-B3 P3）
# ==========================================
def _to_rgb(color: str) -> tuple:
    text = (color or '').strip().lstrip('#')
    if len(text) == 3:
        text = ''.join(ch * 2 for ch in text)
    if len(text) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def _to_hex(rgb) -> str:
    return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def luminance(color: str) -> float:
    """0(黑) ~ 1(白) 的相对亮度（sRGB 加权）。"""
    r, g, b = _to_rgb(color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


MIN_CONTRAST_DELTA = 0.30     # 绝对亮度差下限（对深色背景尤其重要）
MIN_CONTRAST_RATIO = 3.0      # WCAG 对"非文字图形"建议的对比度下限


def contrast_ratio(lum_a: float, lum_b: float) -> float:
    hi, lo = max(lum_a, lum_b), min(lum_a, lum_b)
    return (hi + 0.05) / (lo + 0.05)


def _visible(fg_lum: float, bg_lum: float) -> bool:
    return (abs(fg_lum - bg_lum) >= MIN_CONTRAST_DELTA
            and contrast_ratio(fg_lum, bg_lum) >= MIN_CONTRAST_RATIO)


def ensure_contrast(color: str, background: str = LIGHT_BACKGROUND) -> str:
    """保证叠层颜色相对图表背景有足够对比度；不足时**保留色相**地压暗/提亮。

    【为什么需要】通达信公式是为**黑底**写的，天然爱用 `COLORWHITE` / `COLORYELLOW`；
    而本软件图表是**白底** —— 照搬就等于"画了但看不见"，正是 §7-B3 要根除的失败模式。
    这里不替换颜色，而是把它朝背景的**反方向**混合到能看清为止（黄仍偏黄，白变成深灰）。

    判据同时看"绝对亮度差"与"对比度比"：只看比值会让黑底上的 `COLORBLACK
    → #1A1A1A` 这种"比值达标但肉眼几乎看不见"的情况漏过去。
    """
    if not color:
        return DEFAULT_OVERLAY_COLOR
    bg_lum = luminance(background)
    if _visible(luminance(color), bg_lum):
        return color
    target = (0, 0, 0) if bg_lum > 0.5 else (255, 255, 255)
    src = _to_rgb(color)
    for step in range(1, 21):
        blended = tuple(s + (d - s) * (step / 20.0) for s, d in zip(src, target))
        if _visible(luminance(_to_hex(blended)), bg_lum):
            return _to_hex(blended)
    return _to_hex(target)
