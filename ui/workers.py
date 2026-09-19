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
  ⚠ 唯一的例外是 `core/updater.py` 的 UpdateCheckerThread —— 它属于 core 层
    （版本检测不是 UI 职责），不搬进 ui/。
"""
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.backtest import BacktestEngine
from core.cross_section import ScanCancelled
from data.market_db import DataLakeManager
from data.readiness import ReadinessCancelled, probe_readiness
from data.scan_store import scan_cached
from data.sync_service import (MarketSyncService, ThrottlePolicy, ZONE_KLINE,
                               short_fetch_reason)

logger = logging.getLogger(__name__)


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


class SyncWorker(QThread):
    """批量同步若干标的（数据管理页 / 预下载弹窗共用）

    信号：
        progress(done, total, symbol)
        failed(symbol, reason)
        finished(summary)   # {ok, fail, skipped, added, aborted, symbols_failed}
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

    # 供 UI 的「中断」按钮调用
    def cancel(self):
        self._cancel = True

    def run(self):
        service = MarketSyncService()
        stats = {"ok": 0, "fail": 0, "skipped": 0, "added": 0,
                 "aborted": False, "symbols_failed": [], "total": len(self._symbols)}
        consecutive_fail = 0

        for index, symbol in enumerate(self._symbols, start=1):
            if self._cancel:
                stats["aborted"] = True
                break

            self.progress.emit(index, len(self._symbols), symbol)
            result = service.refresh_one(
                symbol, zone=self._zone, force_full=self._force_full,
                min_date=self._min_date, policy=self._policy)

            if result.get("skipped"):
                stats["skipped"] += 1
                consecutive_fail = 0
            elif result.get("ok"):
                stats["ok"] += 1
                stats["added"] += int(result.get("added", 0))
                consecutive_fail = 0
            else:
                stats["fail"] += 1
                consecutive_fail += 1
                stats["symbols_failed"].append(symbol)
                # 给 UI 一条"一句话归类"（网络？还是无数据/退市？），避免技术报错直接甩给用户
                self.failed.emit(symbol, short_fetch_reason(result))
                # 【温柔抓取·熔断】连续失败过多判定为"疑似被限流"，主动停手保护用户 IP
                if consecutive_fail >= max(1, self._policy.circuit_breaker):
                    stats["aborted"] = True
                    break

        self.finished.emit(stats)


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
        result = MarketSyncService().refresh_one(
            self._symbol, zone=self._zone, force_full=self._force_full,
            min_date=self._min_date, policy=self._policy, period=self._period)
        self.finished.emit(result)


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
    ⚠ 现状：`ui/dialogs/bulk_download.py` 的 `_cons_token` 是同一套判据的**手写版**，
      **择机改用本类**（本轮不动已验证的页面，§7-G 纪律）。
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
    · **增量路径**（`incremental=True`，M3 的「⚡ 增量到最新」，主案 D7）：
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
