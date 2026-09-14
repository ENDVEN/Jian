# ui/widgets/adaptive_axis.py
"""
坐标轴自适应公共件（§7-B4 · 全 App 唯一的"刻度/量程"来源）。

【要解决的两个真实问题】（§9-S 立项）
  ① **放大后横轴只剩一个刻度**：全 App 的 x 轴都是 **bar 序号**，日期只是"序号 → 文本"
     的映射，pyqtgraph 不知道这层映射，于是没人管刻度该变密/变疏/换格式；
  ② **纵轴不随可视区自适应**：放大时间轴后 y 仍钉在全量极值上 —— 副图最明显，
     跨 6 年的指标被压成一条看不见的线。
  参考实现早就存在（`backtest.py` 的 K 线/净值两处手写对了），但**没抽成公共件**，
  于是"改一处漏三处"（§9-O7 的同款教训）。本模块就是那次抽取。

【对外契约】
    compute_ticks(dates, i0, i1, ...)        # 纯函数：可视区间 → [(bar序号, 日期文本)]，零 Qt
    compute_text_ticks(texts, i0, i1, ...)   # 纯函数：同上，但文本直接给（序数轴用）
    slice_span(lo, hi, i0, i1)               # 纯函数：可视区间的 (最低, 最高)，NaN 自动忽略
    attach_date_axis(pane, dates, ...)       # 给一条轴挂"横轴刻度自适应"（可再给 y provider）
    follow_y(pane, provider, ...)            # 只挂"纵轴跟随可视区间"
    attach_all(host, dates, providers)       # 给整台 ChartHost 的每个窗格一次挂好

【provider 契约】`provider(i0, i1) -> (最低, 最高) | None`
  由**页面**回答"该窗格在可视 bar 区间内的数值范围"，因为每个窗格的数据形状不同：
  K 线用 high/low、量柱用 volume、MACD 要**含 0**、公式副图用 `overlay_extent`。
  本模块只负责"拿到范围后加上 padding 落到 y 轴"，不猜任何业务。

【纪律】
  · 纯 UI 公共件：零业务、零网络、不读数据；x 一律假定 **bar 序号**（与全 app 现状一致；
    `pg.DateAxisItem` 那种 epoch 秒的轴不适用本模块）。
  · **重复 attach 同一条轴 = 自动替换旧跟随器**（内部弱引用登记表）——
    页面每次重渲染都可以无脑调，不会累积信号连接（§9-O7 类泄漏的预防）。
  · 只有**最下窗格**算横轴刻度：x 联动的窗格重复显示刻度会互相压字（宿主已隐藏其刻度值）。
    但 **y 跟随必须逐窗格** —— 每张图的数据范围各不相干。
"""
from __future__ import annotations

import math
import weakref

import numpy as np
import pandas as pd

from ui.widgets.chart_pane import ChartPane

DEFAULT_TARGET_TICKS = 8
MIN_TARGET_TICKS = 2
DEFAULT_PAD = 0.06

# 单个刻度标签的估算宽度（px）：按轴的像素长度算"这一屏放得下几个刻度"，
# 否则窄窗口下会出现标签互相压字（比"只剩一个刻度"更难看的失败模式）。
_LABEL_WIDTH_PX = {
    '%H:%M': 46,
    '%m-%d': 46,
    '%Y-%m': 54,
    '%Y-%m-%d': 76,
    '%m-%d %H:%M': 96,
    '%Y-%m-%d %H:%M': 118,
}
_FALLBACK_LABEL_PX = 76

# 轴 → 跟随器（弱引用，自动随 ViewBox 回收；重复 attach 时用来"顶掉"旧的）
_HANDLES: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


# ==========================================
# 纯函数（无 Qt，可单测）
# ==========================================
def visible_span(view_box, n: int | None = None) -> tuple[int, int]:
    """可视 x 区间 → 可视 bar 序号 `(i0, i1)`（**向下取整**，保证刻度不落到可视区外）。

    :param n: bar 总数。给了就夹到 `[0, n-1]`（横轴刻度必须两端可读）；不给则只夹下界
              （纵轴跟随不需要知道总数 —— numpy 切片对超界上界是宽容的）。
    """
    try:
        x0, x1 = view_box.viewRange()[0]
    except Exception:  # noqa: BLE001 —— 首帧/已销毁时不致命
        x0, x1 = 0.0, 0.0
    if not (math.isfinite(x0) and math.isfinite(x1)):
        x0, x1 = 0.0, (n - 1 if n else 0)
    i0 = max(0, int(math.floor(x0)))
    i1 = int(math.floor(max(x1, x0)))
    if n is not None and n > 0:
        i0 = min(i0, n - 1)
        i1 = min(max(i1, i0), n - 1)
    return i0, max(i1, i0)


