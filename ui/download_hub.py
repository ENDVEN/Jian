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
from typing import Iterable

from PyQt6.QtCore import QObject, pyqtSignal

from core.preferences import preferences
from data.sync_service import (DEFAULT_DOWNLOAD_CONCURRENCY, ZONE_KLINE,
                               ThrottlePolicy,
                               format_duration)
from ui.workers import SyncWorker

# ★v6.70 / §4 体积债：任务形状、状态口径、单只互斥已拆到 `ui/download_jobs.py`
#   （纯搬家）。这里**再导出**一遍 ⇒ 既有 `from ui.download_hub import ...` 零改动。
from ui.download_jobs import (DownloadJob, SingleSyncGate, hub_of,  # noqa: F401
                              STATUS_QUEUED, STATUS_RUNNING, STATUS_DONE,
                              STATUS_CANCELLED, STATUS_LABELS,
                              FINISHED_STATUSES, KEEP_FINISHED)


logger = logging.getLogger(__name__)

# ★v6.70 / §9-F①：退出等待**超时**时，仍在跑的 worker 挂到这里。
# 【为什么必须留引用】它的 parent 是 hub（随主窗口销毁）——若不摘 parent 并**握住引用**，
#   Python 对象被回收 = C++ QThread 在运行中被 delete = 崩（就是那条
#   `QThread: Destroyed while thread is still running`）。摘了 parent + 本列表握着，
#   最坏情况只是“一条日志 + 进程退出时操作系统收尾”，而不是必崩。
_ORPHAN_WORKERS: list = []


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
    # ★v6.74：兜底默认改取 `preferences.DEFAULTS['download_prefs']`（**唯一真源**）——
    #   否则"偏好默认一套、`ThrottlePolicy` 字段默认另一套"会静默漂移（B 档 0.5/2）。
    _defs = {}
    try:
        from core.preferences import DEFAULTS as _ALL_DEFAULTS
        _defs = dict(_ALL_DEFAULTS.get('download_prefs') or {})
    except Exception:  # noqa: BLE001 —— 偏好模块不可用 ⇒ 退回字段默认（不阻断下载）
        _defs = {}
    try:
        interval = float(d.get("interval", _defs.get('interval', base.interval)))
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
    # ★v6.74（B 档 · 用户 2026-09-27 拍板）：**检测到东财限流 ⇒ 自动降到最保守档**（1.2s / K=1）。
    #   依据：用户实测自己的 `0.3s × K=3`（≈10 请求/秒）正是被限流的形态；一旦已在退避中，
    #   先把**我们这一侧**的请求率压到底，别拿账号去硬试（§10-10：直说，不静默）。
    try:
        from data import em_throttle as _thr_dl
        if _thr_dl.is_cooling():
            interval = max(interval, 1.2)
            conc = 1
            logger.info("东财取数在退避中 ⇒ 本次下载自动降档（interval≥1.2s / 并发 1）")
    except Exception:  # noqa: BLE001 —— 判据坏了就按原档走（不阻断下载）
        pass
    return ThrottlePolicy(
        interval=interval,
        jitter=0.3 if d.get("jitter", True) else 0.0,
        circuit_breaker=max(1, breaker),
        skip_fresh=bool(d.get("skip_fresh", True)),
        concurrency=max(1, min(4, conc)),
    )


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
        self._closing = False                       # ★v6.70 §9-F①：退出中 ⇒ 拒收新任务
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
        if self._closing:
            # ★v6.70 / §9-F①：退出守卫在分片等待期间会让窗口重画（转一圈事件循环），
            #   这扇子里“还能投新任务”必须先关掉 —— 否则刚排空的队列会被用户的一次误点重新填上。
            logger.info(f"正在退出，已拒绝新任务：{label}")
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

    def continue_unfinished(self, job_id: int) -> int:
        """★v6.70 / §9-F②：把一条**已结束**任务里“真没碰过”的标的重新入队（同参数）。

        【还的是什么债】旧面板只有「只重试失败」，而“中断时还没轮到的那批”**不在失败清单里**
        （它们一次请求都没发过）⇒ 批量侧只能用户自己重新提交同范围（靠 `skip_fresh` 续传），
        属**可发现性**问题，不是数据问题。
        【口径】只认 `symbols_attempted`（见 `DownloadJob.unprocessed`）；新任务**完全沿用**
        旧任务的 `zone` / `min_date` / `force_full` / `policy` ⇒ 不会出现“续传换了口径”。
        :return: 新 job id；0 = 没有可继续的（没这条任务 / 已全部碰过 / 正在退出）。
        """
        job = self.get(job_id)
        if job is None or job.status not in FINISHED_STATUSES:
            return 0
        # ★v6.70 加固（二次修改）：上一次续传**还在跑/还在排队** ⇒ 直接把它还给调用方。
        #   为什么不是"另投一条"：同一批"没轮到的"投两遍 = 白抓一遍（新任务结束 + `force_full`
        #   时更是整段重下）；而且这对调用方是幂等的（点两下 = 一条任务）。
        #   ⚠ 只挡"在途"：上一次续传**已经结束**（可能自己也被中断了）⇒ 允许再续一次，
        #   否则那批"二次中断"剩下的标的就再也没入口了。
        prev = self.get(job.continued_to) if job.continued_to else None
        if prev is not None and prev.status not in FINISHED_STATUSES:
            return prev.id
        rest = job.unprocessed()
        if not rest:
            return 0
        new_id = self.submit(f"继续未完成 · {job.label}", rest, zone=job.zone,
                             force_full=job.force_full, min_date=job.min_date,
                             policy=job.policy, origin=job.origin)
        if new_id:
            job.continued_to = new_id      # 面板据此把旧行收成「已续传」（不可点）
        return new_id

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
    def shutdown(self, wait_ms: int = 15000, tick_ms: int = 250,
                 on_tick=None) -> bool:
        """中断所有任务并**分片**等线程结束；超时也不让在跑的 QThread 被销毁。

        ⚠ 【为什么必须等】QThread 在运行时被销毁 = 程序崩溃（旧弹窗的 `_try_stop_worker`
          就为这件事写过 15 秒硬等）。这里同样：先请求中断，再等它自己结束。
        ★v6.70 / §9-F①【为什么改成一片一片等】原先是一次 `worker.wait(15000)` ⇒
          界面在这 15 秒里**完全不动**（用户以为程序死了，而它其实在等一次网络请求）。
          现在每 `tick_ms` 醒一次，把“已经等了多久”交给 `on_tick` 去刷“正在停止…”并重画。
          （`SyncWorker.cancel()` 的标志只在**只与只之间**生效，单次 HTTP 请求不可中断 ⇒
          预算只需覆盖“当前这一只剩下的那一次请求”，15 秒极少不够。）
        :param on_tick: 每片回调一次（主窗口用它刷回执 + `processEvents`）；测试可注入计数桩。
        :return: True = 线程已停干净；False = 超时（已摘 parent + 握住引用）。
        """
        self._closing = True          # 会转事件循环 ⇒ 先关掉“还能投任务”这扇门
        self.cancel(None)
        worker = self._worker
        if worker is None or not worker.isRunning():
            return True
        waited = 0
        while worker.isRunning() and waited < wait_ms:
            worker.wait(tick_ms)
            waited += tick_ms
            if on_tick is not None:
                try:
                    on_tick(waited)
                except Exception as e:  # noqa: BLE001 —— 刷提示失败不该拖住退出
                    logger.warning(f"退出提示回调异常（已忽略，继续等待）: {type(e).__name__}: {e}")
        if not worker.isRunning():
            return True
        # 超时：绝不“带着在跑的线程去销毁”。摘 parent ⇒ 主窗口与 hub 析构碰不到它；
        # 模块级列表握住 Python 引用 ⇒ 不会被 GC 顺手 delete（两条加起来 = 必崩 → 一条日志）。
        logger.warning(f"退出时仍有下载在收尾（已等 {waited} ms），已把它脱离窗口生命周期")
        self._orphan(worker)
        return False

    def _orphan(self, worker) -> None:
        """★v6.70 加固（二次修改）：把"超时仍在收尾"的 worker 交给自己管，**跑完自清**。

        三步：① `setParent(None)` 脱离 hub / 主窗口的生命周期；② 挂进模块级 `_ORPHAN_WORKERS`
        握住 Python 引用；③ `finished` 一到就摘引用 + `deleteLater()` 交还 Qt 回收。

        【为什么必须有 ③】旧版只做了 ①②：列表**只增不减** —— 每次"退出超时"都往里面堆一个
          跑完的线程对象，引用常驻（内存不回收），C++ 侧也永远等不到删除。次数少看不出，
          但这是"退出路径上的慢性泄漏"。跑完即摘 ⇒ 列表最终回到空。
        【安全性】`finished` 是**线程已结束**后才发的 ⇒ 此刻 `deleteLater()` 安全
          （危险的是"运行中被 delete"，那正是本路径要避免的）。
        """
        worker.setParent(None)
        self._worker = None           # 之后它的 `finished` 迟到也不会再被 `_on_finished` 收
        _ORPHAN_WORKERS.append(worker)
        fin = getattr(worker, "finished", None)      # 真 worker 必有；测试假件可能没有
        if fin is not None:
            fin.connect(lambda *_, w=worker: self._release_orphan(w))

    @staticmethod
    def _release_orphan(worker) -> None:
        """孤儿线程跑完 ⇒ 摘引用 + 交还 Qt（**幂等**：重复回调不会炸）。"""
        try:
            _ORPHAN_WORKERS.remove(worker)
        except ValueError:
            pass
        worker.deleteLater()

    def has_unfinished(self) -> bool:
        """是否还有未完成（排队或在跑）的任务 —— 主窗口 closeEvent 的退出守卫用。

        ⚠ 普通方法、不是 @property（与 `pending_count()`/`is_busy()` 同形）：
          调用方写的是 `has_unfinished()`，若定义成 property 会返回 bool 再被 `()` 调 →
          `TypeError: 'bool' object is not callable`，且会在 `shutdown()` 之前抛 →
          线程没等就销毁（QThread destroyed while running）。
        """
        return self.pending_count() > 0
