"""Synthetic checks for consecutive trigger failure spacing."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trigger_failure_spacing as spacing


def event(status, created):
    return {'status': status, 'created': created}


class Spacing(unittest.TestCase):
    def test_first_two_failures_keep_the_normal_schedule(self):
        events = [event('failed', 30), event('failed', 20), event('dispatched', 10)]
        self.assertEqual(spacing.consecutive_failures(events), 2)
        self.assertEqual(spacing.delay_seconds(2), 0)
        self.assertIsNone(spacing.next_allowed_at(events))
        self.assertFalse(spacing.decision(events, 40)['delayed'])

    def test_three_failures_delay_one_hour_and_four_delay_four_hours(self):
        three = [event('failed', 30 + i) for i in range(3)]
        self.assertEqual(spacing.delay_seconds(3), 3600)
        self.assertEqual(spacing.delay_seconds(4), 14400)
        self.assertEqual(spacing.delay_seconds(9), 14400)
        three.sort(key=lambda e: -e['created'])
        allowed = spacing.next_allowed_at(three)
        self.assertEqual(allowed, 32 + 3600)
        early = spacing.decision(three, 32 + 60)
        self.assertEqual((early['delayed'], early['error'], early['failures']), (True, 'team_trigger_failure_spacing', 3))
        self.assertFalse(spacing.decision(three, 32 + 3600)['delayed'])

    def test_success_resets_and_skips_do_not_count(self):
        self.assertEqual(spacing.consecutive_failures([event('failed', 5), event('dispatched', 4), event('completed', 3)]), 1)
        self.assertEqual(spacing.consecutive_failures([event('failed', 5), event('dispatched', 4)]), 1)
        mixed = [event('skipped', 40), event('failed', 30), event('failed', 20), event('failed', 10)]
        self.assertEqual(spacing.consecutive_failures(mixed), 3, 'skipped slots keep the failure run intact')
        self.assertEqual(spacing.consecutive_failures([event('skipped', 9), event('failed', 8), event('failed', 7), event('failed', 6)]), 3)

    def test_unknown_and_blocked_never_count_as_failures(self):
        for status in ('unknown', 'blocked', 'claiming', 'cancelled', 'interrupted'):
            with self.subTest(status=status):
                self.assertEqual(spacing.consecutive_failures([event(status, 9), event('failed', 8), event('failed', 7), event('failed', 6)]), 0)
        self.assertFalse(spacing.decision([event('unknown', 9)] * 3, 10)['delayed'])

    def test_events_before_activation_are_ignored_and_the_run_is_bounded(self):
        events = [event('failed', 90), event('failed', 80), event('failed', 70), event('failed', 10)]
        self.assertEqual(spacing.consecutive_failures(events, activated_at=50), 3)
        self.assertEqual(spacing.consecutive_failures(events, activated_at=95), 0)
        many = [event('failed', 1000 - i) for i in range(50)]
        self.assertEqual(spacing.consecutive_failures(many), spacing.MAX_FAILURES)

    def test_invalid_inputs_are_rejected(self):
        for value in ('text', 5, {'a': 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                spacing.consecutive_failures(value)
        with self.assertRaises(ValueError):
            spacing.consecutive_failures([{'status': 'failed'}, 'not a dict'])
        for value in (-1, 1.5, '3', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                spacing.delay_seconds(value)
        with self.assertRaises(ValueError):
            spacing.decision([], 'now')


if __name__ == '__main__':
    unittest.main()
