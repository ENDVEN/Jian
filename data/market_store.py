# data/market_store.py
"""统一读门面（★2.05 / DATA-PLATFORM P1）。

日更采用“symbol 历史 + 日快照”混合布局；正常路径下快照已立即合并进历史。
本门面负责**兜底合并**：如果合并中断/失败，读取时仍能把最新快照并进来，
页面不必知道快照文件存在。

只读；写路径仍由 `DailySnapshotWorker` / `DataLakeManager` 负责。
"""
from __future__ import annotations

import logging

import pandas as pd

from data import daily_store
from data.market_db import DataLakeManager
from data.sync_service import ZONE_KLINE

logger = logging.getLogger(__name__)

__all__ = ["MarketDataStore"]


class MarketDataStore:
    """历史 + 快照的唯一读口；不改变已有落盘格式。"""

    def __init__(self, lake: DataLakeManager = None):
        self.lake = lake or DataLakeManager()

    def history(self, symbol: str, zone: str = ZONE_KLINE) -> pd.DataFrame:
        """读单只历史；日线额外合并最新快照（同日以快照为准）。"""
        sym = str(symbol or "").strip()
        if not sym:
            return pd.DataFrame()
        old = self.lake.load_data(zone, sym)
        if zone != ZONE_KLINE:
            return old
        try:
            _asof, snap = daily_store.latest_snapshot()
            if snap is None or snap.empty or "symbol" not in snap.columns:
                return old
            row = snap[snap["symbol"].astype(str) == sym]
            if row.empty:
                return old
            return daily_store.merge_row(old, row.iloc[-1])
        except Exception as e:  # noqa: BLE001 —— 快照坏了不能挡住历史
            logger.warning("快照兜底合并失败 [%s]: %s", sym, e)
            return old

    def cross_section(self, asof, symbols=None) -> pd.DataFrame:
        """读某日全市场快照（没有快照 ⇒ 空表；不从 5000 个历史文件反扫）。"""
        data = daily_store.read_snapshot(asof)
        if data is None or data.empty:
            return pd.DataFrame()
        want = [str(s).strip() for s in (symbols or []) if str(s).strip()]
        if want:
            data = data[data["symbol"].astype(str).isin(set(want))]
        return data.reset_index(drop=True)

    def latest_asof(self) -> str:
        asof, _ = daily_store.latest_snapshot()
        return asof
