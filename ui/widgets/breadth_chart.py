# ui/widgets/breadth_chart.py
"""📊 M3「广度统计」—— L0 双窗格折线（§7-B1/B2 主案 STEP 5 · B2 / E 节）。

【为什么用 ChartHost】主案 B2 拍板：M3 的"双轴"用「**上下两窗格 x 联动**」而不是真·双 y 轴
—— 上窗格 = **每天有多少只满足条件**（家数 / 占比%），下窗格 = 指数收盘（叠加参照）。
ChartHost（§7-B3 B②）是全 app 唯一的多窗格编排者（x 联动 / 十字光标 / 只有最下窗格显示
日期轴），M3 不许自己 `addPlot` 拼窗格（§10-12）。

【坐标系：bar 序号，不是 epoch 秒】⚠ 这是 v6.42 修过的最大一课：
`adaptive_axis` 的契约（其模块头原话）是「x 一律假定 bar 序号；epoch 秒的
`pg.DateAxisItem` 轴不适用本模块」。第一版这里用的正是 epoch 秒轴 + `attach_all`，
结果是**两个窗格的 y 跟随器 100% 失效**（provider 收到 1.7e9 当"bar 序号"，切片恒空、
恒返回 None），指数副图退化成"对全历史自动量程"（2000~6000 一根线压成一条），
底部日期刻度钉在序号 729 的位置上 ⇒ 视野外 ⇒ 整根轴没有标签。
现在：x = 0..n-1，日期刻度由 `attach_all(dates=frame.index)` 提供 —— 与行情页/回测页
同一套已验证口径；指数 df 先**前向填充对齐到广度日期轴**再画（副图只画当前区间，
不再把全历史喂给渲染器）。

【两种视觉（用户 2026-09-21 拍板：柱状/折线都要有）】
  · `bars`（默认）= 每日家数**细柱** + MA5 **实线主角** —— 整数家数天然该用柱状读；
  · `line` = 原始折线 + 浅面积填充 + MA5 橙色虚线（旧形态，留给偏好折线的用户）。
家数模式纵轴刻度**取整**（"3.5 只"是谎话）；占比模式保留小数。

【读数条】业务文案由本模块提供 provider（§7-B6 STEP 2 同款约定：宿主不猜业务，
provider 返回空 ⇒ 回退内置文案；读数绝不能连累图表）。

【只渲染不调度】数据（切片后的广度帧 / 指数 df）由 `breadth_flow` 喂入；本模块不取数、
不存跨渲染状态（`_frame` 等只是**当前画面**的只读镜像，供读数与 y 跟随用）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.widgets.adaptive_axis import attach_all, slice_span
from ui.widgets.chart_host import ChartHost
from ui.widgets.chart_style import apply_pokorny_style
from ui.widgets.custom_widgets import CandlestickItem, OhlcBarItem

__all__ = ['BreadthChart', 'CHART_TYPES', 'DEFAULT_CHART_TYPE',
           'INDEX_STYLES', 'DEFAULT_INDEX_STYLE']

# 配色沿用现状色板（E 节：accent 主色 / 平滑橙 / 指数灰；深色主题仍推迟）
_BREADTH_COLOR = '#1976D2'
_SMOOTH_COLOR = '#FB8C00'
_INDEX_COLOR = '#5B6472'
_FILL_RGBA = (25, 118, 210, 36)          # 折线态：主线下方浅填充（配角，§11.5-44）
_BARS_RGBA = (25, 118, 210, 90)          # 柱状态：每日家数细柱（半透明，让 MA5 主角线）

RATIO_MAX_PAD = 1.08                     # 量程上限 = 可见最大值 × 它（再 +1 只，折线不贴边）

# 视觉方案（唯一事实来源：抽屉下拉与 render 参数共用这两个键）
CHART_TYPES = (('bars', '柱状 + 趋势线（推荐）'), ('line', '折线 + 面积'))
DEFAULT_CHART_TYPE = 'bars'

# 指数副图可选图形（用户 2026-09-21 拍板：不止折线 —— K线/美国线都要有）。
# K线/美国线需要本地指数有开高低列；缺列诚实退回折线（不画假四价）。
INDEX_STYLES = (('line', '折线'), ('area', '面积'),
                ('kline', 'K 线'), ('ohlc', '美国线 (OHLC)'))
DEFAULT_INDEX_STYLE = 'line'
_INDEX_OHLC_NEED = ('open', 'high', 'low')     # kline/ohlc 的最低列要求（close 恒需）


class _BreadthTickAxis(pg.AxisItem):
    """纵轴刻度：`integer=True` 时只写整数（家数模式）—— 其余行为与原生轴一致。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.integer = False

    def tickStrings(self, values, scale, spacing):
        if self.integer:
            return [f'{value:.0f}' for value in values]
        return super().tickStrings(values, scale, spacing)