def axis_px(axis) -> float | None:
    """轴在屏幕上的可用长度（px）。离屏首帧拿不到几何 → None（调用方退回 target_ticks）。"""
    try:
        rect = axis.geometry()
    except Exception:  # noqa: BLE001
        return None
    if rect is None:
        return None
    width = float(rect.width())
    return width if width > 8 else None


def choose_date_format(dates, i0: int, i1: int) -> str:
    """按可视区间的**跨度与年份关系**选日期格式（统一口径，全 app 只有这一份）。

    梯子（与 §7-B4 规格 / 原 `backtest.py` 参考实现一致）：
      · 日内数据（任一时刻带时分）→ 同日 `%H:%M`，跨日 `%m-%d %H:%M`；
      · 跨年 → 跨度 ≤ 90 根用 `%Y-%m-%d`（"哪一天"要能辨），否则 `%Y-%m`；
      · 同年 → `%m-%d`。
    ⚠ 将来做分钟线（`kline_min`）**只改这里**，页面一行都不用动（这正是抽公共件的意义）。
    """
    first, last = dates[i0], dates[i1]
    span = i1 - i0 + 1
    try:
        intraday = bool(first.hour or first.minute or last.hour or last.minute)
    except (AttributeError, ValueError):
        return '%Y-%m-%d'
    if intraday:
        return '%H:%M' if first.date() == last.date() else '%m-%d %H:%M'
    if first.year != last.year:
        return '%Y-%m-%d' if span <= 90 else '%Y-%m'
    return '%m-%d'


def estimate_label_px(text: str) -> float:
    """粗估一个刻度标签的像素宽度（CJK 按 13px、其余按 7.5px，+10px 间距）。

    用于**文本刻度**（如资金 K 线的"5日"）—— 这类轴没有固定的格式表可查。
    """
    wide = sum(1 for char in text if ord(char) > 0x2E80)
    return 10.0 + wide * 13.0 + (len(text) - wide) * 7.5


