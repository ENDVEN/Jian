# ui/widgets/desk_layers.py
"""行情工作台的"渲染装配"：显示用行情 + 统一图层 + 自适应坐标轴（1.23 自 `ui/views/trading_desk.py` 拆出 · §7-B6 STEP 6）。

【职责】`render_charts` 是页面**唯一**的落笔入口（幂等，可安全重复调用）：
  ① `prepared_df`：按周期聚合 → 按开关算指标（顺序不能反，见其 docstring）；
  ② 内置指标 + 用户公式**都翻成 DrawData**，窗格全部就位后一次落笔（全 app 唯一渲染器 §10-11）；
  ③ 副图按需创建（量 / MACD / 公式副图 1-3），公式副图可被工具行 chip 单独隐藏；
  ④ 坐标轴量程交给 `adaptive_axis`，本页只回答"每个窗格在可视区间内的数值范围"。

【为什么 `SUB_PLOT_HEIGHT` 定义在这里】它是**图层布局**的常量（附图统一高度），
随渲染一起搬走；`ui/views/trading_desk.py` 里保留了同名 re-export，
既有 `from ui.views.trading_desk import SUB_PLOT_HEIGHT` 的用法零改动（§11.7）。

【约定】状态留页面（`host` / `main_plot` / `_axes` / `_layer_*` / `formula_plots` /
`current_df` / `current_period` / `current_adjust` / `current_name` / `_rendered_df`），
本模块只承载行为。
"""
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt

from core.indicators import TAEngine
from core.utils import (is_minute_period, parse_params_text, period_label,
                        resample_ohlcv)
from core.formula.program import (FormulaProgramError,
                                  execute_programs_with_draws_grouped)
from data.sync_service import adjust_label
from ui.widgets.adaptive_axis import slice_span
from ui.widgets.chart_layers import (builtin_indicator_layers, layer_value_range)
from ui.widgets.chart_pane import ChartPane
from ui.widgets.custom_widgets import CandlestickItem
from ui.widgets.draw_overlay import OverlayPainter, overlay_extent
from ui.widgets.indicator_panes import fill_macd_pane, fill_volume_pane

# 附图（成交量 / MACD / 公式副图）统一高度
SUB_PLOT_HEIGHT = 150
# 默认可视 K 线根数，超出后只展示最近一段
DEFAULT_VISIBLE_BARS = 150


