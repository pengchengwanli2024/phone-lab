"""Atomic local feed snapshots shared by crawler CLI and commerce readers.

Integrity checks detect damaged local artifacts; they do not authenticate a
publisher or independently establish the truth of its statements.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.local/crawlers/published'
REGISTRY = {s['id']: s for s in json.loads((ROOT / 'crawlers/sources.json').read_text())['sources']}
MAPPING = {'fed': ('federal-reserve-press', 'macro', '美联储 · 政策发布'),
           'ecb': ('ecb-press', 'macro', 'ECB · 政策发布'),
           'eia': ('eia-energy', 'energy', 'EIA · 能源资讯'),
           'hmrc': ('hmrc-news', 'trade', 'HMRC · 税务与海关'),
           'transport': ('uk-transport-news', 'logistics', 'DfT · 交通物流')}
SNAPSHOT_MAPPING = {**MAPPING, 'wto': ('wto-trade', 'trade', 'WTO news')}
SOURCES = {key: {'name': name, 'url': REGISTRY[ident]['url'], 'category': category,
                 'coverage': REGISTRY[ident]['scope'] + '；此处更新仅导入本机最近快照，不会重新抓取。',
                 'provider': 'local_verified_snapshot', 'crawler_source_id': ident}
           for key, (ident, category, name) in MAPPING.items()}
MAX_BYTES = 4_000_000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        result = parsed.timestamp()
        if not 0 < result <= time.time() + 300:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError('crawler_snapshot_invalid') from None


def read(path, optional=False):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('crawler_snapshot_invalid')
        return json.loads(data)
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError('crawler_snapshot_missing') from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('crawler_snapshot_invalid') from None


def atomic(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(canonical(data) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def valid_url(value):
    try:
        p = urlsplit(value)
        return p.scheme in ('http', 'https') and bool(p.hostname) and not p.username and not p.password
    except (ValueError, TypeError):
        return False


def validate(payload, ident):
    if not isinstance(payload, dict) or payload.get('source_id') != ident or payload.get('status') != 'verified':
        raise ValueError('crawler_snapshot_invalid')
    stamp(payload.get('checked_at'))
    rows, records, attempts = payload.get('rows'), payload.get('records'), payload.get('attempts')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500 or not isinstance(records, list) or len(rows) != len(records) or not isinstance(attempts, list):
        raise ValueError('crawler_snapshot_invalid')
    families = {'feed-http': 'stdlib', 'feed-scrapling': 'scrapling', 'feed-native': 'native-curl'}
    routes = {a['id']: families[a['engine']] for a in attempts
              if isinstance(a, dict) and a.get('status') == 'complete' and a.get('engine') in families and isinstance(a.get('id'), str)}
    by_id = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('data'), dict):
            raise ValueError('crawler_snapshot_invalid')
        data, sources = record['data'], record.get('sources')
        if not isinstance(data.get('id'), str) or data['id'] in by_id or not isinstance(sources, list):
            raise ValueError('crawler_snapshot_invalid')
        seen = set()
        for source in sources:
            if not isinstance(source, dict) or source.get('route') not in routes or source.get('source_url') != REGISTRY[ident]['url']:
                raise ValueError('crawler_snapshot_invalid')
            if source.get('source_id') != ident or source.get('publisher') != REGISTRY[ident]['publisher'] or not source.get('locator'):
                raise ValueError('crawler_snapshot_invalid')
            for key in ('payload_sha256', 'record_sha256'):
                if not re.fullmatch('[a-f0-9]{64}', str(source.get(key, ''))):
                    raise ValueError('crawler_snapshot_invalid')
            stamp(source.get('captured_at'))
            seen.add(routes[source['route']])
        if len(seen) < 2:
            raise ValueError('crawler_snapshot_invalid')
        by_id[data['id']] = record
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ('id', 'title', 'url', 'published')):
            raise ValueError('crawler_snapshot_invalid')
        if not row['id'] or not row['title'].strip() or not valid_url(row['url']) or row != by_id.get(row['id'], {}).get('data'):
            raise ValueError('crawler_snapshot_invalid')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('crawler_snapshot_invalid')
    return payload


def persist_collection(source, result, cache=None):
    ident = source['id']
    if ident not in REGISTRY:
        raise ValueError('crawler_source_unknown')
    cache = Path(cache) if cache is not None else CACHE
    if cache.is_symlink():
        raise ValueError('crawler_snapshot_invalid')
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache.chmod(0o700)
    receipt = {'source_id': ident, 'status': result['status'], 'checked_at': result['checked_at'],
               'attempts': [{key: item[key] for key in ('id', 'engine', 'status', 'errors', 'records') if key in item}
                            for item in result.get('attempts', [])]}
    observed = stamp(receipt['checked_at'])
    payload = None
    if result['status'] == 'verified':
        payload = {key: result[key] for key in ('status', 'checked_at', 'rows', 'records', 'attempts')}
        payload['source_id'] = ident
        validate(payload, ident)
    fd = os.open(cache / (ident + '.lock'), os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read(cache / (ident + '.attempt.json'), optional=True)
        if previous and stamp(previous['checked_at']) > observed:
            return {'status': 'older_run_ignored'}
        good = read(cache / (ident + '.json'), optional=True)
        if good and good.get('schema') == 'verified-feed-snapshot-v1' and good.get('integrity_sha256') == digest(good.get('payload')):
            if stamp(good['payload']['checked_at']) > observed:
                return {'status': 'older_run_ignored'}
        if payload:
            atomic(cache / (ident + '.json'), {'schema': 'verified-feed-snapshot-v1',
                                             'integrity_sha256': digest(payload), 'payload': payload})
        atomic(cache / (ident + '.attempt.json'), receipt)
    return {'status': 'stored' if payload else 'previous_success_retained'}


def load_snapshot(key, cache=None):
    ident, category, _ = SNAPSHOT_MAPPING[key]
    cache = Path(cache) if cache is not None else CACHE
    if cache.is_symlink():
        raise ValueError('crawler_snapshot_invalid')
    envelope = read(cache / (ident + '.json'))
    if not isinstance(envelope, dict) or envelope.get('schema') != 'verified-feed-snapshot-v1' or envelope.get('integrity_sha256') != digest(envelope.get('payload')):
        raise ValueError('crawler_snapshot_invalid')
    payload = validate(envelope['payload'], ident)
    receipt = read(cache / (ident + '.attempt.json'), optional=True)
    if not receipt or stamp(receipt['checked_at']) < stamp(payload['checked_at']):
        receipt = {'source_id': ident, 'status': 'verified', 'checked_at': payload['checked_at'],
                   'recovered_from_snapshot': True}
    rows = []
    captured = []
    for record in payload['records']:
        row = record['data']
        for source in record['sources']:
            captured.append(stamp(source['captured_at']))
        rows.append({'source_key': row['id'], 'title': row['title'], 'url': row['url'],
                     'published_original': row['published'], 'category': category,
                     'country': None, 'country_code': None, 'location': None, 'publisher_alert': None,
                     'publisher': REGISTRY[ident]['publisher'], 'collection_provenance': record['sources']})
    collected = min(captured)
    warning = 'crawler_latest_attempt_failed_using_previous' if receipt and receipt.get('status') != 'verified' and stamp(receipt['checked_at']) >= stamp(payload['checked_at']) else None
    return canonical(envelope).encode(), rows, {'collected_at': collected,
             'snapshot_checked_at': payload['checked_at'], 'warning': warning,
             'last_collection_attempt': receipt, 'integrity_sha256': envelope['integrity_sha256']}


def snapshot_status(cache=None):
    cache = Path(cache) if cache is not None else CACHE
    if cache.is_symlink():
        raise ValueError('crawler_snapshot_invalid')
    result = []
    for ident, source in REGISTRY.items():
        row = {'source_id': ident, 'publisher': source['publisher'], 'status': 'never_collected',
               'cached_records': 0, 'last_success': None, 'last_attempt': None}
        try:
            receipt = read(cache / (ident + '.attempt.json'), optional=True)
            envelope = read(cache / (ident + '.json'), optional=True)
            if receipt:
                row.update(status=receipt['status'], last_attempt=receipt['checked_at'], attempts=receipt.get('attempts', []))
            if envelope:
                if envelope.get('integrity_sha256') != digest(envelope.get('payload')):
                    raise ValueError('crawler_snapshot_invalid')
                payload = validate(envelope['payload'], ident)
                if not receipt or stamp(receipt['checked_at']) < stamp(payload['checked_at']):
                    row.update(status='verified', last_attempt=payload['checked_at'])
                observed = min(stamp(s['captured_at']) for r in payload['records'] for s in r['sources'])
                row.update(cached_records=len(payload['rows']), last_success=datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                           freshness='stale' if time.time() - observed > 21600 else 'recently_collected')
        except (ValueError, KeyError, TypeError):
            row.update(status='invalid_snapshot', error='crawler_snapshot_invalid')
        result.append(row)
    return result
