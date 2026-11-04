import unittest
from unittest.mock import patch

from data import em_history


class TestEMHistory(unittest.TestCase):
    def test_parse_klines_units_and_columns(self):
        rows = [
            "2026-11-03,1470.0,1446.44,1480.6,1439.0,65434,965000000,0,0,0,0",
            "2026-11-04,1446.0,1450.0,1455.0,1440.0,1000,145000000,0,0,0,0",
        ]
        df = em_history.parse_klines(rows, "600519")
        self.assertEqual(len(df), 2)
        self.assertEqual(float(df.iloc[-1]["volume"]), 100000.0)
        self.assertEqual(float(df.iloc[-1]["amount"]), 145000000.0)
        self.assertEqual(str(df.iloc[-1]["date"])[:10], "2026-11-04")

    def test_fetch_requires_login(self):
        with patch("data.em_history.em_auth.is_logged_in", return_value=False):
            self.assertTrue(em_history.fetch_daily("600519").empty)

    def test_fetch_stops_at_budget(self):
        with patch("data.em_history.em_auth.is_logged_in", return_value=True), \
             patch("data.em_history.em_auth.budget_left", return_value=0):
            self.assertTrue(em_history.fetch_daily("600519").empty)


if __name__ == "__main__":
    unittest.main()
