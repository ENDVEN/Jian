# ui/widgets/relation_chart.py
"""🔗 M3「与指数的关系」两张小图（★1.75 / §7-B16 期 3）。

【两张图各回答什么】
  · `EventStudyChart`（**图 C**）：把每次"命中"当成事件、把指数**按事件对齐**后取平均 ——
    一眼看出"命中前是涨完了还是才起来、命中后怎么走"。这是回答用户 2026-10-12 那个问题
    （"80 和 20 跟上证指数到底什么关系"）最直观的一张。
  · `LeadLagChart`（**图 D 的左半**）：占比与指数日收益在 lag = −10…+10 的相关 ——
    峰值落在负侧 = **指标领先**。

【口径一律不在这里】数据全部来自 `core/relation_stats`（事件对齐 / 领先滞后 / 两个 n）；
  本件只做**画**。三条诚实纪律（写进图与脚注）：
  ① 样本不足（`enough=False`）**照画但标注**，绝不悄悄不画；
  ② 某个偏移上没有样本 ⇒ 该点 NaN ⇒ 折线**断开**（不插值、不拿 0 顶替）；
  ③ 相关 ≠ 因果：轴标题写"同期 / 领先 N 期相关"，不写"预测"。

【复用】多窗格/十字线/读数一律走 `ChartHost`（§10-12：页面与图表件都不自己 `addPlot` 组窗格）。
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.widgets.chart_host import ChartHost
from ui.widgets.chart_style import apply_pokorny_style

__all__ = ['EventStudyChart', 'LeadLagChart']

_GRID = '#E8ECF1'
_ZERO = '#90A4AE'
_NAN_NOTE = '样本不足的点已断开（不插值）'


def _qss(lbl: QLabel, size: float = 11.0, color: str = '#8A94A6') -> None:
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f'font-size: {size}px; color: {color};')


class _BaseRelationChart(QWidget):
    """两张图的共同底座：一个 `ChartHost` + 一行脚注（诚实提示）。"""

    def __init__(self, parent=None, *, pane_name: str = 'relation'):
        super().__init__(parent)
        self._host = ChartHost(self, name=pane_name, crosshair=True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(self._host, 1)
        self.lbl_note = QLabel('')
        _qss(self.lbl_note)
        lay.addWidget(self.lbl_note)
        self._host.set_readout_visible(True)

    # ---------- 内部 ----------
    def _reset(self) -> None:
        pane = self._host.main_pane
        pane.plot_item.clear()
        apply_pokorny_style(pane.plot_item, background=None, margins=0)
        pane.plot_item.showGrid(x=True, y=True, alpha=0.12)

    def _static_provider(self, text: str):
        """读数条：**常显一句结论**（本图不需要逐点业务读数 —— 曲线本身就是答案）。"""
        self._host.set_readout_text(text)


class EventStudyChart(_BaseRelationChart):
    """事件对齐图：`x = 相对命中日的交易日（负 = 命中之日之前）`。"""

    def __init__(self, parent=None):
        super().__init__(parent, pane_name='event')
        self._offsets: list[int] = []

    def render(self, series, *, window: int = 20) -> int:
        """`series` = `[(label, color, event_study_dict)]`；返回**画了几条**。

        `event_study_dict` = `core.relation_stats.event_study(...)` 的返回（含 `mean/median/se`、
        `n_hit_days`、`n_independent`、`enough`）。
        """
        self._reset()
        pane = self._host.main_pane
        series = [s for s in (series or []) if s and s[2]]
        if not series or not series[0][2].get('offsets'):
            self.lbl_note.setText('')
            self._static_provider('')
            return 0
        self._offsets = [int(o) for o in series[0][2]['offsets']]
        xs = np.asarray(self._offsets, dtype=float)
        drawn, notes, lines = 0, [], []
        for label, color, ev in series:
            mean = np.asarray([ev['mean'].get(int(o), float('nan')) for o in self._offsets],
                              dtype=float)
            se = np.asarray([ev['se'].get(int(o), float('nan')) for o in self._offsets],
                            dtype=float)
            if np.isfinite(mean).sum() < 2:
                notes.append(f'{label}：有效点不足 ⇒ 未画线')
                continue
            up, dn = mean + se, mean - se
            if np.isfinite(up).sum() >= 2 and np.isfinite(dn).sum() >= 2:
                _c_up = pg.PlotDataItem(xs, up, pen=pg.mkPen(color, width=0.9,
                                                             style=Qt.PenStyle.DotLine))
                _c_dn = pg.PlotDataItem(xs, dn, pen=pg.mkPen(color, width=0.9,
                                                             style=Qt.PenStyle.DotLine))
                pane.plot_item.addItem(_c_up)
                pane.plot_item.addItem(_c_dn)
                # ⚠ **不是** `pg.mkBrush(color).setAlpha(...)` —— `pg.mkBrush` 回的是 QBrush，
                #   它没有 `setAlpha`（本轮实测踩到）；要先 `pg.mkColor` 拿 QColor 再设 alpha。
                #   （另：Qt 的 8 位 hex 是 `#AARRGGBB`，别用 CSS 习惯拼字符串。）
                _fill_color = pg.mkColor(color)
                _fill_color.setAlpha(0x1A)
                pane.plot_item.addItem(pg.FillBetweenItem(_c_up, _c_dn,
                                                          brush=pg.mkBrush(_fill_color)))
            pane.plot_item.addItem(pg.PlotDataItem(xs, mean, pen=pg.mkPen(color, width=2.2),
                                                   connect='finite'))
            drawn += 1
            notes.append(f'{label}：n = {ev.get("n_hit_days", 0)} 个命中日 / '
                         f'{ev.get("n_independent", 0)} 个独立事件'
                         + ('' if ev.get('enough', True) else '（**样本不足，仅参考**）'))
            lines.append(f'{label} 0→+{window} 期 '
                         f'{(ev["mean"].get(window, float("nan"))):+.2f}%')
        pane.plot_item.addItem(pg.InfiniteLine(pos=0, angle=90,
                                               pen=pg.mkPen(_ZERO, width=1.2,
                                                            style=Qt.PenStyle.DashLine)))
        pane.plot_item.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(_GRID, width=1)))
        pane.plot_item.setLabel('bottom', '相对命中日的交易日（负 = 命中之前）')
        pane.plot_item.setLabel('left', '指数累计涨跌 %')
        self.lbl_note.setText('　'.join(notes) + f'　·　{_NAN_NOTE}'
                              + '　·　相关 ≠ 因果：只说"同期 / 领先"关系，不是预测')
        self._static_provider('　'.join(lines) if lines else '')
        return drawn


class LeadLagChart(_BaseRelationChart):
    """领先滞后（柱）：`x = lag`，**峰值落在负侧 = 指标领先指数**。"""

    def __init__(self, parent=None):
        super().__init__(parent, pane_name='leadlag')
        self._lags: list[int] = []

    def render(self, series, *, lags=range(-10, 11)) -> int:
        """`series` = `[(label, color, {lag: r})]`；返回画了几条。"""
        self._reset()
        pane = self._host.main_pane
        series = [s for s in (series or []) if s and s[2]]
        self._lags = [int(l) for l in lags]
        if not series:
            self.lbl_note.setText('')
            self._static_provider('')
            return 0
        xs = np.asarray(self._lags, dtype=float)
        drawn, notes, lines = 0, [], []
        for label, color, corr in series:
            ys = np.asarray([corr.get(int(l), float('nan')) for l in self._lags], dtype=float)
            if not np.isfinite(ys).any():
                notes.append(f'{label}：相关算不出来（样本不足或常数）')
                continue
            pane.plot_item.addItem(pg.BarGraphItem(x=xs - 0.18, height=np.nan_to_num(ys),
                                                   width=0.34, brush=pg.mkBrush(color),
                                                   pen=pg.mkPen(width=0)))
            drawn += 1
            _valid = np.where(np.isfinite(ys), np.abs(ys), -1.0)
            _peak = int(self._lags[int(np.argmax(_valid))])
            _peak_r = float(ys[int(np.argmax(_valid))])
            _where = '指标**领先**指数' if _peak < 0 else ('同期' if _peak == 0 else '指标**滞后**指数')
            notes.append(f'{label}：峰值在 {_peak:+d} 期（r = {_peak_r:+.2f}）⇒ {_where}')
            lines.append(f'{label}：{_where.replace("**", "")} {abs(_peak)} 期')
        pane.plot_item.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen(_ZERO, width=1.2)))
        pane.plot_item.setLabel('bottom', 'lag（负 = 指标领先指数；正 = 指数领先）')
        pane.plot_item.setLabel('left', '与指数日收益的相关')
        self.lbl_note.setText('　'.join(notes) + '　·　只报"相关"，不报"因果"')
        self._static_provider('　'.join(lines) if lines else '')
        return drawn