class BreadthChart(QWidget):
    """广度（主窗格：柱状/折线两种视觉）+ 指数收盘（副窗格），x 联动 + 自适应刻度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = ChartHost(self, name='breadth', date_axis=False, crosshair=True,
                               sub_panes=('index',))
        self._host.setBackground('w')
        for pane in self._host.panes:
            # 换掉原生左轴（家数要整数刻度；指数窗格保留小数 ⇒ integer 恒 False）
            pane.plot_item.setAxisItems({'left': _BreadthTickAxis('left')})
            apply_pokorny_style(pane.plot_item, background=None, margins=0)
        self._host.set_readout_provider(self._readout)
        self._host.set_readout_visible(True)

        # —— 当前画面的只读镜像（读数条 / y 跟随 provider 用；每次 render 整体替换）——
        self._frame = pd.DataFrame()
        self._n = 0
        self._xs = np.zeros(0, dtype=float)
        self._ys = np.zeros(0, dtype=float)
        self._ma = np.zeros(0, dtype=float)
        self._ratio = False
        self._idx_close = np.zeros(0, dtype=float)   # 指数收盘，**已对齐到广度 bar 轴**
        self._idx_lo = np.zeros(0, dtype=float)      # 逐 bar 纵轴下限（线=收盘 / K线=最低）
        self._idx_hi = np.zeros(0, dtype=float)      # 逐 bar 纵轴上限（y 跟随用）
        self._index_label = ''

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._host, 1)
        # 分界线拖动调高（用户："想看指数的时候把指数图的空间调大"）：
        # 按住两图交界拖动，双击交界恢复 3:1。
        self._host.enable_divider_drag('breadth', 'index')

    # ==========================================
    # 渲染
    # ==========================================
    def render(self, frame: pd.DataFrame, index_df: pd.DataFrame = None,
               index_label: str = '', smooth: bool = True, ratio: bool = False,
               chart_type: str = DEFAULT_CHART_TYPE,
               index_style: str = DEFAULT_INDEX_STYLE) -> bool:
        """把一段广度帧画上去。`:returns: 是否真的画了（False = 帧为空，调用方给空态）。"""
        self._ratio = bool(ratio)
        self._index_label = str(index_label or '')
        self._frame = pd.DataFrame()
        self._host.clear_pane_content('breadth')
        self._host.clear_pane_content('index')
        if frame is None or frame.empty or 'hits' not in frame.columns:
            self._n = 0
            self._xs = np.zeros(0, dtype=float)
            self._ys = np.zeros(0, dtype=float)
            self._ma = np.zeros(0, dtype=float)
            self._idx_close = np.zeros(0, dtype=float)
            self._idx_lo = np.zeros(0, dtype=float)
            self._idx_hi = np.zeros(0, dtype=float)
            return False

        values = frame['ratio'] * 100.0 if ratio else frame['hits'].astype(float)
        self._frame = frame
        self._n = len(frame)
        self._xs = np.arange(self._n, dtype=float)          # x = bar 序号（见模块头）
        self._ys = values.to_numpy(dtype=float)
        self._ma = (values.rolling(5, min_periods=3).mean().to_numpy(dtype=float)
                    if smooth else np.zeros(0, dtype=float))
        has_ma = self._ma.size >= 3 and not np.isnan(self._ma).all()

        pane = self._host.pane('breadth')
        axis = pane.plot_item.getAxis('left')
        if isinstance(axis, _BreadthTickAxis):
            axis.integer = not self._ratio                  # 家数取整；占比留小数
        unit = '占比（%）' if ratio else '家数（只）'
        pane.plot_item.setLabel('left', unit)

        if chart_type == 'line':
            curve = pg.PlotDataItem(self._xs, self._ys,
                                    pen=pg.mkPen(_BREADTH_COLOR, width=1.7))
            curve.setFillLevel(0.0)
            curve.setBrush(pg.mkBrush(*_FILL_RGBA))
            pane.plot_item.addItem(curve)
            if has_ma:
                pane.plot_item.addItem(pg.PlotDataItem(
                    self._xs, self._ma,
                    pen=pg.mkPen(_SMOOTH_COLOR, width=1.3, style=Qt.PenStyle.DashLine),
                    connect='finite'))
                tip = self._ma[-1] if np.isfinite(self._ma[-1]) else self._ys[-1]
            else:
                tip = self._ys[-1]
        else:                                               # 'bars'（默认）
            pane.plot_item.addItem(pg.BarGraphItem(
                x=self._xs, height=np.nan_to_num(self._ys, nan=0.0), width=0.8,
                brush=pg.mkBrush(*_BARS_RGBA), pen=pg.mkPen(width=0)))
            if has_ma:                                      # MA5 = 主角实线
                pane.plot_item.addItem(pg.PlotDataItem(
                    self._xs, self._ma, pen=pg.mkPen(_BREADTH_COLOR, width=1.8),
                    connect='finite'))
                tip = self._ma[-1] if np.isfinite(self._ma[-1]) else self._ys[-1]
            else:                                           # 平滑关了 ⇒ 细折线兜住主角
                pane.plot_item.addItem(pg.PlotDataItem(
                    self._xs, self._ys, pen=pg.mkPen(_BREADTH_COLOR, width=1.2),
                    connect='finite'))
                tip = self._ys[-1]
        if self._n:
            pane.plot_item.addItem(pg.ScatterPlotItem(
                x=[self._xs[-1]], y=[tip], size=7,
                pen=pg.mkPen(None), brush=pg.mkBrush(_BREADTH_COLOR)))

        self._render_index(index_df, index_style)
        self._attach_axes()
        # 两窗格纵轴共用同一个固定左槽（R8 第二版口径：tickTextWidth 预留宽，
        # 对齐且**不留大片空白**）—— 家数轴短标签/指数轴 4~5 位标签不再错位。
        self._host.align_axis_widths()
        self._host._update_divider_position()       # 重画后交界位置变了，把手跟上
        self._host.set_readout_text(self._readout('breadth', float(self._n - 1), 0.0))
        return True

    def _render_index(self, index_df, style: str = DEFAULT_INDEX_STYLE) -> None:
        """副窗格：指数，**按日精确对齐到广度 bar 轴**后画可选四种图形。

        旧版直接画全历史 df（x=epoch）—— 与主窗格不同轴不同序，y 跟随拿不到正确切片；
        现在两窗格共用同一根 0..n-1 轴，缩放/联动/量程天然同步，且只画当前区间。
        K线/美国线缺开高低列 ⇒ 诚实退回折线（不画假四价）。
        """
        pane = self._host.pane('index')
        pane.plot_item.setLabel('left', self._index_label or '指数')
        self._idx_close = np.full(self._n, np.nan, dtype=float)
        self._idx_lo = self._idx_close
        self._idx_hi = self._idx_close
        if index_df is None or index_df.empty or 'close' not in index_df.columns \
                or self._n == 0:
            return
        cols = ['date', 'close'] + [c for c in _INDEX_OHLC_NEED
                                    if c in index_df.columns]
        data = index_df[cols].copy()
        data['date'] = pd.to_datetime(data['date'])
        for c in data.columns:
            if c != 'date':
                data[c] = pd.to_numeric(data[c], errors='coerce')
        data = (data.dropna(subset=['date', 'close'])
                    .drop_duplicates(subset='date', keep='last')
                    .sort_values('date'))
        if data.empty:
            return
        # 精确对齐（不再 ffill）：只认**日期相等**的 bar，对不上的留 NaN（绝不拿后一天冒充）
        dvals = data['date'].to_numpy()
        fvals = self._frame.index.to_numpy()
        pos = np.searchsorted(dvals, fvals, side='left')
        in_bounds = pos < len(dvals)
        ok = np.zeros(len(pos), dtype=bool)
        ok[in_bounds] = dvals[pos[in_bounds]] == fvals[in_bounds]
        okv = pos[ok]
        close = data['close'].to_numpy(dtype=float)
        self._idx_close[ok] = close[okv]
        has_ohlc = all(c in data.columns for c in _INDEX_OHLC_NEED)
        style = style if style in ('line', 'area', 'kline', 'ohlc') else 'line'
        if style in ('kline', 'ohlc') and not has_ohlc:
            style = 'line'
        if style in ('kline', 'ohlc'):
            highs = data['high'].to_numpy(dtype=float)
            lows = data['low'].to_numpy(dtype=float)
            opens = data['open'].to_numpy(dtype=float)
            bars_lo = np.full(self._n, np.nan, dtype=float)
            bars_hi = np.full(self._n, np.nan, dtype=float)
            bars_lo[ok] = lows[okv]
            bars_hi[ok] = highs[okv]
            self._idx_lo, self._idx_hi = bars_lo, bars_hi
            k_data = [(float(i), float(opens[p]), float(close[p]),
                       float(lows[p]), float(highs[p]))
                      for i, p in zip(self._xs[ok], okv)]
            item = (CandlestickItem(k_data) if style == 'kline'
                    else OhlcBarItem(k_data))
            pane.plot_item.addItem(item)
        elif style == 'area':
            item = pg.PlotDataItem(self._xs, self._idx_close,
                                   pen=pg.mkPen(_INDEX_COLOR, width=1.3),
                                   connect='finite')
            floor = float(np.nanmin(self._idx_close)) if np.isfinite(self._idx_close).any() else 0.0
            item.setFillLevel(floor)
            item.setBrush(pg.mkBrush(91, 100, 114, 40))
            pane.plot_item.addItem(item)
        else:
            pane.plot_item.addItem(pg.PlotDataItem(
                self._xs, self._idx_close, pen=pg.mkPen(_INDEX_COLOR, width=1.3),
                connect='finite'))

    def _attach_axes(self) -> None:
        """刻度挂最下窗格（日期文本来自广度帧），纵轴逐窗格跟随可视 bar 区间
        （§7-B4 / adaptive_axis 的 bar 序号契约 —— 别再喂 epoch 秒，见模块头）。"""
        def breadth_provider(i0: int, i1: int):
            segment = self._ys[i0:i1 + 1]
            if segment.size == 0 or not np.isfinite(segment).any():
                return None
            top = float(np.nanmax(segment)) * RATIO_MAX_PAD + 1.0
            return (0.0, top)

        def index_provider(i0: int, i1: int):
            return slice_span(self._idx_lo, self._idx_hi, i0, i1)

        attach_all(self._host, list(self._frame.index),
                   {'breadth': breadth_provider, 'index': index_provider})

    # ==========================================
    # 读数条（业务文案；provider 返回空 ⇒ 宿主回退内置文案）
    # ==========================================
    def _bar_at(self, x: float) -> int:
        if self._n == 0:
            return -1
        return int(min(max(int(round(x)), 0), self._n - 1))

    def _readout(self, pane_name: str, x: float, _y: float) -> str:
        i = self._bar_at(x)
        if i < 0:
            return ''
        if pane_name == 'breadth':
            day = pd.Timestamp(self._frame.index[i]).date()
            hits = int(round(float(self._ys[i])))
            if self._ratio:
                text = f"{day} · 占比 {self._ys[i]:.2f}%"
                if i < len(self._ma) and np.isfinite(self._ma[i]):
                    text += f" · MA5 {self._ma[i]:.2f}%"
                return text
            text = f"{day} · 命中 {hits} 只"
            if i < len(self._ma) and np.isfinite(self._ma[i]):
                text += f" · MA5 {self._ma[i]:.1f} 只"
            valid = int(self._frame['valid'].iloc[i]) if 'valid' in self._frame.columns else 0
            if valid > 0:
                text += f"（占比 {hits / valid * 100:.1f}%）"
            return text
        if pane_name == 'index' and i < len(self._idx_close) \
                and np.isfinite(self._idx_close[i]):
            day = pd.Timestamp(self._frame.index[i]).date()
            return f"{day} · {self._index_label or '指数'} {self._idx_close[i]:,.2f}"
        return ''
