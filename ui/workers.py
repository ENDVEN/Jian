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
"""
from PyQt6.QtCore import QThread, pyqtSignal

from data.market_db import DataLakeManager
from data.sync_service import (MarketSyncService, ThrottlePolicy, ZONE_KLINE,
                               short_fetch_reason)


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
                 min_date: str = None, policy: ThrottlePolicy = None, parent=None):
        super().__init__(parent)
        self._symbol = symbol
        self._zone = zone
        self._force_full = force_full
        self._min_date = min_date
        self._policy = policy

    def run(self):
        result = MarketSyncService().refresh_one(
            self._symbol, zone=self._zone, force_full=self._force_full,
            min_date=self._min_date, policy=self._policy)
        self.finished.emit(result)
