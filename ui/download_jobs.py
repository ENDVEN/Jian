# ui/download_jobs.py
"""下载任务的"数据与判据"件（★v6.70 / §4 体积债：从 `ui/download_hub.py` 拆出）。

【为什么单独成文件】`download_hub.py` 越了 400 行线（§4 红榜登记的拆法就是这一条）：
  队列本体（`DownloadHub`）与"任务形状 / 状态口径 / 单只互斥"是三件事，混在一个文件里
  只会让调度逻辑越来越难读。**本轮是纯搬家，零行为改动。**
【里面有什么】
  · 任务状态常量与中文标签（面板与下载条共用，别处不许再写状态字面量）；
  · `DownloadJob` —— 一条批量任务：不可变参数 + 可变进度 + **回执文案的唯一出口**；
  · `hub_of` / `SingleSyncGate` —— 页面取队列的统一入口与"单只同步"的互斥占位。
【纪律】`DownloadHub` 仍在本包 `download_hub.py`；`ui/download_hub.py` 会 **re-export**
  这里的所有名字 ⇒ 既有 `from ui.download_hub import ...` 的调用方与断言零改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from data.sync_service import (ZONE_KLINE, ThrottlePolicy, abort_reason_text,
                               failure_hint, format_duration)


# 任务状态（面板与下载条共用同一套标签，别处不许再写中文状态字面量）
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUS_LABELS = {STATUS_QUEUED: "排队中", STATUS_RUNNING: "下载中",
                 STATUS_DONE: "已完成", STATUS_CANCELLED: "已中断"}
FINISHED_STATUSES = (STATUS_DONE, STATUS_CANCELLED)

KEEP_FINISHED = 20          # 面板里最多回看多少条已结束任务（纯内存，不落盘）


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
    # ★v6.70 加固（二次修改）：这条任务"没轮到的那些"已经续传给了哪个 job（0 = 没有）。
    #   面板据此把旧行收成**不可点**的「已续传」—— 否则旧行会一直挂着「继续 N 只」，
    #   用户再点一次就是同范围重投（新任务已结束 + `force_full` 时 = 整段重下）。
    continued_to: int = 0

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

    def attempted(self) -> list:
        """本批里**真发过一次请求**的标的（含“已最新跳过”、“跳过了也算碰过”）。"""
        return list((self.stats or {}).get("symbols_attempted") or [])

    def rest_count(self) -> int:
        """还没碰过的只数（**O(1)**，只给按钮写标签用）。

        口径 = 总数 − 已尝试数：不构集合 ⇒ 队列面板每只刷一次也能算得起
        （`refresh()` 是跟着 `job_progress` 跑的，不能在这里埋 O(n) 的活）。
        两侧同尺：`symbols` 里有重复时，尝试清单也会重复记 ⇒ 差值仍成立。
        """
        return max(0, self.total - len(self.attempted()))

    def unprocessed(self) -> list:
        """**真没碰过**的标的清单（保持原提交顺序）—— 中断后续传的唯一正确依据。

        ⚠ 绝不能用“按 `done` 计数切前缀”那种写法（拿已处理数当下标）：批内并发（v1.44，K>1）
        下完成顺序与提交顺序无关，而“已最新跳过”也计入 `done` ⇒ 按位置切会**同时**漏掉
        没抓的那几只、又重抓已经抓过的（§9-F②）。只认 `SyncWorker` 记下的 `symbols_attempted`。
        """
        seen = set(self.attempted())
        return [s for s in self.symbols if s not in seen]

    @property
    def hint_text(self) -> str:
        """有失败才给教学文案（原因只走 `sync_service.failure_hint` 单出口）。"""
        return failure_hint(self.stats) if self.failures else ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "origin": self.origin,
                "status": self.status, "done": self.done, "total": self.total,
                "current": self.current, "percent": self.percent,
                "text": self.progress_text(), "eta": self.eta_text(),
                "receipt": self.receipt_text(), "failed": len(self.failures),
                "rest": self.rest_count(),            # ★v6.70 §9-F②：没轮到的只数（O(1)）
                "continued": bool(self.continued_to)}  # ★v6.70 加固：已续传 ⇒ 面板收成"不可点"

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
