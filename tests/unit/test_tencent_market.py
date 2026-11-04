import unittest
from datetime import date

from data.provider_router import history_order, is_recent_start
from data.tencent_market import parse_payload


class TestTencentMarket(unittest.TestCase):
    def test_parse_qfq_and_volume_unit(self):
        obj = {"data": {"sh600519": {"qfqday": [
            ["2026-11-03", "1470.0", "1446.44", "1480.6", "1439.0", "65434.0", "x"],
            ["2026-11-04", "1446.0", "1450.0", "1455.0", "1440.0", "1000.0"],
        ]}}}
        df = parse_payload(obj, "600519")
        self.assertEqual(len(df), 2)
        self.assertEqual(float(df.iloc[-1]["volume"]), 100000.0)
        self.assertEqual(float(df.iloc[-1]["close"]), 1450.0)
        self.assertEqual(str(df.iloc[-1]["date"])[:10], "2026-11-04")

    def test_parse_empty(self):
        self.assertTrue(parse_payload({}, "600519").empty)

    def test_recent_start_orders_tencent(self):
        self.assertTrue(is_recent_start("20260101", today=date(2026, 11, 5)))
        self.assertEqual(history_order("20260101", today=date(2026, 11, 5)),
                         ["sina", "tencent", "eastmoney"])

    def test_old_start_skips_tencent(self):
        self.assertFalse(is_recent_start("20100101", today=date(2026, 11, 5)))
        self.assertEqual(history_order("20100101", today=date(2026, 11, 5)),
                         ["sina", "eastmoney"])


if __name__ == "__main__":
    unittest.main()
