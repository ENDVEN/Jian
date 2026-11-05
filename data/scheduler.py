# data/scheduler.py
"""按 provider/channel 的调度器内核（★2.09 / DATA-PLATFORM P3-3）。

只做“谁能开始、何时开始、失败后等多久”，不取数、不碰 UI。
P3-4 再把 DownloadHub / StartupCheck 接到这里；本轮先保证调度规则可单测。

设计：
- 每个 channel 独立：in_flight / last_start / cooldown / fails / latency；
- 优先级：用户 > 自选/组合 > 启动 > 后台 backfill > 预取；
- 代理失败固定 300s；限流失败指数退避；连续两次成功才清零；
- max_concurrency 自适应：成功且 p95 低则升，失败/慢则降；
- 预算仍是 `em_auth` 的唯一职责，本模块不读取、不绕过。
"""
from __future__ import annotations

import heapq
import threading
import time
from dataclasses import dataclass, field

__all__ = ["PRIORITY", "ChannelPolicy", "Task", "ChannelState",
           "Scheduler", "SchedulerBusy"]


class SchedulerBusy(RuntimeError):
    """通道冷却/排队超过调用方允许的等待时间。"""


# 数值越小越优先
PRIORITY = {"user": 10, "watchlist": 20, "startup": 30,
            "backfill": 40, "prefetch": 50}


@dataclass(frozen=True)
class ChannelPolicy:
    name: str
    max_concurrency: int = 2
    min_interval: float = 0.0
    max_attempts: int = 3
    cooldown_base: float = 60.0
    cooldown_max: float = 600.0
    proxy_cooldown: float = 300.0


@dataclass
class Task:
    payload: object
    channel: str = "default"
    priority: int = PRIORITY["backfill"]
    attempts: int = 0
    not_before: float = 0.0
    done: bool = False
    running: bool = False


@dataclass
class ChannelState:
    in_flight: int = 0
    last_start: float = 0.0
    cooldown_until: float = 0.0
    fails: int = 0
    streak: int = 0
    last_latency: float = 0.0
    p95: float = 0.0
    max_concurrency: int = 2
    fail_class: str = ""


