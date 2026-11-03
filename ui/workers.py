# ui/workers.py
"""全 app 的 QThread 门面（★2.04 / P2 拆件后只做再导出）。

QThread 类已按领域拆到：
  · `workers_scan.py`      扫描 / 成分股 / 就绪度 / 日历
  · `workers_download.py`  批量下载 / 自检 / 缓存 / 更新
  · `workers_backtest.py`  回测 / 参数扫描 / 组合池化
  · `workers_sync.py`      单只同步 / 花名册 / 估值 / 行业
  · `workers_imports.py`   期货交割单解析
  · `workers_core.py`      JobGuard（竞态守卫）
  · `workers_throttle.py`  RateGovernor / 日历注入

页面与弹窗仍一律 `from ui.workers import X`（旧路径不变）；
**不得**在页面/弹窗里自造 QThread 类（§10-12）。
"""
from __future__ import annotations

import logging

# ★2.04：旧 `ui.workers` 的这些模块级名字曾被测试/旧代码打桩或直接引用；
#   保留同名再导出，避免拆件改变打桩点。
from core.backtest import BacktestEngine  # noqa: F401
from core.cross_section import ScanCancelled  # noqa: F401
from core.param_sweep import run_sweep  # noqa: F401
from core.sweep_plan import GridPlan, StudyInterval  # noqa: F401
from data.market_db import DataLakeManager  # noqa: F401
from data.readiness import ReadinessCancelled, probe_readiness  # noqa: F401
from data.scan_store import scan_cached  # noqa: F401
from data.sync_service import (MarketSyncService, ThrottlePolicy, ZONE_KLINE,
                               fetch_enrich_map, fetch_industry_page,
                               is_daily_bar_settled, network_self_check,
                               short_fetch_reason, spot_valuation_map)  # noqa: F401
from data.trade_calendar import load_or_fetch, previous_trading_day  # noqa: F401
from ui.workers_backtest import (BacktestRunWorker, ParamSweepWorker,
                                 PoolSweepWorker)
from ui.workers_core import JobGuard
from ui.workers_download import (CacheCleanWorker, NetSelfCheckWorker,
                                 SyncWorker, UpdateCheckWorker)
from ui.workers_imports import FuturesImportWorker
from ui.workers_scan import (CalendarWorker, ConstituentsWorker,
                             CrossSectionWorker, ReadinessWorker, ScanWorker)
from ui.workers_sync import (IndustryMapWorker, IndustryPoolWorker,
                             RosterSyncWorker, SingleSyncWorker,
                             SpotValuationWorker)
from ui.workers_throttle import (RateGovernor, _CAL_UNSET, _load_calendar_safely,
                                 inject_expected_latest)

logger = logging.getLogger(__name__)

__all__ = [
    "ScanWorker", "SyncWorker", "RosterSyncWorker", "SingleSyncWorker",
    "SpotValuationWorker", "IndustryMapWorker", "IndustryPoolWorker",
    "NetSelfCheckWorker", "CacheCleanWorker", "UpdateCheckWorker",
    "BacktestRunWorker", "ParamSweepWorker", "PoolSweepWorker",
    "ConstituentsWorker", "FuturesImportWorker", "CrossSectionWorker",
    "ReadinessWorker", "CalendarWorker", "JobGuard", "RateGovernor",
    "inject_expected_latest", "_load_calendar_safely", "_CAL_UNSET",
]
