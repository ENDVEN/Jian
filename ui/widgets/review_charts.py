# ui/widgets/review_charts.py
"""复盘页的**图表渲染（日历 / 月度 / 持仓时长）**（1.25 自 `ui/views/review.py` 拆出 · §9-L）。

【职责】只负责"把 `page.current_view_df` 画成图"，不持任何业务状态：
  · 日历热力图（当月每日净额着色 + 📝 复盘标记）；
  · 月度图表（累计盈亏净值曲线 + 按日聚合成 K 线的资金曲线）；
  · 持仓时长分布（精确计时按对数分钟 / 仅日期按交易日计数）。

【交易回放（K 线双点锚定）已在 `ui/widgets/review_playback.py`】—— 它体量大、依赖数据湖，
  单独成文件（§9-L 拆分：任一文件都回到 400 行内）。

【设计约定（与 desk_*.py 同源）】**状态全部留在页面** —— 当前视图 df、当前日期、
  日历/图表控件、交易日历缓存 `_trading_cal` 都归 `ReviewView`；本模块只读它们
  并把结果画回页面控件（`self.page.X`）。
"""
import calendar
import math

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QTableWidgetItem

from config import settings
from core.utils import (extract_root_symbol, format_duration,
                        record_entry_has_clock, record_holding_seconds,
                        trading_day_count)
from ui.widgets.adaptive_axis import attach_date_axis, slice_span
from ui.widgets.chart_style import plot_equity_curve
from ui.widgets.custom_widgets import CandlestickItem


