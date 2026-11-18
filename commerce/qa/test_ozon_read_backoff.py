"""Backoff policy alone: no database, network or connector."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ozon_read_backoff import wait_seconds, RATE_LIMITED

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def rows(*items):
    return [(error, (NOW - timedelta(seconds=age)).isoformat()) for error, age in items]


class BackoffTests(unittest.TestCase):
    def test_no_history_or_a_latest_success_means_no_wait(self):
        self.assertEqual(wait_seconds([], NOW), 0)
        self.assertEqual(wait_seconds(rows((None, 5), (RATE_LIMITED, 60)), NOW), 0)
        self.assertEqual(wait_seconds(rows(('ozon_network_error', 5), (RATE_LIMITED, 60)), NOW), 0)

    def test_wait_doubles_with_the_streak_and_is_capped_at_one_hour(self):
        self.assertEqual(wait_seconds(rows((RATE_LIMITED, 0)), NOW), 600)
        self.assertEqual(wait_seconds(rows((RATE_LIMITED, 0), (RATE_LIMITED, 120)), NOW), 1200)
        self.assertEqual(wait_seconds(rows((RATE_LIMITED, 0), (RATE_LIMITED, 1), (RATE_LIMITED, 2)), NOW), 2400)
        self.assertEqual(wait_seconds(rows(*[(RATE_LIMITED, i) for i in range(8)]), NOW), 3600)

    def test_elapsed_time_is_subtracted_and_never_goes_negative(self):
        self.assertEqual(wait_seconds(rows((RATE_LIMITED, 200)), NOW), 400)
        self.assertEqual(wait_seconds(rows((RATE_LIMITED, 601)), NOW), 0)

    def test_a_success_between_rate_limits_resets_the_streak(self):
        self.assertEqual(wait_seconds(rows((RATE_LIMITED, 0), (None, 10), (RATE_LIMITED, 20), (RATE_LIMITED, 30)), NOW), 600)


if __name__ == '__main__':
    unittest.main()
