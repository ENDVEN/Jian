import os
import tempfile
import unittest

import pandas as pd

from config import settings
from data.catalog import Catalog
from data.contracts import AssetId, QualityReport, spec_for
from data.market_db import DataLakeManager
from data.sync_service import ZONE_KLINE


class TestContracts(unittest.TestCase):
    def test_asset_id_normalized(self):
        a = AssetId(" 600000 ", " cn ", " STOCK ").normalized()
        self.assertEqual(a.code, "600000")
        self.assertEqual(a.market, "CN")
        self.assertEqual(a.asset_type, "stock")
        self.assertEqual(str(a), "CN:stock:600000")

    def test_dataset_spec(self):
        spec = spec_for("bar_daily")
        self.assertEqual(spec.adjust, "qfq")
        self.assertIn("close", spec.required)
        self.assertEqual(spec.validate_columns(["date", "open", "close"]),
                         ["high", "low", "volume"])
        with self.assertRaises(KeyError):
            spec_for("no_such_dataset")

    def test_quality_report(self):
        q = QualityReport("sina", 10, 8)
        self.assertTrue(q.ok)
        self.assertIn("8/10", q.summary_line())
        q.throttled = True
        self.assertFalse(q.ok)
        self.assertIn("限流", q.summary_line())


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="jian_catalog_")
        self._old = settings.USER_DATA_DIR
        settings.USER_DATA_DIR = self._tmp.name
        self.cat = Catalog(os.path.join(self._tmp.name, "catalog.sqlite"))

    def tearDown(self):
        settings.USER_DATA_DIR = self._old
        self._tmp.cleanup()

    def test_register_record_summary(self):
        self.cat.register_specs()
        self.cat.record("bar_daily", "600000", last_date="2026-11-04",
                        rows=100, source="test")
        self.cat.record("bar_daily", "000001", last_date="2026-11-05",
                        rows=200, source="test")
        got = self.cat.get("bar_daily", "600000")
        self.assertEqual(got["rows"], 100)
        self.assertEqual(got["last_date"], "2026-11-04")
        summary = self.cat.summary("bar_daily")
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["covered"], 2)
        self.assertEqual(summary["rows"], 300)
        self.assertEqual(summary["last_date"], "2026-11-05")
        self.assertEqual(summary["sources"], ["test"])

    def test_scan_inventory(self):
        lake = DataLakeManager()
        for sym, day in (("600000", "2026-11-04"), ("000001", "2026-11-05")):
            df = pd.DataFrame({
                "date": pd.to_datetime([day]),
                "open": [10.0], "high": [10.1], "low": [9.9],
                "close": [10.0], "volume": [1000.0],
            })
            self.assertTrue(lake.save_data(ZONE_KLINE, sym, df))
        n = self.cat.scan_inventory(lake, ZONE_KLINE, "bar_daily", source="lake")
        self.assertEqual(n, 2)
        summary = self.cat.summary("bar_daily")
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["last_date"], "2026-11-05")


if __name__ == "__main__":
    unittest.main()
