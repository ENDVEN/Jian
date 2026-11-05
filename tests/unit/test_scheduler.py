import unittest

from data.scheduler import PRIORITY, ChannelPolicy, Scheduler, Task


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.s = Scheduler(
            policies=[ChannelPolicy("em", max_concurrency=1, min_interval=0),
                      ChannelPolicy("sina", max_concurrency=2, min_interval=0)],
            clock=lambda: self.now)

    def test_priority_order(self):
        low = Task("low", "em", PRIORITY["backfill"])
        high = Task("high", "em", PRIORITY["user"])
        self.s.add(low); self.s.add(high)
        self.assertIs(self.s.next_ready(), high)

    def test_channel_cooldown_does_not_block_other_channel(self):
        a = Task("a", "em", PRIORITY["user"])
        b = Task("b", "sina", PRIORITY["backfill"])
        self.s.add(a); self.s.add(b)
        self.assertIs(self.s.next_ready(), a)
        self.assertTrue(self.s.acquire(a))
        self.s.finish(a, ok=False, error_class="limit")
        self.assertIs(self.s.next_ready(), b)
        self.assertEqual(self.s.wait_seconds(), 0.0)   # b 健康通道仍可跑

    def test_concurrency_limit(self):
        a = Task("a", "em", PRIORITY["user"])
        b = Task("b", "em", PRIORITY["backfill"])
        self.s.add(a); self.s.add(b)
        self.assertTrue(self.s.acquire(a))
        self.assertIsNone(self.s.next_ready())
        self.s.finish(a, ok=True, latency=0.5)
        self.assertIs(self.s.next_ready(), b)

    def test_proxy_fixed_cooldown_and_recovery(self):
        t = Task("t", "em", PRIORITY["user"])
        self.s.add(t); self.assertTrue(self.s.acquire(t))
        self.s.finish(t, ok=False, error_class="proxy")
        state = self.s.state("em")
        self.assertAlmostEqual(state.cooldown_until - self.now, 300.0)
        self.assertEqual(state.fail_class, "proxy")
        self.assertEqual(self.s.state("em").max_concurrency, 1)

    def test_success_adapts_concurrency(self):
        s = Scheduler(policies=[ChannelPolicy("em", max_concurrency=2)],
                      clock=lambda: self.now)
        s.state("em").max_concurrency = 1
        for _ in range(2):
            t = Task("x", "em", PRIORITY["user"])
            s.add(t); self.assertTrue(s.acquire(t))
            s.finish(t, ok=True, latency=0.5)
        self.assertEqual(s.state("em").max_concurrency, 2)

    def test_limited_failure_exponential(self):
        t = Task("t", "em", PRIORITY["user"])
        self.s.add(t); self.assertTrue(self.s.acquire(t))
        self.s.finish(t, ok=False, error_class="limit")
        first = self.s.state("em").cooldown_until - self.now
        t2 = Task("t2", "em", PRIORITY["user"])
        self.s.add(t2); self.assertTrue(self.s.acquire(t2, now=self.now + first + 1))
        self.s.finish(t2, ok=False, error_class="limit")
        second = self.s.state("em").cooldown_until - self.now
        self.assertGreater(second, first)


if __name__ == "__main__":
    unittest.main()