class ReviewCharts:
    """复盘页图表渲染（页面持状态，本类只画）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 日历热力图
    # ==========================================
    def _render_calendar(self):
        p = self.page
        p.review_calendar.clearContents()
        y, m = p.current_review_date.year, p.current_review_date.month
        cal = calendar.monthcalendar(y, m)
        df = p.current_view_df.copy()
        daily_stats = {}
        max_abs_net = 0.0

        if not df.empty:
            # v1.2 净额口径：当日真实到手 = 平仓盈亏 − 手续费
            df['net_amount'] = df['net_profit'] - df['commission'].fillna(0)
            df['day'] = df['trade_time'].dt.day
            daily_sums = df.groupby('day')['net_amount'].sum()
            if not daily_sums.empty:
                max_abs_net = daily_sums.abs().max()
                if max_abs_net == 0:
                    max_abs_net = 1.0

            for day, group in df.groupby('day'):
                daily_stats[day] = {
                    'net': group['net_amount'].sum(),
                    'reviewed': any((pd.notna(group['reflection'])
                                     & (group['reflection'].str.strip() != '')))
                }

        for row, week in enumerate(cal):
            for col, day in enumerate(week):
                if day == 0:
                    continue
                item = QTableWidgetItem(str(day))

                if day in daily_stats:
                    net = daily_stats[day]['net']
                    intensity = 40 + int((abs(net) / max_abs_net) * 215)

                    if net > 0:
                        r, g, b = settings.RGB_PROFIT
                        bg_color = QColor(r, g, b, intensity)
                        text_color = QColor(settings.COLOR_PROFIT_TEXT)
                    elif net < 0:
                        r, g, b = settings.RGB_LOSS
                        bg_color = QColor(r, g, b, intensity)
                        text_color = QColor(settings.COLOR_LOSS_TEXT)
                    else:
                        bg_color = QColor("#F5F5F5")
                        text_color = QColor("#757575")

                    item.setBackground(bg_color)
                    item.setForeground(text_color)
                    item.setText(f"{day}\n{'+' if net>0 else ''}{net:,.0f}")

                    if daily_stats[day]['reviewed']:
                        item.setText(item.text() + "\n📝")
                else:
                    item.setForeground(QColor("#BDBDBD"))

                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                font = QFont()
                font.setBold(day in daily_stats)
                item.setFont(font)
                item.setData(Qt.ItemDataRole.UserRole, QDate(y, m, day))
                p.review_calendar.setItem(row, col, item)

    # ==========================================
    # 月度图表：净值曲线 + 资金 K 线
    # ==========================================
    def _render_monthly_charts(self):
        """月度复盘图表：累计盈亏净值曲线 + 按日聚合成K线的资金曲线。

        NOTE(v1.1): 原"时长分析"散点图依赖开/平仓双时间，交割单不再提供，已删除。
        """
        p = self.page
        p.review_pnl_chart.clear()
        p.review_kline_chart.clear()
        df = p.current_view_df.copy()
        if df.empty:
            return

        # v1.2 净额口径：净值曲线 / 资金 K线 均基于真实到手盈亏（扣手续费后）
        df_sorted = df.sort_values(by='trade_time').copy()
        df_sorted['net_amount'] = df_sorted['net_profit'] - df_sorted['commission'].fillna(0)
        equity_curve = [0.0] + df_sorted['net_amount'].cumsum().tolist()
        # 累计盈亏曲线：统一走 chart_style（v5.12 · §9-O7），基准线 0
        plot_equity_curve(p.review_pnl_chart, equity_curve, fill_base=0.0, width=2)

        # 资金 K 线：把同一天的多笔交易聚合成一根蜡烛 (当日权益的开高低收)
        df_sorted['day'] = df_sorted['trade_time'].dt.day
        k_data, day_labels = [], []
        current_equity = 0.0
        for i, (day, group) in enumerate(df_sorted.groupby('day')):
            open_eq = current_equity
            high_eq = current_equity
            low_eq = current_equity
            for pnl in group['net_amount']:
                current_equity += pnl
                high_eq = max(high_eq, current_equity)
                low_eq = min(low_eq, current_equity)
            k_data.append((i, open_eq, current_equity, low_eq, high_eq))
            day_labels.append(f"{day}日")

        if k_data:
            p.review_kline_chart.addItem(CandlestickItem(k_data))
            # 自适应坐标轴（§7-B4）：
            #  · 横轴 = "当月第几日"的**序数轴**（不是真日期）→ 走文本刻度，只求密度自适应
            #    （原来把当月每个交易日都写上，窄窗口必定互相压字）；
            #  · 纵轴跟随可视区间（蜡烛自身高低即数据源），放大后不再被全月极值压扁。
            lows = np.array([row[3] for row in k_data], dtype=float)
            highs = np.array([row[4] for row in k_data], dtype=float)
            attach_date_axis(
                p.review_kline_chart, texts=day_labels,
                y_provider=(lambda i0, i1, _lo=lows, _hi=highs:
                            slice_span(_lo, _hi, i0, i1)))

    # ==========================================
    # 交易日历（仅日期记录按"交易日"计数用，带缓存）
    # ==========================================
    def _trading_dates_for(self, symbol: str) -> list:
        """按需读取某品种主体的本地交易日历（带缓存），无本地数据返回空列表"""
        p = self.page
        root = extract_root_symbol(symbol)
        if root in p._trading_cal:
            return p._trading_cal[root]
        dates: list = []
        try:
            if p.data_lake.exists("kline_daily", root):
                df_k = p.data_lake.load_data("kline_daily", root)
                if not df_k.empty and 'date' in df_k.columns:
                    dates = list(pd.to_datetime(df_k['date']).dropna().unique())
        except Exception:
            dates = []
        p._trading_cal[root] = dates
        return dates

    # ==========================================
    # 持仓时长分布
    # ==========================================
    def _render_duration_analysis(self):
        """
        v1.3 持仓时长分析（v1.1 曾因无开仓时间而下线，数据补齐后重新引入）：
          - 开仓带时分的记录 → 精确计时，按"分钟(对数)"绘制分布直方图；
          - 开仓仅日期的记录 → 用本地交易日历按「交易日」计数（周末/节假日不虚增），
            本地无行情时回退自然日并如实标注；
          - 完全缺开仓时间 → 不参与统计，覆盖率始终明示。
        """
        p = self.page
        chart = p.review_duration_chart
        chart.clear()
        df = p.current_view_df.copy()
        if df.empty:
            chart.setTitle("⏱ 当前区间暂无数据", color="#9E9E9E", size="11pt")
            return

        exact_minutes: list[float] = []
        day_days: list[int] = []
        day_natural_fallback = 0
        unknown = 0
        total = len(df)

        for _, rec in df.iterrows():
            entry_raw = rec.get('entry_time')
            if entry_raw is None or pd.isna(entry_raw):
                unknown += 1
                continue
            if record_entry_has_clock(rec):
                secs = record_holding_seconds(rec)
                if secs is not None and secs >= 0:
                    exact_minutes.append(secs / 60.0)
            else:
                # 仅日期：交易日计数优先，日历不足回退自然日
                cal = self._trading_dates_for(str(rec.get('symbol', '')))
                days = trading_day_count(entry_raw, rec.get('trade_time'), cal) if cal else None
                if days is None:
                    try:
                        a = pd.to_datetime(entry_raw).date()
                        b = pd.to_datetime(rec.get('trade_time')).date()
                        days = max(0, (b - a).days + 1)
                        day_natural_fallback += 1
                    except Exception:
                        # 【v5.12 修正 · §9-O8】旧代码在此把 0 天计入均值，
                        # 与"算不出来就不参与统计"的设计自相矛盾（会系统性拉低均值）。
                        # 算不出来就如实跳过，绝不拿 0 冒充。
                        continue
                day_days.append(days)

        covered = len(exact_minutes)
        if not exact_minutes and not day_days:
            chart.setTitle(f"⏱ 无可计时持仓（{total} 笔均缺开仓时间）",
                           color="#FF9800", size="11pt")
            return

        # 概要（覆盖率 / 中位 / 仅日期交易日口径）
        summary = []
        if exact_minutes:
            median_min = float(np.median(exact_minutes))
            summary.append(f"精确 {covered} 笔 · 中位 {format_duration(median_min * 60)}")
        if day_days:
            mean_day = float(np.mean(day_days))
            label = f"仅日期 {len(day_days)} 笔 · 平均跨 {mean_day:.1f} 个交易日"
            if day_natural_fallback:
                label += "（其中部分因本地无行情按自然日计）"
            summary.append(label)
        if unknown:
            summary.append(f"无开仓时间 {unknown} 笔")
        chart.setTitle("⏱ " + " | ".join(summary), color="#1976D2", size="11pt")

        if exact_minutes:
            log_mins = [math.log10(max(m, 0.2)) for m in exact_minutes]
            hi = max(math.log10(max(exact_minutes) * 1.05), math.log10(0.2))
            bins = np.linspace(math.log10(0.2), hi, 16)
            hist, edges = np.histogram(log_mins, bins=bins)
            x_vals, y_vals = [], []
            for i in range(len(edges) - 1):
                x_vals += [edges[i], edges[i + 1]]
                y_vals += [hist[i], hist[i]]
            chart.plot(x_vals, y_vals, pen=pg.mkPen(color='#1976D2', width=2),
                       fillLevel=0, fillBrush=pg.mkBrush((25, 118, 210, 90)))
            chart.getAxis('left').setLabel('笔数')
            chart.getAxis('bottom').setLabel('持仓时长（对数分钟）')

            # 平均线参考
            avg_min = float(np.mean(exact_minutes))
            chart.addLine(x=math.log10(max(avg_min, 0.2)),
                          pen=pg.mkPen(color='#FB8C00', width=1.5,
                                       style=Qt.PenStyle.DashLine))

            # 可读时间刻度
            refs = [(0.5, "30秒"), (1, "1分"), (5, "5分"), (15, "15分"),
                    (60, "1小时"), (240, "4小时"), (1440, "1天"), (10080, "7天")]
            ticks = [[(math.log10(v), label) for v, label in refs
                      if math.log10(v) <= hi]]
            chart.getAxis('bottom').setTicks(ticks)
