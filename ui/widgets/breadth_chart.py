# ui/widgets/breadth_chart.py
"""📊 M3「广度统计」—— L0 双窗格折线（§7-B1/B2 主案 STEP 5 · B2 / E 节）。

【为什么用 ChartHost】主案 B2 拍板：M3 的"双轴"用「**上下两窗格 x 联动**」而不是真·双 y 轴
—— 上窗格 = **每天有多少只满足条件**（家数 / 占比%），下窗格 = 指数收盘（叠加参照）。
ChartHost（§7-B3 B②）是全 app 唯一的多窗格编排者（x 联动 / 十字光标 / 只有最下窗格显示
日期轴），M3 不许自己 `addPlot` 拼窗格（§10-12）。

【坐标系】x = epoch 秒（`date_axis=True`），y = 家数（只）或占比（%）。
刻度与量程自适应走 `adaptive_axis.attach_all`（全 app 唯一刻度来源，禁止手写 setTicks）。

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

from ui.widgets.adaptive_axis import attach_all
from ui.widgets.chart_host import ChartHost
from ui.widgets.chart_style import apply_pokorny_style

__all__ = ['BreadthChart']

# 配色沿用现状色板（E 节：accent 主色 / 平滑橙 / 指数灰；深色主题仍推迟）
_BREADTH_COLOR = '#1976D2'
_SMOOTH_COLOR = '#FB8C00'
_INDEX_COLOR = '#5B6472'
_FILL_RGBA = (25, 118, 210, 36)          # 主线下方浅填充（原型同款；K线/主角永远在场，填充是配角 §11.5-44）

RATIO_MAX_PAD = 1.08                     # 量程上限 = 可见最大值 × 它（再 +1 只，折线不贴边）


def _epoch_seconds(dates) -> np.ndarray:
    """DatetimeIndex → epoch 秒（ChartHost 的 DateAxisItem 口径）。"""
    return np.asarray(dates.asi8, dtype=np.int64) // 10 ** 9


class BreadthChart(QWidget):
    """广度折线（主窗格）+ 指数收盘（副窗格），x 联动 + 十字光标 + 自适应刻度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = ChartHost(self, name='breadth', date_axis=True, crosshair=True,
                               sub_panes=('index',))
        self._host.setBackground('w')
        for pane in self._host.panes:
            apply_pokorny_style(pane.plot_item, background=None, margins=0)
        self._host.set_readout_provider(self._readout)
        self._host.set_readout_visible(True)

        # —— 当前画面的只读镜像（读数条 / y 跟随 provider 用；每次 render 整体替换）——
        self._frame = pd.DataFrame()
        self._xs = np.zeros(0, dtype=np.int64)
        self._ys = np.zeros(0, dtype=float)
        self._ma = np.zeros(0, dtype=float)
        self._ratio = False
        self._idx_xs = np.zeros(0, dtype=np.int64)
        self._idx_ys = np.zeros(0, dtype=float)
        self._index_label = ''

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._host, 1)

    # ==========================================
    # 渲染
    # ==========================================
    def render(self, frame: pd.DataFrame, index_df: pd.DataFrame = None,
               index_label: str = '', smooth: bool = True, ratio: bool = False) -> bool:
        """把一段广度帧画上去。`:returns: 是否真的画了（False = 帧为空，调用方给空态）。"""
        self._ratio = bool(ratio)
        self._index_label = str(index_label or '')
        self._frame = pd.DataFrame()
        self._host.clear_pane_content('breadth')
        self._host.clear_pane_content('index')
        if frame is None or frame.empty or 'hits' not in frame.columns:
            self._xs = np.zeros(0, dtype=np.int64)
            self._ys = np.zeros(0, dtype=float)
            self._ma = np.zeros(0, dtype=float)
            self._idx_xs = np.zeros(0, dtype=np.int64)
            self._idx_ys = np.zeros(0, dtype=float)
            return False

        values = frame['ratio'] * 100.0 if ratio else frame['hits'].astype(float)
        self._frame = frame
        self._xs = _epoch_seconds(frame.index)
        self._ys = values.to_numpy(dtype=float)
        self._ma = (values.rolling(5, min_periods=3).mean().to_numpy(dtype=float)
                    if smooth else np.zeros(0, dtype=float))

        pane = self._host.pane('breadth')
        unit = '占比（%）' if ratio else '家数（只）'
        pane.plot_item.setLabel('left', unit)
        curve = pg.PlotDataItem(self._xs, self._ys,
                                pen=pg.mkPen(_BREADTH_COLOR, width=1.7))
        curve.setFillLevel(0.0)
        curve.setBrush(pg.mkBrush(*_FILL_RGBA))
        pane.plot_item.addItem(curve)
        if smooth and len(self._ma) >= 3 and not np.isnan(self._ma).all():
            pane.plot_item.addItem(pg.PlotDataItem(
                self._xs, self._ma,
                pen=pg.mkPen(_SMOOTH_COLOR, width=1.3, style=Qt.PenStyle.DashLine)))
        if len(self._ys):
            pane.plot_item.addItem(pg.ScatterPlotItem(
                x=[self._xs[-1]], y=[self._ys[-1]], size=7,
                pen=pg.mkPen(None), brush=pg.mkBrush(_BREADTH_COLOR)))

        self._render_index(index_df)
        self._attach_axes()
        self._host.set_readout_text(self._readout('breadth', float(self._xs[-1]), 0.0))
        return True

    def _render_index(self, index_df) -> None:
        """副窗格：指数收盘线（画它**自己的日期**，x 联动会对齐重叠区间）。"""
        pane = self._host.pane('index')
        pane.plot_item.setLabel('left', self._index_label or '指数')
        self._idx_xs = np.zeros(0, dtype=np.int64)
        self._idx_ys = np.zeros(0, dtype=float)
        if index_df is None or index_df.empty or 'close' not in index_df.columns:
            return
        data = index_df.copy()
        data['date'] = pd.to_datetime(data['date'])
        data['close'] = pd.to_numeric(data['close'], errors='coerce')
        data = data.dropna(subset=['date', 'close']).sort_values('date')
        if data.empty:
            return
        self._idx_xs = _epoch_seconds(pd.DatetimeIndex(data['date'].to_numpy()))
        self._idx_ys = data['close'].to_numpy(dtype=float)
        pane.plot_item.addItem(pg.PlotDataItem(
            self._idx_xs, self._idx_ys, pen=pg.mkPen(_INDEX_COLOR, width=1.3)))

    def _attach_axes(self) -> None:
        """刻度挂最下窗格（日期），纵轴逐窗格跟随可视区间（§7-B4：禁止手写 setTicks）。"""
        def breadth_provider(i0: int, i1: int):
            segment = self._ys[i0:i1 + 1]
            if segment.size == 0 or not np.isfinite(segment).any():
                return None
            top = float(np.nanmax(segment)) * RATIO_MAX_PAD + 1.0
            return (0.0, top)

        def index_provider(i0: int, i1: int):
            if self._idx_xs.size == 0:
                return None
            x0 = float(self._xs[max(0, min(i0, len(self._xs) - 1))])
            x1 = float(self._xs[max(0, min(i1, len(self._xs) - 1))])
            lo, hi = np.searchsorted(self._idx_xs, (min(x0, x1), max(x0, x1)), side='right')
            segment = self._idx_ys[lo:hi]
            if segment.size == 0 or not np.isfinite(segment).any():
                return None
            return (float(np.nanmin(segment)), float(np.nanmax(segment)))

        attach_all(self._host, self._xs,
                   {'breadth': breadth_provider, 'index': index_provider})

    # ==========================================
    # 读数条（业务文案；provider 返回空 ⇒ 宿主回退内置文案）
    # ==========================================
    def _nearest(self, xs: np.ndarray, x: float) -> int:
        if xs.size == 0:
            return -1
        return int(min(max(np.searchsorted(xs, x), 0), xs.size - 1))

    def _readout(self, pane_name: str, x: float, _y: float) -> str:
        if pane_name == 'breadth' and self._frame is not None and len(self._xs):
            i = self._nearest(self._xs, x)
            day = self._frame.index[i]
            hits = int(round(float(self._ys[i])))
            if self._ratio:
                return f"{pd.Timestamp(day).date()} · 占比 {self._ys[i]:.2f}% · MA5 {self._ma[i]:.2f}%" \
                    if i < len(self._ma) and np.isfinite(self._ma[i]) \
                    else f"{pd.Timestamp(day).date()} · 占比 {self._ys[i]:.2f}%"
            text = f"{pd.Timestamp(day).date()} · 命中 {hits} 只"
            if i < len(self._ma) and np.isfinite(self._ma[i]):
                text += f" · MA5 {self._ma[i]:.1f} 只"
            valid = int(self._frame['valid'].iloc[i]) if 'valid' in self._frame.columns else 0
            if valid > 0:
                text += f"（占比 {hits / valid * 100:.1f}%）"
            return text
        if pane_name == 'index' and self._idx_xs.size:
            i = self._nearest(self._idx_xs, x)
            day = pd.Timestamp(self._idx_xs[i], unit='s').date()
            return f"{day} · {self._index_label or '指数'} {self._idx_ys[i]:,.2f}"
        return ''
