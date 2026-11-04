import unittest
from unittest.mock import patch

import pandas as pd

from data.sina_market import parse_batch
from data.sync_service import MarketSyncService


class TestSinaMarket(unittest.TestCase):
    def test_parse_batch_standard_columns(self):
        text = (
            'var hq_str_sh600000="浦发银行,10.050,10.090,10.090,10.230,10.050,'
            '10.090,10.100,82408649,835024728.000,32500,10.090,48200,10.080,'
            '199600,10.070,343400,10.060,355200,10.050,32000,10.100,49700,10.110,'
            '38700,10.120,29230,10.130,13500,10.140,2026-11-04,15:34:59,00,D";\n'
            'var hq_str_sz000001="平安银行,10.0,10.1,10.2,10.3,9.9,10.2,10.3,'
            '100,1000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-11-04,15:00:00,00";\n')
        df = parse_batch(text)
        self.assertEqual(len(df), 2)
        self.assertEqual(set(df["symbol"]), {"600000", "000001"})
        self.assertEqual(float(df[df["symbol"] == "600000"].iloc[0]["close"]), 10.09)
        self.assertEqual(float(df[df["symbol"] == "600000"].iloc[0]["volume"]), 82408649)

    def test_parse_batch_ignores_empty_and_bad(self):
        text = ('var hq_str_sh600000="";\n'
                'var hq_str_sz000001="平安银行,1,2";\n')
        self.assertTrue(parse_batch(text).empty)

    def test_spot_snapshot_fallback_opt_in(self):
        svc = MarketSyncService.__new__(MarketSyncService)   # 不走 __init__/数据湖
        fallback = pd.DataFrame({
            "symbol": ["600000"], "name": ["浦发银行"], "open": [10.0],
            "prev_close": [9.9], "close": [10.1], "high": [10.2],
            "low": [9.9], "volume": [1000], "amount": [1e6],
        })
        empty = pd.DataFrame()
        with patch("data.sync_service.AkShareFeed.fetch_market_spot_daily",
                   return_value=empty), \
             patch("data.sina_market.fetch_batch_quotes", return_value=fallback):
            out = svc.fetch_spot_snapshot(["600000"], allow_fallback=True)
            off = svc.fetch_spot_snapshot(["600000"], allow_fallback=False)
        self.assertIn("600000", out)
        self.assertEqual(off, {})

    def test_market_snapshot_fallback(self):
        svc = MarketSyncService.__new__(MarketSyncService)
        fallback = pd.DataFrame({"symbol": ["600000"], "close": [10.1]})
        with patch("data.em_market.fetch_market_quotes", return_value=pd.DataFrame()), \
             patch("data.sina_market.fetch_batch_quotes", return_value=fallback):
            out = svc.fetch_market_snapshot(fallback_symbols=["600000"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["symbol"], "600000")


if __name__ == "__main__":
    unittest.main()
