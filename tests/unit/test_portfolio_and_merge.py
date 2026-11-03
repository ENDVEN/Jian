# tests/unit/test_portfolio_and_merge.py
"""组合统计 / 横截面增量续接的纯函数测试（★2.04 / B1 第三层）。"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from core.cross_section import CrossSectionResult
from core.portfolio_stats import (build_returns, cap_weights, holdings_rows,
                                   industry_mix, market_mix, nav_series)
from data.scan_store import merge_tail


def _frame(dates, closes):
    return pd.DataFrame({"date": pd.to_datetime(dates), "close": closes})


class TestPortfolioReturns(unittest.TestCase):
    def test_build_returns_uses_intersection(self):
        f1 = _frame(["2024-01-01", "2024-01-02", "2024-01-03"], [10.0, 11.0, 12.0])
        f2 = _frame(["2024-01-02", "2024-01-03", "2024-01-04"], [20.0, 22.0, 24.0])
        days, rets = build_returns({"A": f1, "B": f2})
        self.assertEqual(days, ["2024-01-02", "2024-01-03"])
        self.assertEqual(list(rets["A"].index), days)
        self.assertEqual(list(rets["B"].index), days)
        self.assertFalse(rets["A"].isna().any())
        self.assertAlmostEqual(float(rets["A"].iloc[-1]), 12.0 / 11.0 - 1.0)

    def test_build_returns_empty(self):
        days, rets = build_returns({})
        self.assertEqual(days, [])
        self.assertEqual(rets, {})


class TestNavSeries(unittest.TestCase):
    def test_flat_returns_keep_one(self):
        days = ["2024-01-02", "2024-01-03", "2024-01-04"]
        rets = {"A": np.zeros(3), "B": np.zeros(3)}
        nav = nav_series(days, rets, {"A": 50, "B": 50}, cash=0.0)
        self.assertEqual(list(nav.index), days)
        self.assertTrue(all(abs(v - 1.0) < 1e-12 for v in nav))

    def test_cash_kept_as_fixed_share(self):
        days = ["2024-01-02", "2024-01-03"]
        rets = {"A": np.zeros(2), "B": np.zeros(2)}
        nav = nav_series(days, rets, {"A": 40, "B": 40}, cash=20.0)
        self.assertTrue(all(abs(v - 1.0) < 1e-12 for v in nav))

    def test_buy_hold_weight_drifts(self):
        days = ["2024-01-02", "2024-01-03"]
        rets = {"A": np.array([0.0, 0.10]), "B": np.array([0.0, 0.0])}
        nav = nav_series(days, rets, {"A": 50, "B": 50}, cash=0.0, rebalance="buy_hold")
        self.assertAlmostEqual(float(nav.iloc[0]), 1.0)
        self.assertAlmostEqual(float(nav.iloc[1]), 1.05)


class TestHoldingsAndMix(unittest.TestCase):
    def test_holdings_rows_honest_when_missing(self):
        rows = holdings_rows(["600000", "000001"], {"600000": "浦发"}, {"600000": 60, "000001": 40},
                             {"600000": 10.0, "000001": None}, {"600000": 11.0, "000001": 20.0})
        self.assertTrue(rows[0]["data_ok"])
        self.assertAlmostEqual(rows[0]["pnl"], 0.1)
        self.assertFalse(rows[1]["data_ok"])
        self.assertIsNone(rows[1]["pnl"])

    def test_market_and_industry_mix(self):
        members = [{"symbol": "600000", "weight": 60}, {"symbol": "000001", "weight": 40}]
        mix = dict(market_mix(members, cash=0.0))
        self.assertEqual(mix["沪市"], 60)
        self.assertEqual(mix["深市"], 40)
        ind = dict(industry_mix(members, {"600000": "银行"}, cash=0.0))
        self.assertEqual(ind["银行"], 60)
        self.assertEqual(ind["未分类"], 40)

    def test_cap_weights_sum_to_target_and_skip_missing(self):
        out = cap_weights({"A": 1.0, "B": 3.0}, ["A", "B", "C"], cash=10.0)
        self.assertEqual(set(out), {"A", "B"})
        self.assertAlmostEqual(sum(out.values()), 90.0, places=2)
        self.assertEqual(cap_weights({}, ["A"]), {})


def _res(dates, counters, matrix, symbols, **kw):
    return CrossSectionResult(
        dates=pd.DatetimeIndex(dates),
        counters=np.asarray(counters, dtype=int),
        status_matrix=np.asarray(matrix, dtype=np.uint8),
        symbols=list(symbols), **kw)


class TestMergeTail(unittest.TestCase):
    def setUp(self):
        self.base = _res(["2024-01-02", "2024-01-03"],
                         [[1, 2, 3, 4], [5, 6, 7, 8]], [[1, 2], [3, 4]], ["A", "B"])
        self.fresh = _res(["2024-01-02", "2024-01-03", "2024-01-04"],
                          [[9, 9, 9, 9], [10, 10, 10, 10], [11, 11, 11, 11]],
                          [[1, 2, 5], [3, 4, 6]], ["A", "B"])

    def test_appends_only_new_tail(self):
        merged = merge_tail(self.base, self.fresh)
        self.assertIsNotNone(merged)
        self.assertEqual([str(d.date()) for d in merged.dates],
                         ["2024-01-02", "2024-01-03", "2024-01-04"])
        self.assertEqual(merged.symbols, ["A", "B"])
        self.assertEqual(merged.counters.tolist(),
                         [[1, 2, 3, 4], [5, 6, 7, 8], [11, 11, 11, 11]])
        self.assertEqual(merged.status_matrix.tolist(), [[1, 2, 5], [3, 4, 6]])
        # 入参不被修改
        self.assertEqual(len(self.base.dates), 2)
        self.assertEqual(len(self.fresh.dates), 3)

    def test_no_new_day_returns_none(self):
        same = _res(["2024-01-02", "2024-01-03"],
                    [[1, 2, 3, 4], [5, 6, 7, 8]], [[1, 2], [3, 4]], ["A", "B"])
        self.assertIsNone(merge_tail(self.base, same))

    def test_signal_set_mismatch_is_reported(self):
        self.base.counters_by_signal = {"A": self.base.counters, "B": self.base.counters}
        self.fresh.counters_by_signal = {"A": self.fresh.counters}
        merged = merge_tail(self.base, self.fresh)
        self.assertIn("判定变量集合", " ".join(merged.warnings))
        self.assertNotIn("B", merged.counters_by_signal)


if __name__ == "__main__":
    unittest.main()
