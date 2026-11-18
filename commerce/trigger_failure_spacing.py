"""Spacing after consecutive trigger failures, without disabling the trigger.

Studied from the routine failure spacing in a related local agent project: a
routine that keeps failing should back off instead of retrying on every slot,
and it must stay enabled so a human can fix the cause and see the schedule.

Independent implementation. Two choices differ from that reference:

* Only real failures count. "Skipped" slots (channel busy, missed grace) and
  "unknown" outcomes never count, because an unknown outcome must be reviewed
  by a person rather than treated as a failure or retried.
* Spacing never edits the trigger: it only delays the next dispatched slot and
  records why, so history and the stored schedule keep their meaning.
"""

# Consecutive failures before the first delay, then the delay in seconds.
THRESHOLD = 3
DELAYS = (3600, 14400)  # 1 hour, then 4 hours
MAX_FAILURES = 20
COUNTED = ('failed',)


def _status(event):
    return event.get('status') if isinstance(event, dict) else None


def consecutive_failures(events, activated_at=None):
    """Count the most recent run of failures, newest first, for one trigger."""
    if events is None:
        return 0
    if not isinstance(events, (list, tuple)):
        raise ValueError('spacing_invalid_events')
    count = 0
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('spacing_invalid_events')
        if activated_at is not None and (event.get('created') or 0) < activated_at:
            break
        status = _status(event)
        if status == 'skipped':
            # A slot we chose not to run says nothing about the work itself.
            continue
        if status in COUNTED:
            count += 1
            if count >= MAX_FAILURES:
                break
            continue
        break
    return count


def delay_seconds(failures):
    """Zero until the threshold is reached, then a bounded increasing delay."""
    if type(failures) is not int or failures < 0:
        raise ValueError('spacing_invalid_failures')
    if failures < THRESHOLD:
        return 0
    return DELAYS[min(failures - THRESHOLD, len(DELAYS) - 1)]


def next_allowed_at(events, activated_at=None):
    """Earliest time the next slot may run, or None when no delay applies."""
    failures = consecutive_failures(events, activated_at)
    delay = delay_seconds(failures)
    if not delay:
        return None
    last_failure = None
    for event in events:
        if activated_at is not None and (event.get('created') or 0) < activated_at:
            break
        if _status(event) == 'skipped':
            continue
        if _status(event) in COUNTED:
            last_failure = event.get('created')
            break
        break
    if last_failure is None:
        return None
    return last_failure + delay


def decision(events, at, activated_at=None):
    """{'delayed', 'failures', 'next_allowed_at', 'error'} for one due slot."""
    if type(at) not in (int, float):
        raise ValueError('spacing_invalid_at')
    failures = consecutive_failures(events, activated_at)
    allowed = next_allowed_at(events, activated_at)
    if allowed is None or at >= allowed:
        return {'delayed': False, 'failures': failures, 'next_allowed_at': allowed, 'error': None}
    return {'delayed': True, 'failures': failures, 'next_allowed_at': allowed,
            'error': 'team_trigger_failure_spacing'}
