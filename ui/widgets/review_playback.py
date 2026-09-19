# ui/widgets/review_playback.py
"""复盘页的**交易回放渲染**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。

【职责】把一笔交易画成"K 线 + 开/平锚点 + 盈亏高亮带"：
  · 双点区间锚定（完整闭环：开仓时刻 + 开/平价齐全）；
  · 单点锚定降级（孤儿单 / 老数据缺开仓信息）；
  · 数据缺口诚实提示（无本地行情 / 断层过大时不硬凑坐标，自动跳回累计盈亏）。

【为什么单独成文件】它体量大、且是复盘页里唯一"要读数据湖"的渲染路径 ——
  单独成文件让 `review_charts.py` 保持"只画当前 df"的纯渲染职责（§9-L 拆分）。

【设计约定】**状态全部留在页面**：`playback_chart` / `review_chart_tabs` / `data_lake`
  都是 `ReviewView` 的属性；`_format_leg_time` / `_display_time` 是页面薄壳（→ review_editor）。
"""
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt

from config import settings
from core.indicators import TAEngine
from core.utils import (extract_root_symbol, format_points, format_price,
                        format_trade_time, record_net_amount, row_points)
from ui.widgets.adaptive_axis import attach_date_axis, slice_span
from ui.widgets.custom_widgets import CandlestickItem

# 交易回放上下文窗口 (交易时间前后各多少天) 与可容忍的锚点误差
PLAYBACK_CONTEXT_DAYS = 45
MAX_ANCHOR_GAP_DAYS = 7


