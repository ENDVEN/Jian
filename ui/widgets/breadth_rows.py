# ui/widgets/breadth_rows.py
"""📊 M3「多统计项」：**多行小图**（每项一行：柱 + 5 周均线）+ 底部固定指数副图（★1.73 / §7-B16 期 1）。

【形态来源】`design/1.72-m3-multi-plan-ui/b-多行小图.html`（用户 2026-10-12 拍板）：
  · 每行 = **柱（每日占比，可切家数）+ 折线（5 周均）** —— 柱给"每天实际多少"的量感，
    线给"趋势形状"；用户原话："折线太单一，还是需要柱状图作为叠加"；
  · 行数多时的**布局统筹**：1~3 项单列等分 · **4~6 项焦点行（约 1.6×）+ 迷你条** ·
    7~12 项两列（本控件先做单列；两列留给布局层）· >12 项只留关注项；
  · 底部指数副图**高度固定、贴底、不随行数被压扁**（三条硬规则之一）；
  · 所有行与副图**共享 x 轴 + 同一条竖向十字线**，读数**统一显示一处**
    （不在每行各弹一个框 —— 那会变成视觉噪声）。

【为什么用 ChartHost】§10-12：多窗格编排**只许**走 `ChartHost`（它管 x 联动 / 日期轴 /
  十字光标 / 轴宽对齐 / 分界拖动）。本件**只喂数据、只调它的公开方法**，不自己 `addPlot`。

【x 轴口径】沿用 M3 既有约定（`breadth_chart` 模块头那一课）：x = **bar 序号** 0..n-1，
  日期文本由 `adaptive_axis.attach_all(host, dates, providers)` 提供 —— 绝不喂 epoch 秒
  （喂了会让 y 跟随器与底部刻度整根失效）。
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
# 指数副图的**图形目录 / 配色 / 列要求**与抽屉下拉同一份（§11.5-112：同一事实只存一处）——
#   ★1.74 复核：旧版在本文件又抄了一份，现从 `breadth_chart` 取（本地沿用旧名，避免改名扩散）。
from ui.widgets.breadth_chart import (DEFAULT_INDEX_STYLE, INDEX_COLOR as _INDEX_COLOR,
                                      INDEX_OHLC_NEED as _INDEX_OHLC_NEED)
from ui.widgets.custom_widgets import CandlestickItem, OhlcBarItem

__all__ = ['BreadthRowsChart', 'ROW_COLORS', 'BAR_MODE_RATIO', 'BAR_MODE_HITS',
           'MA_WINDOW_DEFAULT', 'FOCUS_STRETCH', 'INDEX_PANE_HEIGHT',
           'INDEX_HEIGHT_RANGE', 'MINI_ROW_MIN_H']

# 统计项的配色（按添加顺序取，循环用）—— 与设计稿 A/B 两页同源色板
ROW_COLORS = ('#E53935', '#1E88E5', '#6A1B9A', '#2E7D32', '#EF6C00', '#00838F')

BAR_MODE_RATIO = 'ratio'          # 柱 = 占比（%），默认
BAR_MODE_HITS = 'hits'            # 柱 = 家数（只）
MA_WINDOW_DEFAULT = 5             # 折线 = N 周均（默认 5）
FOCUS_STRETCH = 3                 # 焦点行相对高度（迷你行 = 1）
INDEX_PANE_HEIGHT = 170           # 指数副图**默认高度**（设计稿硬规则②：不随行数被压扁）
# ★1.73 / §7-B16 期 1 收尾：副图高度**可调**（用户 2026-10-12 拍板"必须有调整入口"）——
#   旧版只有固定 170px，而 v6.43 的"拖分界线调高"与固定高度互斥（拖动只改 stretch）⇒
#   改为**数值框精确设**（比拖更准、也能记住）。合法域见 `INDEX_HEIGHT_RANGE`。
INDEX_HEIGHT_RANGE = (120, 400)
MINI_ROW_MIN_H = 56               # 迷你行**高度下限**（行数多时不让行被压成一条线）

# 纵轴量程留白：可见最大值 × 它（再 +1，线不贴边）。
# ★1.74 复核：这个数值原本只在旧的 `breadth_chart.RATIO_MAX_PAD`（已删）里，
#   而本文件把它**硬编码**了一次 —— 现在收成一个常量，本文件是唯一使用者。
RANGE_PAD = 1.08


def _axis_tick_axis(integer: bool) -> pg.AxisItem:
    """纵轴：家数模式**只写整数**（"3.5 只"是谎话）；占比模式保留小数。"""
    axis = pg.AxisItem('left')
    axis.integer = bool(integer)

    def _strings(values, scale, spacing, _axis=axis):
        if _axis.integer:
            return [f'{v:.0f}' for v in values]
        return pg.AxisItem.tickStrings(_axis, values, scale, spacing)

    axis.tickStrings = _strings
    return axis


class BreadthRowsChart(QWidget):
    """多行小图：`render(items, frames, index_df, …)` 一次重排全部行。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = ChartHost(self, name='row0', date_axis=False, crosshair=True)
        self._host.setBackground('w')
        self._host.set_readout_provider(self._readout)
        self._host.set_readout_visible(True)
        # 当前画面的只读镜像（读数 / 轴跟随用；每次 render 整体替换）
        self._items: list[dict] = []
        self._rows: list[dict] = []                 # [{'key','label','color','values','ma','valid'}]
        self._dates: pd.Index | None = None
        self._n = 0
        self._bar_mode = BAR_MODE_RATIO
        self._idx_close = np.zeros(0, dtype=float)
        self._idx_lo = np.zeros(0, dtype=float)
        self._idx_hi = np.zeros(0, dtype=float)
        self._index_label = ''
        self._focus_on = False                   # 是否有焦点行（决定内容最小高度的权重）
        # 窗格增删计数（"切口径 / 切区间不该重建窗格"要有**可断言的证据**，不靠"看着没闪"）
        self.rebuilds = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._host, 1)

    # ==========================================
    # 渲染
    # ==========================================
    def render(self, items, frames, index_df: pd.DataFrame = None, *,
               bar_mode: str = BAR_MODE_RATIO, ma_window: int = MA_WINDOW_DEFAULT,
               focus: str = '', index_label: str = '', with_index: bool = True,
               chart_type: str = 'bars', index_style: str = DEFAULT_INDEX_STYLE,
               index_height: int = INDEX_PANE_HEIGHT) -> int:
        """把多个统计项各画一行。

        :param items:  `[{'key','label','color'}]` —— **顺序即行序**（第 0 项是主行）
        :param frames: `{key: DataFrame}`（每个 = `CrossSectionResult.breadth_frame(signal=…)`
                       的产出：index=交易日，含 `hits` / `valid` / `ratio`）
        :param index_df: 指数日线（含 `date`/`close`，可选 `open/high/low`）
        :param focus: 焦点行 key（空 = 全部等分；非空 = 那一行 `FOCUS_STRETCH` 倍高）
        :returns: 真正画出来的**行数**（0 = 没有可画的东西，调用方给空态）
        """
        self._bar_mode = bar_mode if bar_mode in (BAR_MODE_RATIO, BAR_MODE_HITS) else BAR_MODE_RATIO
        self._index_label = str(index_label or '')
        self._with_index = bool(with_index)      # 关掉「叠加指数」⇒ 不建副图窗格（不占地方）
        self._chart_type = str(chart_type or 'bars')
        self._ma_window = int(ma_window or 0)    # 0 = 不画均线（「叠加均线」取消勾选时）
        self.last_ma_window = self._ma_window    # 公开只读别名（断言/回执要引用"这一帧用了什么窗口"）
        self._index_height = self._clamp_index_h(index_height)
        self._focus_on = bool(focus)
        self._items = [dict(it) for it in (items or [])]
        self._clean_lines()
        self._rows = []
        self._dates = None
        self._n = 0

        # ---- ① 逐项取数（只认**有内容**的项；空项如实不画，不画零线冒充）----
        drawn = []
        for it in self._items:
            key = str(it.get('key') or '')
            frame = (frames or {}).get(key)
            if frame is None or frame.empty or 'hits' not in frame.columns:
                continue
            if str(it.get('visible', True)) in ('0', 'False', 'false'):
                continue
            drawn.append((it, frame))
        if not drawn:
            self._rebuild_panes(0, focus='')
            self._host.set_readout_text('')
            return 0
        # ---- ② 行序：焦点行**置顶**（设计稿：焦点行是主角，放最上面一眼看到）----
        drawn.sort(key=lambda pair: 0 if str(pair[0].get('key')) == str(focus) else 1)

        # ---- ③ 交易日轴：以**交集**为准（行与行必须逐 bar 对齐，否则跨行读数会错位）----
        axis = None
        for _it, frame in drawn:
            axis = frame.index if axis is None else axis.intersection(frame.index)
        axis = pd.DatetimeIndex(sorted(axis))
        if len(axis) == 0:
            self._rebuild_panes(0, focus='')
            return 0
        self._dates = axis
        self._n = len(axis)

        # ---- ④ 逐行算数据（柱值 + 均线）----
        for it, frame in drawn:
            sub = frame.reindex(axis)
            ratio_mode = self._bar_mode == BAR_MODE_RATIO
            if ratio_mode:
                values = (sub['ratio'] * 100.0).to_numpy(dtype=float)
            else:
                values = sub['hits'].to_numpy(dtype=float)
            if self._ma_window >= 2:
                win = self._ma_window
                ma = pd.Series(values).rolling(win, min_periods=max(2, win // 2)).mean().to_numpy()
            else:
                ma = np.zeros(0, dtype=float)        # 不画均线（取消勾选「叠加均线」）
            self._rows.append({
                'key': str(it.get('key') or ''), 'label': str(it.get('label') or ''),
                'color': str(it.get('color') or ROW_COLORS[0]), 'values': values, 'ma': ma,
                'valid': (sub['valid'].to_numpy(dtype=float)
                          if 'valid' in sub.columns else np.zeros(self._n)),
                'hits': (sub['hits'].to_numpy(dtype=float)
                         if 'hits' in sub.columns else np.zeros(self._n)),
            })

        # ---- ⑤ 重建窗格并逐行画 ----
        self._rebuild_panes(len(self._rows), focus=focus)
        for i, row in enumerate(self._rows):
            self._draw_row(i, row)
        if self._with_index:
            self._render_index(index_df, index_style)
        self._attach_axes()
        self._host.align_axis_widths()
        try:
            self._host._update_divider_position()
        except Exception:                    # noqa: BLE001 —— 把手是装饰件，绝不许打断渲染
            pass
        self._host.set_readout_text(self._readout(self._pane_name(0), float(self._n - 1), 0.0))
        return len(self._rows)

    # ---------- 内部：窗格管理 ----------
    @staticmethod
    def _clamp_index_h(value) -> int:
        """副图高度夹进合法域（脏值回落默认，**不抛** —— 界面每帧都在传它）。"""
        try:
            h = int(round(float(value)))
        except (TypeError, ValueError):
            return int(INDEX_PANE_HEIGHT)
        return int(min(max(h, INDEX_HEIGHT_RANGE[0]), INDEX_HEIGHT_RANGE[1]))

    def min_content_height(self) -> int:
        """**内容需要的最小高度** —— 放进 `QScrollArea` 后据此决定要不要出竖向滚动条。

        = 行数 × 迷你行下限（焦点行按 `FOCUS_STRETCH` 计）+ 副图高度（设计稿硬规则：
          副图**不被压扁**、行区**自己滚动**）。没有行时给一个小的空态高度。
        """
        n = len(self._rows)
        if n == 0:
            return 160
        weights = [FOCUS_STRETCH if (i == 0 and self._focus_on) else 1 for i in range(n)]
        unit = max(MINI_ROW_MIN_H, 1)
        rows_h = unit * sum(weights)
        return int(rows_h + (self._index_height if self._with_index else 0))

    def _pane_name(self, i: int) -> str:
        return f'row{i}'

    def _clean_lines(self) -> None:
        """清掉**上一帧**的图元（窗格结构交给 `_rebuild_panes`）。

        ⚠ 这里**不许**再 `clear_sub_panes()`：那会把副图窗格拆掉，导致下一次渲染
          "形状对不上"⇒ 每帧都重建窗格 ⇒ 外部缓存的窗格引用全部失效
          （表现为"K 线明明画了却断言不到"），也白白多做增删。
        """
        for pane in self._host.panes:
            self._host.clear_pane_content(pane.name)

    def _rebuild_panes(self, n_rows: int, *, focus: str) -> None:
        """按行数准备窗格：第 0 行用主窗格，其余 `add_pane`；指数副图**固定高度贴底**。

        ⚠ **形状没变时复用窗格对象、只清内容**（不 remove+add）：
          ① 高频重画（切口径 / 切区间 / 悬停重画）不该做无谓的增删；
          ② 窗格对象一旦被换掉，**外部缓存的引用就失效**（冒烟里 `pane('index')` 的引用
             就是这么变成悬空的 —— 表现是"K 线明明画了却断言不到"）；
          ③ 分界把手 / 拖动配置不必每次重建。
        """
        want = [self._pane_name(i) for i in range(n_rows)]
        if n_rows and self._with_index:
            want.append('index')
        have = self._host.pane_names
        same_shape = bool(have) and have[1:] == want[1:]
        if same_shape:
            for name in want:
                self._host.clear_pane_content(name)
        else:
            self.rebuilds += 1
            self._host.clear_sub_panes()
            for i in range(1, n_rows):
                self._host.add_pane(self._pane_name(i))
            if n_rows and self._with_index:
                # ⚠ **取舍（记在方案书 §6 未决项）**：这里给的是**固定高度**（设计稿硬规则②：
                #   "副图贴底、不随行数被压扁"）。它与 v6.43 的"拖分界线把指数图调高"**互斥**——
                #   `ChartHost` 的拖动只改 `_stretch`，而 `fixed_height` 把 min==max 钉死 ⇒
                #   拖了也不会变。⇒ 本版选**固定**，**不启用**分界拖动（留个假把手比没有更坏）；
                #   "调高"改走**数值框**（★1.73 收尾已落地：`index_height`，120~400px）。
                self._host.add_pane('index', fixed_height=self._index_height)
        # 副图高度：**复用分支也要重设**（用户改高度时窗格通常被复用 ⇒ 只在这里设一次就够两用）
        _idx_pane = self._host.pane('index')
        if _idx_pane is not None and self._with_index:
            _idx_pane.plot_item.setMinimumHeight(self._index_height)
            _idx_pane.plot_item.setMaximumHeight(self._index_height)
        for i, pane in enumerate(self._host.panes):
            if pane.name == 'index':
                continue
            pane.plot_item.setAxisItems({'left': _axis_tick_axis(self._bar_mode == BAR_MODE_HITS)})
            apply_pokorny_style(pane.plot_item, background=None, margins=0)
            # 焦点模式：焦点行 3 倍高，其余等分（ChartHost 负责把它落到行高上）
            stretch = (FOCUS_STRETCH if (focus and n_rows
                                         and self._pane_name(i) == self._pane_name(0))
                       else 1)
            self._host.set_pane_stretch(pane.name, stretch)
        idx_pane = self._host.pane('index')
        if idx_pane is not None:
            idx_pane.plot_item.setAxisItems({'left': _axis_tick_axis(False)})
            apply_pokorny_style(idx_pane.plot_item, background=None, margins=0)

    def _draw_row(self, i: int, row: dict) -> None:
        pane = self._host.pane(self._pane_name(i))
        if pane is None:
            return
        xs = np.arange(self._n, dtype=float)
        unit = '%' if self._bar_mode == BAR_MODE_RATIO else '只'
        mark = '①②③④⑤⑥⑦⑧⑨'[i] if i < 9 else f'{i + 1}'
        # 行名写在**窗格内标题**（带该行配色）：比纵轴标签稳 —— 纵轴那点儿宽度会把长中文裁掉，
        #   而"这一行是谁"是读图的第一要素（用户要的"一眼看得出"）。
        pane.plot_item.setTitle(
            f'<span style="color:{row["color"]}; font-size:10pt; font-weight:600;">'
            f'{mark} {row["label"]}</span>')
        pane.plot_item.setLabel('left', unit)          # 纵轴只留单位，避免被裁
        pane.plot_item.setToolTip(f'{row["label"]}（{"占比%" if unit == "%" else "家数只"}）')
        # 柱 = 当日值（半透明，让均线当主角）—— 只在「柱状 + 趋势线」形态下画
        # ⚠ Qt 的 8 位 hex 是 **#AARRGGBB**（alpha 在前）—— 别写成 `色值+'66'`，
        #   那会被当成"alpha=E5 的深色"，画出来是另一个颜色（§11.5-102 同族）。
        if self._chart_type != 'line':
            _brush = pg.mkColor(row['color'])
            _brush.setAlpha(0x66)
            pane.plot_item.addItem(pg.BarGraphItem(
                x=xs, height=np.nan_to_num(row['values'], nan=0.0), width=0.8,
                brush=pg.mkBrush(_brush), pen=pg.mkPen(width=0)))
        # 线：有均线画均线（主角实线），否则画原始序列
        if row['ma'].size and np.isfinite(row['ma']).any():
            pane.plot_item.addItem(pg.PlotDataItem(
                xs, row['ma'], pen=pg.mkPen(row['color'], width=1.8), connect='finite'))
        else:
            pane.plot_item.addItem(pg.PlotDataItem(
                xs, row['values'], pen=pg.mkPen(row['color'], width=1.2), connect='finite'))

    def _render_index(self, index_df, style: str = DEFAULT_INDEX_STYLE) -> None:
        """底行：指数（固定高度）。**只认日期相等**的 bar，对不上留 NaN（不拿后一天冒充）。

        ★1.73：把 M3 既有的四种指数图形（折线 / 面积 / K 线 / 美国线）**原样搬过来**——
          用户在 v6.43 拍板要过的东西，升级不能静默退化；缺开高低列 ⇒ 诚实退回折线。
        """
        pane = self._host.pane('index')
        if pane is None:
            return
        pane.plot_item.setLabel('left', self._index_label or '指数')
        self._idx_close = np.full(self._n, np.nan, dtype=float)
        self._idx_lo, self._idx_hi = self._idx_close, self._idx_close
        if index_df is None or getattr(index_df, 'empty', True) or self._n == 0 \
                or 'close' not in index_df.columns:
            return
        cols = ['date', 'close'] + [c for c in _INDEX_OHLC_NEED if c in index_df.columns]
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
        dvals = data['date'].to_numpy()
        fvals = pd.DatetimeIndex(self._dates).to_numpy()
        pos = np.searchsorted(dvals, fvals, side='left')
        inb = pos < len(dvals)
        ok = np.zeros(len(pos), dtype=bool)
        ok[inb] = dvals[pos[inb]] == fvals[inb]
        okv = pos[ok]
        close = data['close'].to_numpy(dtype=float)
        self._idx_close[ok] = close[okv]
        has_ohlc = all(c in data.columns for c in _INDEX_OHLC_NEED)
        style = style if style in ('line', 'area', 'kline', 'ohlc') else 'line'
        if style in ('kline', 'ohlc') and not has_ohlc:
            style = 'line'
        xs = np.arange(self._n, dtype=float)
        if style in ('kline', 'ohlc'):
            highs = data['high'].to_numpy(dtype=float)
            lows = data['low'].to_numpy(dtype=float)
            opens = data['open'].to_numpy(dtype=float)
            lo = np.full(self._n, np.nan, dtype=float)
            hi = np.full(self._n, np.nan, dtype=float)
            lo[ok] = lows[okv]
            hi[ok] = highs[okv]
            self._idx_lo, self._idx_hi = lo, hi
            k_data = [(float(i), float(opens[p]), float(close[p]), float(lows[p]), float(highs[p]))
                      for i, p in zip(xs[ok], okv)]
            pane.plot_item.addItem(CandlestickItem(k_data) if style == 'kline'
                                   else OhlcBarItem(k_data))
        elif style == 'area':
            item = pg.PlotDataItem(xs, self._idx_close, pen=pg.mkPen(_INDEX_COLOR, width=1.3),
                                   connect='finite')
            floor = (float(np.nanmin(self._idx_close))
                     if np.isfinite(self._idx_close).any() else 0.0)
            item.setFillLevel(floor)
            item.setBrush(pg.mkBrush(91, 100, 114, 40))
            pane.plot_item.addItem(item)
        else:
            pane.plot_item.addItem(pg.PlotDataItem(
                xs, self._idx_close, pen=pg.mkPen(_INDEX_COLOR, width=1.3), connect='finite'))

    def _attach_axes(self) -> None:
        """刻度挂最下窗格；**逐行**纵轴跟随可视 bar 区间（各自量纲、互不干扰）。"""
        if not self._rows:
            return
        providers = {}

        def _make(i, row):
            def _provider(i0: int, i1: int):
                seg = row['values'][i0:i1 + 1]
                if seg.size == 0 or not np.isfinite(seg).any():
                    return None
                top = float(np.nanmax(seg)) * RANGE_PAD + 1.0
                return (0.0, top)
            return _provider

        for i, row in enumerate(self._rows):
            providers[self._pane_name(i)] = _make(i, row)
        providers['index'] = lambda i0, i1: slice_span(self._idx_lo, self._idx_hi, i0, i1)
        attach_all(self._host, list(self._dates), providers)

    # ==========================================
    # 读数：**统一一处**（悬停任一行 ⇒ 显示那天**所有行**的值）
    # ==========================================
    def _bar_at(self, x: float) -> int:
        if self._n == 0:
            return -1
        return int(min(max(int(round(x)), 0), self._n - 1))

    def _readout(self, _pane_name: str, x: float, _y: float) -> str:
        i = self._bar_at(x)
        if i < 0 or self._dates is None:
            return ''
        day = pd.Timestamp(self._dates[i]).date()
        ratio = self._bar_mode == BAR_MODE_RATIO
        parts = []
        for k, row in enumerate(self._rows):
            mark = '①②③④⑤⑥⑦⑧⑨'[k] if k < 9 else f'{k + 1}'
            if ratio:
                seg = f'{row["values"][i]:.1f}%'
            else:
                hits = int(round(row['values'][i]))
                seg = f'{hits} 只'
                if row['valid'][i] > 0:
                    seg += f'（{hits / row["valid"][i] * 100:.1f}%）'
            parts.append(f'{mark}{row["label"]} {seg}')
        idx = (f' · {self._index_label} {self._idx_close[i]:,.2f}'
               if len(self._idx_close) > i and np.isfinite(self._idx_close[i]) else '')
        return f'{day} · ' + ' · '.join(parts) + idx

    # ---------- 供断言 / 页面读现状 ----------
    def row_keys(self) -> list[str]:
        return [r['key'] for r in self._rows]

    def pane_names(self) -> list[str]:
        return self._host.pane_names

    def focus_stretch(self) -> int:
        """当前主行（第 0 行）的相对高度权重（= `FOCUS_STRETCH` 表示焦点模式生效）。"""
        return self._host.pane_stretch(self._pane_name(0))
