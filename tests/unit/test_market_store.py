import tempfile
import unittest

import pandas as pd

from config import settings
from data import daily_store
from data.market_db import DataLakeManager
from data.market_store import MarketDataStore


class TestMarketStore(unittest.TestCase):
    def setUp(self):
        self._old = settings.USER_DATA_DIR
        self._tmp = tempfile.TemporaryDirectory(prefix="jian_market_store_")
        settings.USER_DATA_DIR = self._tmp.name
        daily_store._LATEST_CACHE.clear()
        self.lake = DataLakeManager()
        self.store = MarketDataStore(self.lake)

    def tearDown(self):
        settings.USER_DATA_DIR = self._old
        daily_store._LATEST_CACHE.clear()
        self._tmp.cleanup()

    @staticmethod
    def _history(days=("2026-11-02", "2026-11-03")):
        return pd.DataFrame({
            "date": pd.to_datetime(list(days)),
            "open": [10.0, 10.1], "high": [10.2, 10.3],
            "low": [9.9, 10.0], "close": [10.1, 10.2],
            "volume": [100, 200],
        })

    @staticmethod
    def _snap(close=10.5):
        return pd.DataFrame({
            "symbol": ["600000"], "close": [close], "open": [10.3],
            "high": [10.6], "low": [10.2], "volume": [300],
            "prev_close": [10.2], "name": ["浦发"],
        })

    def test_history_without_snapshot(self):
        self.lake.save_data("kline_daily", "600000", self._history())
        got = self.store.history("600000")
        self.assertEqual(len(got), 2)

    def test_history_merges_snapshot_fallback(self):
        self.lake.save_data("kline_daily", "600000", self._history())
        daily_store.write_snapshot(self._snap(), "2026-11-04")
        got = self.store.history("600000")
        self.assertEqual(len(got), 3)
        self.assertEqual(float(got.iloc[-1]["close"]), 10.5)
        self.assertNotIn("prev_close", got.columns)
        self.assertNotIn("name", got.columns)

    def test_snapshot_same_day_wins(self):
        self.lake.save_data("kline_daily", "600000", self._history())
        daily_store.write_snapshot(self._snap(10.5), "2026-11-04")
        daily_store.write_snapshot(self._snap(10.8), "2026-11-04")
        got = self.store.history("600000")
        self.assertEqual(len(got), 3)
        self.assertEqual(float(got.iloc[-1]["close"]), 10.8)

    def test_cross_section_filter(self):
        daily_store.write_snapshot(
            pd.DataFrame({"symbol": ["600000", "000001"], "close": [10.0, 20.0]}),
            "2026-11-04")
        got = self.store.cross_section("2026-11-04", symbols=["000001"])
        self.assertEqual(len(got), 1)
        self.assertEqual(got.iloc[0]["symbol"], "000001")

    def test_latest_asof(self):
        self.assertEqual(self.store.latest_asof(), "")
        daily_store.write_snapshot(self._snap(), "2026-11-04")
        self.assertEqual(self.store.latest_asof(), "2026-11-04")


if __name__ == "__main__":
    unittest.main()
