import unittest
from unittest.mock import patch

from data import provider_caps
from data.provider_registry import PROVIDERS, providers_for


class TestProviderCaps(unittest.TestCase):
    def test_rows_cover_known_features(self):
        keys = {r.key for r in provider_caps.rows()}
        self.assertIn("market_snapshot", keys)
        self.assertIn("sina_history", keys)
        self.assertIn("em_history", keys)
        self.assertIn("fundamentals", keys)

    def test_summary_mentions_anonymous_limits(self):
        with patch("data.provider_caps.current_mode", return_value="anonymous"):
            text = provider_caps.summary_line()
        self.assertIn("匿名", text)
        self.assertIn("东财单只历史受限", text)

    def test_detail_contains_both_columns(self):
        text = provider_caps.detail_text()
        self.assertIn("匿名：可用", text)
        self.assertIn("登录：已实测 K=16", text)
        self.assertIn("未登录不会让软件不可用", text)


class TestProviderRegistry(unittest.TestCase):
    def test_bar_daily_providers(self):
        names = [p.name for p in providers_for("bar_daily")]
        self.assertEqual(names, ["eastmoney", "sina", "tencent", "netease", "baostock"])

    def test_snapshot_eastmoney_and_sina(self):
        names = [p.name for p in providers_for("quote_snapshot")]
        self.assertEqual(names, ["eastmoney", "sina"])

    def test_statuses_are_explicit(self):
        status = {p.name: p.status for p in PROVIDERS}
        self.assertEqual(status["netease"], "unavailable")
        self.assertEqual(status["tencent"], "limited")
        self.assertEqual(status["baostock"], "not_installed")


if __name__ == "__main__":
    unittest.main()
