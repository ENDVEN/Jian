# ui/download_hub.py
"""
全局后台下载调度器 (v1.43 · §7-B11) —— 把"下载任务"的归属从**弹窗**搬到**主窗口**。

【为什么要有它 · 用户实测反馈驱动】
  批量预下载是一个 `QDialog.exec()` 的**模态弹窗**，而 `SyncWorker` 的 parent 就是弹窗本身。
  两个后果叠在一起：
    ① 模态 ⇒ 下载期间整个主界面被冻住，用户什么都不能做；
    ② 线程随弹窗生灭 ⇒ 想关窗口只能"中断并硬等 15 秒"（见旧 `_try_stop_worker`），
      于是用户被要求**守在旁边看进度条**。
  而"下载 5849 只 ≈ 几十分钟"恰恰是最不该占用界面的一件事。
  ⇒ 本模块只做一件事：**任务排队 + 串行执行 + 把进度广播出去**。
    窗口只负责收集参数；进度由主窗口底部下载条 / 导航角标 / 队列面板呈现。

【架构纪律】
  · 这里**不自造 QThread**（§2：`ui/workers.py` 是全 app 唯一 QThread 定义处）——
    本文件是 `QObject` 调度件，编排现成的 `ui.workers.SyncWorker`。
  · 数据层保持纯同步：`data/sync_service.py` 零 Qt、不知道有队列这回事。
    节流/熔断/定稿守卫/日历注入全在 worker 与 service 里，本模块一律不重复实现
    （`expected_latest` 的注入仍由 `ui.workers.inject_expected_latest` 在每批开始时做一次）。
  · **串行 K=1**：与"宁可慢也不封 IP"的既有取向一致。并发档是另一件事（§11.6 待拍板），
    不许顺手在这里加线程池。
  · 完成回执文案只有一个出口：`sync_service.abort_reason_text`（§7-E2）；
    指称下载按钮的文字只有一个出口：`custom_widgets.SYNC_ACTION_LABEL`（§11.5-80）。

【单一真源】进度真源在 hub。各页面原有的进度条一律**降级为投影**
  （订阅 `job_progress` / `job_finished`），绝不自存一份 —— 否则"两套进度打架"。
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from PyQt6.QtCore import QObject, pyqtSignal

from core.preferences import preferences
from data.sync_service import (DEFAULT_DOWNLOAD_CONCURRENCY, ZONE_KLINE,
                               ThrottlePolicy, abort_reason_text, failure_hint,
                               format_duration)
from ui.workers import SyncWorker

logger = logging.getLogger(__name__)

# 任务状态（面板与下载条共用同一套标签，别处不许再写中文状态字面量）
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUS_LABELS = {STATUS_QUEUED: "排队中", STATUS_RUNNING: "下载中",
                 STATUS_DONE: "已完成", STATUS_CANCELLED: "已中断"}
FINISHED_STATUSES = (STATUS_DONE, STATUS_CANCELLED)

KEEP_FINISHED = 20          # 面板里最多回看多少条已结束任务（纯内存，不落盘）


def download_policy_from_prefs(prefs=None) -> ThrottlePolicy:
    """★v1.45 / §7-B11 后续：从**全局下载偏好**构造节流策略（批量下载的唯一真源）。

    所有批量 submit（数据管理 / 预下载弹窗 / M2/M3）均经 `DownloadHub.submit` 读同一份，
    “一处调、处处生效”（编辑面 = `ui/dialogs/download_settings.py`）。
    【字段映射】`jitter: bool`(勾) → float 0.3/0.0；`concurrency` 夹进 [1, 4]（K≤4，与
    “宁可慢也不封 IP”一致）；其余逐项直读。
    【容错】偏好缺键/脏值 ⇒ 逐项回落默认（“锦上添花”原则，绝不让偏好坏了阻断下载）。
    :param prefs: 测试可注入带 `get()` 的对象；None ⇒ 用进程级 `preferences` 单例。
    """
    store = preferences if prefs is None else prefs
    try:
        d = store.get("download_prefs") or {}
    except Exception:  # noqa: BLE001 —— 偏好不可用 ⇒ 全默认
        d = {}
    base = ThrottlePolicy()
    try:
        interval = float(d.get("interval", base.interval))
    except (TypeError, ValueError):
        interval = base.interval
    try:
        breaker = int(d.get("circuit_breaker", base.circuit_breaker))
    except (TypeError, ValueError):
        breaker = base.circuit_breaker
    try:
        conc = int(d.get("concurrency", DEFAULT_DOWNLOAD_CONCURRENCY))
    except (TypeError, ValueError):
        conc = DEFAULT_DOWNLOAD_CONCURRENCY
    return ThrottlePolicy(
        interval=interval,
        jitter=0.3 if d.get("jitter", True) else 0.0,
        circuit_breaker=max(1, breaker),
        skip_fresh=bool(d.get("skip_fresh", True)),
        concurrency=max(1, min(4, conc)),
    )


def hub_of(owner):
    """取主窗口的下载队列（页面与流程件统一走它）。

    `owner` 可以是页面（自动取 `page.main_win`）也可以是主窗口；**拿不到就返回 None**
    ⇒ 调用方的互斥检查与后台提交自然降级成旧行为，不会因为这个件不存在而报错
    （测试里常用自建的假页面，根本没有 `main_win`）。
    """
    win = getattr(owner, "main_win", owner)
    return getattr(win, "downloads", None)


class SingleSyncGate:
    """单只同步的**互斥占位**（§7-B11）—— 唯一实现，别各处手写 `note_single/release_single`。

    【为什么收成一个件】单只同步（行情页 / 回测滞后补 / M3 指数补拉）本身**不进队列**
    （秒级、回包直接喂当页），但必须与批量任务互斥：同一个 parquet 不能有两个写者。
    早先的写法是每个调用方各存一个 `self._token` 再 `getattr` 回来释放 —— 一旦某条
    return 路径漏释放，`is_busy_for` 就**永久为真**（该标的再也同步不了，界面上还看不出原因）。
    ⇒ 收敛到这里：`blocked_by()` 问一句、`hold()` 占位（**幂等**）、`release()` 释放（**可重复调用**）。

        gate = SingleSyncGate(page)          # 构造一次，常驻
        if gate.blocked_by(symbol, zone):    # 命中 ⇒ 别启动，先告诉用户
            return
        gate.hold(symbol, zone)
        ...起 SingleSyncWorker...
        gate.release()                       # 回包里调用即可（漏调也不会误占）

    ⚠ `hub` **惰性取**（构造期页面可能还没挂上 `main_win`）⇒ 不写死在 `__init__` 里。
    """

    def __init__(self, owner=None):
        self._owner = owner
        self._token = None

    @property
    def _hub(self):
        return hub_of(self._owner) if self._owner is not None else None

    def blocked_by(self, symbol: str, zone: str = ZONE_KLINE) -> bool:
        """这只标的是否已在批量任务里 / 已被别的单只占着（命中就别再抓一遍）。"""
        hub = self._hub
        return hub is not None and hub.is_busy_for(symbol, zone)

    def hold(self, symbol: str, zone: str = ZONE_KLINE) -> None:
        """占位；**幂等**：已有占位先释放 —— 换标的/重试时不会泄漏旧占位。"""
        self.release()
        hub = self._hub
        if hub is not None:
            self._token = hub.note_single(symbol, zone)

    def release(self) -> None:
        """释放占位（可重复调用；没有占位时是空操作）。"""
        hub = self._hub
        if hub is not None and self._token is not None:
            hub.release_single(self._token)
        self._token = None


@dataclass
class DownloadJob:
    """一次批量下载任务（提交后不可变的部分 = 参数；可变的 = 进度与回执）。"""

    label: str                          # 用户能看懂的任务名（"全市场 A 股 日线"）
    symbols: list                       # 待抓取标的
    zone: str = ZONE_KLINE
    force_full: bool = False
    min_date: str | None = None
    policy: ThrottlePolicy | None = None
    origin: str = ""                    # 发起方标识：bulk / data_manager / scan / breadth
    id: int = 0
    status: str = STATUS_QUEUED
    done: int = 0
    total: int = 0
    current: str = ""
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        self.total = len(self.symbols)

    # ---- 展示（唯一出口：下载条与面板都从这里取文案，别各拼一遍）----
    @property
    def percent(self) -> int:
        return int(self.done * 100 / self.total) if self.total else 0

    @property
    def running(self) -> bool:
        return self.status == STATUS_RUNNING

    def progress_text(self) -> str:
        """运行中的一行短状态：`223/5849 · 正在处理 000622`。"""
        if self.status == STATUS_QUEUED:
            return f"排队中 · {self.total} 只"
        if self.running:
            return f"{self.done}/{self.total} · 正在处理 {self.current}"
        return self.receipt_text()

    def eta_text(self) -> str:
        """还剩多久 —— 按**剩余只数**估（不是总数），避免"永远 50 分钟"的劝退式预估。"""
        if not self.running or not self.total:
            return ""
        remain = max(0, self.total - self.done)
        interval = (self.policy.interval if self.policy is not None
                    else ThrottlePolicy().interval)
        return f"约剩 {format_duration(remain * interval)}"

    def receipt_text(self) -> str:
        """结束回执（成功 / 已最新 / 失败 + 中断原因）。原因只走 `abort_reason_text`。"""
        s = self.stats or {}
        base = (f"成功 {s.get('ok', 0)} · 已最新 {s.get('skipped', 0)}"
                f" · 失败 {s.get('fail', 0)} · 新增 {s.get('added', 0)} 行")
        spot = int(s.get('spot_hit', 0) or 0)      # ★v1.45：多少只走了 1 次全市场快照秒补
        if spot:
            base += f" · 其中 {spot} 只走快照秒补"
        why = abort_reason_text(s)
        if why:
            base = f"已中断：{why}（可再点「更新到最新」续传）· " + base
        return base

    @property
    def failures(self) -> list:
        return list((self.stats or {}).get("symbols_failed") or [])

    @property
    def hint_text(self) -> str:
        """有失败才给教学文案（原因只走 `sync_service.failure_hint` 单出口）。"""
        return failure_hint(self.stats) if self.failures else ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "origin": self.origin,
                "status": self.status, "done": self.done, "total": self.total,
                "current": self.current, "percent": self.percent,
                "text": self.progress_text(), "eta": self.eta_text(),
                "receipt": self.receipt_text(), "failed": len(self.failures)}


class DownloadHub(QObject):
    """串行下载队列（主窗口持有，与 `engine` 同级；页面经 `main_win.downloads` 取用）。"""

    jobs_changed = pyqtSignal()                        # 队列增删 / 状态变化
    job_progress = pyqtSignal(int, int, int, str)      # (job_id, done, total, symbol)
    job_failed = pyqtSignal(int, str, str)             # (job_id, symbol, 一句话原因)
    job_finished = pyqtSignal(int, dict)               # (job_id, stats)
    activity_changed = pyqtSignal(bool)                # 有没有活在跑（驱动角标与下载条显隐）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: deque[DownloadJob] = deque()
        self._jobs: list[DownloadJob] = []             # 全量（含已结束，供面板回看）
        self._running: DownloadJob | None = None
        self._worker: SyncWorker | None = None
        self._next_id = 1
        # 单只同步的"占位登记"：不排队、不接管回包，只用来避免与批量重复抓同一只
        self._singles: set[tuple[str, str]] = set()
        self._active_flag = False

    # ==========================================
    # 提交 / 查询
    # ==========================================
    def submit(self, label: str, symbols: Iterable[str], *, zone: str = ZONE_KLINE,
               force_full: bool = False, min_date: str = None,
               policy: ThrottlePolicy = None, origin: str = "") -> int:
        """投递一个批量下载任务，返回 job id（0 = 列表为空，什么都没投）。

        防手残：**完全相同的在途任务不重复入队**（同一批标的、同一分区、同一档力度）——
        用户连点两次「开始下载」不该把 5849 只抓两遍。
        """
        syms = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        if not syms:
            return 0
        # ★v1.45：未传策略 ⇒ 读全局下载偏好（间隔/抖动/熍断/跳过/并发均一处真源）；
        #   传了策略（目前仅单测/去重验证会传）⇒ 完全尊重它，不再自动升档。
        policy = policy if policy is not None else download_policy_from_prefs()
        dup = self._find_duplicate(syms, zone, force_full, min_date, policy)
        if dup is not None:
            logger.info(f"重复的下载任务被合并（已在 #{dup.id} {dup.status}）：{label}")
            return dup.id
        job = DownloadJob(id=self._next_id, label=label, symbols=syms, zone=zone,
                          force_full=force_full, min_date=min_date,
                          policy=policy,
                          origin=origin)
        self._next_id += 1
        self._jobs.append(job)
        self._queue.append(job)
        self._trim_finished()
        self.jobs_changed.emit()
        self._pump()
        return job.id

    def jobs(self) -> list:
        return list(self._jobs)

    def snapshot(self) -> list:
        """给队列面板的只读视图（面板不许存状态，只画这里给的东西）。"""
        return [j.to_dict() for j in self._jobs]

    def get(self, job_id: int) -> DownloadJob | None:
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None

    @property
    def current(self) -> DownloadJob | None:
        return self._running

    def next_queued(self) -> DownloadJob | None:
        """下一个在排队的任务（下载条在"还没开跑"时也要能显示排队数）。"""
        return self._queue[0] if self._queue else None

    def pending_count(self) -> int:
        return len(self._queue) + (1 if self._running is not None else 0)

    def is_busy(self) -> bool:
        return self._active_flag

    def last_finished(self) -> DownloadJob | None:
        """最近一条已结束任务 —— 下载条靠它在"全部跑完"后还留一句回执。"""
        for j in reversed(self._jobs):
            if j.status in FINISHED_STATUSES:
                return j
        return None

    # ==========================================
    # 中断 / 重试 / 清理
    # ==========================================
    def cancel(self, job_id: int = None) -> None:
        """`job_id=None` ⇒ 中断当前 + 清空排队；否则只停这一个（排队中的直接出队）。"""
        if job_id is None:
            for job in list(self._queue):
                job.status = STATUS_CANCELLED
                # ★ 排队中的任务也必须发 `job_finished`：消费方（M2/M3 的 `_syncing`、
                #   批量弹窗的 `_job_id`）**只靠它收尾** —— 漏发 = 页面永久卡在"进行中"，
                #   连「更新到最新」都点不动（§11.5-82 新增坑）。
                self._emit_finished(job, {"aborted": True, "aborted_by": "cancel"})
            self._queue.clear()
            if self._worker is not None:
                self._worker.cancel()
            self.jobs_changed.emit()
            self._settle_activity()
            return
        job = self.get(job_id)
        if job is None or job.status in FINISHED_STATUSES:
            return
        if job is self._running:
            if self._worker is not None:
                self._worker.cancel()          # 等当前这一只跑完再停（不硬杀线程）
        else:
            if job in self._queue:
                self._queue.remove(job)
            job.status = STATUS_CANCELLED
            self._emit_finished(job, {"aborted": True, "aborted_by": "cancel"})
        self.jobs_changed.emit()

    def retry_failures(self, job_id: int) -> int:
        """只重试失败清单（旧版只能在弹窗里手动复制清单再来一遍）。"""
        job = self.get(job_id)
        if job is None or not job.failures:
            return 0
        return self.submit(f"重试失败 · {job.label}", job.failures, zone=job.zone,
                           force_full=False, min_date=job.min_date,
                           policy=job.policy, origin=job.origin)

    def clear_finished(self) -> None:
        """面板里的「清空已完成」：只动内存，绝不动正在跑与排队的。"""
        self._jobs = [j for j in self._jobs if j.status not in FINISHED_STATUSES]
        self.jobs_changed.emit()

    # ==========================================
    # 单只同步的占位登记（不接管线程、不改回包路径）
    # ==========================================
    def note_single(self, symbol: str, zone: str = ZONE_KLINE) -> tuple:
        """登记一次单只同步（**不动 `activity_changed`**：秒级任务闪一下角标只会变噪声，
        它只用来与批量任务互斥）。"""
        token = (str(symbol), zone)
        self._singles.add(token)
        return token

    def release_single(self, token: tuple) -> None:
        self._singles.discard(token)

    def is_busy_for(self, symbol: str, zone: str = ZONE_KLINE) -> bool:
        """这只标的是否已在批量任务里 / 正在被单只同步 —— 命中就别再抓一遍。"""
        sym = str(symbol)
        if (sym, zone) in self._singles:
            return True
        pool = list(self._queue) + ([self._running] if self._running else [])
        return any(sym in job.symbols and job.zone == zone for job in pool)

    # ==========================================
    # 内部：串行执行
    # ==========================================
    def _find_duplicate(self, syms: list, zone: str, force_full: bool,
                        min_date: str = None, policy=None):
        """完全同参的在途任务（**起点与档力度也算"参"**）。

        ⚠ 去重键漏了 `min_date` 就会出现"同样清单、不同起点被判成重复 ⇒ 第二个发起方的
          数据范围被静默忽略"（属静默错值）；档力度（间隔/熔断）同理 —— 用户特意调慢的
          那一轮不该被并进快的那一轮。
        """
        pool = list(self._queue) + ([self._running] if self._running else [])
        want = self._policy_key(policy)
        for job in pool:
            if (job.zone == zone and job.force_full == force_full
                    and job.min_date == min_date
                    and self._policy_key(job.policy) == want
                    and job.symbols == syms):
                return job
        return None

    @staticmethod
    def _policy_key(policy) -> tuple:
        """档力度的可比签名（去重用；`None` 与默认策略视为同档）。"""
        if policy is None:
            return ()
        return (float(getattr(policy, "interval", 0.0) or 0.0),
                int(getattr(policy, "circuit_breaker", 0) or 0))

    def _trim_finished(self) -> None:
        finished = [j for j in self._jobs if j.status in FINISHED_STATUSES]
        if len(finished) > KEEP_FINISHED:
            drop = set(id(j) for j in finished[:len(finished) - KEEP_FINISHED])
            self._jobs = [j for j in self._jobs if id(j) not in drop]

    def _pump(self) -> None:
        """只有一个坑位：有任务在跑就等着；跑完再取下一个。"""
        if self._running is not None or not self._queue:
            return
        job = self._queue.popleft()
        job.status = STATUS_RUNNING
        self._running = job
        self._set_active(True)
        worker = SyncWorker(job.symbols, zone=job.zone, force_full=job.force_full,
                            min_date=job.min_date, policy=job.policy, parent=self)
        worker.progress.connect(self._on_progress)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()
        self.jobs_changed.emit()

    def _on_progress(self, done: int, total: int, symbol: str) -> None:
        job = self._running
        if job is None:
            return
        job.done, job.total, job.current = done, total, symbol
        self.job_progress.emit(job.id, done, total, symbol)

    def _on_failed(self, symbol: str, reason: str) -> None:
        """逐只失败透传出去（发起页的“失败清单”需要它）；队列自己不改任何口径。"""
        job = self._running
        if job is not None:
            self.job_failed.emit(job.id, symbol, reason)

    def _on_finished(self, stats: dict) -> None:
        job = self._running
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()          # 线程已结束 ⇒ 交还 Qt 回收（parent 是本 hub）
        if job is None:                   # 理论上不该发生：无跑动任务时的迟到回包 ⇒ 丢弃
            logger.warning("收到没有归属的下载回包，已丢弃")
            return
        job.stats = stats or {}
        if not (stats or {}).get("aborted"):
            job.done = job.total          # 正常跑完 ⇒ 100%；被中断 ⇒ **保留真实进度**
            #（拿中断时的数字充成 100% 就是假账：用户会以为已经下完了）
        job.current = ""
        job.status = (STATUS_CANCELLED if (stats or {}).get("aborted") else STATUS_DONE)
        self._running = None
        self._emit_finished(job, stats or {})
        self.jobs_changed.emit()
        self._pump()                      # 串行：接着跑下一个
        self._settle_activity()           # 全跑完 ⇒ 收起角标（下载条仍留一句回执）

    def _settle_activity(self) -> None:
        """没有跑动任务、也没有排队任务 ⇒ 收起活动标记（角标/下载条据此显隐）。

        ⚠ 必须**单独成方法**：`cancel(None)` 那条路不会走 `_on_finished`，
          少了它角标会一直亮着骗人。
        """
        if self._running is None and not self._queue:
            self._set_active(False)

    def _emit_finished(self, job: DownloadJob, stats: dict) -> None:
        self.job_finished.emit(job.id, stats or {})

    def _set_active(self, flag: bool) -> None:
        if flag == self._active_flag:
            return
        self._active_flag = flag
        self.activity_changed.emit(flag)

    # ==========================================
    # 退出守卫（主窗口 closeEvent 调用）
    # ==========================================
    def shutdown(self, wait_ms: int = 15000) -> None:
        """中断所有任务并等待线程结束。

        ⚠ 【为什么必须等】QThread 在运行时被销毁 = 程序崩溃（旧弹窗的 `_try_stop_worker`
          就为这件事写过 15 秒硬等）。这里同样：先请求中断，再等它自己结束。
        """
        self.cancel(None)
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(wait_ms)

    def has_unfinished(self) -> bool:
        """是否还有未完成（排队或在跑）的任务 —— 主窗口 closeEvent 的退出守卫用。

        ⚠ 普通方法、不是 @property（与 `pending_count()`/`is_busy()` 同形）：
          调用方写的是 `has_unfinished()`，若定义成 property 会返回 bool 再被 `()` 调 →
          `TypeError: 'bool' object is not callable`，且会在 `shutdown()` 之前抛 →
          线程没等就销毁（QThread destroyed while running）。
        """
        return self.pending_count() > 0
