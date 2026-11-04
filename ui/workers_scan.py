# ui/workers_scan.py
"""扫描 / 成分股 / 就绪度 / 日历类 QThread（★2.04 / P2 拆件）。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from core.cross_section import ScanCancelled
from data.backfill import plan_startup
from data.market_db import DataLakeManager
from data.readiness import ReadinessCancelled, probe_readiness
from data.scan_store import scan_cached
from data.sync_service import MarketSyncService
from data.trade_calendar import (latest_settled_trading_day, load_or_fetch,
                                 previous_trading_day)
from ui.workers_throttle import _load_calendar_safely

logger = logging.getLogger(__name__)

__all__ = ["ScanWorker", "ConstituentsWorker", "CrossSectionWorker",
           "ReadinessWorker", "CalendarWorker", "StartupCheckWorker"]


def _resolve_worker_dep(name: str, fallback):
    """惰性取 `ui.workers.<name>`（兼容旧打桩点）。"""
    try:
        from ui import workers as _workers_mod
        return getattr(_workers_mod, name, fallback)
    except Exception:  # noqa: BLE001
        return fallback


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
            result = _resolve_worker_dep("MarketSyncService", MarketSyncService)(
            ).fetch_index_constituents(self._code)
        except Exception as e:  # noqa: BLE001 —— 兜底，绝不让异常穿透线程
            logger.warning(f"指数成分股解析异常 [{self._code}]: {e}")
            result = {"ok": False, "symbols": [], "index_code": self._code,
                      "reason": "error", "message": str(e)}
        self.finished_signal.emit(result)


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
                 store=None, chunk: int = 200, parent=None, signal_names=None):
        super().__init__(parent)
        self._job_id = int(job_id)
        self._kwargs = dict(zone_dir=zone_dir, formula=formula, symbols=symbols,
                            params=params, thresholds=thresholds, asof=asof, names=names,
                            adjust=adjust, snapshot_columns=snapshot_columns,
                            force=force, incremental=incremental, store=store,
                            # ★1.73 / §7-B16 期 1：**多判定变量**（M3 多统计项）——
                            #   一次扫描全部拿到；它进缓存键（换变量必须重算，§11.5-19 同族）。
                            signal_names=signal_names)
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


class StartupCheckWorker(QThread):
    """启动时的只读检查：本地日线是否过期，决定 snapshot / backfill / none。

    只读 parquet footer + 交易日历，不联网下载；日历冷缓存时可能有一次网络，
    但整个线程在后台，不阻塞首屏。回包 `{action, symbols, reason, report}`。
    """

    finished = pyqtSignal(object)

    def __init__(self, symbols, zone_dir: str, parent=None):
        super().__init__(parent)
        self._symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        self._zone_dir = zone_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            calendar = _load_calendar_safely()
            expected = latest_settled_trading_day(calendar=calendar)
            previous = previous_trading_day(expected, calendar) if expected else None
            report = probe_readiness(
                self._zone_dir, self._symbols, min_bars=250,
                should_stop=lambda: self._cancel)
            plan = plan_startup(report, expected, previous)
            self.finished.emit({
                "action": plan.action,
                "symbols": plan.symbols,
                "reason": plan.reason,
                "report": report,
            })
        except ReadinessCancelled:
            self.finished.emit(None)
        except Exception as e:  # noqa: BLE001 —— 启动检查失败绝不阻断
            logger.warning("启动数据检查失败（忽略）: %s", e)
            self.finished.emit(None)


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
