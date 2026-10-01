# ui/widgets/sweep_chart.py
"""
参数稳健性研究（§7-B15）· 图表区四件（SW-6）。

- `RegimeTimeline`：上证切块时间轴（图①，右栏顶部全宽）。**纯 QWidget 手绘**
  （收盘线 + 段色带 + 年份刻度 + 悬停读数 + 点段配对）—— 不走 pyqtgraph：它没有 y 轴、
  没有缩放需求，自绘最短且不会踩 §11.5-64 的轴口径坑。交互 = 方案书 §4 图①：点段 = 设
  样本内、**紧随其后的段**设样本外；**Shift+点 = 只设样本外**（★R3 补）。
- `TradesDistribution`：交易次数分布（图②，左栏滑块正下方紧凑版）——
  回答"我该填多少"：直方图 + 中位数标记 + 当前门槛线（pyqtgraph，只读）。
- `ScatterIso`：IS×OOS 散点（冠军崩塌的主图）+ y=x 参考线。
- `HeatmapGrid`：参数平面热力图（OOS 年化；平台 vs 尖峰一眼可见）。

样式纪律：不就地 setStyleSheet（§10-9），文字用 styles.ui_font / ui_painter_font（§10-15）。
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QPainter, QPen, QPolygonF,
                           QTextOption)  # noqa: F401
from PyQt6.QtCore import QRectF
from PyQt6.QtWidgets import (QGraphicsRectItem, QHBoxLayout, QLabel,
                             QStackedWidget, QVBoxLayout, QWidget)

from ui.widgets.styles import SEC_HINT_QSS, apply_ui_font, ui_font, ui_painter_font
from ui.widgets.summary_chip import build_chip, set_chip_state  # ★R4：全站同一张 chip 脸

#: 状态配色（与全站"绿=正/红=负"语言一致：涨=绿、跌=红、震荡=灰蓝）
REGIME_COLORS = {"up": "#2E7D32", "down": "#C62828", "sideways": "#546E7A"}
_REGIME_QCOLOR = {k: QColor(v) for k, v in REGIME_COLORS.items()}
_REGIME_NAMES = {"up": "涨", "down": "跌", "sideways": "震荡"}


def regime_legend_row() -> QWidget:
    """时间轴图例 = 彩色 chip 行（**QLabel 底色**，不靠字形 ■ —— 免字体回退乱码）。"""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(12, 0, 12, 4)
    lay.setSpacing(10)
    for regime, name in _REGIME_NAMES.items():
        chip = QLabel(name)
        chip.setStyleSheet(
            f"QLabel {{ background: {REGIME_COLORS[regime]}; color: white;"
            f" border-radius: 4px; padding: 1px 7px; font-size: 11px; }}")
        lay.addWidget(chip)
    tip = QLabel("点一段 = 设样本内，紧随其后的段 = 样本外 · Shift+点 = 只设样本外")
    tip.setStyleSheet(SEC_HINT_QSS)
    lay.addWidget(tip)
    lay.addStretch(1)
    apply_ui_font(row)
    return row


class _NoWheelPlot(pg.PlotWidget):
    """★R4-c：滚轮**让给页面滚动**（与全站 `NoWheel*` 控件同一条纪律，§6.6-U2）。

    【为什么】用户实测："想用滚轮下滚都会误触成图表的缩放"。pyqtgraph 默认鼠标模式下
    滚轮 = 缩放，而右栏本身是可滚区域 ⇒ 滚轮落在图上时必须**穿透**给滚动区（`event.ignore()`）。
    拖动平移仍可用（那是有意图的动作，不会误触）；框选缩放同理不受影响。

    ⚠ 定义必须排在使用它的类**之前**（`TradesDistribution` 在文件上半部分）——
    否则是"运行时 NameError、编译期查不出来"（实测踩过）。
    """

    def wheelEvent(self, ev) -> None:  # noqa: N802 —— Qt 原生命名
        ev.ignore()


class RegimeTimeline(QWidget):
    """上证指数切块时间轴（图① · ★R3 重做）。

    【为什么重做】旧版 = 一条纯色彩带：**没有价格参照、没有年份刻度、没有"我选了哪对"的标注**
    ⇒ 用户实测"莫名其妙、根本看不懂"。本版补齐三个"看懂要素"：
      ① **价格** —— 上证收盘线（归一化到控件高度）；
      ② **时间** —— 年份刻度（每 2 年 + 首末）；
      ③ **当前选择** —— 样本内蓝框 / 样本外橙框 + 顶部区间条。
    色义按**全站口径**（绿=涨 / 红=跌 / 灰蓝=震荡）—— 用户 2026-10-01 拍板（设计稿那句
    "红=上涨段"按笔误处理）。

    【交互】点段 = 该段设样本内 + **紧随其后的段**设样本外；**Shift+点** = 只把该段设为样本外；
    悬停 = 右上角常驻读数（段型 / 起止 / 交易日数 / 该段指数涨跌幅），**不弹 tooltip**（弹窗会挡图）。
    """

    segment_picked = pyqtSignal(str, str, str, str)   # 点段：(is_start, is_end, oos_start, oos_end)
    segment_oos_picked = pyqtSignal(str, str)         # Shift+点：(oos_start, oos_end)

    BAND_H = 11        # 段色带高度
    STRIP_H = 4        # 顶部"当前配对"条高度
    AXIS_H = 15        # 底部年份刻度行高

    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments: list[dict] = []
        self._closes: list[tuple[str, float]] = []
        self._window = 60     # 切块的滚动窗口（判定值要它；set_payload 用 payload.params 覆盖）
        self._marks: tuple[str, str, str, str] | None = None   # (内起, 内止, 外起, 外止)
        self._hover: str = ""
        self._hint = "暂无切块数据 —— 点右上角「⟳ 重新切块」生成"
        self.setMinimumHeight(104)
        self.setMouseTracking(True)
        self.setFont(ui_font())
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---------------- 数据 ----------------
    def set_payload(self, payload, closes=None) -> None:
        """`payload` = `core.index_regimes` 缓存；`closes` = 上证收盘 Series（None ⇒ 只画色带）。"""
        segs = (payload or {}).get("segments") or []
        self._segments = [s for s in segs
                          if isinstance(s, dict) and s.get("start") and s.get("end")]
        try:      # 判定窗口（悬停读数要用它解释"为什么这段标成跌/涨"）
            self._window = int(((payload or {}).get("params") or {}).get("window") or 60)
        except (TypeError, ValueError):
            self._window = 60
        self._closes = []
        if closes is not None and len(closes):
            self._closes = [(str(idx)[:10], float(v))
                            for idx, v in zip(closes.index, closes.to_numpy(dtype=float))
                            if v == v]
        if not (self._segments or self._closes):
            self._hint = "暂无切块数据 —— 点右上角「⟳ 重新切块」生成"
        self.update()

    def set_marks(self, is_start: str, is_end: str, oos_start: str, oos_end: str) -> None:
        """当前研究的样本内 / 样本外窗口（★R3：分开给 ⇒ 图上能分辨哪段是内、哪段是外）。"""
        self._marks = (str(is_start or ""), str(is_end or ""),
                       str(oos_start or ""), str(oos_end or ""))
        self.update()

    # ---------------- 坐标与命中 ----------------
    def _bounds(self) -> tuple[date, date]:
        iso = [*(s["start"] for s in self._segments), *(s["end"] for s in self._segments),
               *(p[0] for p in self._closes)]
        return date.fromisoformat(min(iso)), date.fromisoformat(max(iso))

    def _x_of(self, iso: str, lo: date, hi: date, w: float) -> float:
        return (date.fromisoformat(str(iso)) - lo).days / max(1, (hi - lo).days) * w

    def _seg_at(self, x: float) -> dict | None:
        if not self._segments:
            return None
        lo, hi = self._bounds()
        # ⚠ `hi - lo` 是 timedelta（date 相减），取 `.days` 才是天数 —— 直接乘会 TypeError
        pick = lo + timedelta(days=(hi - lo).days * (x / max(1, self.width())))
        return next((s for s in self._segments
                     if date.fromisoformat(s["start"]) <= pick <= date.fromisoformat(s["end"])), None)

    def _seg_change(self, seg: dict) -> str:
        """段内首末涨跌幅 + **判定值**（末日往前 window 个交易日的涨跌幅 —— 段型就是这么判的）。

        ⚠ 只给"段内首末"会自相矛盾：段型按**滚动 window 日窗口**判定（`core.index_regimes`），
          所以一个"单边下跌"段的段内首末完全可能是正的（窗口看的是前 window 天）。
          把两个数一起给，用户才看得懂"为什么这段标成跌"（§11.5-112 族：口径要同屏）。
        """
        idx = [i for i, (d, _v) in enumerate(self._closes) if seg["start"] <= d <= seg["end"]]
        if not idx:
            return ""
        first, last = idx[0], idx[-1]
        parts = []
        if last > first:
            parts.append(f"段内 {(self._closes[last][1] / self._closes[first][1] - 1) * 100:+.1f}%")
        w = max(2, int(self._window))
        if last - w >= 0:
            parts.append(f"判定 {w} 日窗口 "
                         f"{(self._closes[last][1] / self._closes[last - w][1] - 1) * 100:+.1f}%")
        return " · ".join(parts)

    def _hover_text(self, seg: dict) -> str:
        name = _REGIME_NAMES.get(seg.get("regime"), str(seg.get("regime") or ""))
        chg = self._seg_change(seg)
        return (f"{name} {seg['start']} ~ {seg['end']} · {seg['n_days']} 交易日"
                + (f" · {chg}" if chg else ""))

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802 —— Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor("#FBFCFE"))
        if not (self._segments or self._closes):
            p.setPen(QPen(QColor("#8A94A6")))
            p.setFont(ui_font())
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._hint)
            p.end()
            return
        lo, hi = self._bounds()
        band_top = max(20, h - self.AXIS_H - self.BAND_H - 2)
        # ① 当前配对：整列淡色底（内=蓝 / 外=橙）+ 顶部区间条
        if self._marks:
            a, b, c, d = self._marks
            for s0, s1, stripe in ((a, b, "#1976D2"), (c, d, "#E67E22")):
                if not (s0 and s1):
                    continue
                x0, x1 = self._x_of(s0, lo, hi, w), self._x_of(s1, lo, hi, w)
                tint = QColor(stripe)
                tint.setAlpha(30)
                p.fillRect(int(x0), self.STRIP_H, max(1, int(x1 - x0)),
                           band_top - self.STRIP_H, tint)
                p.fillRect(int(x0), 1, max(1, int(x1 - x0)), self.STRIP_H - 1, QColor(stripe))
        # ② 上证收盘线
        if len(self._closes) > 1:
            ys = [v for _d, v in self._closes]
            y0, y1 = min(ys), max(ys)
            span = max(1e-9, y1 - y0)
            top, bot = 8.0, float(max(12, band_top - 8))
            pts = [QPointF(self._x_of(d, lo, hi, w), bot - (v - y0) / span * (bot - top))
                   for d, v in self._closes]
            p.setPen(QPen(QColor("#5B6472"), 1.2))
            p.drawPolyline(QPolygonF(pts))
        # ③ 段色带
        for seg in self._segments:
            x0, x1 = self._x_of(seg["start"], lo, hi, w), self._x_of(seg["end"], lo, hi, w)
            p.fillRect(int(x0), band_top, max(1, int(x1 - x0)), self.BAND_H,
                       _REGIME_QCOLOR.get(seg.get("regime"), QColor("#90A4AE")))
        # ④ 年份刻度（每 2 年 + 首末）
        p.setPen(QPen(QColor("#8A94A6")))
        p.setFont(ui_painter_font(8))
        y = h - 3
        for yr in range(lo.year + (lo.year % 2), hi.year, 2):
            x = self._x_of(f"{yr + 1}-01-01", lo, hi, w)
            if 4 <= x <= w - 30:
                p.drawText(int(x), y, str(yr + 1))
        p.drawText(2, y, str(lo.year))
        p.drawText(w - 30, y, str(hi.year))
        # ⑤ 悬停读数（右上角常驻一行，绝不弹 tooltip 挡图）
        if self._hover:
            p.setPen(QPen(QColor("#3A4250")))
            p.setFont(ui_painter_font(8, bold=True))
            p.drawText(min(6, max(0, w - 470)), 11, self._hover)
        p.end()

    # ---------------- 交互 ----------------
    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        seg = self._seg_at(ev.position().x())
        text = self._hover_text(seg) if seg is not None else ""
        if text != self._hover:
            self._hover = text
            self.setToolTip(text)      # 键盘/触控板用户也能拿到（不靠弹窗）
            self.update()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        seg = self._seg_at(ev.position().x())
        if seg is None:
            return
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            # Shift+点 = **只设样本外**（设计稿 p2 口径）—— 样本内保持不动
            self.segment_oos_picked.emit(seg["start"], seg["end"])
            return
        nxt = next((s for s in self._segments if s["start"] > seg["end"]), None)
        if nxt is not None:      # 末段没有"紧随段"⇒ 不发（诚实：配不成对）
            self.segment_picked.emit(seg["start"], seg["end"], nxt["start"], nxt["end"])


class TradesDistribution(_NoWheelPlot):
    """交易次数分布（图②）：直方图 + 中位数线 + 当前门槛线。只读。"""

    def __init__(self, parent=None):
        super().__init__(parent, background="w")
        self.setMaximumHeight(150)
        self.setMouseEnabled(x=False, y=False)
        self.hideButtons()
        self._bar = pg.BarGraphItem(x0=[0.0], x1=[0.0], height=[0.0], brush="#90CAF9")
        self.addItem(self._bar)
        self._gate = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#1976D2", width=2))
        self.addItem(self._gate)
        self._median = pg.InfiniteLine(angle=90, movable=False,
                                       pen=pg.mkPen("#C62828", width=1, style=Qt.PenStyle.DashLine))
        self.addItem(self._median)
        self.getAxis("bottom").setLabel("每组交易次数")
        self.getAxis("left").setLabel("组数")
        for ax in ("bottom", "left"):
            self.getAxis(ax).setTickFont(ui_font(10))

    def set_trades(self, trades: list[int], gate: int) -> str:
        """画分布；返回给引导卡的一句话（中位数 ⇒ 建议范围）。"""
        arr = np.asarray(trades, dtype=float)
        self.clear()
        self.addItem(self._bar)
        self.addItem(self._gate)
        self.addItem(self._median)
        if arr.size == 0:
            self._gate.setPos(gate)
            return "还没有跑完任何组 —— 跑完样本内再看分布"
        lo, hi = 0.0, max(20.0, float(arr.max()) + 2)
        bins = np.arange(lo, hi + 2, max(1.0, (hi - lo) / 40))
        hist, edges = np.histogram(arr, bins=bins)
        centers = (edges[:-1] + edges[1:]) / 2
        width = (edges[1] - edges[0]) * 0.9
        self._bar.setOpts(x0=centers - width / 2, x1=centers + width / 2,
                          height=hist, brush="#90CAF9")
        med = float(np.median(arr))
        self._gate.setPos(float(gate))
        self._median.setPos(med)
        self.setXRange(lo, hi, padding=0.02)
        suggest_lo, suggest_hi = max(1, int(med * 0.5)), int(med * 1.5) + 1
        return (f"本次分布中位数 {med:.0f} ⇒ 建议门槛 {suggest_lo}~{suggest_hi}"
                f"（门槛只筛不排：改它不改变排名，只换候选成员）")


class ScatterIso(_NoWheelPlot):
    """IS×OOS 散点（冠军崩塌）—— ★R4-b 按设计稿重做
    （`design/1.58-param-sweep/_charts.js::scatter`，用户实测："轴名晦涩、0.001 摸不准头脑"）。

    与设计稿逐项对齐：
    - **轴 = 年化百分比**（"样本内年化（%）"/"样本外年化（%）"），刻度是 -5 / 0 / 2.5 / 5 这种人读的数
      （输入仍是小数，本件内 ×100 —— 界面上不出现 0.001 那种原始小数）；
    - **0 轴加深**（两轴都画）+ 中位线（竖 = IS 中位、横 = OOS 中位，浅灰虚线）；
    - **稳健平台区** = 平台格（`core.sweep_stats.platform_spike_flags`）的包围盒 ⇒ 绿虚线框 +
      "选参看这里"那一句（没有平台格就不画框：没平台就不假装有）；
    - **样本内冠军** = 橙点 + 拉线 + 两行标注（该点**参数** + 两端年化 + 一句"为什么"）；
    - 左上角一行 **Rank IC 结论**（红字）；
    - 悬停 = 该点的**参数与读数**（per-point `tip`），不再只报坐标（用户实测口径）。
    """

    def __init__(self, parent=None):
        super().__init__(parent, background="w")
        self.setMouseEnabled(x=True, y=True)
        self.hideButtons()
        self.showGrid(x=True, y=True, alpha=0.18)
        self.getAxis("bottom").setLabel("样本内年化（%）")
        self.getAxis("left").setLabel("样本外年化（%）")
        for ax in ("bottom", "left"):
            self.getAxis(ax).setTickFont(ui_font(10))
        self._scatter = pg.ScatterPlotItem(pen=None, hoverable=True)
        # ★R4-b：悬停文字自己出 —— pyqtgraph 0.14 **不认 per-point `tip`**
        #   （实测报 `Unknown spot parameter: tip`），只认 `data`；
        #   所以要接 `sigHovered` 把 `data` 里的文字塞进 tooltip。
        self._scatter.sigHovered.connect(self._on_hover)
        self.addItem(self._scatter)
        self._deco: list = []                 # 参考线/框/标注（重复 set_data 不叠加）
        self._hover_tip = ""
        self._out_n = 0
        self._ic = None
        self._ic_verdict = ""
        self._champ = ""

    def _on_hover(self, *args) -> None:
        """悬停 = 该点的**参数与读数**（用户实测口径：不要再报坐标）。"""
        pts = next((a for a in args if isinstance(a, (list, tuple))), None)
        txt = ""
        if pts:
            d = getattr(pts[0], "data", None)
            d = d() if callable(d) else d
            if isinstance(d, dict):
                d = d.get("tip") or d.get("data")
            txt = str(d or "")
        if txt != self._hover_tip:
            self._hover_tip = txt
            self.setToolTip(txt)

    # ---------------- 装饰件 ----------------
    def _plate(self, x: float, y: float, txt: str, color: str) -> None:
        """图内**白底短标签**（★R4-e：压在数据上的字必须有底色，且必须短）。"""
        t = pg.TextItem(txt, color=color, anchor=(0, 0.5),
                        fill=pg.mkBrush(255, 255, 255, 235), border=pg.mkPen("#E6EAF0"))
        f = ui_font(11)
        f.setBold(True)
        t.setFont(f)
        self._add(t)
        t.setPos(x, y)

    def caption(self) -> str:
        """**图外说明行**（★R4-e）：长句、口径、图例一律在这里说 —— 图面只留数据与短标签。"""
        parts = []
        if getattr(self, "_ic", None) is not None and np.isfinite(self._ic):
            parts.append(f"Rank IC = {self._ic:.2f} —— {self._ic_verdict}"
                         "（≥0.15 才算有预测力）")
        parts.append("① = 样本内冠军（样本内年化最高那一格，也最容易在样本外塌）"
                     "· ② 绿框 = 稳健平台区（邻域高且不塌，选参看这里）")
        if getattr(self, "_out_n", 0):
            parts.append(f"视图取景 Tukey 1.5×IQR（含 0）：视图外另有 {self._out_n} 个极值点，"
                         "拖动可移（滚轮已让给页面滚动）")
        else:
            parts.append("视图取景 Tukey 1.5×IQR（含 0）· 滚轮已让给页面滚动，拖动可平移")
        return "　".join(parts)

    def _clear_deco(self) -> None:
        for it in self._deco:
            self.removeItem(it)
        self._deco = []

    def _add(self, item) -> None:
        self.addItem(item)
        self._deco.append(item)

    def _text(self, x, y, txt, color, anchor=(0, 0), bold=False, size=10):
        t = pg.TextItem(txt, color=color, anchor=anchor)
        f = ui_font(size)
        f.setBold(bool(bold))
        t.setFont(f)
        self._add(t)
        t.setPos(x, y)
        return t

    @staticmethod
    def _nice_step(lo, hi, target=6) -> float:
        span = max(1e-9, float(hi) - float(lo))
        raw = span / max(2, target)
        for step in (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 500, 1000):
            if raw <= step:
                return float(step)
        return float(raw)

    def set_data(self, is_annual, oos_annual, highlight: set[int] = (),
                 champion: int | None = None, candidate: int | None = None,
                 combos=None, nb_mean=None, rank_ic=None, platform=None) -> None:
        """画散点。`combos` = 每点的参数（悬停与标注要用）；`platform` = 平台格布尔序列。"""
        ia = np.asarray(is_annual, dtype=float) * 100.0      # ← 小数 → 百分比（设计稿口径）
        oa = np.asarray(oos_annual, dtype=float) * 100.0
        nb = None if nb_mean is None else np.asarray(nb_mean, dtype=float) * 100.0
        tips = []
        for i in range(ia.size):
            if combos is not None and i < len(combos):
                kv = " · ".join(f"{k}={float(v):.6g}" for k, v in sorted(combos[i].items()))
            else:
                kv = "（未带参数）"
            extra = "" if nb is None or not np.isfinite(nb[i]) else f" · 邻域 {nb[i]:.2f}%"
            tips.append(f"{kv} ⇒ IS {ia[i]:.2f}% · OOS {oa[i]:.2f}%{extra}")
        pts = [{"pos": (float(ia[i]), float(oa[i])), "brush": pg.mkBrush(124, 138, 160, 140),
                "size": 6, "data": tips[i]} for i in range(ia.size)]
        self._scatter.setData(pts)
        self._clear_deco()
        if not ia.size:
            return
        # 0 轴（比网格重）
        self._add(pg.InfiniteLine(pos=0, angle=90, movable=False,
                                  pen=pg.mkPen("#C9D3E0", width=1.2)))
        self._add(pg.InfiniteLine(pos=0, angle=0, movable=False,
                                  pen=pg.mkPen("#C9D3E0", width=1.2)))
        # 中位线（看"样本内排名有没有预测力"）
        if np.isfinite(ia).any():
            self._add(pg.InfiniteLine(pos=float(np.nanmedian(ia)), angle=90, movable=False,
                                      pen=pg.mkPen("#8A94A6", style=Qt.PenStyle.DashLine)))
        if np.isfinite(oa).any():
            self._add(pg.InfiniteLine(pos=float(np.nanmedian(oa)), angle=0, movable=False,
                                      pen=pg.mkPen("#8A94A6", style=Qt.PenStyle.DashLine)))
        # 稳健平台区（平台格包围盒）
        if platform is not None and np.asarray(platform, dtype=bool).any():
            m = np.asarray(platform, dtype=bool)[:ia.size]
            px, py = ia[m], oa[m]
            ok = np.isfinite(px) & np.isfinite(py)
            if ok.any():
                x0, x1 = float(px[ok].min()), float(px[ok].max())
                y0, y1 = float(py[ok].min()), float(py[ok].max())
                rect = QGraphicsRectItem(QRectF(x0, y0, max(0.01, x1 - x0), max(0.01, y1 - y0)))
                rect.setPen(pg.mkPen("#2E7D32", style=Qt.PenStyle.DashLine, width=1.5))
                rect.setBrush(pg.mkBrush(46, 125, 50, 16))
                self._add(rect)
                pad = max(0.05, (float(np.nanmax(oa)) - float(np.nanmin(oa))) * 0.03)
                self._plate(x0 + pad, y1 - pad, "② 稳健平台区", "#2E7D32")
        # 样本内冠军（橙点 + 拉线 + 两行话）
        if champion is not None and 0 <= int(champion) < ia.size:
            c = int(champion)
            self._add(pg.ScatterPlotItem([float(ia[c])], [float(oa[c])], symbol="o", size=11,
                                         brush=pg.mkBrush("#E65100"), pen=pg.mkPen("#E65100")))
            if combos is not None and c < len(combos):
                kv = " ".join(f"{k}={float(v):.6g}" for k, v in sorted(combos[c].items()))
            else:
                kv = "组合 #%d" % (c + 1)
            # ★R4-e：只留一句**短**的白底标签（长解释搬到图外说明行）
            self._champ = (f"① 样本内冠军 {kv}：{ia[c]:.1f}% → {oa[c]:.1f}%")
            self._plate(float(ia[c]), float(oa[c]), self._champ, "#E65100")
        # 左上角 Rank IC 结论
        if rank_ic is not None and np.isfinite(float(rank_ic)):
            r = float(rank_ic)
            verdict = ("样本内排名对样本外**有**预测力" if r >= 0.15 else
                       "样本内排名对样本外几乎没有预测力")
            self._ic, self._ic_verdict = r, verdict
            self._plate(float(np.nanmin(ia)), float(np.nanmax(oa)),
                        f"Rank IC = {r:.2f}", "#2E7D32" if r >= 0.15 else "#C62828")
        # ★R4-c：视口 = **两轴各自稳健取景**（用户实测："结果图过分的大 / 点挤成一条"）。
        #   旧版把 IS 与 OOS 揉成一个 min/max 同时喂给两轴 —— 只要有一个极端值（小样本下
        #   年化能飙到几百 %），整个画面就被撑到"点挤在一条竖线里、其余全是空白"。
        #   ⇒ ① 两轴各自看自己的数据；② 取 2%~98% 分位（必含 0）；③ 视图外的点**如实报数**。
        rx, ry = self._robust_range(ia), self._robust_range(oa)
        self.setXRange(*rx, padding=0.05)
        self.setYRange(*ry, padding=0.05)
        out = (int(np.sum((ia < rx[0]) | (ia > rx[1])))
               + int(np.sum((oa < ry[0]) | (oa > ry[1]))))
        # ★R4-e：**长句一律搬到图外的说明行**（用户实测："文字太长直接遮挡了大片的图表内容"）
        #   —— 图里只留"一眼要用到"的东西；这句话同时挂在 tooltip 上（想细看悬停就有）。
        self._out_n = int(out)
        self.setToolTip(f"视图取景 = Tukey 1.5×IQR（必含 0）：视图外另有 {out} 个极值点，"
                        "拖动可移（滚轮已让给页面滚动）" if out else
                        "视图取景 = Tukey 1.5×IQR（必含 0）：本次所有点都在视图内")
        # 刻度：自己给"人读的数"（否则 pyqtgraph 会按窄区间吐出 0.001 这种字）
        for axis, (a, b) in (("bottom", rx), ("left", ry)):
            st = self._nice_step(a, b)
            ticks = [(float(v), f"{v:g}")
                     for v in np.arange(np.floor(a / st) * st, b + st, st)]
            self.getAxis(axis).setTicks([ticks])

    @staticmethod
    def _robust_range(v) -> tuple[float, float]:
        """稳健取景 = **Tukey 1.5×IQR 胡须** + **必含 0**（"赚/亏"的分界必须在画面里）。

        为什么不是 min/max：小样本下年化能有几百 %（某组只成交 1~2 笔）⇒ 画面被一个点撑爆，
        其余点挤成一条竖线（用户实测："结果图过分的大、点挤成一条"）。
        为什么是 IQR 而不是分位：IQR 随分布本身缩放 —— 分布真的宽就照实给宽，
        而"远在天边的孤立点"被稳定排除（分位在 n 小时反而不稳）。
        极值点**不改变取景**但仍在图上（拖动可见，角落如实报出"视图外有多少个"）——
        绝不悄悄丢点，也绝不让一个异常值毁掉整张图。
        """
        f = np.asarray(v, dtype=float)
        f = f[np.isfinite(f)]
        if f.size == 0:
            return -1.0, 1.0
        q1, q3 = (float(np.percentile(f, 25)), float(np.percentile(f, 75)))
        iqr = max(1e-6, q3 - q1)
        lo = min(q1 - 1.5 * iqr, 0.0)
        hi = max(q3 + 1.5 * iqr, 0.0)
        if hi - lo < 1e-6:
            lo, hi = lo - 1.0, hi + 1.0
        return lo, hi


class HeatmapGrid(QWidget):
    """参数平面热力图 —— ★R4-b 按设计稿重做（`_charts.js::heat`，手绘件）。

    【为什么改手绘】设计稿的样子 pyqtgraph 的 `ImageItem` 画不出来：**圆角格 + 1px 间隙 +
    负值单独一档灰 + 平台整片绿框 + 尖峰橙圈 + 右侧离散色标**。手绘 100 行，样式与稿子逐项对齐。

    色义（照稿）：**蓝阶 = 数值大小**（刻意避开红绿 —— A 股红涨绿跌会误读）；**灰 = 亏钱**（负年化）；
    **白 = 没跑到**（NaN，与"亏钱"必须分得开）；绿框 = 平台（一整片都不错，选这里）；
    橙圈 = 尖峰（自己高、邻居全塌 ⇒ 噪声）。
    """

    CELL = 40          # 格边长（设计稿值）；控件窄了会自动缩
    L, T = 52, 26      # 左边距（y 刻度）/ 上边距（x 刻度）
    BAR = 46           # 右侧色标宽度

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self._xv: list[float] = []
        self._yv: list[float] = []
        self._vals = None
        self._names = ("", "")
        self._plat: list = []
        self._spike: list = []
        self._hover = ""
        self._notice = ""

    def set_notice(self, text: str) -> None:
        """空态说明（单维 / 未跑）—— 与 `set_grid` 二选一，互不干扰。"""
        self._notice = str(text or "")
        self.update()

    def caption(self) -> str:
        if self._vals is None or not len(self._xv):
            return ("热力图看的是**参数的整片地形**：蓝越深年化越高 · 灰 = 亏钱 · 白 = 没跑到"
                    "（两维网格才有热力图）")
        return ("蓝越深 = 样本外年化越高 · 灰 = 亏钱 · 白 = 没跑到 · "
                "绿框格 = 平台（邻域均值 ≥ 上四分位，即前 25%）· 橙圈 = 尖峰（自己高、邻居全塌）")

    def set_grid(self, dim_x_name, dim_x_vals, dim_y_name, dim_y_vals, values,
                 platform_cells=(), spike_cells=()) -> None:
        """`values[i_y, i_x]`（NaN = 没跑到）；`platform_cells` / `spike_cells` = (i_x, i_y)。"""
        self._names = (str(dim_x_name), str(dim_y_name))
        self._xv = [float(v) for v in dim_x_vals]
        self._yv = [float(v) for v in dim_y_vals]
        self._vals = np.asarray(values, dtype=float)
        self._plat = list(platform_cells)
        self._spike = list(spike_cells)
        self.update()

    # ---------------- 颜色 ----------------
    @staticmethod
    def _cell_color(v: float) -> QColor:
        """照稿：负 ⇒ 灰 #D8DEE8；非负 ⇒ 蓝阶（白蓝 → 深蓝）。"""
        if v != v:
            return QColor("#FFFFFF")
        if v < 0:
            return QColor("#D8DEE8")
        t = min(1.0, float(v) / 0.095)          # 9.5% 打到最深（与稿子 maxV 同量级）
        return QColor(int(round(232 - t * 206)), int(round(240 - t * 126)),
                      int(round(250 - t * 14)))

    def _geom(self):
        n_x, n_y = (len(self._xv), len(self._yv))
        if not n_x or not n_y:
            return 0, 0, 0, 0
        avail_w = max(60, self.width() - self.L - self.BAR - 8)
        avail_h = max(60, self.height() - self.T - 40)
        cell = max(16, min(self.CELL, int(min(avail_w / n_x, avail_h / n_y))))
        return cell, self.L, self.T, cell

    # ---------------- 绘制 ----------------
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(ui_painter_font(10))
        v = self._vals
        if v is None or not len(self._xv) or not len(self._yv):
            # ★R4-e：**单维 / 未跑**时也必须让这一页看得见原因（用户实测："热力图直接是空的"）
            p.setPen(QPen(QColor("#3A4250")))
            p.setFont(ui_painter_font(12, bold=True))
            p.drawText(16, 30, self._notice or "还没有跑出网格 —— 跑完样本内 + 样本外后出图")
            p.setPen(QPen(QColor("#8A94A6")))
            p.setFont(ui_painter_font(11))
            p.drawText(16, 54, "热力图要**两维**参数：把左栏第 2 维也选上参数，再跑一次")
            p.end()
            return
        cell, L, T, _c = self._geom()
        n_x, n_y = len(self._xv), len(self._yv)
        vmax = float(np.nanmax(v)) if np.isfinite(v).any() else 0.0
        for iy in range(n_y):
            for ix in range(n_x):
                val = float(v[iy, ix])
                x, y = L + ix * cell, T + iy * cell
                if val != val:                                   # 没跑到：白底 + 虚线边
                    p.setBrush(QBrush(QColor("#FFFFFF")))
                    p.setPen(QPen(QColor("#E6EAF0"), 1, Qt.PenStyle.DotLine))
                else:
                    p.setBrush(QBrush(self._cell_color(val)))
                    p.setPen(QPen(QColor("#FFFFFF"), 1))
                p.drawRoundedRect(int(x), int(y), int(cell - 1), int(cell - 1), 3, 3)
        # ★R4-d：平台改成**逐格描绿边**。旧版画"包围盒"（min/max 的整块矩形）—— 平台格一散开
        #   就把整张图圈住，等于什么也没说（用户实测："挤压在一块 / 看不懂"）；
        #   逐格描边天然只把**连成片**的格子读成一块（稿子里那个大框本来就是"一整片连续"的意思）。
        for (ix, iy) in self._plat:
            p.setBrush(Qt.BrushStyle.NoBrush)
            # 半透明细边：平台格可能有几十个（判据是"≥ 中位数"），描太重会把整张图糊成一片绿
            p.setPen(QPen(QColor(46, 125, 50, 150), 1.6))
            p.drawRoundedRect(int(L + ix * cell - 1), int(T + iy * cell - 1),
                              int(cell + 1), int(cell + 1), 4, 4)
        # 尖峰：橙圈（只圈最高的那个）+ **白底标签**（旧版文字直接压在格子上，读不出）
        if self._spike:
            best = max(self._spike,
                       key=lambda c: (v[c[1], c[0]] if np.isfinite(v[c[1], c[0]]) else -9e9))
            cx, cy = L + best[0] * cell + cell / 2, T + best[1] * cell + cell / 2
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#E65100"), 2.2))
            p.drawEllipse(QPointF(cx, cy), cell * 0.42, cell * 0.42)
            self._plate_text(p, cx - cell, cy + cell * 0.42 + 4,
                             f"尖峰 {float(v[best[1], best[0]]):.1%}：邻居全塌 ⇒ 噪声",
                             QColor("#E65100"))
        # 轴刻度与轴名（★R4-d：格子窄了就**抽稀**刻度，否则数字挤在一起读不出）
        p.setPen(QPen(QColor("#8A94A6")))
        p.setFont(ui_painter_font(9))
        stride = 1 if cell >= 34 else (2 if cell >= 24 else 3)
        for ix in range(n_x):
            if ix % stride == 0 or ix == n_x - 1:
                p.drawText(int(L + ix * cell), int(max(11, T - 6)), f"{self._xv[ix]:g}")
        for iy in range(n_y):
            if iy % stride == 0 or iy == n_y - 1:
                p.drawText(int(L - 38), int(T + iy * cell + cell / 2 + 3), 40, 12,
                           int(Qt.AlignmentFlag.AlignRight), f"{self._yv[iy]:g}")
        p.setPen(QPen(QColor("#616B7A")))
        p.setFont(ui_painter_font(10))
        p.drawText(int(L + n_x * cell / 2 - 40), self.height() - 18, f"参数 {self._names[0]}")
        p.save()
        p.translate(13, int(T + n_y * cell / 2))
        p.rotate(-90)
        p.drawText(0, 0, f"参数 {self._names[1]}")
        p.restore()
        # 离散色标（8 段）+ 说明
        bx = L + n_x * cell + 12
        p.setFont(ui_painter_font(9))
        for k in range(8):
            t = 1 - k / 7.0
            c = self._cell_color(max(0.0, vmax) * t)
            p.setBrush(QBrush(c))
            p.setPen(QPen(QColor("#E6EAF0")))
            p.drawRect(int(bx), int(T + k * 16), 12, 16)
        # ★R4-d：色标读数**方向**要跟渐变一致 —— 最深蓝在**顶**，最大值就得写在顶上
        #   （旧版把 max 写在底部 ⇒ 用户看到"顶上是深蓝、标的是 1.8%"这种自相矛盾的图）。
        p.setPen(QPen(QColor("#8A94A6")))
        p.drawText(int(bx), int(max(11, T - 6)), "年化%")
        p.drawText(int(bx + 15), int(T + 10), f"{max(0.0, vmax):.1%}")
        p.drawText(int(bx + 15), int(T + 8 * 8 + 4), f"{max(0.0, vmax) / 2:.1%}")
        p.setBrush(QBrush(QColor("#D8DEE8")))
        p.setPen(QPen(QColor("#E6EAF0")))
        p.drawRect(int(bx), int(T + 8 * 16 + 18), 12, 12)
        p.setPen(QPen(QColor("#8A94A6")))
        p.drawText(int(bx + 15), int(T + 8 * 16 + 28), "亏钱")
        # 悬停读数（卡内一行，不弹窗）
        if self._hover:      # ★R4-e：悬停读数放大到 11px（原 10px 太小看不清）
            p.setPen(QPen(QColor("#3A4250")))
            p.setFont(ui_painter_font(11, bold=True))
            p.drawText(int(L), 13, self._hover)
        p.end()

    def _plate_text(self, p, x, y, text: str, color: QColor) -> None:
        """白底标签（压在格子上也能读）—— 位置夹在控件内，绝不画到看不见的地方。"""
        p.setFont(ui_painter_font(10, bold=True))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 10
        h = fm.height() + 2
        x = min(max(0.0, float(x)), max(0.0, self.width() - w))
        y = min(max(0.0, float(y)), max(0.0, self.height() - h))
        p.setBrush(QBrush(QColor(255, 255, 255, 235)))
        p.setPen(QPen(QColor("#E6EAF0")))
        p.drawRoundedRect(QRectF(x, y, w, h), 4, 4)
        p.setPen(QPen(color))
        p.drawText(int(x + 5), int(y + h - 4), text)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        v = self._vals
        if v is None or not len(self._xv):
            return
        cell, L, T, _c = self._geom()
        ix = int((ev.position().x() - L) // max(1, cell))
        iy = int((ev.position().y() - T) // max(1, cell))
        txt = ""
        if 0 <= iy < len(self._yv) and 0 <= ix < len(self._xv):
            val = float(v[iy, ix])
            txt = (f"{self._names[0]}={self._xv[ix]:g} · {self._names[1]}={self._yv[iy]:g}"
                   f" ⇒ 年化 " + ("没跑到" if val != val else f"{val:.2%}"))
        if txt != self._hover:
            self._hover = txt
            self.setToolTip(txt)
            self.update()


def fmt_pct(v) -> str:
    """百分比读数（NaN ⇒ 「—」，绝不冒充 0）—— 图内文字统一从这里取。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if f != f else f"{f:.1%}"


def fmt_pct(v) -> str:
    """百分比读数（NaN ⇒ 「—」，绝不冒充 0）—— 图内文字统一从这里取。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "—" if f != f else f"{f:.1%}"


class NeighborhoodBars(QWidget):
    """邻域稳健排行 —— ★R4-b 按设计稿重做（`_charts.js::neighbors`，手绘件）。

    【为什么改】上一版是"组合序 × 柱高"的匿名柱状图 —— 用户实测："根本不可读"。
    设计稿的口径是**一行一个组合、左边写参数**：

        条形 = 邻域均值（越长越好，前三名加粗+蓝）· 竖线 = **邻域最差**（绿=没塌、红=塌了）
        右侧 = 「邻域均值 / 邻域最差」两个数 · 橙条 = 样本内冠军那一格（"别看它"）
        ⇒ 排序按这个，**不看样本内冠军**

    只画前 `SHOW_MAX` 名（诚实截断，末行写明"共 N 组"）。
    """

    SHOW_MAX = 20
    ROW_H = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self._rows: list[tuple[str, float, float, bool]] = []   # (参数文本, mean, worst, is_champ)
        self._total = 0
        self._lo, self._hi = 0.0, 1.0
        self._row_h = float(self.ROW_H)
        self._vis = 0
        self._hover = ""

    def set_data(self, nb_mean, worst=None, labels=None,
                 champion: int | None = None) -> None:
        """`nb_mean` 邻域均值；`worst` 邻域最差；`labels` 每格的参数文本；`champion` 冠军下标。"""
        nb = np.asarray(nb_mean, dtype=float) * 100.0
        w = (np.full(nb.shape, np.nan) if worst is None
             else np.asarray(worst, dtype=float) * 100.0)
        n = nb.size
        idx = [i for i in np.argsort(-np.nan_to_num(nb, nan=-1e9)) if np.isfinite(nb[i])]
        self._rows = []
        for i in idx[:self.SHOW_MAX]:
            lab = (str(labels[i]) if labels is not None and i < len(labels) else f"组合 #{i + 1}")
            self._rows.append((lab, float(nb[i]),
                               float(w[i]) if np.isfinite(w[i]) else float("nan"),
                               champion is not None and int(champion) == int(i)))
        self._total = n
        fin = nb[np.isfinite(nb)]
        lo, hi = ((float(fin.min()), float(fin.max())) if fin.size else (0.0, 1.0))
        span = max(1e-6, hi - lo)
        step = 10 ** np.floor(np.log10(span / 4))
        for mult in (1, 2, 5, 10):
            if span / (step * mult) <= 6:
                step *= mult
                break
        self._step = float(step)
        self._lo, self._hi = lo, hi
        # ★R4-c：**不**按行数把自己撑高（否则图把右栏顶出窗口）—— 行高在 paintEvent 里
        #   按实际可用高度自适应（12~26px）；行数本来就有 SHOW_MAX 上限。
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(ui_painter_font(10))
        if not self._rows:
            p.setPen(QPen(QColor("#8A94A6")))
            p.drawText(12, 24, "还没有邻域读数 —— 跑完样本内 + 样本外后出图")
            p.end()
            return
        lab_w, right_w = 132, 96
        x0, x1 = lab_w + 10, max(lab_w + 40, self.width() - right_w - 10)
        lo, hi = self._lo, self._hi
        pos = min(0.0, lo)
        neg = max(0.0, hi)
        span = max(1e-6, neg - pos)
        X = lambda v: x0 + (float(v) - pos) / span * (x1 - x0)     # noqa: E731
        # ★R4-c：行高**自适应**（12~26px）—— 图不再靠行数撑高自己，右栏就永远不会被顶出窗口
        # ★R4-d：**先按可读行高（18px）定能显示几行**，再让行高在 18~26 之间撑开 ——
        #   旧版把行高压到 12px（下限），20 行文字与条形互相压在一起（用户实测"挤压在一块"）。
        #   行数本来就有 SHOW_MAX 上限、且已按邻域均值降序 ⇒ 少显示的一定是**排在后面的**。
        vis = max(4, min(len(self._rows), int((self.height() - 74) / 18.0)))
        row_h = max(14.0, min(float(self.ROW_H), (self.height() - 74) / max(1, vis)))
        self._row_h, self._vis = row_h, vis
        # 头两行：口径说明（照稿）
        # ★R4-e：那两行"口径说明"搬到图外说明行；图里只留一条 0 线与数据
        p.setPen(QPen(QColor("#C9D3E0")))
        p.drawLine(int(X(0)), 18, int(X(0)), int(22 + row_h * vis))
        for i, (lab, mean, worst, is_champ) in enumerate(self._rows[:vis]):
            y = 26 + i * row_h
            top3 = i < 3
            p.setFont(ui_painter_font(11, bold=top3))     # ★R4-e：11px（原 10.5 太小）
            p.setPen(QPen(QColor("#E65100" if is_champ else "#20242C")))
            p.drawText(int(2), int(y + 15), lab)
            bar_lo, bar_hi = min(0.0, mean), max(0.0, mean)
            fill = (QColor("#FBE3D6") if is_champ else
                    QColor("#D6E8FA") if top3 else QColor("#EDF2F8"))
            edge = (QColor("#E65100") if is_champ else
                    QColor("#1976D2") if top3 else QColor("#CBD6E4"))
            p.setBrush(QBrush(fill))
            p.setPen(QPen(edge))
            p.drawRoundedRect(QRectF(X(bar_lo), y + 5, max(2.0, X(bar_hi) - X(bar_lo)), 13), 3, 3)
            if np.isfinite(worst):
                p.setPen(QPen(QColor("#C62828" if worst < 0 else "#2E7D32"), 2))
                p.drawLine(int(X(worst)), int(y + 3), int(X(worst)), int(y + 20))
            p.setFont(ui_painter_font(10))
            p.setPen(QPen(QColor("#E65100" if is_champ else "#616B7A")))
            txt = (f"{mean:.2f} / " + ("—" if not np.isfinite(worst) else f"{worst:.2f}"))
            p.drawText(int(x1 + 6), int(y + 14), txt)
        p.setFont(ui_painter_font(9))
        p.setPen(QPen(QColor("#8A94A6")))
        # 迷你横轴（0 与两端各标一个数 —— 全为负值时"0 在右"才看得懂方向）
        ay = int(34 + row_h * vis)
        p.setFont(ui_painter_font(9))
        p.setPen(QPen(QColor("#8A94A6")))
        for val in {0.0, pos, neg}:
            p.drawText(int(X(val)) - 12, ay, f"{val:.1f}%")
        p.drawText(int(x0), int(min(self.height() - 6, ay + 14)),
                   f"横轴 = 邻域均值（%）· 只显示前 {vis} 名（共 {self._total} 组）")
        if self._hover:
            p.setPen(QPen(QColor("#3A4250")))
            p.setFont(ui_painter_font(10, bold=True))
            p.drawText(int(x0), self.height() - 6, self._hover)
        p.end()

    def caption(self) -> str:
        """图外说明行（★R4-e）。"""
        if not self._rows:
            return "邻域稳健 = 每个组合**周围一圈**的平均表现：前几名要站在一片高地上，别选孤峰"
        return ("条形 = 邻域均值（越长越好）· 竖线 = **邻域最差**（绿 = 没塌、红 = 塌了）· "
                "橙条 = 样本内冠军（自己高、邻居塌）· 排序按邻域均值，不看样本内冠军")

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        i = int((ev.position().y() - 26) // max(1.0, self._row_h))
        txt = ""
        if 0 <= i < min(len(self._rows), self._vis):     # ★R4-d：只对**画出来**的行出提示
            lab, mean, worst, is_champ = self._rows[i]
            txt = (f"{lab} ⇒ 邻域均值 {mean:.2f}% · 邻域最差 "
                   + ("—" if not np.isfinite(worst) else f"{worst:.2f}%")
                   + ("（样本内冠军：自己高、邻居塌）" if is_champ else ""))
        if txt != self._hover:
            self._hover = txt
            self.setToolTip(txt)
            self.update()


class RollingIC(_NoWheelPlot):
    """滚动 IC（12 折）—— ★R4-b 按设计稿重做（`_charts.js::rollIC`）。

    设计稿的三件事上一版都缺：**±0.15 门槛带**（绿虚线 + 淡绿底 + 一句"弱可用门槛"）、
    **低于门槛的点变红**（"多数折低于门槛 ⇒ 该参数化不稳定"，一眼看出）、**人读的刻度**
    （0.5 / 0.25 / 0 / -0.25 / -0.5）。折内算不出 IC ⇒ **断开**（不插值，也不补 0）。
    """

    THRESH = 0.15      # 弱可用门槛（与结论条那个 0.15 同一个数）
    FOLDS = 12

    def __init__(self, parent=None):
        super().__init__(parent, background="w")
        self.hideButtons()
        self.setMouseEnabled(x=False, y=True)
        self.showGrid(x=False, y=True, alpha=0.18)
        self.getAxis("bottom").setLabel("第几折（天轴等分 · walk-forward）")
        self.getAxis("left").setLabel("折内 Rank IC")
        for ax in ("bottom", "left"):
            self.getAxis(ax).setTickFont(ui_font(10))
        self._band = QGraphicsRectItem(QRectF(0, -self.THRESH, 1, 2 * self.THRESH))
        self._band.setPen(pg.mkPen("#2E7D32", style=Qt.PenStyle.DashLine))
        self._band.setBrush(pg.mkBrush(46, 125, 50, 16))
        self.addItem(self._band)
        self._hi = pg.InfiniteLine(pos=self.THRESH, angle=0, movable=False,
                                   pen=pg.mkPen("#2E7D32", style=Qt.PenStyle.DashLine))
        self._lo = pg.InfiniteLine(pos=-self.THRESH, angle=0, movable=False,
                                   pen=pg.mkPen("#2E7D32", style=Qt.PenStyle.DashLine))
        self.addItem(self._hi)
        self.addItem(self._lo)
        self._zero = pg.InfiniteLine(pos=0, angle=0, movable=False,
                                     pen=pg.mkPen("#C9D3E0", width=1.2))
        self.addItem(self._zero)
        self._line = pg.PlotDataItem(pen=pg.mkPen("#1976D2", width=2), connect="finite")
        self.addItem(self._line)
        self._dots = pg.ScatterPlotItem(size=7, hoverable=True)
        self._dots.sigHovered.connect(self._on_hover)   # 同上：0.14 只认 `data`
        self.addItem(self._dots)
        self._hover_tip = ""
        self._tag = pg.TextItem("IC 0.15（弱可用门槛）", color="#2E7D32", anchor=(0, 1))
        self.addItem(self._tag)

    def _on_hover(self, *args) -> None:
        pts = next((a for a in args if isinstance(a, (list, tuple))), None)
        txt = ""
        if pts:
            d = getattr(pts[0], "data", None)
            d = d() if callable(d) else d
            if isinstance(d, dict):
                d = d.get("tip") or d.get("data")
            txt = str(d or "")
        if txt != self._hover_tip:
            self._hover_tip = txt
            self.setToolTip(txt)

    def caption(self) -> str:
        """图外说明行（★R4-e）：把"这张图怎么读"写清楚，别塞在图里。"""
        return ("每折 = 该段时间里「前一半排序 → 后一半排序」的 Rank IC；"
                "绿带内（|IC| < 0.15）= 该折没有预测力 ⇒ 折线起伏 = 这套参数只在某几段灵"
                "（单个 Rank IC 会骗人）")

    def set_ic(self, values) -> None:
        arr = np.asarray(values, dtype=float)
        n = arr.size or self.FOLDS
        x = np.arange(arr.size)
        self._line.setData(x, arr)
        pts = []
        for i, v in enumerate(arr):
            if not np.isfinite(v):
                pts.append({"pos": (float(i), 0.0), "brush": pg.mkBrush(0, 0, 0, 0),
                            "pen": pg.mkPen("#9AA5B1", style=Qt.PenStyle.DotLine, width=1),
                            "size": 7, "data": f"第 {i + 1} 折：算不出（该段秩为常数）"})
                continue
            low = abs(float(v)) < self.THRESH
            pts.append({"pos": (float(i), float(v)),
                        "brush": pg.mkBrush("#C62828" if low else "#1976D2"),
                        "data": f"第 {i + 1} 折：IC {float(v):.2f}"
                                + ("（低于 0.15 门槛）" if low else "")})
        self._dots.setData(pts)
        self._band.setRect(QRectF(-0.5, -self.THRESH, max(1.0, n - 0.5), 2 * self.THRESH))
        self._tag.setPos(-0.3, self.THRESH * 1.15)
        self.setXRange(-0.5, max(1.5, n - 0.5), padding=0.02)
        finite = arr[np.isfinite(arr)]
        m = max(self.THRESH * 1.6, float(np.max(np.abs(finite))) * 1.15 if finite.size else 0.3)
        self.setYRange(-m, m, padding=0.02)
        step = max(0.05, round(m / 2, 2))
        self.getAxis("left").setTicks([[(float(v), f"{v:g}")
                                        for v in np.arange(-m, m + step, step)]])


class ChartSwitcher(QWidget):
    """★R4 ⑥：**四视图切换**（chip 单张占满宽 —— §6-2 用户拍板：默认单张，别挤）。

    【为什么单独成件】页面只该"装配 + 编排"（R0 拆件的纪律）；四个画布 + 色标 + 切换 chip
    都归本件。公共面（`scatter` / `heatmap`）与页面时代**同名** ⇒ `sweep_results` 与冒烟的
    既有调用点一个字都不用改。

    【视图】① 散点 IS×OOS ② 参数热力图（+ 色标）③ 邻域稳健 ④ 滚动 IC（12 折）。
    切到没数据的视图不会装死：图是空的，但**抬头的那句话说明它要看什么**。
    """

    VIEWS = (("scatter", "① 散点 IS×OOS"), ("heatmap", "② 参数热力图"),
             ("nb", "③ 邻域稳健"), ("roll", "④ 滚动 IC 12 折"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scatter = ScatterIso()
        self.heatmap = HeatmapGrid()
        self.nb = NeighborhoodBars()
        self.roll = RollingIC()
        self._chips: dict[str, object] = {}
        self.setMinimumHeight(300)          # ★1.66 口径：图体硬底线，亏空交给右栏滚动条
        # ★R4-c：同时给**上限** —— 用户实测"结果图过分的大，超过窗口、把候选表顶出去"。
        #   四视图高度按设计稿的图幅（约 340~420）+ chip 行取 460。
        self.setMaximumHeight(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        chips = QHBoxLayout()
        chips.setContentsMargins(8, 0, 8, 0)
        chips.setSpacing(6)
        self.lbl_scene = QLabel("")
        self.lbl_scene.setStyleSheet(SEC_HINT_QSS)
        for key, text in self.VIEWS:
            btn = build_chip(text, state="on")
            btn.clicked.connect(lambda _c=False, k=key: self.show_view(k))
            chips.addWidget(btn)
            self._chips[key] = btn
        chips.addStretch(1)
        lay.addLayout(chips)
        # ★R4-e：说明行**单独一行、整行宽、可换行**（原挂在 chip 行右侧 ⇒ 长句被切掉，
        #   而把长句塞进图里又会挡数据 —— 两头的病一个改法：说明搬到图外）。
        self.lbl_scene.setWordWrap(True)
        self.lbl_scene.setContentsMargins(8, 0, 8, 0)
        lay.addWidget(self.lbl_scene)

        self._stack = QStackedWidget()
        self._stack.setMinimumHeight(260)
        # ★R4-b：色标画在热力图内部（照设计稿）⇒ 这里不再另挂一条色标件
        for w in (self.scatter, self.heatmap, self.nb, self.roll):
            self._stack.addWidget(w)
        lay.addWidget(self._stack, 1)
        self.show_view("scatter")

    # ---------------- 切换 ----------------
    def view_key(self) -> str:
        return self.VIEWS[self._stack.currentIndex()][0]

    def show_view(self, key: str) -> None:
        idx = next((i for i, (k, _t) in enumerate(self.VIEWS) if k == key), 0)
        self._stack.setCurrentIndex(idx)
        for k, btn in self._chips.items():
            set_chip_state(btn, "sel" if k == key else "on")
        self.lbl_scene.setText({
            "scatter": "离对角线越远，样本内冠军在样本外塌得越狠",
            "heatmap": "蓝深 = 好、灰 = 亏钱；绿框格 = 平台（邻域均值 ≥ 上四分位，即前 25%）"
                       "· 橙圈 = 尖峰（自己高、邻居全塌）",
            "nb": "排序键第一项长什么样：柱越高越好，前几名要站在一片高地上",
            "roll": "折线起伏 = 这套参数只在某几段灵；全线贴 0 ⇒ 毫无预测力",
        }.get(key, ""))

    # ---------------- 数据（只 set_data，不重算）----------------
    def _caption_of(self, widget) -> None:
        """把该图自己的说明取出来写进说明行（图的作者最清楚怎么读它）。"""
        fn = getattr(widget, "caption", None)
        if callable(fn):
            self.lbl_scene.setText(str(fn()))

    def set_scatter(self, *a, **kw) -> None:
        self.scatter.set_data(*a, **kw)
        self._caption_of(self.scatter)

    def set_heatmap(self, *a, **kw) -> None:
        self.heatmap.set_grid(*a, **kw)
        self._caption_of(self.heatmap)

    def set_neighborhood(self, *a) -> None:
        self.nb.set_data(*a)
        self._caption_of(self.nb)

    def set_rolling_ic(self, *a) -> None:
        self.roll.set_ic(*a)
        self._caption_of(self.roll)

    def show_notice(self, key: str) -> None:
        """某个视图没有图可画时的**空态**（例如单维网格下的热力图）。"""
        if key == "heatmap":
            self.heatmap.show()          # ★R4-e：**不许再 hide**（隐藏 = 用户看到一片空白）
            self.heatmap.set_notice("热力图需要**两维**网格 —— 现在是单维："
                                    "把左栏第 2 维也选上参数，再跑一次")
            self._caption_of(self.heatmap)
        idx = next((i for i, (k, _t) in enumerate(self.VIEWS) if k == key), None)
        if idx is not None:
            self._stack.setCurrentIndex(idx)
            for k, btn in self._chips.items():
                set_chip_state(btn, "off" if k == key else "on")
