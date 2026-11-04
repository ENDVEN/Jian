import unittest
from types import SimpleNamespace

from data.backfill import plan_from_report, plan_startup


class TestBackfillPlan(unittest.TestCase):
    def _report(self):
        return SimpleNamespace(
            total=10,
            ready=["600000", "600001", "600002"],
            missing=["600003", "600004"],
            partial={"600005": 100, "600006": 50},
            unreadable={"600007": "bad parquet"},
        )

    def test_order_and_dedup(self):
        plan = plan_from_report(self._report())
        self.assertEqual(plan.symbols,
                         ["600003", "600004", "600005", "600006", "600007"])
        self.assertEqual(plan.need_count, 5)
        self.assertEqual(plan.coverage, 0.3)

    def test_batches(self):
        plan = plan_from_report(self._report())
        self.assertEqual(plan.batches(2),
                         [["600003", "600004"], ["600005", "600006"], ["600007"]])
        self.assertEqual(plan.batches(100), [plan.symbols])

    def test_empty(self):
        plan = plan_from_report(None)
        self.assertEqual(plan.symbols, [])
        self.assertEqual(plan.coverage, 0.0)
        self.assertIn("范围是空的", plan.summary_line())

    def test_summary_mentions_all_buckets(self):
        text = plan_from_report(self._report()).summary_line()
        self.assertIn("未下载 2", text)
        self.assertIn("历史不足 2", text)
        self.assertIn("坏文件 1", text)


class TestStartupPlan(unittest.TestCase):
    def _report(self, latest, last_by_symbol=None, missing=None):
        return SimpleNamespace(
            total=3, representative_latest=latest,
            last_by_symbol=last_by_symbol or {"600000": latest},
            missing=missing or [],
        )

    def test_no_expected_does_nothing(self):
        plan = plan_startup(self._report("2026-11-04"), None, None)
        self.assertEqual(plan.action, "none")

    def test_already_latest(self):
        plan = plan_startup(self._report("2026-11-05"), "2026-11-05", "2026-11-04")
        self.assertEqual(plan.action, "none")

    def test_only_today_missing_uses_snapshot(self):
        plan = plan_startup(self._report("2026-11-04"), "2026-11-05", "2026-11-04")
        self.assertEqual(plan.action, "snapshot")

    def test_larger_gap_uses_backfill(self):
        plan = plan_startup(
            self._report("2026-11-01",
                         last_by_symbol={"600000": "2026-11-01",
                                         "000001": "2026-10-30"},
                         missing=["600002"]),
            "2026-11-05", "2026-11-04")
        self.assertEqual(plan.action, "backfill")
        self.assertEqual(plan.symbols, ["600000", "000001", "600002"])

    def test_no_data_uses_snapshot(self):
        plan = plan_startup(self._report(None, last_by_symbol={}, missing=[]),
                            "2026-11-05", "2026-11-04")
        self.assertEqual(plan.action, "snapshot")


if __name__ == "__main__":
    unittest.main()
