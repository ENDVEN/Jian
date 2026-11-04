import unittest
from unittest.mock import patch

import pandas as pd

from data import em_history
from data.quality import check_ohlcv


def _df():
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-11-03", "2026-11-04"]),
        "open": [10.0, 10.1], "high": [10.2, 10.3],
        "low": [9.9, 10.0], "close": [10.1, 10.2],
        "volume": [100, 200],
    })


class TestQuality(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(check_ohlcv(_df()), [])

    def test_negative_close(self):
        df = _df()
        df.loc[0, "close"] = -1
        self.assertTrue(any("close" in p for p in check_ohlcv(df)))

    def test_high_low(self):
        df = _df()
        df.loc[0, "high"] = 1
        self.assertIn("high < low", check_ohlcv(df))

    def test_duplicate_date(self):
        df = _df()
        df.loc[1, "date"] = df.loc[0, "date"]
        self.assertIn("date 重复", check_ohlcv(df))


class TestEMHistoryRejectsBadRows(unittest.TestCase):
    def test_reject_negative(self):
        with patch("data.em_history.em_auth.is_logged_in", return_value=True), \
             patch("data.em_history.em_auth.budget_left", return_value=10), \
             patch("data.em_history.em_market._http_get",
                   return_value={"data": {"klines": [
                       "2026-11-04,-10,-10.1,10.2,9.9,100,1000,0,0,0,0"]}}):
            self.assertTrue(em_history.fetch_daily("600000").empty)


if __name__ == "__main__":
    unittest.main()
