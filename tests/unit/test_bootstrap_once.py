import os
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from data import bootstrap_once, em_history


class TestBootstrapOnce(unittest.TestCase):
    def setUp(self):
        self._old = settings.USER_DATA_DIR
        self._tmp = tempfile.TemporaryDirectory(prefix="jian_boot_once_")
        settings.USER_DATA_DIR = self._tmp.name

    def tearDown(self):
        settings.USER_DATA_DIR = self._old
        self._tmp.cleanup()

    def test_arm_consume(self):
        self.assertFalse(bootstrap_once.allowed())
        path = bootstrap_once.arm("test")
        self.assertTrue(os.path.exists(path))
        self.assertTrue(bootstrap_once.allowed())
        bootstrap_once.consume()
        self.assertFalse(bootstrap_once.allowed())
        self.assertIn("已消费", bootstrap_once.text())

    def test_over_budget_requires_explicit_flag(self):
        with patch("data.em_history.em_auth.is_logged_in", return_value=True), \
             patch("data.em_history.em_auth.budget_left", return_value=0), \
             patch("data.em_history.em_market._http_get",
                   return_value={"data": {"klines": [
                       "2026-11-04,10,10.1,10.2,9.9,100,1000,0,0,0,0"]}}):
            self.assertTrue(em_history.fetch_daily("600000").empty)
            got = em_history.fetch_daily("600000", allow_over_budget=True)
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()
