# ui/widgets/draw_overlay.py
"""
公式叠层的**唯一渲染器**（§7-B3 B③ · P3）。

把引擎产出的绘图 IR（`core/formula/draw.DrawData`）翻译成 pyqtgraph 图元，
挂到某个 `ChartPane` 上。**全 app 只此一份** —— 回测 K 线、行情页、未来任何图表
要展示 STICKLINE / 公式线 / DRAWICON，都走这里，禁止各页面自己画（§10-11/§10-12）。

【对外契约】
    painter = OverlayPainter(pane, bars_x)     # pane 由宿主切好窗口；bars_x = 该窗口的 x
    painter.render(draws)                      # draws 已按窗口切片、数组长度 == len(bars_x)
模块级工具（宿主用）：
    slice_draws(draws, index)                  # 把整段 DrawData 按窗口索引切片（不二次求值）
    overlay_extent(draws, n)                   # 逐 bar 的叠层最低/最高（供宿主扩 y 范围）

【堆叠顺序】宿主负责：K线 → 公式叠层 → 买卖点标记（本模块只保证"一次一批"）。

【为什么带对比度守卫】见 `chart_style.ensure_contrast` —— 公式按黑底写的
`COLORWHITE` 直接画在白底上等于没画，那正是 §7-B3 要根除的失败模式。
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pyqtgraph as pg
from pyqtgraph import QtCore, QtGui

from ui.widgets.chart_pane import ChartPane
from ui.widgets.chart_style import (
    DEFAULT_OVERLAY_COLOR, LIGHT_BACKGROUND, ensure_contrast,
)

# DRAWICON 图标号 → pyqtgraph 符号（一期常用子集；未收录的一律默认菱形 + tooltip 提示）
ICON_SYMBOLS = {
    0: 'o', 1: 'arrow_up', 2: 'arrow_down', 3: 't', 4: 't1', 5: 't2',
    6: 't3', 7: 's', 8: 'd', 9: 'star', 10: 'x', 11: '+', 12: 'p', 13: 'h',
}
DEFAULT_ICON_SYMBOL = 'd'
ICON_SIZE = 13
STICK_MIN_WIDTH = 1.0        # width <= 1 → 画细线；> 1 → 画实体
STICK_FULL_WIDTH = 5.0       # width == 5 → 占满一个 bar 槽位（TDX 常用档位）


class _StickItem(pg.GraphicsObject):
    """STICKLINE 的自绘图元：cond 为真处画 lo→hi 的竖段。

    · width <= 1 → 1px 竖线（cosmetic，不随缩放变粗）
    · width  > 1 → 小实体（占 bar 槽位的 width/5，最多占满）
    · hollow=True → 空心（只描边不填充）
    画法与 `CandlestickItem` 同源：QPicture + 抗锯齿 + 去描边（§10-1）。
    """

    def __init__(self, x, cond, lo, hi, width, color, hollow: bool = False):
        super().__init__()
        self._picture = QtGui.QPicture()
        self._rect = QtCore.QRectF()
        self._build(x, cond, lo, hi, width, color, hollow)

    def _build(self, x, cond, lo, hi, width, color, hollow):
        x = np.asarray(x, dtype=float)
        cond = np.asarray(cond, dtype=bool)
        lo = np.asarray(lo, dtype=float)
        hi = np.asarray(hi, dtype=float)
        width = np.asarray(width, dtype=float)
        if width.ndim == 0:
            width = np.full(x.size, float(width))

        active = cond & np.isfinite(lo) & np.isfinite(hi) & np.isfinite(width)
        if not active.any():
            return

        painter = QtGui.QPainter(self._picture)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # 颜色/画法只有一种状态，画笔在循环外一次性创建（照 §custom_widgets 的性能纪律）
        line_pen = pg.mkPen(color, width=1)
        line_pen.setCosmetic(True)
        body_pen = pg.mkPen(color, width=1) if hollow else pg.mkPen(None)
        body_brush = pg.mkBrush(None) if hollow else pg.mkBrush(color)
        # 「零高度横杠」用的 cosmetic 画笔：按 1~3 像素预建，避免在循环里造对象
        flat_pens = {w: pg.mkPen(color, width=w) for w in (1, 2, 3)}
        for pen in flat_pens.values():
            pen.setCosmetic(True)

        x_min = y_min = float('inf')
        x_max = y_max = float('-inf')
        for i in np.nonzero(active)[0]:
            y0, y1 = float(lo[i]), float(hi[i])
            if y1 < y0:
                y0, y1 = y1, y0
            if width[i] <= STICK_MIN_WIDTH:
                painter.setPen(line_pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawLine(QtCore.QPointF(x[i], y0), QtCore.QPointF(x[i], y1))
                half = 0.5
            else:
                half = 0.5 * min(1.0, max(0.12, float(width[i]) / STICK_FULL_WIDTH))
                if y1 - y0 <= 1e-12:
                    # TDX 高频写法 STICKLINE(状态, P, P, w, 0) = 在**该价位画一段横杠**
                    # （用户的状态柱正是这种）。退化成 0 高度矩形会"什么都看不见"，
                    # 因此按 width 取一条 cosmetic（像素宽、不随缩放变粗）的水平线。
                    painter.setPen(flat_pens[int(min(3, max(1, round(width[i]))))])
                    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                    painter.drawLine(QtCore.QPointF(x[i] - half, y0),
                                     QtCore.QPointF(x[i] + half, y0))
                else:
                    painter.setPen(body_pen)
                    painter.setBrush(body_brush)
                    painter.drawRect(QtCore.QRectF(x[i] - half, y0, 2 * half, y1 - y0))
            x_min, x_max = min(x_min, x[i] - half), max(x_max, x[i] + half)
            y_min, y_max = min(y_min, y0), max(y_max, y1)
        painter.end()

        if x_min <= x_max:
            self._rect = QtCore.QRectF(x_min, y_min, x_max - x_min, y_max - y_min)

    def paint(self, painter, *args):
        if not self._rect.isNull():
            painter.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return QtCore.QRectF(self._rect)


class OverlayPainter:
    """把 `DrawData` 批次渲染到**一个** ChartPane 上（全 app 唯一实现）。

    :param pane:        目标窗格（`ChartPane` / `pg.PlotItem` / `pg.PlotWidget` 均可）
    :param bars_x:      宿主已按窗口切好的 x（通常是窗口内 bar 序号 0..n-1）
    :param background:  图表背景色，用于对比度守卫（默认白底）
    """

    def __init__(self, pane, bars_x, *, background: str = LIGHT_BACKGROUND):
        self._pane = ChartPane.wrap(pane)
        self._x = np.asarray(bars_x, dtype=float)
        self._background = background or LIGHT_BACKGROUND
        self._items: list = []

    # ---------------- 查询 ----------------
    @property
    def pane(self) -> ChartPane:
        return self._pane

    @property
    def items(self) -> list:
        return list(self._items)

    # ---------------- 渲染 ----------------
    def render(self, draws) -> list:
        """渲染一批已按窗口切片的 DrawData，返回新增的图元列表。"""
        for data in draws or ():
            item = self._render_one(data)
            if item is not None:
                self._pane.add_overlay(item)
                self._items.append(item)
        return self.items

    def clear(self) -> None:
        self._pane.clear_overlays()
        self._items = []

    # ---------------- 内部 ----------------
    def _color(self, data) -> str:
        return ensure_contrast(data.color or DEFAULT_OVERLAY_COLOR, self._background)

    def _render_one(self, data):
        if data.kind == 'line':
            return self._render_line(data)
        if data.kind == 'stick':
            return self._render_stick(data)
        if data.kind == 'icon':
            return self._render_icon(data)
        return None

    def _render_line(self, data):
        if data.y is None:
            return None
        y = np.asarray(data.y, dtype=float)
        if y.size != self._x.size:        # 长度不符 = 对不齐窗口 → 宁可不画，也不画错位
            return None
        if not np.isfinite(y).any():
            return None
        pen = pg.mkPen(color=self._color(data), width=max(1, int(data.thickness or 1)))
        if data.style == 'dot':
            pen.setStyle(QtCore.Qt.PenStyle.DotLine)
        elif data.style == 'dash':
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        # connect='finite'：指标预热区的 NaN 直接断线，不画成穿堂线
        return pg.PlotDataItem(self._x, y, pen=pen, connect='finite')

    def _render_stick(self, data):
        if data.cond is None or data.lo is None or data.hi is None:
            return None
        cond = np.asarray(data.cond, dtype=bool)
        if cond.size != self._x.size or not cond.any():
            return None
        lo = np.asarray(data.lo, dtype=float)
        hi = np.asarray(data.hi, dtype=float)
        width = (np.full(cond.size, 1.0) if data.width is None
                 else np.asarray(data.width, dtype=float))
        return _StickItem(self._x, cond, lo, hi, width,
                          self._color(data), hollow=bool(data.hollow))

    def _render_icon(self, data):
        if data.cond is None or data.pos is None:
            return None
        cond = np.asarray(data.cond, dtype=bool)
        pos = np.asarray(data.pos, dtype=float)
        if cond.size != self._x.size:
            return None
        keep = cond & np.isfinite(pos)
        if not keep.any():
            return None
        icon_id = int(data.icon_id) if data.icon_id is not None else -1
        symbol = ICON_SYMBOLS.get(icon_id, DEFAULT_ICON_SYMBOL)
        item = pg.ScatterPlotItem(
            x=self._x[keep], y=pos[keep], symbol=symbol, size=ICON_SIZE,
            brush=pg.mkBrush(self._color(data)), pen=pg.mkPen(None))
        if icon_id not in ICON_SYMBOLS:
            item.setToolTip(f"未收录的图标号 {icon_id}，已用默认菱形显示")
        return item


# ==========================================
# 宿主工具：窗口切片 / y 范围扩展
# ==========================================
def slice_draws(draws, index) -> list:
    """按窗口索引切片整段 DrawData（返回**新对象**，不改引擎产物）。

    数组逐字段取值；`icon_id` / `hollow` 等标量原样保留。
    index 为整数数组（通常 = 窗口行在整段 df 中的原始行号）。
    """
    idx = np.asarray(index, dtype=int)

    def take(array):
        if array is None:
            return None
        return np.asarray(array)[idx]

    return [
        replace(d,
                x=take(d.x), y=take(d.y), cond=take(d.cond),
                lo=take(d.lo), hi=take(d.hi), width=take(d.width), pos=take(d.pos))
        for d in (draws or ())
    ]


def overlay_extent(draws, n: int):
    """逐 bar 的叠层最低/最高价（NaN = 该 bar 无叠层），供宿主把 y 范围扩到盖住叠层。

    返回 `(lo_array, hi_array)`，两者长度均为 n。
    """
    lo = np.full(int(n), np.nan)
    hi = np.full(int(n), np.nan)
    for data in draws or ():
        if data.kind == 'line' and data.y is not None:
            y = np.asarray(data.y, dtype=float)
            if y.size == n:
                lo, hi = np.fmin(lo, y), np.fmax(hi, y)      # fmin/fmax 自动忽略 NaN
        elif data.kind == 'stick' and data.cond is not None:
            cond = np.asarray(data.cond, dtype=bool)
            if cond.size != n or data.lo is None or data.hi is None:
                continue
            a = np.asarray(data.lo, dtype=float)
            b = np.asarray(data.hi, dtype=float)
            seg_lo, seg_hi = np.fmin(a, b), np.fmax(a, b)
            mask = cond & np.isfinite(seg_lo) & np.isfinite(seg_hi)
            lo = np.where(mask, np.fmin(lo, seg_lo), lo)
            hi = np.where(mask, np.fmax(hi, seg_hi), hi)
        elif data.kind == 'icon' and data.cond is not None:
            cond = np.asarray(data.cond, dtype=bool)
            if cond.size != n or data.pos is None:
                continue
            pos = np.asarray(data.pos, dtype=float)
            mask = cond & np.isfinite(pos)
            lo = np.where(mask, np.fmin(lo, pos), lo)
            hi = np.where(mask, np.fmax(hi, pos), hi)
    return lo, hi
