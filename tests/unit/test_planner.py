import unittest

from data.planner import Planner


def _rec(day, rows=300):
    return {"last_date": day, "rows": rows}


class TestPlanner(unittest.TestCase):
    def _plan(self, records, roster=None, snapshot=(), expected="2026-11-05",
              previous="2026-11-04"):
        return Planner().plan(expected, previous, roster=roster or [],
                              snapshot_symbols=snapshot, records=records)

    def test_all_ready(self):
        p = self._plan({"600000": _rec("2026-11-05")}, ["600000"])
        self.assertEqual(p.task_count(), 0)
        self.assertEqual(p.ready, ("600000",))

    def test_only_today_is_daily(self):
        p = self._plan({"600000": _rec("2026-11-04")}, ["600000"])
        daily = p.by_action("daily")
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0].symbols, ("600000",))

    def test_larger_gap_is_repair(self):
        p = self._plan({"600000": _rec("2026-11-03")}, ["600000"])
        self.assertEqual(p.by_action("repair")[0].symbols, ("600000",))

    def test_no_record_is_bootstrap(self):
        p = self._plan({}, ["600000"])
        self.assertEqual(p.by_action("bootstrap")[0].symbols, ("600000",))

    def test_new_snapshot_symbol_is_bootstrap(self):
        p = self._plan({"688999": _rec("2026-11-04")}, [],
                       snapshot=["688999"])
        self.assertEqual(p.by_action("bootstrap")[0].symbols, ("688999",))
        self.assertEqual(p.by_action("daily"), [])

    def test_one_row_new_stock_is_bootstrap_even_if_today(self):
        p = self._plan({"688999": _rec("2026-11-05", rows=1)}, [],
                       snapshot=["688999"])
        self.assertEqual(p.by_action("bootstrap")[0].symbols, ("688999",))

    def test_minute_is_separate(self):
        p = Planner().plan("2026-11-05", "2026-11-04",
                           records={}, minute_symbols=["600000"])
        minute = p.by_action("minute")
        self.assertEqual(len(minute), 1)
        self.assertEqual(minute[0].dataset, "bar_minute")

    def test_summary(self):
        p = self._plan({"600000": _rec("2026-11-04"),
                        "000001": _rec("2026-11-03")}, ["600000", "000001"])
        self.assertIn("daily 1", p.summary_line())
        self.assertIn("repair 1", p.summary_line())


if __name__ == "__main__":
    unittest.main()
