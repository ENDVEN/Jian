# ui/workers.py
"""
共享的后台工作线程 (QThread Workers) —— v5.8。

【为什么单独成文件】
  数据管理页、批量预下载弹窗、市场行情页、市场回测页**都需要**"同步行情"这一件事。
  以前各自在 UI 文件里定义 `FetchDataThread` / `_StockSyncThread` / `_IndexSyncThread`，
  造成三份几乎一样的实现（也是 §9-H 的成因之一）。这里收敛为唯一一份。

【分工】
  · data/sync_service.py —— 纯 Python，**干活的**（拉数 / 合并 / 落盘 / 节流）
  · ui/workers.py        —— Qt，**调度的**（把活丢到后台线程，用信号回报进度）
  两者严格分层：service 零 Qt 依赖，可单测、可被未来 CLI 复用。

【收口范围 (v5.12 · §9-O2)】
  本文件是全 app **唯一的 QThread 定义处**（页面与弹窗一律不得自造线程类）：
    · ScanWorker          扫数据湖分区
    · SyncWorker          批量同步
    · SingleSyncWorker    同步单只
    · BacktestRunWorker   回测计算
    · ConstituentsWorker  解析指数成分股
    · FuturesImportWorker 解析期货交割单
    · CrossSectionWorker  M2/M3 横截面扫描（§7-B1/B2 D4：分块 + 进度 + 取消 + 竞态守卫）
    · ReadinessWorker     就绪度体检（§7-B1/B2 D6-1：只读 parquet footer，不联网不写盘）
    · CalendarWorker      交易日历一次性后台抓取（§7-B10：失败/无网回 None，UI 回退本地最新）
  ⚠ 唯一的例外是 `core/updater.py` 的 UpdateCheckerThread —— 它属于 core 层
    （版本检测不是 UI 职责），不搬进 ui/。
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from core.backtest import BacktestEngine
from core.cross_section import ScanCancelled
from data.market_db import DataLakeManager
from data.readiness import ReadinessCancelled, probe_readiness
from data.scan_store import scan_cached
from data.sync_service import (MarketSyncService, ThrottlePolicy, ZONE_KLINE,
                               fetch_industry_page, is_daily_bar_settled,
                               network_self_check, short_fetch_reason, spot_valuation_map)
from data.trade_calendar import (latest_settled_trading_day, load_or_fetch,
                                 previous_trading_day)

logger = logging.getLogger(__name__)

# `inject_expected_latest` 的“日历未提供”哨兵（区别于“提供了但为 None”）。
_CAL_UNSET = object()


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
        cal = load_or_fetch() if calendar is _CAL_UNSET else calendar
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
        return load_or_fetch()
    except Exception as e:  # noqa: BLE001 —— 日历故障绝不阻断下载（退回旧判据、不开秒补）
        logger.warning("交易日历不可用，本次退回旧判据且不启用快照秒补: %s", e)
        return None


class ScanWorker(QThread):
    """扫描某个分区的清单（大目录时避免卡住 UI）"""

    # 携带 zone：接收方必须校验 == 当前选中分区，
    # 否则快速切换分区时"旧扫描的晚到结果"会覆盖新分区内容（竞态）
    result = pyqtSignal(str, object)   # (zone, list[dict])

    def __init__(self, zone: str, lake: DataLakeManager = None, parent=None):
        super().__init__(parent)
        self._zone = zone
        self._lake = lake or DataLakeManager()

    def run(self):
        try:
            items = self._lake.inventory(self._zone)
        except Exception as e:  # noqa: BLE001 —— 扫描失败也要给 UI 一个确定的回包
            items = []
            print(f"数据湖扫描失败 [{self._zone}]: {e}")
        self.result.emit(self._zone, items)


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


class SyncWorker(QThread):
    """批量同步若干标的（数据管理页 / 预下载弹窗 / M2-M3 更新共用）

    信号：
        progress(done, total, symbol)
        failed(symbol, reason)
        finished(summary)   # {ok, fail, skipped, added, aborted, aborted_by, symbols_failed}
                            #   aborted_by ∈ ""/"cancel"/"proxy"/"circuit"（v1.38/§7-E2）
                            #   ⇒ 消费方用 `sync_service.abort_reason_text(stats)` 出人话，别各写一遍

    ★v1.44 / §7-B11 后续：`policy.concurrency > 1` 时走**批内并发池**（本类内部用
      `ThreadPoolExecutor` 编排现成的 `refresh_one`，数据层仍纯同步、零 Qt）；
      并发只发生在**单个 job 内部**（任务级仍由 DownloadHub 串行 K=1）。`concurrency <= 1`
      时逐字节走旧串行（裸构造 / 单测 / 回滚开关）。熔断与代理计数改为**跨线程共享**。
    """

    progress = pyqtSignal(int, int, str)
    failed = pyqtSignal(str, str)
    finished = pyqtSignal(dict)

    def __init__(self, symbols, zone: str = ZONE_KLINE, force_full: bool = False,
                 min_date: str = None, policy: ThrottlePolicy = None, parent=None):
        super().__init__(parent)
        self._symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        self._zone = zone
        self._force_full = force_full
        self._min_date = min_date
        self._policy = policy or ThrottlePolicy()
        self._cancel = False
        self._spot_ctx = None                  # ★v1.45：循环外取好的全市场快照上下文（或 None）

    # 供 UI 的「中断」按钮调用
    def cancel(self):
        self._cancel = True

    def run(self):
        service = MarketSyncService()
        # ★v1.45：日历一次取，inject 与 spot 共用（保证“每批只取一次”，§7-E5）
        calendar = _load_calendar_safely()
        policy = inject_expected_latest(self._policy, calendar=calendar)
        # ★v1.45 / §7-B11 后续：daily qfq job 且非盘中 ⇒ 1 次全市场快照，秒补“只差当天”那根
        self._spot_ctx = self._build_spot_ctx(service, policy, calendar)
        stats = {"ok": 0, "fail": 0, "skipped": 0, "added": 0, "spot_hit": 0,
                 "aborted": False, "aborted_by": "", "symbols_failed": [],
                 # ★v6.70 / §9-F②：**真正跑过一只请求**的清单（含“已最新跳过”）——
                 #   它是“中断后还剩哪些没碰”的**唯一正确依据**：`done` 只是计数，
                 #   并发下与提交顺序无关 ⇒ 拿 `symbols[done:]` 切会同时漏抓与重抓。
                 "symbols_attempted": [],
                 "total": len(self._symbols)}
        if (policy.concurrency or 1) > 1:
            self._run_pool(service, policy, stats)
        else:
            self._run_serial(service, policy, stats)
        self.finished.emit(stats)

    # ---- ★v1.45：全市场快照上下文（一次取、跨只复用；不满足安全前提 ⇒ None）----
    def _build_spot_ctx(self, service, policy, calendar):
        """daily qfq 且“无未定稿盘中会话”时，取 1 次全市场快照供逐只秒补当天。

        任一安全前提不满足 ⇒ 返回 None（整批退回逐只网络增量，零风险）：
          · 非 ZONE_KLINE（raw/分钟/指数）/ force_full ⇒ 不做；
          · 无日历 / expected_latest 缺失 ⇒ 无法安全判“只缺一根” ⇒ 不做；
          · 今天是交易日且未到定稿点（盘中）⇒ spot 是半截当日，写了脏 ⇒ 不做；
          · 快照接口不存在（打桩）/ 拉回空 ⇒ 不做。
        """
        if self._zone != ZONE_KLINE or self._force_full:
            return None
        if policy is None or getattr(policy, "expected_latest", None) is None:
            return None
        if not calendar:
            return None
        snap_fn = getattr(service, "fetch_spot_snapshot", None)
        if snap_fn is None:
            return None
        now = datetime.now()
        today = now.date()
        try:
            if (today in set(calendar)) and not is_daily_bar_settled(today, now):
                return None                    # 盘中：spot 是半截当日，绝不用
            prev = previous_trading_day(policy.expected_latest, calendar)
        except Exception:  # noqa: BLE001 —— 日历判定异常 ⇒ 保守不开秒补
            return None
        if prev is None:
            return None
        snap = snap_fn(self._symbols)
        if not snap:
            return None
        return {"prev": prev, "snap": snap}

    def _spot_kwargs(self, symbol):
        """给 `refresh_one` 的 spot 透传参（无 ctx ⇒ 空 ⇒ 走网络增量）。"""
        ctx = getattr(self, "_spot_ctx", None)
        if not ctx:
            return {}
        return {"spot_bar": ctx["snap"].get(symbol), "spot_prev": ctx["prev"]}

    # ---- 串行快路径（== v1.43 及以前的既有行为，零漂移）----
    def _run_serial(self, service, policy, stats):
        total = len(self._symbols)
        consecutive_fail = 0
        consecutive_proxy = 0

        for index, symbol in enumerate(self._symbols, start=1):
            if self._cancel:
                stats.update(aborted=True, aborted_by="cancel")
                break

            self.progress.emit(index, total, symbol)
            result = service.refresh_one(
                symbol, zone=self._zone, force_full=self._force_full,
                min_date=self._min_date, policy=policy, **self._spot_kwargs(symbol))
            stats["symbols_attempted"].append(symbol)     # ★v6.70 §9-F②：发了请求才算“碰过”

            if result.get("skipped"):
                stats["skipped"] += 1
                consecutive_fail = 0
                consecutive_proxy = 0
            elif result.get("ok"):
                stats["ok"] += 1
                stats["added"] += int(result.get("added", 0))
                if result.get("reason") == "spot":
                    stats["spot_hit"] = stats.get("spot_hit", 0) + 1
                consecutive_fail = 0
                consecutive_proxy = 0
            else:
                stats["fail"] += 1
                consecutive_fail += 1
                if str(result.get("reason") or "") == "proxy":
                    consecutive_proxy += 1          # ★v1.38/§7-E2：代理类失败单独计数
                else:
                    consecutive_proxy = 0
                stats["symbols_failed"].append(symbol)
                # 给 UI 一条"一句话归类"（代理 / 网络 / 无数据·退市？），避免技术报错直接甩给用户
                self.failed.emit(symbol, short_fetch_reason(result))
                # ★【代理全灭 ⇒ 提前停手】§9.3 实测：本机代理瞬断时失败率是 100%，
                #   按默认 12 连败熔断等于白等十几次超时；用户的正确动作是"立刻去查代理"。
                if consecutive_proxy >= max(1, policy.proxy_circuit_breaker):
                    stats.update(aborted=True, aborted_by="proxy")
                    break
                # 【温柔抓取·熔断】其余原因的连续失败过多判定为"疑似被限流"，主动停手保护用户 IP
                if consecutive_fail >= max(1, policy.circuit_breaker):
                    stats.update(aborted=True, aborted_by="circuit")
                    break

    # ---- 批内并发池（★v1.44 / §7-B11 后续）----
    def _run_pool(self, service, policy, stats):
        total = len(self._symbols)
        governor = RateGovernor()
        throttle = governor.throttle          # 作为共享 sleep_fn 注入 refresh_one
        lock = threading.Lock()
        stop = threading.Event()               # 熔断/取消 ⇒ 未启动的任务直接跳过
        done = [0]                             # 已完成计数（锁内自增，跨线程单调）
        consec = {"fail": 0, "proxy": 0}       # 连续失败计数（**跨线程共享**）
        breaker = max(1, policy.circuit_breaker)
        pbreaker = max(1, policy.proxy_circuit_breaker)

        def one(symbol):
            if stop.is_set() or self._cancel:
                return                          # 已停 ⇒ 排队任务不再发请求（保留真实进度）
            result = service.refresh_one(
                symbol, zone=self._zone, force_full=self._force_full,
                min_date=self._min_date, policy=policy, sleep_fn=throttle,
                **self._spot_kwargs(symbol))
            fail_reason = None
            with lock:
                done[0] += 1
                d = done[0]
                stats["symbols_attempted"].append(symbol)   # ★v6.70 §9-F②（与串行路径同口径）
                if result.get("skipped"):
                    stats["skipped"] += 1
                    consec["fail"] = consec["proxy"] = 0
                elif result.get("ok"):
                    stats["ok"] += 1
                    stats["added"] += int(result.get("added", 0))
                    if result.get("reason") == "spot":
                        stats["spot_hit"] = stats.get("spot_hit", 0) + 1
                    consec["fail"] = consec["proxy"] = 0
                else:
                    stats["fail"] += 1
                    consec["fail"] += 1
                    if str(result.get("reason") or "") == "proxy":
                        consec["proxy"] += 1
                    else:
                        consec["proxy"] = 0
                    stats["symbols_failed"].append(symbol)
                    fail_reason = short_fetch_reason(result)
                    trip_by = ""
                    if consec["proxy"] >= pbreaker:
                        trip_by = "proxy"
                    elif consec["fail"] >= breaker:
                        trip_by = "circuit"
                    if trip_by:
                        stats.update(aborted=True, aborted_by=trip_by)
                        stop.set()               # 任一线程达阈 ⇒ 全体收手
            self.progress.emit(d, total, symbol)
            if fail_reason is not None:
                self.failed.emit(symbol, fail_reason)

        workers = max(1, min(int(policy.concurrency), 4, total or 1))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for symbol in self._symbols:
                ex.submit(one, symbol)
            # `with` 退出 = shutdown(wait=True)：在途那只自然跑完、排队的靠 stop/cancel 秒退
        if self._cancel and not stats.get("aborted"):
            stats.update(aborted=True, aborted_by="cancel")   # 与串行一致：用户中断单独归类


class SingleSyncWorker(QThread):
    """同步单个标的（市场行情页 / 市场回测页共用）"""

    finished = pyqtSignal(dict)   # MarketSyncService.refresh_one 的返回结构

    def __init__(self, symbol: str, zone: str = ZONE_KLINE, force_full: bool = False,
                 min_date: str = None, policy: ThrottlePolicy = None, parent=None,
                 period: str = None):
        super().__init__(parent)
        self._symbol = symbol
        self._zone = zone
        self._force_full = force_full
        self._min_date = min_date
        self._policy = policy
        # ★v6.21/§7-B6 STEP 3：仅 `zone=ZONE_MIN` 用（分钟按档位各存一份，见 sync_service.minute_key）
        self._period = period

    def run(self):
        # ★v1.40/§7-E5：单只同步同样吃"日历感知新鲜度" —— 盘中点同步不再白跑一次请求
        # （日线的今天那根要 15:05 才定稿，此前拉回来也只会被定稿守卫裁掉）。
        result = MarketSyncService().refresh_one(
            self._symbol, zone=self._zone, force_full=self._force_full,
            min_date=self._min_date, policy=inject_expected_latest(self._policy),
            period=self._period)
        self.finished.emit(result)


class SpotValuationWorker(QThread):
    """★P5：后台拉**当前估值**（供 M2 结果表 B 层列：市盈率/市净率/总市值）。

    非阻塞、失败回 None（那几列诚实留 '—'），与 M3 指数副图后台补拉同款"不连累主流程"。
    走 `spot_valuation_map()` 门面（§9-H：ui 不直连行情源，联网抓取一律经 data 层）。
    ★v6.69：**按标的池取**（`symbols`）—— 旧版无参 = 全市场快照（东财内部 ~56 页突发），
      会与行业分页抢同一份匿名额度；现在几百只池子只需 2~3 个请求（§11.5-100）。
    """

    finished = pyqtSignal(object)   # {symbol: {pe, pb, total_mktcap}} 或 None

    def __init__(self, symbols=None, parent=None):
        super().__init__(parent)
        self._symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        self._cancel = False

    def cancel(self):
        """供页面在关窗/取消时调用（只置一个 bool，跨线程安全）。"""
        self._cancel = True

    def run(self):
        try:
            data = spot_valuation_map(self._symbols)
        except Exception as e:  # noqa: BLE001 —— 网络/接口异常一律回 None，绝不外泄到 UI
            logger.warning(f"估值快照后台拉取失败: {e}")
            data = None
        self.finished.emit(data or None)


class IndustryMapWorker(QThread):
    """★v6.68：后台**分批**取全市场「代码→行业」（东财列表 `f100`：单页 100、全市场 ~56 页）。

    【为什么分批】东财对**匿名高频**请求有频次窗（连打几十次整段拒绝、约 30 分钟自恢复，§11.5-99）
    ⇒ **每批只抓几页** + 页间隔，分几次扫描摊平；进度由页面按"断点续抓"给出。
    ★v6.69：加 `cancel()` —— 关窗时页面会取消并 `wait()`，不再让 QThread 运行中被销毁
      （用户实测日志里的 `QThread: Destroyed while thread '' is still running`）。
    回包 `{"map", "page_start", "pages_done", "total_pages", "done", "error"}`；整体失败回 None。
    走 `fetch_industry_page()` 门面（§9-H：ui 不直连行情源）。
    """

    finished = pyqtSignal(object)   # 上面那个 dict，或 None（失败）

    def __init__(self, page_start: int = 1, pages: int = 1, parent=None):
        super().__init__(parent)
        self._page_start = int(page_start)
        self._pages = int(pages)
        self._cancel = False

    def cancel(self):
        """供页面在关窗/取消时调用（**在页与页之间**生效，最多多等一个页间隔）。"""
        self._cancel = True

    def run(self):
        try:
            data = fetch_industry_page(self._page_start, self._pages,
                                       should_stop=lambda: self._cancel)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"行业映射后台拉取失败: {e}")
            data = None
        self.finished.emit(data or None)


class NetSelfCheckWorker(QThread):
    """★v6.74 / §7-B13 S2-1b：**网络与取数自检**（后台跑，绝不阻塞界面）。

    【自检做多少】策略 / 代理 / DNS / 登录 / 档位 / 额度 / 退避 = **零请求**；
      只额外发 **1 个** `ulist`（1 只票）验"现在能不能取到数" ⇒ 不刷量（用户拍板口径）。
    【纪律】走门面 `network_self_check()`（§9-H：ui 不直连行情源）；
      结果**同时进日志**（`app.log`）把整段报告留痕，方便事后复盘。
    """

    finished = pyqtSignal(str)   # 人话报告（多行）；异常也回一段说明，绝不空回

    def __init__(self, probe: bool = True, parent=None):
        super().__init__(parent)
        self._probe = bool(probe)
        self._cancel = False

    def cancel(self):
        """关窗取消（自检本身很短，只标记不再发新请求）。"""
        self._cancel = True

    def run(self):
        try:
            text = '' if self._cancel else network_self_check(self._probe)
        except Exception as e:  # noqa: BLE001 —— 自检炸了也要给用户一句话
            logger.warning(f"网络自检失败: {type(e).__name__}: {e}")
            text = f'网络自检失败：{type(e).__name__}: {e}'
        try:
            logger.info("网络自检报告：\n" + (text or '（已取消）'))
        except Exception:  # noqa: BLE001
            pass
        self.finished.emit(text or '（已取消）')


class CacheCleanWorker(QThread):
    """★v6.75 / §7-B13 S2-5：**缓存清理**（后台跑 —— 只删"可再生成"的东西）。

    【纪律】删除范围由 `data/storage_maintenance` 定义（**唯一实现处**：轮转日志 + `*.tmp`；
      数据湖 / 回测存档 / 截图 / 交易库 / **登录凭据**一律不碰）。本类只负责"别卡界面"。
    """

    finished = pyqtSignal(str)   # 人话回执

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self._cancel:
                text = '已取消（未清理任何文件）'
            else:
                from data.storage_maintenance import clear_cache
                text = str(clear_cache().get('text') or '')
        except Exception as e:  # noqa: BLE001 —— 清理失败要给用户一句话，不能空回
            logger.warning(f"缓存清理失败: {type(e).__name__}: {e}")
            text = f'缓存清理失败：{type(e).__name__}: {e}'
        logger.info(f"缓存清理：{text}")
        self.finished.emit(text or '清理完成')


class BacktestRunWorker(QThread):
    """回测计算（市场回测页）。

    异常一律在线程内吞掉并记日志，用 `None` 回包让 UI 给出统一的失败提示 ——
    绝不让异常穿透 QThread 造成静默失败或崩溃。
    """

    finished_signal = pyqtSignal(object)   # BacktestResult | None

    def __init__(self, df, symbol: str, buy_expr: str, sell_expr: str,
                 start_date: str, end_date: str, risk: dict = None,
                 fill_mode: str = None, trigger_tick=None, parent=None):
        super().__init__(parent)
        self.df = df
        self.symbol = symbol
        self.buy_expr = buy_expr
        self.sell_expr = sell_expr
        self.start_date = start_date
        self.end_date = end_date
        self.risk = risk or {}
        # v6.17 成交时点模型（默认 None -> 引擎侧归一回 next_open / 1 跳）
        self.fill_mode = fill_mode
        self.trigger_tick = trigger_tick

    def run(self):
        result = None
        try:
            result = BacktestEngine().run(
                self.df, self.buy_expr, self.sell_expr, symbol=self.symbol,
                start_date=self.start_date, end_date=self.end_date, risk=self.risk,
                fill_mode=self.fill_mode, trigger_tick=self.trigger_tick)
        except Exception as e:  # noqa: BLE001 —— 回测异常绝不穿透线程
            logger.error(f"市场回测-计算异常 [{self.symbol}]: {e}")
        self.finished_signal.emit(result)


class ConstituentsWorker(QThread):
    """解析指数成分股（网络操作，必须后台执行）。

    【v6.9 收编 · §9-T4-①】此前本线程**直接 import 行情源**发请求，绕过了
    `MarketSyncService` —— 与 §9-H 的红线（"任何联网抓取必须经该门面"）冲突。
    现在改为调用 `MarketSyncService.fetch_index_constituents()`：本线程只负责
    "把活丢到后台"，联网细节与失败分类文案全部归门面（§10-3）。
    """

    finished_signal = pyqtSignal(object)   # {"ok", "symbols", "index_code", "reason", "message"}

    def __init__(self, index_code: str, parent=None):
        super().__init__(parent)
        self._code = index_code

    def run(self):
        try:
            result = MarketSyncService().fetch_index_constituents(self._code)
        except Exception as e:  # noqa: BLE001 —— 兜底，绝不让异常穿透线程
            logger.warning(f"指数成分股解析异常 [{self._code}]: {e}")
            result = {"ok": False, "symbols": [], "index_code": self._code,
                      "reason": "error", "message": str(e)}
        self.finished_signal.emit(result)


class FuturesImportWorker(QThread):
    """
    后台解析期货交割单。

    【职责边界】**只解析、不落库**：`engine.parse_cfmmc()` 是耗时步骤，落库
    （`engine.commit_cfmmc()`）由 UI 主线程收结果后执行 —— 避免子线程**写** SQLite
    与主线程读数据争抢同一份内存状态。

    ⚠ 诚实记一笔（§9-T4-② 的历史挂账）：解析内部**会读** SQLite
    （`parse_cfmmc` → `db.load_open_legs()` 取历史未平仓腿，好让分月导入无缝衔接）。
    所以准确说法是"**子线程只读、不写库**"，而不是旧注释里的"子线程完全不碰 SQLite"。
    """

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, engine, file_paths, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.file_paths = file_paths

    def run(self):
        try:
            self.finished.emit(self.engine.parse_cfmmc(self.file_paths))
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))


class JobGuard:
    """竞态守卫（§9-O5）：**只接受最新一次任务的结果**，迟到的旧回包一律丢弃。

    页面侧两行就够：
        self._guard = JobGuard()
        job = self._guard.next()                     # 发起任务时取号
        worker.finished.connect(self._on_done)
    def _on_done(self, job_id, outcome):
        if not self._guard.accept(job_id):           # 迟到 ⇒ 直接丢
            return

    【为什么做成公共件】"发起新任务 ⇒ 旧回包作废"在本项目至少三处需要（数据管理页的分区扫描、
    批量下载弹窗的成分股解析、扫描页的多个动作）。各写一遍 `_token` 计数器，迟早有一处忘了比
    ⇒ **旧结果覆盖新结果**，而且界面看起来完全正常（§11.5-11「同类防护只改一处」的正解）。
    ✅ v1.38/§7-E2：`ui/dialogs/bulk_download.py` 原先那套手写判据（`_cons_token`）已改用本类 ——
      至此"发起新任务 ⇒ 旧回包作废"在全仓**只有一处实现**（§11.5-11「同类防护做全套」还清这笔挂账）。
    """

    def __init__(self):
        self._latest = 0

    def next(self) -> int:
        """发起一次新任务：作废此前所有任务的回包，返回本次的 `job_id`"""
        self._latest += 1
        return self._latest

    def accept(self, job_id) -> bool:
        """这个回包是不是**当前最新**那次任务的？（类型容错：`"3"` 与 `3` 同等看待）"""
        try:
            return int(job_id) == self._latest
        except (TypeError, ValueError):
            return False

    @property
    def latest(self) -> int:
        return self._latest


class CrossSectionWorker(QThread):
    """M2 / M3 横截面扫描（§7-B1/B2 STEP 3 · 主案 D4）—— 分块 + 进度 + 取消 + 竞态守卫。

    信号：
        progress(done, total, note)   # `total=0` 表示"还不知道总数"（读数阶段）
        finished(job_id, outcome)     # `ScanOutcome`；**取消时为 `None`**
        failed(job_id, reason)        # 一句话原因（异常绝不穿透线程）

    · **竞态守卫（§9-O5）**：`job_id` **原样回包**，页面用 `JobGuard.accept()` 判定；
    · **取消**：`cancel()` ⇒ 内核在**块边界**抛 `ScanCancelled` ⇒
      **绝不落半成品矩阵**（半个矩阵的命中家数 / 广度占比全是错的，且界面上看不出来）；
      事后可读 `worker.cancelled`；
    · **增量路径**（`incremental=True`，M3 的「⚡ 只补新交易日」，主案 D7）：
      `scan_cached` 先找同配置旧条目做**尾段续接**（历史矩阵逐位不动）；
      找不到 / 结构变了 ⇒ 诚实退化全量，过程说明在 `outcome.note`；
    · **会话缓存命中时不进计算循环** —— `scan_cached` 直接返回上次的矩阵
      （切日期 / 换统计窗口走这条 ⇒ 连进度信号都不会有）。

    本线程**只做调度**：读盘、掩码、求值全在 `core/cross_section` + `data/scan_store` 里
    （零 Qt 依赖，可被冒烟脚本直接验证）。
    """

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, job_id: int, zone_dir: str, formula: str, symbols=None, params=None,
                 thresholds=None, asof=None, names=None, adjust: str = 'qfq',
                 snapshot_columns=(), force: bool = False, incremental: bool = False,
                 store=None, chunk: int = 200, parent=None):
        super().__init__(parent)
        self._job_id = int(job_id)
        self._kwargs = dict(zone_dir=zone_dir, formula=formula, symbols=symbols,
                            params=params, thresholds=thresholds, asof=asof, names=names,
                            adjust=adjust, snapshot_columns=snapshot_columns,
                            force=force, incremental=incremental, store=store)
        self._chunk = max(1, int(chunk or 1))
        self._cancel = False
        self.cancelled = False          # 事后判读：这次是不是被用户取消掉的

    def cancel(self):
        """供 UI 的「取消」按钮调用（只置一个 bool，跨线程安全）"""
        self._cancel = True

    def _on_progress(self, done: int, total: int, note: str):
        self.progress.emit(int(done), int(total), str(note))

    def run(self):
        try:
            outcome = scan_cached(progress=self._on_progress,
                                  should_stop=lambda: self._cancel,
                                  chunk=self._chunk, **self._kwargs)
        except ScanCancelled as e:
            self.cancelled = True
            logger.info(f"横截面扫描已取消 [job {self._job_id}]: {e}")
            self.finished.emit(self._job_id, None)       # 明确"没有结果"，而不是半个矩阵
            return
        except Exception as e:  # noqa: BLE001 —— 异常绝不穿透 QThread
            logger.error(f"横截面扫描异常 [job {self._job_id}]: {e}")
            self.failed.emit(self._job_id, str(e))
            return
        self.finished.emit(self._job_id, outcome)


class ReadinessWorker(QThread):
    """就绪度体检（§7-B1/B2 D6-1 · 主案 D6）—— 扫描前回答"本地能真正拿到多少只"。

    · **只读 parquet footer**（行数 + date 统计），不读数据行、不联网、不写盘
      （实测 0.66 ms/只 ⇒ 全市场 ≈3.6 s，后台跑 + 进度）；
    · 信号与 `CrossSectionWorker` 同款：`progress(done,total,note)` /
      `finished(job_id, report)`（**取消 ⇒ report=None**）/ `failed(job_id, reason)`；
    · `job_id` 原样回包，页面用 `JobGuard.accept()` 丢弃迟到回包（§9-O5）。
    """

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, job_id: int, zone_dir: str, symbols, min_bars: int = None,
                 chunk: int = 200, parent=None):
        super().__init__(parent)
        self._job_id = int(job_id)
        self._zone_dir = zone_dir
        self._symbols = list(symbols or [])
        self._min_bars = min_bars
        self._chunk = max(1, int(chunk or 1))
        self._cancel = False
        self.cancelled = False

    def cancel(self):
        """供 UI 调用（只置一个 bool，跨线程安全）"""
        self._cancel = True

    def _on_progress(self, done: int, total: int, note: str):
        self.progress.emit(int(done), int(total), str(note))

    def run(self):
        try:
            report = probe_readiness(self._zone_dir, self._symbols, min_bars=self._min_bars,
                                     progress=self._on_progress,
                                     should_stop=lambda: self._cancel, chunk=self._chunk)
        except ReadinessCancelled as e:
            self.cancelled = True
            logger.info(f"就绪度体检已取消 [job {self._job_id}]: {e}")
            self.finished.emit(self._job_id, None)
            return
        except Exception as e:  # noqa: BLE001 —— 异常绝不穿透 QThread
            logger.error(f"就绪度体检异常 [job {self._job_id}]: {e}")
            self.failed.emit(self._job_id, str(e))
            return
        self.finished.emit(self._job_id, report)


class CalendarWorker(QThread):
    """交易日历一次性后台抓取（v6.45 / §7-B10）。

    · 缓存命中即零网络；未命中才联网一次（`data.trade_calendar.load_or_fetch`）；
    · 异常一律在线程内吞掉并回 `None` —— 绝不让网络失败冒泡到 UI，
      调用方收到 `None` 就回退"本地数据湖最新日"（拿不到日历绝不阻断回测默认值）。
    """

    finished_signal = pyqtSignal(object)   # list[date] | None

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            calendar = load_or_fetch()
        except Exception as e:  # noqa: BLE001 —— 网络/接口异常一律回 None，交 UI 回退
            logger.warning(f"交易日历后台抓取失败，UI 将回退本地最新日: {e}")
            calendar = None
        self.finished_signal.emit(calendar)
