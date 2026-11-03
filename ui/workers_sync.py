# ui/workers_sync.py
"""同步类小 worker（★2.04 / P2 拆件）。

从 `ui/workers.py` 抽出不依赖批量调度/并发池的小线程类。仍是全 app 唯一
QThread 定义处的一部分；页面与弹窗只从 `ui.workers` / 本模块导入，不自己造线程类。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from data.sync_service import (MarketSyncService, ThrottlePolicy, ZONE_KLINE,
                               fetch_enrich_map, fetch_industry_page, spot_valuation_map)
from ui.workers_throttle import inject_expected_latest

__all__ = ["RosterSyncWorker", "SingleSyncWorker", "SpotValuationWorker",
           "IndustryMapWorker", "IndustryPoolWorker"]

logger = logging.getLogger(__name__)


def _resolve_worker_dep(name: str, fallback):
    """惰性取 `ui.workers.<name>`（兼容旧打桩点；拆件前测试在 workers 上替换门面）。

    ★2.04：`fetch_enrich_map` 等被移到本模块后，旧测试仍会 `ui.workers.fetch_enrich_map = ...`；
    这里优先看那个属性，没有才用本模块导入。拆件不改变“唯一 HTTP 出口”的分层。
    """
    try:
        from ui import workers as _workers_mod
        return getattr(_workers_mod, name, fallback)
    except Exception:  # noqa: BLE001
        return fallback


class RosterSyncWorker(QThread):
    """★1.70 / §11.5-125：**同步花名册**（全市场 A 股 + 期货）。

    【为什么要它】新机器上花名册天然为空 ⇒ "按名字搜标的"全部落空；此前唯一的出路是让用户
      自己去跑 `py scripts/sync_roster.py`（命令行 = 新用户门槛，他连该跑哪个都不知道）。
      本 worker 让 app 内能给「立即同步花名册」一键按钮。

    【口径】只做"加载 + 转发"：真正的同步逻辑（含**数量安全闸**）在 `data/roster_sync.sync_roster()`
      —— 与运维脚本**同一个门面**，闸门只有一份（§9-G）。
    【线程纪律】全 app QThread 只此一处（§10-12）；信号名避开 QThread 自带的 `finished`。
    """

    finished_ok = pyqtSignal(dict)      # 报告 dict（ok=True：a_share/futures/total/elapsed）
    failed = pyqtSignal(str)            # 人话原因（含"残缺名单已中止入库"这类）

    def run(self):
        try:
            from data.roster_sync import sync_roster
            rep = sync_roster()
        except Exception as e:                      # noqa: BLE001 —— 异常绝不穿透 QThread
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        if rep.get("ok"):
            self.finished_ok.emit(rep)
        else:
            self.failed.emit(str(rep.get("reason") or "未知原因"))


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
        #
        # ★2.0：**兜底**。它是 18 个 worker 里唯一原先没有 try 的 —— 槽里漏出异常会被 PyQt
        #   判为未捕获 ⇒ `qFatal`（进程 fastfail，§11.5-149 同族）。失败就发一条**同形状**的回包，
        #   调用方按 reason='error' 正常安抚用户，而不是整程序消失。
        try:
            result = MarketSyncService().refresh_one(
                self._symbol, zone=self._zone, force_full=self._force_full,
                min_date=self._min_date, policy=inject_expected_latest(self._policy),
                period=self._period)
        except Exception as e:                    # noqa: BLE001 —— 异常绝不穿透 QThread
            logger.warning("单只同步失败 %s: %s", self._symbol, e)
            result = {
                "ok": False, "symbol": self._symbol, "zone": self._zone,
                "key": self._symbol, "period": self._period or "",
                "rows": 0, "added": 0, "skipped": False, "reason": "error",
                "first": None, "last": None, "rescaled": False,
                "message": f"同步失败：{type(e).__name__}: {e}",
            }
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
            data = _resolve_worker_dep("spot_valuation_map", spot_valuation_map)(self._symbols)
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
            data = _resolve_worker_dep("fetch_industry_page", fetch_industry_page)(
                self._page_start, self._pages, should_stop=lambda: self._cancel)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"行业映射后台拉取失败: {e}")
            data = None
        self.finished.emit(data or None)


class IndustryPoolWorker(QThread):
    """★1.91：**按池**补行业（组合页用）—— 走 `fetch_enrich_map()`（`ulist`，100 只/请求）。

    【为什么不走分页通道】`IndustryMapWorker` 是"全市场按代码序翻页"（~56 页、每批几页）⇒
      一个 300 只的组合要等十几轮才轮到它关心的票（§11.5-106：按代码升序补齐会制造"什么都没抓到"的错觉）。
      按标的批量取 = **1~3 个请求**把池子一次补满。

    回包 `{"map": {symbol: 行业}, "missed": [没拿到的], "error": ""}`；失败也是同一形状（绝不无回包）。
    """
    finished = pyqtSignal(object)

    def __init__(self, symbols, parent=None):
        super().__init__(parent)
        self._symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]

    def run(self):
        mp, err = {}, ""
        try:
            raw = _resolve_worker_dep("fetch_enrich_map", fetch_enrich_map)(self._symbols)
            for sym, rec in (raw or {}).items():
                name = str((rec or {}).get("industry") or "").strip()
                if name and name != "-":
                    mp[str(sym)] = name
            # ⚠ 门面会**吞掉**网络错误回 `{}` ⇒ 这里必须把"一个都没回"翻译成人话，
            #   否则界面会误报成"东财没给这几只（停牌/退市）"—— 那是把网络问题说成数据问题。
            if not raw and self._symbols:
                err = "行情源没有返回数据（网络 / 频控 / 未登录）"
        except Exception as e:            # noqa: BLE001 —— 异常绝不穿透 QThread
            logger.warning("按池补行业失败: %s", e)
            err = f"{type(e).__name__}: {e}"
        missed = [s for s in self._symbols if s not in mp]
        self.finished.emit({"map": mp, "missed": missed, "error": err})
