# ui/widgets/desk_readout.py
"""读数条的业务翻译（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 5/6）。

【职责】把"一根行情"翻译成读数条上那行文字：日期 / 开 / 高 / 低 / 收 / 量 / MA5 / MA20。

【为什么由页面给、宿主不猜】`ChartHost` 只转交 `(窗格, x, y)` —— 它不知道也不该知道
"这一页读的是 OHLC 还是某个指标"；业务口径归页面（§10-3 / §10-4）。

【诚实原则】读数只认**本次真正渲染的那一份 df**（页面在 `render_charts` 里存进
`_rendered_df`），绝不现场重算一份 —— 否则悬停读到的可能是另一套数据。

【约定】状态留页面（`_rendered_df`、`current_period`、`host`），本模块只做翻译。
"""
from core.utils import is_minute_period


class DeskReadout:
    """读数条文案（常驻摘要 + 悬停翻译）。"""

    def __init__(self, page):
        self.page = page

    @staticmethod
    def _readout_text_for_row(row, stamp_fmt: str, prev_close=None) -> str:
        """把一行行情翻译成读数条文案（**唯一格式来源**，悬停与常驻共用）。

        ★v6.23：补两项**纯数据事实**，专治"这图是不是画错了"的困惑（用户 2026-09-17 反馈）：
          · **涨跌幅**（相对前一根收盘；第一根没有前收就不显示）；
          · **一字**标签 —— 当日最高 == 最低（无振幅）。常见于涨停/跌停一字板，
            也可能是全天只有一个价位成交；配合前面的涨跌幅，一眼就能判断是哪种。
        ⚠ 只标"数据说得清的事实"：不猜涨跌停规则（主板 10% / 创业板 20% / ST 5% 各不相同，
        按规则推会给出会骗人的标签）。
        """
        parts = [row['date'].strftime(stamp_fmt),
                 f"开 {float(row['open']):.2f}", f"高 {float(row['high']):.2f}",
                 f"低 {float(row['low']):.2f}", f"收 {float(row['close']):.2f}"]
        volume = row.get('volume', None)
        if volume is not None and volume == volume:      # 非 NaN
            parts.append(f"量 {float(volume):,.0f}")
        try:
            if prev_close is not None and float(prev_close) > 0:
                change = float(row['close']) / float(prev_close) - 1.0
                parts.append(f"{change:+.2%}")
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        try:
            if float(row['high']) == float(row['low']):
                parts.append("一字")
        except (TypeError, ValueError, KeyError):
            pass
        for column in ("MA_5", "MA_20"):                 # 与 TAEngine.add_ma 的列名同源
            value = row.get(column, None)
            if value is not None and value == value:
                parts.append(f"{column.replace('MA_', 'MA')} {float(value):.2f}")
        return "  ".join(parts)

    def _readout_stamp_fmt(self) -> str:
        return ('%Y-%m-%d %H:%M'
                if is_minute_period(self.page.current_period) else '%Y-%m-%d')

    def _readout_for_pane(self, pane_name: str, x: float, y: float) -> str:
        """读数条 provider（宿主只转交 `(窗格, x, y)`，业务翻译在本模块）。

        只给**主图**业务读数：副图（量/MACD/公式）的 y 含义各不相同，
        由宿主的内置文案（窗格名 + X + Y）交代更诚实。
        """
        p = self.page
        if str(pane_name) != 'main':
            return ""
        df = getattr(p, "_rendered_df", None)
        if df is None or len(df) == 0 or "date" not in df.columns:
            return ""
        try:
            index = int(round(float(x)))
        except (TypeError, ValueError):
            return ""
        if index < 0 or index >= len(df):
            return ""
        prev_close = df.iloc[index - 1]['close'] if index > 0 else None
        return self._readout_text_for_row(df.iloc[index], self._readout_stamp_fmt(),
                                          prev_close=prev_close)

    def _refresh_readout_default(self) -> None:
        """常驻读数 = 最新一根（用户不悬停时也有东西可看）。"""
        p = self.page
        df = getattr(p, "_rendered_df", None)
        if df is None or len(df) == 0 or "date" not in df.columns:
            p.host.set_readout_text("")
            return
        prev_close = df.iloc[-2]['close'] if len(df) > 1 else None
        p.host.set_readout_text(
            self._readout_text_for_row(df.iloc[-1], self._readout_stamp_fmt(),
                                       prev_close=prev_close))