def _tick_indexes(i0: int, i1: int, *, target_ticks: int,
                  per_label_px: float, width_px: float | None) -> list:
    """刻度密度：按轴的像素长度估"这一屏放得下几个"，窄窗口自动变疏。"""
    budget = max(MIN_TARGET_TICKS, int(target_ticks))
    if width_px and per_label_px > 0:
        budget = max(MIN_TARGET_TICKS, min(budget, int(width_px // per_label_px)))
    step = max(1, math.ceil((i1 - i0 + 1) / max(1, budget)))
    indexes = list(range(i0, i1 + 1, step))
    if indexes[-1] != i1:
        indexes.append(i1)          # 右端补齐（左端天然是 i0）
    return indexes


def compute_ticks(dates, i0: int, i1: int, *, target_ticks: int = DEFAULT_TARGET_TICKS,
                  width_px: float | None = None) -> list:
    """可视区间 → 刻度列表 `[(bar序号, 文本), ...]`（文本由**日期格式梯子**决定）。

    · 刻度密度：由 `width_px` 估"放得下几个"（窄窗口自动变疏），拿不到宽度就用 `target_ticks`；
    · **两端一定有刻度**：可视区边界是用户判断"我看到哪儿"的锚点，缺了会失去方位感；
    · 日期无法解析（NaT）的 bar 不给刻度 —— 宁可不显示，也不在轴上写 "NaT"。
    """
    if dates is None or len(dates) == 0:
        return []
    n = len(dates)
    i0 = max(0, min(n - 1, int(i0)))
    i1 = max(i0, min(n - 1, int(i1)))
    fmt = choose_date_format(dates, i0, i1)
    indexes = _tick_indexes(i0, i1, target_ticks=target_ticks, width_px=width_px,
                            per_label_px=_LABEL_WIDTH_PX.get(fmt, _FALLBACK_LABEL_PX))
    ticks = [(index, _label(dates[index], fmt)) for index in indexes]
    return [tick for tick in ticks if tick[1]]


def compute_text_ticks(texts, i0: int, i1: int, *, target_ticks: int = DEFAULT_TARGET_TICKS,
                       width_px: float | None = None) -> list:
    """可视区间 → 刻度列表，文本**直接取自给定序列**（不套日期格式梯子）。

    给"看着像日期、其实是序数"的轴用：复盘页**资金 K 线**的 x 是"当月第几日"
    （`2日 / 5日 / 9日…`，只含当月有交易的日），套 `%m-%d` 反而会说谎。这类轴需要的是
    **密度自适应**（原来把 20 多个标签全写上去，窄窗口必定互相压字），而不是格式自适应。
    """
    if texts is None or len(texts) == 0:
        return []
    n = len(texts)
    i0 = max(0, min(n - 1, int(i0)))
    i1 = max(i0, min(n - 1, int(i1)))
    sample = str(texts[i0]) or "0"
    indexes = _tick_indexes(i0, i1, target_ticks=target_ticks, width_px=width_px,
                            per_label_px=estimate_label_px(sample))
    return [(index, str(texts[index])) for index in indexes]


def slice_span(lo, hi, i0: int, i1: int):
    """可视 bar 区间的 `(最低, 最高)`；无有效数值返回 None。

    `lo` / `hi` 是**逐 bar 极值数组**（可为 None；`±inf` / NaN 一律忽略 —— 指标预热区
    和"该 bar 无叠层"都靠 NaN 表达）。传 `np.fmin(a, b)` 可先把两路数据并成一路。
    """
    pieces = []
    for array in (lo, hi):
        if array is None:
            continue
        values = np.asarray(array, dtype=float)[i0:i1 + 1]
        values = values[np.isfinite(values)]
        if values.size:
            pieces.append(values)
    if not pieces:
        return None
    merged = np.concatenate(pieces)
    return float(merged.min()), float(merged.max())


# ==========================================
# 跟随器：一条轴上的"重算刻度 + 跟随量程"
# ==========================================
def _normalize_dates(dates) -> list:
    """把任意日期序列（Series / list / np.datetime64 / date / 字符串）规整成 Timestamp 列表。"""
    try:
        return list(pd.to_datetime(list(dates)))
    except Exception:  # noqa: BLE001 —— 混入无法解析的值时逐个降级为 NaT
        normalized = []
        for value in dates:
            try:
                normalized.append(pd.Timestamp(value))
            except Exception:  # noqa: BLE001
                normalized.append(pd.NaT)
        return normalized


def _label(value, fmt: str) -> str:
    try:
        text = value.strftime(fmt)
    except (AttributeError, ValueError):
        return ""
    return "" if text == "NaT" else text


class AxisHandle:
    """一条轴上的自适应跟随器：`sigXRangeChanged` → 重算横轴刻度（可选）+ 纵轴量程。

    由 `attach_date_axis()` / `follow_y()` 创建，页面通常不需要直接 new。
    """

    def __init__(self, pane, dates=None, *, texts=None, target_ticks: int = DEFAULT_TARGET_TICKS,
                 is_bottom: bool = True, y_provider=None, pad: float = DEFAULT_PAD):
        self._pane = ChartPane.wrap(pane)
        self._plot_item = self._pane.plot_item
        self._view_box = self._plot_item.getViewBox()
        self._dates = _normalize_dates(dates) if dates is not None else None
        self._texts = list(texts) if texts is not None else None
        self._target_ticks = max(MIN_TARGET_TICKS, int(target_ticks))
        self._is_bottom = bool(is_bottom)
        self._y_provider = y_provider
        self._y_enabled = y_provider is not None
        self._pad = float(pad)
        self._ticks: list = []
        self._connected = False
        if self._dates is not None or self._texts is not None or self._y_provider is not None:
            self._view_box.sigXRangeChanged.connect(self._on_x_range_changed)
            self._connected = True
        self.refresh()

    # ---------------- 查询 ----------------
    @property
    def pane(self) -> ChartPane:
        return self._pane

    @property
    def view_box(self):
        return self._view_box

    @property
    def dates(self) -> list | None:
        return self._dates

    @property
    def total_bars(self) -> int:
        """本轴已知的 bar 总数（日期轴与文本轴二选一；都没有则 0）。"""
        source = self._texts if self._texts is not None else self._dates
        return len(source) if source is not None else 0

    @property
    def attached(self) -> bool:
        """是否仍监听缩放信号（被同轴的后来者顶掉后变 False —— 幂等契约的探针）。"""
        return self._connected

    @property
    def ticks(self) -> list:
        """最近一次算出的刻度（供断言/调试：直接看"轴上到底写了什么"）。"""
        return list(self._ticks)

    @property
    def tick_count(self) -> int:
        return len(self._ticks)

    @property
    def y_enabled(self) -> bool:
        return self._y_enabled

    @property
    def y_range(self) -> tuple:
        return tuple(self._view_box.viewRange()[1])

    # ---------------- 动作 ----------------
    def set_y_enabled(self, enabled: bool) -> None:
        """开关"纵轴跟随"（回测页的「价格轴跟随可视区间」开关就是接在这里）。"""
        enabled = bool(enabled)
        if enabled == self._y_enabled:
            return
        self._y_enabled = enabled
        self.refresh()

    def set_y_provider(self, provider, *, pad: float | None = None) -> None:
        self._y_provider = provider
        if pad is not None:
            self._pad = float(pad)
        self._y_enabled = provider is not None
        self.refresh()

    def refresh(self) -> None:
        """按当前可视区间重算刻度与量程（挂上时、缩放时、换数据后都可显式调）。"""
        total = self.total_bars or None
        i0, i1 = visible_span(self._view_box, total)
        if self._is_bottom and (self._dates is not None or self._texts is not None):
            axis = self._plot_item.getAxis('bottom')
            width_px = axis_px(axis)
            if self._texts is not None:
                self._ticks = compute_text_ticks(self._texts, i0, i1,
                                                 target_ticks=self._target_ticks,
                                                 width_px=width_px)
            else:
                self._ticks = compute_ticks(self._dates, i0, i1,
                                            target_ticks=self._target_ticks,
                                            width_px=width_px)
            axis.setTicks([self._ticks] if self._ticks else [])
        if self._y_enabled and self._y_provider is not None:
            span = None
            try:
                span = self._y_provider(i0, i1)
            except Exception:  # noqa: BLE001 —— provider 是页面给的，出错不许炸掉缩放
                span = None
            if span is not None:
                lo, hi = float(span[0]), float(span[1])
                if math.isfinite(lo) and math.isfinite(hi):
                    if hi < lo:
                        lo, hi = hi, lo
                    pad = (hi - lo) * self._pad or (abs(hi) * 0.01 or 1.0)
                    # ⚠ `padding=0` 不是可选项：pyqtgraph 的 `setYRange` 默认会在**我们给的
                    # 范围之上再叠一层它自己的 defaultPadding**(≈2%~4.7%，随 autoPadding 状态漂移)
                    # —— 那会让"y == 可视极值 ± 6%"变成一个永远差一点的幽灵数值，
                    # 断言没法写、调参也调不准（v6.15 实测：同一次调用能差出 0.2% 的幅宽）。
                    # 因此量程**完全**由本函数算出的 lo/hi 决定，外层不再有任何隐藏加成。
                    self._view_box.setYRange(lo - pad, hi + pad, padding=0)

    def detach(self) -> None:
        """摘掉信号连接（页面销毁/换轴时调用）。重复调用安全。"""
        if not self._connected:
            return
        try:
            self._view_box.sigXRangeChanged.disconnect(self._on_x_range_changed)
        except (TypeError, RuntimeError):
            pass
        self._connected = False

    # ---------------- 内部 ----------------
    def _on_x_range_changed(self, *_args) -> None:
        self.refresh()


def _register(handle: AxisHandle) -> None:
    """把跟随器登记到它的 ViewBox 上，并顶掉（detach）同一条轴上的旧跟随器。"""
    view_box = handle.view_box
    try:
        previous = _HANDLES.get(view_box)
        if previous is not None and previous is not handle:
            previous.detach()
        _HANDLES[view_box] = handle
    except (TypeError, RuntimeError):  # noqa: BLE001 —— ViewBox 已销毁 / 不可弱引用
        pass


def handle_for(pane) -> "AxisHandle | None":
    """取某条轴上**当前生效**的跟随器（供测试/调试/后续调参；页面平时不需要）。

    这是弱引用登记表唯一对外的读口 —— 断言就能直接问"这条轴上到底写了什么刻度"，
    而不必去翻 pyqtgraph 的私有 `_tickLevels`。
    """
    try:
        return _HANDLES.get(ChartPane.wrap(pane).plot_item.getViewBox())
    except (TypeError, RuntimeError):  # noqa: BLE001 —— 视图已销毁
        return None


def attach_date_axis(pane, dates=None, *, texts=None, target_ticks: int = DEFAULT_TARGET_TICKS,
                     is_bottom: bool = True, y_provider=None,
                     pad: float = DEFAULT_PAD) -> AxisHandle:
    """给一条轴挂上"横轴刻度自适应"（给了 `y_provider` 就同时跟随纵轴量程）。

    :param pane:        `ChartPane` / `pg.PlotItem` / `pg.PlotWidget`
    :param dates:       与 x 轴一一对应的**日期**序列（None = 只要 y 跟随，不要刻度）
    :param texts:       与 x 轴一一对应的**纯文本**刻度（序数轴用，如资金 K 线的"5日"）；
                        与 `dates` 二选一，同时给则以 `texts` 为准
    :param is_bottom:   本轴是否显示刻度值（ChartHost 里只有最下窗格为 True）
    :param y_provider:  `provider(i0, i1) -> (lo, hi) | None`，见模块头契约
    ⚠ **幂等**：同一条轴重复 attach 会自动 detach 旧的，页面每次重渲染无脑调即可。
    """
    handle = AxisHandle(pane, dates, texts=texts, target_ticks=target_ticks,
                        is_bottom=is_bottom, y_provider=y_provider, pad=pad)
    _register(handle)
    return handle


def follow_y(pane, provider, *, pad: float = DEFAULT_PAD,
             target_ticks: int = DEFAULT_TARGET_TICKS) -> AxisHandle:
    """只挂"纵轴跟随可视区间"（横轴刻度交给别的轴或另一次 attach）。"""
    return attach_date_axis(pane, None, target_ticks=target_ticks,
                            y_provider=provider, pad=pad)


# ==========================================
# 一台 ChartHost 的总管
# ==========================================
class AdaptiveAxes:
    """一台 `ChartHost` 的自适应坐标轴总管（页面持有一个，每次重渲染调 `attach`）。

    · 横轴刻度只挂在**最下窗格**（x 联动，其余窗格不显示刻度值）；
    · 纵轴跟随**逐窗格**（各自 provider）。
    """

    def __init__(self, host, *, target_ticks: int = DEFAULT_TARGET_TICKS,
                 pad: float = DEFAULT_PAD):
        self._host = host
        self._target_ticks = int(target_ticks)
        self._pad = float(pad)
        self._handles: dict = {}

    # ---------------- 查询 ----------------
    @property
    def handles(self) -> dict:
        return dict(self._handles)

    @property
    def pane_names(self) -> list:
        return list(self._handles)

    def handle(self, pane_name: str) -> AxisHandle | None:
        return self._handles.get(pane_name)

    def ticks_of(self, pane_name: str) -> list:
        handle = self._handles.get(pane_name)
        return handle.ticks if handle is not None else []

    # ---------------- 动作 ----------------
    def attach(self, dates, providers_by_pane=None) -> "AdaptiveAxes":
        """按当前窗格结构重新挂一遍（先摘旧的，幂等）。返回自身便于链式调用。"""
        self.detach()
        providers = dict(providers_by_pane or {})
        bottom = self._host.bottom_axis_pane
        for pane in self._host.panes:
            provider = providers.get(pane.name)
            wants_ticks = pane.name == bottom
            if not wants_ticks and provider is None:
                continue                    # 既不算刻度也不跟随量程 → 不必挂
            self._handles[pane.name] = attach_date_axis(
                pane, dates if wants_ticks else None,
                target_ticks=self._target_ticks, is_bottom=wants_ticks,
                y_provider=provider, pad=self._pad)
        return self

    def refresh(self) -> None:
        for handle in self._handles.values():
            handle.refresh()

    def detach(self) -> None:
        for handle in self._handles.values():
            handle.detach()
        self._handles.clear()


def attach_all(host, dates, providers_by_pane=None, *,
               target_ticks: int = DEFAULT_TARGET_TICKS, pad: float = DEFAULT_PAD) -> AdaptiveAxes:
    """便捷入口：给整台 ChartHost 一次挂好，返回总管（后续要 `refresh/detach` 用它）。"""
    return AdaptiveAxes(host, target_ticks=target_ticks, pad=pad).attach(
        dates, providers_by_pane)
