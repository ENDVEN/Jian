# tests/unit/test_core_math_and_store.py
"""指标 / 净额 / 参数文本 / 组合成分 diff 的纯函数测试（★2.04 / B1 第四层）。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from core.backtest import commission_text, normalize_risk, risk_summary
from core.indicators import TAEngine
from core.utils import (format_points, format_price, format_trade_time,
                        parse_params_text, record_net_amount, row_points)
from data.portfolio_store import diff_members


class TestParamsAndNet(unittest.TestCase):
    def test_parse_params_text(self):
        self.assertEqual(parse_params_text("n1=5, N2 = -2.5; x"),
                         {"N1": 5.0, "N2": -2.5})
        self.assertEqual(parse_params_text(""), {})
        self.assertEqual(parse_params_text("坏文本"), {})

    def test_record_net_amount_dict_series_object(self):
        self.assertAlmostEqual(record_net_amount({"net_profit": 100.0, "commission": 3.0}), 97.0)
        self.assertAlmostEqual(
            record_net_amount(pd.Series({"net_profit": 50.0, "commission": 1.5})), 48.5)
        rec = SimpleNamespace(net_profit=10.0, commission=2.0)
        self.assertAlmostEqual(record_net_amount(rec), 8.0)
        # 缺字段 / NaN / 脏值一律按 0，不抛
        self.assertEqual(record_net_amount({}), 0.0)
        self.assertEqual(record_net_amount({"net_profit": None, "commission": "x"}), 0.0)

    def test_commission_text(self):
        self.assertEqual(commission_text(0.0003), "万3")
        self.assertEqual(commission_text(0), "免佣金")
        self.assertEqual(commission_text(None), "—")


class TestRiskAndFormat(unittest.TestCase):
    def test_risk_summary(self):
        self.assertEqual(risk_summary({}), "全部关闭")
        text = risk_summary({"max_bars": 5, "stop_loss_pct": 8,
                             "take_profit_pct": 20, "trailing_pct": 3})
        self.assertIn("最长持仓 5 根", text)
        self.assertIn("固定止损 8%", text)
        self.assertIn("固定止盈 20%", text)
        self.assertIn("移动止盈回撤 3%", text)
        self.assertEqual(risk_summary({"max_bars": "bad"}), "全部关闭")

    def test_normalize_risk(self):
        out = normalize_risk({"max_bars": "5", "stop_loss_pct": 8,
                              "take_profit_pct": -2, "trailing_pct": "bad"})
        self.assertEqual(out["max_bars"], 5)
        self.assertAlmostEqual(out["stop_loss_pct"], 0.08)
        self.assertEqual(out["take_profit_pct"], 0.0)
        self.assertEqual(out["trailing_pct"], 0.0)

    def test_trade_time_and_price_format(self):
        self.assertEqual(format_trade_time(None), "-")
        self.assertEqual(format_trade_time("2024-01-02"), "2024-01-02")
        self.assertEqual(format_trade_time("2024-01-02 09:31:00"), "2024-01-02 09:31")
        self.assertEqual(format_price(None), "—")
        self.assertEqual(format_price(0), "—")
        self.assertEqual(format_price(12.3400), "12.34")
        self.assertEqual(format_price(6012.4), "6,012.4")
        self.assertEqual(format_points(1.234), "+1.2")

    def test_row_points_direction(self):
        self.assertAlmostEqual(row_points({"entry_price": 10, "exit_price": 12,
                                           "direction": "LONG"}), 2.0)
        self.assertAlmostEqual(row_points({"entry_price": 10, "exit_price": 12,
                                           "direction": "SHORT"}), -2.0)
        self.assertIsNone(row_points({"entry_price": None, "exit_price": 12}))
        self.assertIsNone(row_points({"entry_price": 0, "exit_price": 12}))


class TestIndicators(unittest.TestCase):
    def test_add_ma_values(self):
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
        out = TAEngine.add_ma(df, windows=(2, 3))
        self.assertAlmostEqual(out["MA_2"].iloc[1], 1.5)
        self.assertAlmostEqual(out["MA_2"].iloc[4], 4.5)
        self.assertAlmostEqual(out["MA_3"].iloc[2], 2.0)
        self.assertTrue(pd.isna(out["MA_3"].iloc[1]))

    def test_add_boll_columns_and_mid(self):
        df = pd.DataFrame({"close": [float(i) for i in range(1, 26)]})
        out = TAEngine.add_boll(df, window=20, num_std=2)
        for col in ("BOLL_UP", "BOLL_MID", "BOLL_DOWN"):
            self.assertIn(col, out.columns)
        self.assertAlmostEqual(out["BOLL_MID"].iloc[-1], out["close"].iloc[-20:].mean())
        self.assertGreater(out["BOLL_UP"].iloc[-1], out["BOLL_MID"].iloc[-1])

    def test_add_macd_columns(self):
        df = pd.DataFrame({"close": [float(i) for i in range(1, 50)]})
        out = TAEngine.add_macd(df)
        for col in ("MACD_line", "MACD_signal", "MACD_hist"):
            self.assertIn(col, out.columns)


class TestMemberDiff(unittest.TestCase):
    def test_add_remove_move_and_cash(self):
        before = [{"symbol": "A", "name": "甲", "weight": 50},
                  {"symbol": "B", "name": "乙", "weight": 50}]
        after = [{"symbol": "A", "name": "甲", "weight": 60},
                 {"symbol": "C", "name": "丙", "weight": 40}]
        d = diff_members(before, 0, after, 10)
        self.assertTrue(d["has_change"])
        self.assertEqual([m["symbol"] for m in d["added"]], ["C"])
        self.assertEqual([m["symbol"] for m in d["removed"]], ["B"])
        self.assertEqual([m["symbol"] for m in d["moved"]], ["A"])
        self.assertAlmostEqual(d["moved"][0]["delta"], 10.0)
        self.assertEqual(d["cash_after"], 10.0)

    def test_no_change(self):
        same = [{"symbol": "A", "weight": 50}, {"symbol": "B", "weight": 50}]
        d = diff_members(same, 0, [dict(m) for m in same], 0)
        self.assertFalse(d["has_change"])
        self.assertEqual(d["added"], [])
        self.assertEqual(d["removed"], [])
        self.assertEqual(d["moved"], [])


if __name__ == "__main__":
    unittest.main()