class ReviewPlayback:
    """复盘页交易回放渲染（页面持状态，本类只画）。"""

    def __init__(self, page):
        self.page = page

    @staticmethod
    def _nearest_bar_index(df_slice: pd.DataFrame, anchor_ts) -> int:
        """返回切片内距离目标时间最近的一根 K 线位置索引"""
        return int((df_slice['date'] - anchor_ts).abs().idxmin())

    def _render_trade_playback(self, record):
        """
        v1.2 交易回放：双点区间锚定（完整闭环）/ 单点锚定降级。

        【完整闭环】(entry_time + entry_price + exit_price 齐全)：
          以开仓日与平仓日两根 K 线为双锚点，渲染：
            1. 开/平两条垂直虚线（蓝 / 橙）
            2. 开/平两条价格水平点线（蓝 / 橙）
            3. 两锚点之间半透明高亮带（绿 = 盈利、红 = 亏损）
            4. 平仓锚点叠加「多空箭头 + 点数 + 盈亏」标注

        【降级】(孤儿单 / v1.1 老数据缺少开仓信息)：
          诚实退回单点锚定，标题橙色标注"开仓信息缺失"，
          若存在平仓价则仍画一条平仓价水平线作为参考。

        数据缺口过大时明确给出提示，绝不硬凑坐标。
        """
        p = self.page
        p.playback_chart.clear()
        symbol = str(record['symbol'])
        trade_time = pd.to_datetime(record['trade_time'])

        # 【数据防御】无有效交易时间则无法锚定，给出提示而不是渲染空图
        if pd.isna(trade_time):
            p.playback_chart.setTitle("⚠️ 该记录缺少交易时间，无法回放。",
                                      color="#FF9800", size="11pt")
            p.review_chart_tabs.setCurrentIndex(0)
            return

        is_orphan = int(record.get('is_orphan', 0) or 0) == 1
        entry_raw = record.get('entry_time')
        entry_time = pd.to_datetime(entry_raw) if (entry_raw is not None and pd.notna(entry_raw)) else None
        entry_price = record.get('entry_price')
        exit_price = record.get('exit_price')

        # 双点模式判定：非孤儿 + 真实开仓时刻 + 开/平仓价均有效
        def _valid_price(v):
            return v is not None and not pd.isna(v) and float(v) > 0

        dual = (not is_orphan and entry_time is not None and not pd.isna(entry_time)
                and _valid_price(entry_price) and _valid_price(exit_price))

        # ---- 数据窗口：包住开/平两个时间点并各自外扩上下文 ----
        ts_min, ts_max = trade_time, trade_time
        if dual:
            ts_min = min(entry_time, trade_time)
            ts_max = max(entry_time, trade_time)

        # 提取真实标的主体去数据湖寻址 (品种主体 RB -> 完整合约 RB2410)
        root_sym = extract_root_symbol(symbol)
        df_k = pd.DataFrame()
        for candidate in dict.fromkeys((root_sym, symbol)):
            if not candidate:
                continue
            # 【性能要点】先用轻量探针判断，避免为不存在的文件读取整个 Parquet
            if p.data_lake.exists("kline_daily", candidate):
                df_k = p.data_lake.load_data("kline_daily", candidate)
            if not df_k.empty:
                break

        if df_k.empty:
            p.playback_chart.setTitle(
                f"⚠️ 缺乏 {symbol} 的本地行情，请先前往 [市场行情] 页面进行云端同步！",
                color="#FF9800", size="11pt")
            # 自动跳回累积盈亏，防止用户盯着空图看
            p.review_chart_tabs.setCurrentIndex(0)
            return

        df_k['date'] = pd.to_datetime(df_k['date'])
        start_cut = ts_min - pd.Timedelta(days=PLAYBACK_CONTEXT_DAYS)
        end_cut = ts_max + pd.Timedelta(days=PLAYBACK_CONTEXT_DAYS)
        df_slice = df_k[(df_k['date'] >= start_cut) & (df_k['date'] <= end_cut)].copy()

        if df_slice.empty:
            p.playback_chart.setTitle(
                f"⚠️ {symbol} 缺少 {format_trade_time(ts_min)} 附近 {PLAYBACK_CONTEXT_DAYS} 天的K线数据，请先同步。",
                color="#FF9800", size="11pt")
            p.review_chart_tabs.setCurrentIndex(0)
            return

        df_slice = df_slice.reset_index(drop=True)

        # ---- 锚点定位（开仓日 / 平仓日最近 K 线）----
        exit_idx = self._nearest_bar_index(df_slice, trade_time)
        entry_idx = self._nearest_bar_index(df_slice, entry_time) if dual else None

        def _gap(ts, idx):
            return abs((df_slice['date'].iloc[idx] - ts).days)

        worst_gap = _gap(trade_time, exit_idx)
        if dual:
            worst_gap = max(worst_gap, _gap(entry_time, entry_idx))

        # 【诚实原则】任一时间点与最近 K 线距离过远 (节假日/停牌/数据断层) 时不硬凑坐标
        if worst_gap > MAX_ANCHOR_GAP_DAYS:
            p.playback_chart.setTitle(
                f"⚠️ {symbol} 本地数据距该交易日已达 {worst_gap} 天，无法可靠回放。\n"
                f"请核对交易日期或先前往 [市场行情] 补充同步。",
                color="#FF9800", size="11pt")
            p.review_chart_tabs.setCurrentIndex(0)
            return

        # ---- 基础图层：K 线 + MA20 ----
        df_slice = TAEngine.add_ma(df_slice, windows=(20,))
        x_data = list(range(len(df_slice)))
        k_data = [(i, row['open'], row['close'], row['low'], row['high'])
                  for i, row in df_slice.iterrows()]
        p.playback_chart.addItem(CandlestickItem(k_data))
        p.playback_chart.plot(x_data, df_slice['MA_20'],
                              pen=pg.mkPen(color='#FF9800', width=1.5,
                                           style=Qt.PenStyle.DashLine))

        is_long = record['direction'] == 'LONG'
        # 【v6.9 · §9-P1 收尾】回放标记色与高亮带方向同样按**净额**判定（真实到手），
        # 否则"毛利为正、手续费吃掉"的单子会被画成绿色盈利区间。
        pnl = record_net_amount(record)
        marker_color = settings.COLOR_PROFIT if pnl >= 0 else settings.COLOR_LOSS

        if dual:
            # ================= 双点区间锚定 =================
            lo_x, hi_x = min(entry_idx, exit_idx), max(entry_idx, exit_idx)
            e_p = float(entry_price)
            x_p = float(exit_price)
            lo_y, hi_y = min(e_p, x_p), max(e_p, x_p)

            # 开~平区间高亮带（盈绿 / 亏红）
            brush_rgb = settings.RGB_PROFIT if pnl >= 0 else settings.RGB_LOSS
            region = pg.LinearRegionItem(
                values=[lo_x, hi_x], orientation='vertical',
                brush=pg.mkBrush(*brush_rgb, 30), pen=None, movable=False)
            region.setZValue(-100)
            p.playback_chart.addItem(region)

            # 垂直虚线：开仓(蓝) / 平仓(橙)
            p.playback_chart.addLine(x=entry_idx,
                                     pen=pg.mkPen(color='#1E88E5', width=1.4,
                                                  style=Qt.PenStyle.DashLine))
            p.playback_chart.addLine(x=exit_idx,
                                     pen=pg.mkPen(color='#FB8C00', width=1.4,
                                                  style=Qt.PenStyle.DashLine))
            # 水平价格线：开仓价(蓝) / 平仓价(橙)
            p.playback_chart.addLine(y=e_p,
                                     pen=pg.mkPen(color='#1E88E5', width=1,
                                                  style=Qt.PenStyle.DotLine))
            p.playback_chart.addLine(y=x_p,
                                     pen=pg.mkPen(color='#FB8C00', width=1,
                                                  style=Qt.PenStyle.DotLine))

            # 价格图例（右缘顶部）
            price_legend = pg.TextItem(
                f"开 {format_price(entry_price)}   平 {format_price(exit_price)}",
                color='#455A64', anchor=(1, 0))
            price_legend.setPos(len(df_slice) - 1, hi_y)
            p.playback_chart.addItem(price_legend)

            p.playback_chart.setTitle(
                f"🎯 {symbol} | 开仓 {p._format_leg_time(entry_time)} → 平仓 {p._display_time(record)}",
                color="#1976D2", size="12pt", bold=True)

            # 平仓锚点：方向箭头 + 点数 + 盈亏
            bar = df_slice.loc[exit_idx]
            anchor_y = bar['low'] * 0.97 if is_long else bar['high'] * 1.03
            marker = pg.ScatterPlotItem(
                x=[exit_idx], y=[anchor_y],
                symbol='t' if is_long else 'd', size=18,
                brush=pg.mkBrush(marker_color), pen='w')
            p.playback_chart.addItem(marker)

            pts = row_points(record)
            pts_txt = format_points(pts) if pts is not None else "—"
            annotation = pg.TextItem(
                f"{'做多' if is_long else '做空'}   {pts_txt} 点   ￥{pnl:+,.0f}",
                color=marker_color, anchor=(0.5, 1.2))
            annotation.setPos(exit_idx, anchor_y)
            p.playback_chart.addItem(annotation)

            # 自动聚焦开平区间，跨度不足时保留可读上下文
            span = hi_x - lo_x
            pad = max(10, span + 15)
            x_lo = max(0, lo_x - pad)
            x_hi = min(len(df_slice) - 1, hi_x + pad)
            p.playback_chart.setXRange(x_lo, x_hi, padding=0.05)
        else:
            # ================= 单点锚定（降级） =================
            p.playback_chart.addLine(x=exit_idx,
                                     pen=pg.mkPen(color='#90A4AE', width=1,
                                                  style=Qt.PenStyle.DashLine))
            title_txt = (f"🎯 {symbol} | 交易 {p._display_time(record)} "
                         f"(就近K线 {format_trade_time(df_slice['date'].iloc[exit_idx])})")
            degraded = is_orphan or not _valid_price(entry_price)
            p.playback_chart.setTitle(
                title_txt + ("　⚠️ 开仓信息缺失，单点回放" if degraded else ""),
                color="#F57C00" if degraded else "#1976D2", size="12pt", bold=True)

            bar = df_slice.loc[exit_idx]
            anchor_y = bar['low'] * 0.97 if is_long else bar['high'] * 1.03

            # 平仓价水平线参考（若有）
            if _valid_price(exit_price):
                p.playback_chart.addLine(
                    y=float(exit_price), pen=pg.mkPen(color='#FB8C00', width=1,
                                                      style=Qt.PenStyle.DotLine))

            marker = pg.ScatterPlotItem(
                x=[exit_idx], y=[anchor_y],
                symbol='t' if is_long else 'd', size=18,
                brush=pg.mkBrush(marker_color), pen='w')
            p.playback_chart.addItem(marker)

            note = "  ￥{:+,.0f}".format(pnl)
            if is_orphan:
                note = "  (待缝合) ￥{:+,.0f}".format(pnl)
            annotation = pg.TextItem(
                f"{'做多' if is_long else '做空'}{note}",
                color=marker_color, anchor=(0.5, 1.2))
            annotation.setPos(exit_idx, anchor_y)
            p.playback_chart.addItem(annotation)

            # 自动聚焦锚点附近窗口
            half = min(30, len(df_slice) // 2)
            lo = max(0, exit_idx - half)
            hi = min(len(df_slice) - 1, exit_idx + half)
            p.playback_chart.setXRange(lo, hi, padding=0.05)

        # ---- 自适应坐标轴（§7-B4）：y 跟随**可视区间** + 日期刻度随缩放重算 ----
        # 入场/出场价参考线仍参与 y 范围（否则会被画在图外），但极值只在可视窗口内取 ——
        # 放大到某几根 K 线时，不再被"整段回溯区间"的极值压成一条线（这正是用户报的毛病）。
        pb_low = df_slice['low'].to_numpy(dtype=float)
        pb_high = df_slice['high'].to_numpy(dtype=float)
        refs = [float(v) for v in (entry_price, exit_price) if _valid_price(v)]
        if refs:
            pb_low = np.fmin(pb_low, min(refs))
            pb_high = np.fmax(pb_high, max(refs))
        attach_date_axis(
            p.playback_chart, df_slice['date'],
            y_provider=(lambda i0, i1, _lo=pb_low, _hi=pb_high:
                        slice_span(_lo, _hi, i0, i1)))

        # 【交互体验】点击交易单即自动切到回放页
        p.review_chart_tabs.setCurrentWidget(p.playback_chart)
