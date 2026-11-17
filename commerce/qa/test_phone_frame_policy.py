"""Deterministic capture limits; no devices, accounts, timers or screenshots."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_frame_policy import FrameCapturePolicy


class FramePolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.policy = FrameCapturePolicy(clock=lambda: self.now)

    def test_global_concurrency_and_one_capture_per_device(self):
        tickets = [self.policy.begin(str(i)) for i in range(3)]
        self.assertTrue(all(tickets))
        self.assertIsNone(self.policy.begin('0'))
        self.assertIsNone(self.policy.begin('fourth'))
        self.assertTrue(self.policy.finish(tickets[0], success=True))
        self.assertIsNotNone(self.policy.begin('fourth'))

    def test_rate_budget_refills_without_accumulating_an_unbounded_burst(self):
        for i in range(4):
            ticket = self.policy.begin(str(i))
            self.assertIsNotNone(ticket)
            self.policy.finish(ticket, success=True)
        self.assertIsNone(self.policy.begin('next'))
        self.now += .25
        ticket = self.policy.begin('next')
        self.assertIsNotNone(ticket)
        self.policy.finish(ticket, success=True)
        self.assertIsNone(self.policy.begin('another'))
        self.now += 1000
        tickets = [self.policy.begin(str(i)) for i in range(12)]
        self.assertEqual(sum(t is not None for t in tickets), 3)

    def test_failure_backoff_caps_at_two_minutes_and_success_resets_it(self):
        for delay in (5, 10, 20, 40, 80, 120, 120):
            ticket = self.policy.begin('bad')
            self.assertIsNotNone(ticket)
            self.policy.finish(ticket, success=False)
            self.now += delay - .01
            self.assertIsNone(self.policy.begin('bad'))
            self.now += .01
        ticket = self.policy.begin('bad')
        self.policy.finish(ticket, success=True)
        ticket = self.policy.begin('bad')
        self.assertIsNotNone(ticket)
        self.policy.finish(ticket, success=False)
        self.now += 5
        self.assertIsNotNone(self.policy.begin('bad'))

    def test_failure_on_one_device_does_not_block_others(self):
        self.policy.finish(self.policy.begin('bad'), success=False)
        self.assertIsNotNone(self.policy.begin('healthy'))

    def test_forget_fences_old_result_but_holds_its_slot_until_it_finishes(self):
        old = self.policy.begin('reconnected')
        others = [self.policy.begin(str(i)) for i in range(2)]
        self.policy.forget('reconnected')
        self.assertIsNone(self.policy.begin('new'))
        self.assertIsNone(self.policy.begin('reconnected'))
        self.assertFalse(self.policy.finish(old, success=False))
        self.policy.forget('new')
        self.assertIsNotNone(self.policy.begin('reconnected'))
        self.assertFalse(self.policy.finish(old, success=True))
        self.assertTrue(all(others))

    def test_close_refuses_new_work_and_late_results(self):
        ticket = self.policy.begin('one')
        self.policy.close()
        self.assertIsNone(self.policy.begin('two'))
        self.assertFalse(self.policy.finish(ticket, success=True))

    def test_simultaneous_requests_share_the_same_global_budget(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            tickets = list(pool.map(self.policy.begin, map(str, range(24))))
        self.assertEqual(sum(t is not None for t in tickets), 3)

    def test_waiting_phones_get_a_turn_before_fast_pollers_can_retake_slots(self):
        active = [self.policy.begin(str(i)) for i in range(3)]
        for i in range(3, 12):
            self.assertIsNone(self.policy.begin(str(i)))
        for ticket in active:
            self.policy.finish(ticket, success=True)
        self.now += 2
        self.assertIsNone(self.policy.begin('0'))
        next_ticket = self.policy.begin('3')
        self.assertIsNotNone(next_ticket)

    def test_a_phone_no_longer_being_viewed_cannot_block_new_viewers_forever(self):
        active = [self.policy.begin(str(i)) for i in range(3)]
        self.assertIsNone(self.policy.begin('old-viewer'))
        for ticket in active:
            self.policy.finish(ticket, success=True)
        self.now += 7
        self.assertIsNotNone(self.policy.begin('new-viewer'))


if __name__ == '__main__':
    unittest.main()
