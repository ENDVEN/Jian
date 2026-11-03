# ui/workers_throttle.py
"""下载节流 / 交易日历注入的**无 Qt 辅助件**（★2.04 / P2 拆件）。

从 `ui/workers.py` 抽出：`RateGovernor`（全局请求节流阀）、`inject_expected_latest`
（每批只取一次日历）、`_load_calendar_safely`。它们不创建 QThread、不发信号，
只是被 `SyncWorker` 等线程类调用；单独成文件便于单测与降低 workers.py 体积。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace

from data.sync_service import ThrottlePolicy
from data.trade_calendar import latest_settled_trading_day, load_or_fetch

__all__ = ["RateGovernor", "inject_expected_latest", "_load_calendar_safely",
           "_CAL_UNSET"]

logger = logging.getLogger(__name__)

# `inject_expected_latest` 的“日历未提供”哨兵（区别于“提供了但为 None”）。
_CAL_UNSET = object()


def _load_calendar():
    """取一次日历；**优先用 `ui.workers.load_or_fetch`**（兼容旧打桩点）。

    拆件前测试在 `ui.workers` 上替换 `load_or_fetch`；这里惰性取，避免 import 环，
    也让旧打桩点继续生效。取不到模块时回落到本模块的导入。
    """
    try:
        from ui import workers as _workers_mod
        fn = getattr(_workers_mod, "load_or_fetch", load_or_fetch)
    except Exception:  # noqa: BLE001
        fn = load_or_fetch
    return fn()


def inject_expected_latest(policy: ThrottlePolicy = None, calendar=_CAL_UNSET) -> ThrottlePolicy:
    """★v1.40/§7-E5：把「最近一个已收盘定稿的交易日」注入节流策略（**每批只取一次**）。

    【为什么由 ui/workers 干这件事】`data/trade_calendar` 已依赖 `data/sync_service`
    （它用 `is_daily_bar_settled`），反向 import 会**成环**；而日历**每批只该取一次**
    （冷缓存时含一次网络），绝不能每只标的都取。本模块是唯一调度层，天然持有"批量上下文"。

    【拿不到日历怎么办】原样返回策略（`expected_latest` 保持 None）⇒ `refresh_one`
    完全回落到旧的"末日 == 今天"判据，**不改变任何既有语义** —— 离线也能正常工作
    （只是可能多跑一次空增量，与旧行为一模一样）。

    :param policy: 调用方策略；`None` 时用默认策略。调用方已显式注入时**尊重它**（便于测试打桩）。
    :param calendar: ★v1.45：调用方已取好的日历（`SyncWorker` 一次取、inject 与 spot 共用）。
        传入则**不再自己取**（保证“每批只取一次”）；默认哨兵 `_CAL_UNSET` 才回落到自己取。
    """
    if policy is None:
        policy = ThrottlePolicy()
    if getattr(policy, "expected_latest", None) is not None:
        return policy
    try:
        cal = _load_calendar() if calendar is _CAL_UNSET else calendar
        expected = latest_settled_trading_day(calendar=cal)
    except Exception as e:  # noqa: BLE001 —— 日历故障绝不阻断下载（宁可退回旧判据）
        logger.warning("交易日历不可用，本次按旧判据判新鲜度（可能多跑空增量）: %s", e)
        return policy
    if expected is None:
        return policy
    return replace(policy, expected_latest=expected)


def _load_calendar_safely():
    """★v1.45：取**一次**交易日历（inject 与 spot 共用），失败 ⇒ None。

    【为何单独一个函数】日历每批只能取一次（§7-E5 硬约束）；而 spot 秒补又要用同一份
    日历算相邻交易日 ⇒ 在 `run()` 里取一次、分别喂给 inject（传入 calendar）与 spot。
    """
    try:
        return _load_calendar()
    except Exception as e:  # noqa: BLE001 —— 日历故障绝不阻断下载（退回旧判据、不开秒补）
        logger.warning("交易日历不可用，本次退回旧判据且不启用快照秒补: %s", e)
        return None


class RateGovernor:
    """★v1.44 / §7-B11 后续：**全局请求发起节流阀**（并发池的防封 IP 核心件）。

    【为什么不是"各线程各睡 interval"】那样并发 K 路会把聚合请求率×K —— 那才是招封 IP 的根源。
    本件让 K 个线程在**一条共享时间线**上各自预约一个 `duration` 宽的槽位，睡到自己的槽到点再放行；
    锁只在"预约"一瞬持有、**睡眠在锁外** ⇒ 各线程的网络往返真正重叠。
    结果：**聚合发起节奏 == 串行时的 interval（请求率不变 ⇒ 封 IP 风险持平）**，
    提速全靠把每只的 fetch 往返藏进别的等待里（相同请求率下约 2×）。

    当 `ThrottlePolicy.sleep(sleep_fn)` 被调用时，本件的 `throttle` 即充当 `sleep_fn`：
      · 正常预抓取节流 → 传入含 jitter 的 interval；
      · 失败指数退避 → 传入退避秒数（同样按全局排队，更温柔）。
    时钟/睡眠器可注入（单测用假时钟断言"相邻发起间隔 ≥ interval"、不真等）。
    """

    def __init__(self, clock=time.monotonic, sleeper=time.sleep):
        self._lock = threading.Lock()
        self._next = 0.0
        self._clock = clock
        self._sleeper = sleeper

    def reserve(self, duration: float) -> float:
        """在共享时间线上预约一个宽 `duration` 的槽，返回该槽的**起始时刻**（不发呆）。"""
        duration = max(0.0, float(duration or 0.0))
        with self._lock:
            now = self._clock()
            start = now if now >= self._next else self._next
            self._next = start + duration
        return start

    def throttle(self, duration: float) -> None:
        """充当 `refresh_one` 的 `sleep_fn`：预约一个槽并睡到点（睡在锁外 ⇒ 允许重叠）。"""
        duration = max(0.0, float(duration or 0.0))
        if duration <= 0:
            return
        start = self.reserve(duration)
        remaining = start - self._clock()
        if remaining > 0:
            self._sleeper(remaining)
