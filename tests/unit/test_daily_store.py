import os
import tempfile
import unittest

import pandas as pd

from config import settings
from data import daily_store


class TestDailyStore(unittest.TestCase):
    def setUp(self):
        self._old = settings.USER_DATA_DIR
        self._tmp = tempfile.TemporaryDirectory(prefix="jian_daily_store_")
        settings.USER_DATA_DIR = self._tmp.name

    def tearDown(self):
        settings.USER_DATA_DIR = self._old
        self._tmp.cleanup()

    @staticmethod
    def _snap():
        return pd.DataFrame({
            "symbol": ["600000", "000001", "600000", "bad"],
            "close": [10.0, 20.0, 10.1, 0.0],
            "open": [9.9, 19.9, 10.0, 1.0],
            "high": [10.2, 20.2, 10.2, 1.0],
            "low": [9.8, 19.8, 10.0, 1.0],
            "volume": [100, 200, 101, 10],
            "prev_close": [9.8, 19.8, 9.8, 1.0],
            "name": ["浦发", "平安", "浦发", "坏"],
        })

    def test_normalize_dedup_and_filter(self):
        out = daily_store.normalize_snapshot(self._snap(), "2026-11-04")
        self.assertEqual(len(out), 2)
        self.assertEqual(set(out["symbol"]), {"600000", "000001"})
        self.assertTrue((out["date"] == pd.Timestamp("2026-11-04")).all())
        self.assertEqual(float(out[out["symbol"] == "600000"]["close"].iloc[0]), 10.1)

    def test_write_read_roundtrip_and_latest(self):
        path = daily_store.write_snapshot(self._snap(), "2026-11-04")
        self.assertTrue(path and os.path.exists(path))
        got = daily_store.read_snapshot("2026-11-04")
        self.assertEqual(len(got), 2)
        asof, latest = daily_store.latest_snapshot()
        self.assertEqual(asof, "2026-11-04")
        self.assertEqual(len(latest), 2)

    def test_merge_row_append_and_dedupe(self):
        old = pd.DataFrame({
            "date": pd.to_datetime(["2026-11-02", "2026-11-03"]),
            "symbol": ["600000", "600000"],
            "open": [9.0, 9.5], "high": [9.2, 9.7], "low": [8.9, 9.4],
            "close": [9.1, 9.6], "volume": [1, 2],
        })
        row = pd.Series({"symbol": "600000", "date": "2026-11-04", "open": 9.8,
                         "high": 10.1, "low": 9.7, "close": 10.0, "volume": 3,
                         "prev_close": 9.6, "name": "浦发", "pe": 10.0})
        merged = daily_store.merge_row(old, row)
        self.assertEqual(len(merged), 3)
        self.assertNotIn("prev_close", merged.columns)
        self.assertNotIn("pe", merged.columns)
        # 同日再合并：以新行为准，不新增行
        row2 = row.copy()
        row2["close"] = 10.5
        merged2 = daily_store.merge_row(merged, row2)
        self.assertEqual(len(merged2), 3)
        self.assertEqual(float(merged2.iloc[-1]["close"]), 10.5)

    def test_merge_row_without_symbol_column(self):
        old = pd.DataFrame({
            "date": pd.to_datetime(["2026-11-03"]),
            "open": [9.0], "high": [9.2], "low": [8.9],
            "close": [9.1], "volume": [1],
        })
        row = pd.Series({"symbol": "600000", "date": "2026-11-04", "open": 9.8,
                         "high": 10.1, "low": 9.7, "close": 10.0, "volume": 3})
        merged = daily_store.merge_row(old, row)
        self.assertEqual(len(merged), 2)
        self.assertNotIn("symbol", merged.columns)


if __name__ == "__main__":
    unittest.main()
