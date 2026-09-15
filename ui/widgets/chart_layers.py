# ui/widgets/chart_layers.py
"""
「图层协议」的公共件（§7-B3 D4 · v6.7）。

【为什么单独成文件】
  当时那个 `ui/views/market.py` 已到 425 行、逼近体积上限（§9-L；v6.12 已删除，
  现为 `ui/views/trading_desk.py`）。把两件**与页面无关**的事
  搬出来，页面只留"开关 + 窗格编排"：
    1. 内置指标 → 绘图 IR（`builtin_indicator_layers`）；
    2. 叠层数值与股价是否差得离谱（`scale_mismatch_hint`，给用户的选图引导）。

【纪律】
  · 本模块**不画图、不持有窗口**：产出 `DrawData`、给一句人话提示；
    真正落笔的永远是唯一渲染器 `ui/widgets/draw_overlay.py`（§10-11）。
  · 内置指标的配色只从 `chart_style` 取，禁止在这里写死颜色（§10-12）。
"""
from __future__ import annotations

import numpy as np

from core.formula.draw import DrawData
from ui.widgets.chart_style import BOLL_LINE_COLOR, MA_SERIES

# 叠层量级与股价差多少倍算"明显是副图指标"
SCALE_RATIO_THRESHOLD = 3.0


def builtin_indicator_layers(df, *, ma: bool = False, boll: bool = False) -> list:
    """内置主图指标 → 绘图 IR（与用户公式**同一种数据结构**）。

    这样 MA/BOLL 与用户函数在渲染层没有任何区别：对比度守卫、线型、粗细、
    空值断线全部自动一视同仁（§7-B3 D4「不得为用户公式单开分支」）。
    """
    layers = []
    if ma:
        for column, color in MA_SERIES:
            if column in df.columns:
                layers.append(DrawData(kind='line', name=column, color=color,
                                       thickness=2, y=df[column].to_numpy(dtype=float)))
    if boll:
        for column in ('BOLL_UP', 'BOLL_DOWN'):
            if column in df.columns:
                layers.append(DrawData(kind='line', name=column, color=BOLL_LINE_COLOR,
                                       thickness=1, style='dash',
                                       y=df[column].to_numpy(dtype=float)))
    return layers


def layer_value_range(draws):
    """叠层整体的 `(最低, 最高)`；没有有效数值时返回 None。"""
    lows, highs = [], []
    for data in draws or ():
        for array in (data.y, data.lo, data.hi, data.pos):
            if array is None:
                continue
            values = np.asarray(array, dtype=float)
            values = values[np.isfinite(values)]
            if values.size:
                lows.append(float(values.min()))
                highs.append(float(values.max()))
    if not lows:
        return None
    return min(lows), max(highs)


def scale_mismatch_hint(draws, price_low: float, price_high: float):
    """判断叠层数值与股价是否"差得离谱"；是则返回一句可操作的提示，否则 None。

    【为什么需要这条判据】
      用户手里既有**主图函数**（均线类，与股价同量级）也有**副图函数**
      （MACD/RSI/成交量量级）。后者若被选成"主图"，主图坐标轴会被撑到认不出 K 线
      （用户实测反馈的原话："坐标轴差距特别大，严重影响使用"）。
      与其让用户自己猜，不如在应用后直接告诉他"这条应该放副图"。
    """
    span = layer_value_range(draws)
    if span is None:
        return None
    lo, hi = span
    price_low, price_high = float(price_low), float(price_high)
    price_span = price_high - price_low
    if price_span <= 0:
        return None

    overlay_span = hi - lo
    # 判据①：量级差 3 倍以上；判据②：几乎不落在价格区间里（完全跑在外面）
    beyond = hi < price_low - price_span * 0.5 or lo > price_high + price_span * 0.5
    if overlay_span > price_span * SCALE_RATIO_THRESHOLD or beyond:
        return (f"⚠ 该函数数值范围 {lo:,.2f} ~ {hi:,.2f}，与股价 "
                f"{price_low:,.2f} ~ {price_high:,.2f} 相差很大 —— "
                f"建议把「目标窗格」改成**副图**，否则主图会被压扁。")
    return None
