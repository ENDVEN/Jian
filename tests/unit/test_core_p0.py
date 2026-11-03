# tests/unit/test_core_p0.py
"""纯函数单元测试（★2.04 / B1 测试分层第一层）。

跑法（仓库根目录，秒级）：
    py -m unittest discover -s tests/unit -v

只测**不依赖 Qt / 不读写用户数据**的内核：日期批量解析、roster 向量化、
footer LRU、组合统计的几条口径。页面级仍由两份 smoke 负责。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from core.engine import DataEngine
from core.portfolio_stats import annualized, market_of, max_drawdown, period_return
from data import readiness as rd
from data.trade_calendar import _to_date, to_dates


class TestTradeCalendarBatch(unittest.TestCase):
    def test_to_dates_matches_single(self):
        days = [str(d.date()) for d in pd.bdate_range("2024-01-01", periods=200)]
        mixed = days[:100] + ["", "坏日期", None, "2024-13-01"] + days[100:]
        self.assertEqual(to_dates(mixed), [_to_date(v) for v in mixed])

    def test_to_dates_accepts_series(self):
        # 回归：`values or []` 对 Series 会抛"真值歧义"
        ser = pd.Series(["2024-01-02", "2024-01-03", None])
        self.assertEqual(to_dates(ser), [_to_date(v) for v in ser])


class TestRosterVectorized(unittest.TestCase):
    def test_no_iterrows_and_semantics(self):
        df = pd.DataFrame({"symbol": ["600000", " 000001 ", None, ""],
                           "name": ["浦发银行", "平安银行", None, "x"]})

        class _DB:
            def load_roster(self):
                return df

        class _Eng:
            db = _DB()

        calls = {"n": 0}
        orig = pd.DataFrame.iterrows

        def counted(self):
            calls["n"] += 1
            return orig(self)

        with mock.patch.object(pd.DataFrame, "iterrows", counted):
            out = DataEngine.roster_names(_Eng())
        self.assertEqual(calls["n"], 0)
        self.assertEqual(out.get("600000"), "浦发银行")
        self.assertEqual(out.get("000001"), "平安银行")
        self.assertEqual(len(out), 2)


class TestFooterCache(unittest.TestCase):
    def setUp(self):
        rd._FOOTER_CACHE.clear()
        self._tmp = tempfile.TemporaryDirectory(prefix="jian_unit_footer_")
        self.path = os.path.join(self._tmp.name, "600000.parquet")
        pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                      "close": [1.0, 2.0]}).to_parquet(self.path, index=False)

    def tearDown(self):
        rd._FOOTER_CACHE.clear()
        self._tmp.cleanup()

    def test_hit_and_mtime_invalidation(self):
        real = rd.pq.ParquetFile
        calls = {"n": 0}

        def counted(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        rd.pq.ParquetFile = counted
        try:
            first = rd._footer_cached(self.path)
            second = rd._footer_cached(self.path)
            self.assertEqual(calls["n"], 1)
            self.assertEqual(first, second)
            st = os.stat(self.path)
            os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
            rd._footer_cached(self.path)
            self.assertEqual(calls["n"], 2)
        finally:
            rd.pq.ParquetFile = real


class TestPortfolioStats(unittest.TestCase):
    def test_market_of(self):
        self.assertEqual(market_of("600000"), "sh")
        self.assertEqual(market_of("510300"), "sh")
        self.assertEqual(market_of("000001"), "sz")
        self.assertEqual(market_of("159920"), "sz")
        self.assertEqual(market_of("830799"), "bj")
        self.assertEqual(market_of(""), "other")

    def test_nav_metrics(self):
        nav = pd.Series([1.0, 2.0, 1.0])
        self.assertAlmostEqual(max_drawdown(nav), 0.5)
        self.assertAlmostEqual(period_return(nav), 0.0)
        # 245 个点（244 个交易日 ≈ 1 年）翻倍 ⇒ 年化 ≈ 100%
        nav_year = pd.Series([1.0] + [2.0] * 244)
        self.assertAlmostEqual(annualized(nav_year), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