class DeskLayers:
    """显示用行情 + 渲染 + 坐标轴 provider（页面持状态，本类持行为）。"""

    def __init__(self, page):
        self.page = page

    # ==========================================
    # 显示用行情
    # ==========================================
    def prepared_df(self):
        """当前**显示用**的行情：按周期重采样 + 按开关计算指标。

        ⚠ 顺序不能反：先在周线上聚合出 OHLC，再算 MA —— 否则算出来的是"日线 MA 被抽样"，
        与通达信的"5 周均线"不是一回事。
        """
        p = self.page
        if p.current_df is None or len(p.current_df) == 0:
            return pd.DataFrame()
        df = resample_ohlcv(p.current_df, p.current_period)
        if df.empty:
            return df
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date']).sort_values('date').reset_index(drop=True)
        if df.empty:
            return df
        selected = [key for key, checkbox in
                    (('ma', p.cb_ma), ('boll', p.cb_boll), ('macd', p.cb_macd))
                    if checkbox.isChecked()]
        return TAEngine.apply(df, selected)

    # ==========================================
    # 渲染（幂等，可安全重复调用）
    # ==========================================
    def render_charts(self):
        p = self.page
        p.host.clear_sub_panes()
        p.formula_plots = {}
        p._layer_builtin = []
        p._layer_formula = {}
        p._layer_items = []
        p.host.clear_pane_content('main')    # 保留窗格与十字光标，只清内容
        if p._annotations is not None:
            # 只清"画在图上的标注"，**不动存储** —— 本函数末尾会按当前周期读回来重画
            p._annotations.clear_view()

        df = self.prepared_df()
        # ★STEP 5：读数条的 provider 只认"**本次真正渲染的那一份**"（不用 prepared_df 现算，
        # 否则悬停读数与图上的 K 线可能不是同一份数据 —— §10-4 诚实原则）
        p._rendered_df = df
        if df.empty:
            p.main_plot.setTitle(
                "<span style='color:#8A94A6; font-size:13px;'>"
                "输入代码后点「🔍 查阅」，或双击左侧自选股开始</span>")
            p._refresh_annotation_status()
            p._refresh_chips()      # 没数据也把 chips 对齐（公式副图候选缩回只有量/MACD）
            p._refresh_readout_default()
            return

        x_data = list(range(len(df)))
        p.main_plot.setTitle(self._title_text(df))
        p.main_plot.addItem(CandlestickItem(
            [(i, row['open'], row['close'], row['low'], row['high'])
             for i, row in df.iterrows()]))

        # ---- 统一图层：内置指标与用户公式**都翻成 DrawData**，窗格全部就位后一次落笔 ----
        p._layer_builtin = builtin_indicator_layers(
            df, ma=p.cb_ma.isChecked(), boll=p.cb_boll.isChecked())
        p._layer_formula = self._formula_layers(df)
        p._layer_bars = len(df)
        p._report_formula_status(df)

        if p.cb_vol.isChecked():
            vol_pane = p.host.add_pane('vol', fixed_height=SUB_PLOT_HEIGHT)
            p._apply_pokorny_axis(vol_pane.plot_item)
            fill_volume_pane(vol_pane.plot_item, df, x_data)

        if p.cb_macd.isChecked():
            macd_pane = p.host.add_pane('macd', fixed_height=SUB_PLOT_HEIGHT)
            p._apply_pokorny_axis(macd_pane.plot_item)
            fill_macd_pane(macd_pane.plot_item, df, x_data)

        # ---- 公式副图（v6.8：每段可选 副图 1/2/3，按需创建）----
        if p.cb_formula.isChecked():
            for target in sorted(p._layer_formula):
                if target == 'main' or not p._layer_formula[target]:
                    continue
                # ★STEP 3c：工具行"公式副图 N"chip 可以让某一格单独不显示
                # （函数段本身还留着 —— 关的是**这一格的显示**，不是把用户的函数删掉）
                if not p._sub_visible.get(target, True):
                    continue
                pane = p.host.add_pane(target, fixed_height=SUB_PLOT_HEIGHT)
                p._apply_pokorny_axis(pane.plot_item)
                span = layer_value_range(p._layer_formula[target])
                if span and span[0] <= 0 <= span[1]:
                    # 穿越 0 的振荡型指标给一条零轴参考线（不穿越就不画，免得误导）
                    pane.plot_item.addLine(
                        y=0, pen=pg.mkPen(color='#BDBDBD', style=Qt.PenStyle.DashLine))
                p.formula_plots[target] = pane.plot_item

        self._paint_layers()

        if len(df) > DEFAULT_VISIBLE_BARS:
            p.main_plot.getViewBox().setXRange(len(df) - DEFAULT_VISIBLE_BARS, len(df))

        # ---- 自适应坐标轴（§7-B4）：横轴刻度随可视区间重算 + 每个窗格 y 跟随可视区间 ----
        # ⚠ 必须放在 setXRange **之后**：attach 内部会按当前的 x 区间算一次刻度与量程
        p._axes.attach(df['date'], self._adaptive_providers(df))

        # 【P6】K 线 + 可视窗口就位后再恢复标注；**按 (标的, 周期) 取**，日线画线不串到周线
        p._annotations.bind(p.current_symbol, df['date'], period=p.current_period)
        p._refresh_annotation_status()
        p._refresh_adjust_hint()
        # ★STEP 3c：渲染完顺手把工具行 chips 对齐（"公式副图 N"的候选取决于本次有哪些段）
        p._refresh_chips()
        # ★STEP 5：不悬停时读数条显示**最新一根**（常驻摘要，不移动十字光标）
        p._refresh_readout_default()

    # ==========================================
    # 统一图层（v6.6 · §7-B3 P4）
    # ==========================================
    def _formula_layers(self, df) -> dict:
        """按目标窗格分组求值。**失败不打断整页渲染**，只把原因写进面板状态。

        ⚠ 各段共用**同一个变量池**（后段引用前段变量）—— 所以引擎**只求值一次**，
        再按段归位（`execute_programs_with_draws_grouped`）。
        """
        p = self.page
        targets: dict = {}
        if not p._formula_programs:
            if p._formula_error:
                p._set_formula_status(False, f"❌ {p._formula_error}")
            return targets
        params = parse_params_text(p._formula_params_text)
        try:
            _variables, groups = execute_programs_with_draws_grouped(
                p._formula_programs, df, params)
        except FormulaProgramError as e:
            p._set_formula_status(False, f"❌ 执行失败: {e}")
            return targets
        for (_text, target), draws in zip(p._formula_segments, groups):
            targets.setdefault(target, []).extend(draws)
        return targets

    def _paint_layers(self):
        """把「内置指标 + 用户公式」画到各自窗格 —— 全 app 唯一渲染器（§10-11）。

        两者在渲染层**没有任何区别**（都是 DrawData → OverlayPainter），
        这正是 §7-B3 D4「像 MA 一样显示用户函数」的架构事实。
        """
        p = self.page
        x = np.arange(p._layer_bars)
        items: list = []

        main_pane = p.host.main_pane
        main_pane.clear_overlays()
        OverlayPainter(main_pane, x).render(p._layer_builtin)
        if p.cb_formula.isChecked():
            OverlayPainter(main_pane, x).render(p._layer_formula.get('main', []))
        items += main_pane.overlay_items

        if p.cb_formula.isChecked():
            for target, plot_item in p.formula_plots.items():
                pane = ChartPane.wrap(plot_item, name=target, role='sub')
                pane.clear_overlays()
                OverlayPainter(pane, x).render(p._layer_formula.get(target, []))
                items += pane.overlay_items

        p._layer_items = items

    # ==========================================
    # 标题 + 自适应坐标轴 provider（§7-B4）
    # ==========================================
    def _title_text(self, df) -> str:
        p = self.page
        # 分钟数据的时间戳到分钟 ⇒ 标题也要显示到分钟（否则"截至 2026-09-16"看不出是哪一根）
        minute_mode = is_minute_period(p.current_period)
        stamp_fmt = '%Y-%m-%d %H:%M' if minute_mode else '%Y-%m-%d'
        end_date = df['date'].iloc[-1].strftime(stamp_fmt)
        caliber = "真实价(分钟)" if minute_mode else adjust_label(p.current_adjust)
        display_name = p.current_name or p.current_symbol
        return (f"<span style='color:#212121; font-size:16px; font-weight:bold;'>"
                f"{display_name} ({p.current_symbol})</span> "
                f"<span style='color:#757575; font-size:12px;'> "
                f"{period_label(p.current_period)} · {caliber}"
                f" | 共 {len(df)} 根 | 截至 {end_date}</span>")

    def _adaptive_providers(self, df) -> dict:
        """逐窗格回答"**可视 bar 区间内**的 (最低, 最高)" —— 其余全归 `adaptive_axis`。

        为什么必须由页面给：每个窗格的数据形状不同，公共件不该猜业务：
          · 主图 = K 线高低 ∪ **叠层极值**（公式线/状态柱可能跑出 K 线范围，不并进来会被裁掉）；
          · 量柱以 **0 为基线**（否则柱底会浮在"可视最低量"上，视觉上说谎）；
          · MACD 必须**含 0**（零轴是它的读数基准，丢了就看不出一根柱子是正是负）；
          · 公式副图 = 该段叠层自身的极值。
        范围一律裁到可视窗口，NaN（指标预热区 / 该 bar 无叠层）由 `slice_span` 自动忽略。
        """
        p = self.page
        n = len(df)
        providers: dict = {}

        high = df['high'].to_numpy(dtype=float)
        low = df['low'].to_numpy(dtype=float)
        main_draws = list(p._layer_builtin)
        if p.cb_formula.isChecked():
            main_draws += p._layer_formula.get('main', [])
        overlay_lo, overlay_hi = overlay_extent(main_draws, n)
        providers['main'] = (lambda i0, i1, _lo=np.fmin(low, overlay_lo),
                             _hi=np.fmax(high, overlay_hi): slice_span(_lo, _hi, i0, i1))

        if p.cb_vol.isChecked():
            volume = df['volume'].to_numpy(dtype=float)
            baseline = np.zeros(n, dtype=float)
            providers['vol'] = (lambda i0, i1, _lo=baseline, _hi=volume:
                                slice_span(_lo, _hi, i0, i1))

        if p.cb_macd.isChecked():
            arrays = [df[column].to_numpy(dtype=float)
                      for column in ('MACD_line', 'MACD_signal', 'MACD_hist')
                      if column in df.columns]
            if arrays:
                macd_lo = np.fmin(np.fmin.reduce(arrays), 0.0)
                macd_hi = np.fmax(np.fmax.reduce(arrays), 0.0)
                providers['macd'] = (lambda i0, i1, _lo=macd_lo, _hi=macd_hi:
                                     slice_span(_lo, _hi, i0, i1))

        if p.cb_formula.isChecked():
            for target in p.formula_plots:
                draws = p._layer_formula.get(target, [])
                if not draws:
                    continue
                span_lo, span_hi = overlay_extent(draws, n)
                providers[target] = (lambda i0, i1, _lo=span_lo, _hi=span_hi:
                                     slice_span(_lo, _hi, i0, i1))
        return providers
