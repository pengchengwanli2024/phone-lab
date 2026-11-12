"""Offline transport boundary; no platform or notification calls."""
from datetime import datetime

STATES = ('pending', 'sending', 'unknown', 'sent', 'failed')
OUTCOMES = ('confirmed', 'rejected', 'uncertain', 'none')


def assess_batch(pages, baseline_complete, max_age_seconds, now):
    if type(baseline_complete) is not bool or type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 86400:
        raise ValueError('invalid_controls')
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('timezone_required')
    def reject(reason):
        return dict(accepted=False, reason=reason, record_count=0, notify_new_orders=False)
    if not isinstance(pages, list) or not pages:
        return reject('no_pages')
    seen = set(); total = 0
    for i, page in enumerate(pages):
        if not isinstance(page, dict) or set(page) != {'ok', 'records', 'has_next', 'cursor', 'asof'}:
            return reject('page_shape')
        if type(page['ok']) is not bool or not page['ok'] or type(page['has_next']) is not bool:
            return reject('failed_or_invalid_page')
        if not isinstance(page['records'], list) or any(not isinstance(row, dict) for row in page['records']):
            return reject('invalid_records')
        if page['cursor'] is not None and not isinstance(page['cursor'], str):
            return reject('invalid_cursor')
        if page['has_next'] != (i < len(pages)-1):
            return reject('incomplete_or_early_end')
        if page['has_next']:
            cursor = page['cursor']
            if not cursor or not cursor.strip() or cursor in seen:
                return reject('cursor_not_progressing')
            seen.add(cursor)
        try:
            if not isinstance(page['asof'], str): return reject('invalid_time')
            stamp = datetime.fromisoformat(page['asof'].replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None: return reject('timezone_required')
            age = (now - stamp).total_seconds()
            if age < 0 or age > max_age_seconds: return reject('outside_freshness')
        except (ValueError, TypeError):
            return reject('invalid_time')
        total += len(page['records'])
    return dict(accepted=True, reason='complete_fresh_batch', record_count=total,
                notify_new_orders=baseline_complete)


def delivery_state(current, outcome):
    if not isinstance(current, str) or current not in STATES or not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise ValueError('invalid_delivery_state')
    if current == 'sent': return 'sent'
    if current == 'unknown' and outcome != 'confirmed': return 'unknown'
    if outcome == 'confirmed': return 'sent'
    if outcome == 'rejected': return 'failed'
    if outcome == 'uncertain' or current == 'sending': return 'unknown'
    return current


def can_send(status):
    if not isinstance(status, str) or status not in STATES: raise ValueError('invalid_status')
    return status == 'pending'