class Scheduler:
    """纯调度内核；调用方负责真正执行取数并回报 finish()。"""

    def __init__(self, policies=None, clock=time.monotonic):
        self._clock = clock
        self._policies = {p.name: p for p in (policies or [])}
        self._states = {}
        self._heap = []
        self._seq = 0
        self._lock = threading.RLock()

    def policy(self, channel: str) -> ChannelPolicy:
        return self._policies.get(str(channel),
                                  ChannelPolicy(str(channel)))

    def state(self, channel: str) -> ChannelState:
        key = str(channel)
        with self._lock:
            if key not in self._states:
                p = self.policy(key)
                self._states[key] = ChannelState(max_concurrency=p.max_concurrency)
            return self._states[key]

    def add(self, task: Task) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (int(task.priority), self._seq, task))

    def _discard_done(self) -> None:
        while self._heap and self._heap[0][2].done:
            heapq.heappop(self._heap)

    def next_ready(self, now: float = None) -> Task | None:
        """取当前可开始的最高优先级任务；不满足则返回 None（不阻塞）。

        不只检查堆顶：高优先级通道冷却时，其他健康通道仍应能跑。
        """
        now = self._clock() if now is None else float(now)
        with self._lock:
            self._discard_done()
            for _prio, _seq, task in sorted(self._heap, key=lambda x: (x[0], x[1])):
                if task.done or task.running or task.not_before > now:
                    continue
                st = self.state(task.channel)
                p = self.policy(task.channel)
                if st.cooldown_until > now:
                    continue
                if st.in_flight >= st.max_concurrency:
                    continue
                if st.last_start and now - st.last_start < p.min_interval:
                    continue
                return task
            return None

    def wait_seconds(self, now: float = None) -> float:
        """没有可开始任务时，建议等待多久；0 表示可重试。"""
        now = self._clock() if now is None else float(now)
        task = self.next_ready(now)
        if task is not None:
            return 0.0
        self._discard_done()
        if not self._heap:
            return 0.0
        task = self._heap[0][2]
        return self.wait_for(task, now)

    def wait_for(self, task: Task, now: float = None) -> float:
        """单个任务还要等多久才能 acquire；并发已满时返回 0.01（短轮询）。"""
        now = self._clock() if now is None else float(now)
        st = self.state(task.channel)
        p = self.policy(task.channel)
        if st.in_flight >= st.max_concurrency:
            return 0.01
        waits = [max(0.0, task.not_before - now),
                 max(0.0, st.cooldown_until - now)]
        if st.last_start:
            waits.append(max(0.0, p.min_interval - (now - st.last_start)))
        return max(waits or [0.0])

    def acquire(self, task: Task, now: float = None) -> bool:
        """尝试占用一个并发位；成功返回 True（线程安全）。"""
        now = self._clock() if now is None else float(now)
        with self._lock:
            st = self.state(task.channel)
            p = self.policy(task.channel)
            if (task.done or task.running or task.not_before > now
                    or st.cooldown_until > now):
                return False
            if st.in_flight >= st.max_concurrency:
                return False
            if st.last_start and now - st.last_start < p.min_interval:
                return False
            st.in_flight += 1
            st.last_start = now
            task.running = True
            return True

    def finish(self, task: Task, ok: bool, latency: float = 0.0,
               error_class: str = "") -> None:
        """执行完回报；失败写冷却，成功更新自适应并发。"""
        with self._lock:
            st = self.state(task.channel)
            st.in_flight = max(0, st.in_flight - 1)
            task.running = False
            task.done = True
            now = self._clock()
            if ok:
                st.streak += 1
                st.fails = 0
                st.last_latency = max(0.0, float(latency or 0.0))
                if st.p95 <= 0:
                    st.p95 = st.last_latency
                else:
                    st.p95 = st.p95 * 0.8 + st.last_latency * 0.2
                if st.streak >= 2:
                    st.cooldown_until = 0.0
                    st.fail_class = ""
                p = self.policy(task.channel)
                # 慢或刚恢复时不贸然升并发；连续成功且 p95 低才升一档
                if st.streak >= 2 and st.last_latency <= 2.0:
                    st.max_concurrency = min(max(1, p.max_concurrency),
                                             st.max_concurrency + 1)
                return

            st.streak = 0
            st.fails += 1
            st.fail_class = "proxy" if str(error_class) == "proxy" else "limit"
            p = self.policy(task.channel)
            if st.fail_class == "proxy":
                wait = p.proxy_cooldown
            else:
                wait = min(p.cooldown_base * (2 ** (st.fails - 1)),
                           p.cooldown_max)
            st.cooldown_until = now + max(0.0, wait)
            st.max_concurrency = max(1, st.max_concurrency - 1)

    def call(self, channel: str, fn, *, priority: int = None,
             max_wait: float = None):
        """在 channel 配额内执行一次 fn()（供 Sina/Tencent 等 HTTP 边界用）。

        `max_wait` 非空时，冷却/排队超过该秒数立即抛 `SchedulerBusy`，
        避免备源在一次失败后把调用方卡住 60–300s。
        不读也不绕过 `em_auth` 预算；预算仍由各 provider 自己负责。
        """
        task = Task(payload=None, channel=str(channel),
                    priority=priority if priority is not None
                    else PRIORITY["watchlist"])
        while not self.acquire(task):
            wait = self.wait_for(task)
            if max_wait is not None and wait > max_wait:
                raise SchedulerBusy(
                    f"{channel} 需等待 {wait:.1f}s（上限 {max_wait:.1f}s）")
            time.sleep(min(max(wait, 0.005), 0.2))
        started = time.perf_counter()
        try:
            result = fn()
        except Exception as e:                    # noqa: BLE001
            cls = "proxy" if "proxy" in str(e).lower() else ""
            self.finish(task, ok=False,
                        latency=time.perf_counter() - started,
                        error_class=cls)
            raise
        self.finish(task, ok=True, latency=time.perf_counter() - started)
        return result

    def stats(self) -> dict:
        return {k: {"in_flight": v.in_flight,
                    "max_concurrency": v.max_concurrency,
                    "fails": v.fails,
                    "streak": v.streak,
                    "cooldown_until": v.cooldown_until,
                    "p95": round(v.p95, 4),
                    "fail_class": v.fail_class}
                for k, v in self._states.items()}
