"""Backoff policy for a rate-limited Ozon read endpoint. Pure: no I/O, no clock of its own.

Kept apart from the connector so the policy can be changed and tested on its
own, within the bounded snapshot the engineering executor accepts.
"""
from datetime import datetime

RATE_LIMITED = 'ozon_rate_limited'
BASE_SECONDS, MAX_SECONDS = 600, 3600


def wait_seconds(recent, now):
    """Seconds to wait before the next read.

    recent: (error, iso_timestamp) of the endpoint's latest requests, newest first;
    error is None for a success. now: timezone-aware datetime.
    Consecutive rate limits double the wait from 10 minutes up to one hour; any
    other outcome ends the streak.
    """
    streak = 0
    for error, _ in recent:
        if error != RATE_LIMITED:
            break
        streak += 1
    if not streak:
        return 0
    elapsed = (now - datetime.fromisoformat(recent[0][1])).total_seconds()
    return max(0, int(min(MAX_SECONDS, BASE_SECONDS * 2 ** (streak - 1)) - elapsed))
