# tests/unit/test_scan_and_texts.py
"""缓存键 / 数据版本 / 批量耗时文案 / 交易日定稿的纯函数测试（★2.04 / B1 第二层）。

跑法（仓库根目录）：
    py -m unittest discover -s tests/unit -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

from core.cross_section import ScanThresholds
from data.scan_store import (data_version, formula_fingerprint, scan_key,
                             signals_fingerprint, thresholds_fingerprint,
                             universe_fingerprint)
from data.sync_service import (ThrottlePolicy, abort_reason_text, estimate_seconds,
                               failure_hint, format_duration, is_daily_bar_settled)


class TestFingerprints(unittest.TestCase):
    def test_formula_ignores_comments_space_case(self):
        a = formula_fingerprint("COND := C > REF(C,1);")
        b = formula_fingerprint("cond:=c>ref(c,1);  // 备注\n")
        self.assertEqual(a, b)
        self.assertNotEqual(a, formula_fingerprint("COND := C > REF(C,2);"))

    def test_formula_params_order_insensitive(self):
        self.assertEqual(formula_fingerprint("C>1", {'a': 1, 'b': 2}),
                         formula_fingerprint("C>1", {'b': 2, 'a': 1}))
        self.assertNotEqual(formula_fingerprint("C>1", {'a': 1}),
                            formula_fingerprint("C>1", {'a': 2}))

    def test_thresholds_dict_and_object_same(self):
        default = ScanThresholds()
        self.assertEqual(thresholds_fingerprint(default), thresholds_fingerprint({}))
        changed = ScanThresholds(min_amount=1e8)
        self.assertNotEqual(thresholds_fingerprint(default), thresholds_fingerprint(changed))

    def test_universe_order_insensitive(self):
        self.assertEqual(universe_fingerprint(['600000', '000001']),
                         universe_fingerprint(['000001', '600000']))
        self.assertEqual(universe_fingerprint(None), 'all')
        self.assertNotEqual(universe_fingerprint(['600000']),
                            universe_fingerprint(['600000', '000001']))

    def test_signals_order_and_case_insensitive(self):
        self.assertEqual(signals_fingerprint(['a', 'B']), signals_fingerprint([' b ', 'A']))
        self.assertEqual(signals_fingerprint([]), '-')

    def test_scan_key_changes_with_each_component(self):
        base = dict(formula="C>1", thresholds=ScanThresholds(), symbols=['600000'],
                    adjust='qfq', zone_dir=None, snapshot_columns=('close',),
                    signal_names=['COND'])
        k0 = scan_key(**base)
        self.assertEqual(k0, scan_key(**base))
        self.assertNotEqual(k0, scan_key(**{**base, 'formula': 'C>2'}))
        self.assertNotEqual(k0, scan_key(**{**base, 'thresholds': ScanThresholds(min_amount=1e8)}))
        self.assertNotEqual(k0, scan_key(**{**base, 'adjust': 'none'}))
        self.assertNotEqual(k0, scan_key(**{**base, 'snapshot_columns': ('amount',)}))
        self.assertNotEqual(k0, scan_key(**{**base, 'signal_names': ['OTHER']}))
        # 顺序不影响
        self.assertEqual(k0, scan_key(**{**base, 'symbols': ['600000'],
                                         'snapshot_columns': ('close',)}))

    def test_data_version_changes_with_file_set(self):
        self.assertEqual(data_version(''), 'missing')
        self.assertEqual(data_version(os.path.join(tempfile.gettempdir(), 'no_such_zone_xyz')),
                         'missing')
        with tempfile.TemporaryDirectory(prefix='jian_unit_ver_') as d:
            self.assertTrue(data_version(d).startswith('0-'))
            p1 = os.path.join(d, '600000.parquet')
            with open(p1, 'wb') as f:
                f.write(b'x')
            v1 = data_version(d)
            p2 = os.path.join(d, '000001.parquet')
            with open(p2, 'wb') as f:
                f.write(b'y')
            v2 = data_version(d)
            self.assertNotEqual(v1, v2)
            st = os.stat(p1)
            os.utime(p1, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
            self.assertNotEqual(v2, data_version(d))


class TestBatchTexts(unittest.TestCase):
    def test_estimate_seconds(self):
        policy = ThrottlePolicy(interval=0.5, jitter=0.0)
        self.assertEqual(estimate_seconds(0, policy), 0)
        self.assertEqual(estimate_seconds(100, policy, stale_count=0), 0)
        self.assertGreater(estimate_seconds(100, policy), estimate_seconds(50, policy))

    def test_format_duration(self):
        self.assertEqual(format_duration(0), '0 秒')
        self.assertEqual(format_duration(59), '59 秒')
        self.assertEqual(format_duration(60), '1 分钟')
        self.assertEqual(format_duration(3600), '1.0 小时')

    def test_abort_reason(self):
        self.assertEqual(abort_reason_text({}), '')
        self.assertIn('代理', abort_reason_text({'aborted': True, 'aborted_by': 'proxy'}))
        self.assertIn('中断', abort_reason_text({'aborted': True, 'aborted_by': 'cancel'}))
        self.assertIn('限流', abort_reason_text({'aborted': True, 'aborted_by': 'circuit'}))

    def test_failure_hint_proxy_first(self):
        self.assertNotIn('代理', failure_hint({}))
        self.assertIn('代理', failure_hint({'aborted_by': 'proxy'}))


class TestSettleBoundary(unittest.TestCase):
    def test_settle_at_1505(self):
        day = datetime(2024, 1, 2)          # 周二
        self.assertFalse(is_daily_bar_settled(day.date(), now=day.replace(hour=15, minute=4)))
        self.assertTrue(is_daily_bar_settled(day.date(), now=day.replace(hour=15, minute=5)))
        # 未来日绝不算定稿（周末不在本函数判：交易日历由 trade_calendar 负责）
        self.assertFalse(is_daily_bar_settled(datetime(2024, 1, 7).date(),
                                              now=datetime(2024, 1, 6, 16, 0)))


if __name__ == '__main__':
    unittest.main()
