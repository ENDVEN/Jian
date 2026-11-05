import os
import unittest
from unittest.mock import patch

from data import em_market


class TestSchedulerGate(unittest.TestCase):
    def tearDown(self):
        em_market._NET_SCHEDULER = None

    def test_http_get_returns_to_scheduler(self):
        em_market._NET_SCHEDULER = None
        with patch.dict(os.environ, {"JIAN_SCHEDULER": "1"}), \
             patch("data.em_market._do_get", return_value={"data": {}}):
            out = em_market._http_get("https://example.invalid", {},
                                      kind="unit_gate")
        self.assertEqual(out, {"data": {}})
        stats = em_market._net_scheduler().stats()
        self.assertEqual(stats["unit_gate"]["in_flight"], 0)
        self.assertEqual(stats["unit_gate"]["max_concurrency"], 2)


if __name__ == "__main__":
    unittest.main()
