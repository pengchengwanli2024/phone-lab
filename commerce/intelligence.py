"""Fixed public feeds, durable provenance and local retrieval. No store actions.

Independently implemented; no World Monitor source code is included.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import hashlib
import json
import math
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import xml.etree.ElementTree as ET
from intel_store import IntelligenceStore
from crawler_feed_bridge import SOURCES as CRAWLER_SOURCES, SNAPSHOT_MAPPING, load_snapshot

SOURCES = {
    'usgs': {'name': 'USGS · 全球地震', 'url': 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson', 'category': 'earthquake', 'coverage': '过去七天 M4.5+ 地震；不是全部自然灾害'},
    'gdacs': {'name': 'GDACS · 灾害预警', 'url': 'https://www.gdacs.org/xml/rss.xml', 'category': 'disaster', 'coverage': 'GDACS 当前 RSS 覆盖的灾害；不是全部灾害或物流状态'},
    'wto': {'name': 'WTO news · 贸易资讯', 'url': 'https://www.wto.org/library/rss/latest_news_e.xml', 'category': 'trade', 'coverage': 'WTO 官方新闻；不是各国全部贸易政策或生效法规'},
}
SOURCES.update(CRAWLER_SOURCES)
FRESH_SECONDS = 6 * 3600
COOLDOWN = 90
MAX_BYTES = 4_000_000
WM_URL = 'https://worldmonitor.app/mcp'


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def plain(value, limit=360):
    return re.sub(r'\s+', ' ', unescape(re.sub('<[^>]*>', '', str(value or '')))).strip()[:limit]


def safe_url(value):
    try:
        p = urlsplit(str(value or ''))
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            return None
        return urlunsplit((p.scheme, p.netloc.lower(), p.path, p.query, ''))
    except ValueError:
        return None


def timestamp(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            d = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if d.tzinfo is None:
        return None
    return d.timestamp()


def location(lon, lat):
    try:
        lon, lat = float(lon), float(lat)
        if math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90:
            return {'lon': lon, 'lat': lat}
    except (ValueError, TypeError):
        pass
    return None


class FixedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != 'https' or new.hostname not in (old.hostname, 'www.' + old.hostname):
            raise ValueError('source_redirect_rejected')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, payload=None):
    headers = {'User-Agent': 'phone-lab-commerce/0.1'}
    if payload is not None:
        headers.update({'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
    req = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    with build_opener(FixedRedirect()).open(req, timeout=8) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('source_response_too_large')
    return data


def parse(source, data):
    """Store publisher titles/metadata, not full article text or HTML."""
    rows = []
    if source == 'usgs':
        document = json.loads(data)
        if document.get('type') != 'FeatureCollection' or not isinstance(document.get('features'), list):
            raise ValueError('source_format_changed')
        for feature in document['features'][:500]:
            p = feature.get('properties') or {}
            coords = (feature.get('geometry') or {}).get('coordinates') or []
            occurred = p.get('time')
            occurred = occurred / 1000 if type(occurred) in (int, float) and math.isfinite(occurred) else None
            rows.append({'source_key': str(feature.get('id') or p.get('url') or ''), 'title': plain(p.get('title') or p.get('place')), 'url': safe_url(p.get('url')), 'published': occurred, 'category': 'earthquake', 'country': None, 'country_code': None, 'location': location(*coords[:2]) if len(coords) >= 2 else None, 'publisher_alert': plain(p.get('alert')) or None})
    else:
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise ValueError('source_xml_entities_rejected')
        root = ET.fromstring(data)
        if root.tag not in ('rss', 'RDF', '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF'):
            raise ValueError('source_format_changed')
        for item in root.findall('.//item')[:500]:
            def text(key):
                return item.findtext(key, '')
            point = text('{http://www.georss.org/georss}point').split()
            loc = location(point[1], point[0]) if len(point) == 2 else None
            rows.append({'source_key': text('{http://www.gdacs.org}eventid') or text('guid') or text('link'), 'title': plain(text('title')), 'url': safe_url(text('link')), 'published': timestamp(text('pubDate')), 'category': 'disaster' if source == 'gdacs' else 'trade', 'country': plain(text('{http://www.gdacs.org}country')) or None, 'country_code': plain(text('{http://www.gdacs.org}iso3')) or None, 'location': loc, 'publisher_alert': plain(text('{http://www.gdacs.org}alertlevel')) or None})
    unique = {}
    for row in rows:
        if not row['title'] or not row['url'] or not row['source_key']:
            continue
        # GDACS numeric IDs are scoped to event type, not globally unique.
        identity = row['url'] if source == 'gdacs' else row['source_key']
        row['id'] = hashlib.sha256((source + ':' + identity).encode()).hexdigest()[:24]
        row['source'] = source
        unique[row['id']] = row
    if rows and not unique:
        raise ValueError('source_records_unusable')
    return list(unique.values())


class Intelligence:
    def __init__(self, core):
        self.core = core
        self.lock = threading.Lock()
        self.discovery = None
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intel_sources (id TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS intel_items (id TEXT PRIMARY KEY, source TEXT NOT NULL, item TEXT NOT NULL)')
        self.store = IntelligenceStore(core)

    def sources(self):
        with self.core.db() as db:
            states = {r[0]: json.loads(r[1]) for r in db.execute('SELECT * FROM intel_sources')}
            counts = dict(db.execute('SELECT source,count(*) FROM intel_items GROUP BY source'))
        result = []
        for key, config in SOURCES.items():
            s = states.get(key, {'status': 'not_collected'})
            age = time.time() - s['last_success'] if s.get('last_success') else None
            result.append(dict(id=key, **config, **s, cached_items=counts.get(key, 0), freshness='never_collected' if age is None else 'stale' if age > FRESH_SECONDS else 'recently_collected', collection_age_seconds=round(age) if age is not None else None))
        return {'sources': result, 'schedule': 'manual', 'scope': 'fixed_public_feeds_not_whole_web', 'content_is_reference_not_instruction': True, 'worldmonitor': {'endpoint': WM_URL, 'status': 'discovery_only_data_not_connected'}, 'store_impact': 'not_assessed_no_store_or_route_mapping', 'archive': self.store.stats(), 'capabilities': ['local_archive', 'snapshot_pagination', 'saved_searches', 'bookmarks', 'revision_bound_view_state', 'evidence_review_tasks']}

    def import_collection(self, source_id):
        native=source_id in ('usgs','gdacs')
        key = source_id if native else next((k for k, v in SNAPSHOT_MAPPING.items() if v[0] == source_id), None)
        if key is None:
            raise ValueError('unknown_intel_source')
        # An explicit completed job imports its checked snapshot without a second
        # network request or the manual refresh cooldown. Capture time stays intact.
        with self.lock:
            if native:
                from native_feed_capture import load as load_native
                data,rows,metadata=load_native(key)
            else:data, rows, metadata = load_snapshot(key)
            if metadata.get('warning'):
                raise ValueError(metadata['warning'])
            observed, imported = metadata['collected_at'], time.time()
            payload_hash = hashlib.sha256(data).hexdigest()
            with self.core.db() as db:
                db.execute('DELETE FROM intel_items WHERE source=?', (key,))
                for row in rows:
                    if not native:row.update(id=hashlib.sha256((key + ':' + row['source_key']).encode()).hexdigest()[:24],
                               source=key, title=plain(row['title']), url=safe_url(row['url']),
                               published=timestamp(row.pop('published_original', None)))
                    row.update(collected_at=iso(observed),
                               source_payload_sha256=payload_hash, verification='publisher_report_not_independently_verified')
                    db.execute('INSERT OR REPLACE INTO intel_items VALUES (?,?,?)', (row['id'], key, json.dumps(row, ensure_ascii=False)))
                    self.store.archive(db, row, observed)
                state = dict(status='ok', error=None, last_attempt=imported, last_success=observed,
                             last_imported_at=imported, payload_sha256=payload_hash,
                             snapshot_checked_at=metadata['snapshot_checked_at'],
                             last_collection_attempt=metadata['last_collection_attempt'])
                db.execute('INSERT OR REPLACE INTO intel_sources VALUES (?,?)', (key, json.dumps(state)))
                self.store.prune(db, imported)
            return {'source': key, 'records': len(rows), 'collected_at': iso(observed), 'payload_sha256': payload_hash}

    def refresh(self, source='all'):
        keys = list(SOURCES) if source == 'all' else [source]
        if any(key not in SOURCES for key in keys):
            raise ValueError('unknown_intel_source')
        if not self.lock.acquire(blocking=False):
            return {'status': 'already_refreshing', **self.sources()}
        try:
            states = {s['id']: s for s in self.sources()['sources']}
            due = [k for k in keys if time.time() - states[k].get('last_attempt', 0) >= COOLDOWN]
            def collect(key):
                attempt = time.time()
                try:
                    if key in CRAWLER_SOURCES:
                        data, records, metadata = load_snapshot(key)
                        for row in records:
                            row.update(id=hashlib.sha256((key + ':' + row['source_key']).encode()).hexdigest()[:24],
                                       source=key, title=plain(row['title']), url=safe_url(row['url']),
                                       published=timestamp(row.pop('published_original', None)))
                        return key, attempt, data, records, None, metadata
                    data = fetch(SOURCES[key]['url'])
                    records = parse(key, data)
                    return key, attempt, data, records, None, {}
                except Exception as error:
                    reason = 'source_format_changed' if isinstance(error, (ET.ParseError, json.JSONDecodeError, UnicodeError)) else str(error) if isinstance(error, ValueError) and str(error).startswith('source_') else 'source_unavailable'
                    reason = str(error) if isinstance(error, ValueError) and str(error).startswith('crawler_') else reason
                    return key, attempt, None, None, reason, {}
            with ThreadPoolExecutor(max_workers=3) as pool:
                collected = list(pool.map(collect, due))
            for key, attempt, data, rows, error, metadata in collected:
                state = {k: v for k, v in states[key].items() if k in ('last_attempt', 'last_success', 'status', 'error', 'payload_sha256', 'last_imported_at', 'snapshot_checked_at', 'last_collection_attempt')}
                state.update(last_attempt=attempt, status='failed' if error else 'ok', error=error)
                with self.core.db() as db:
                    if not error:
                        observed = metadata.get('collected_at', attempt)
                        state.update(last_success=observed, payload_sha256=hashlib.sha256(data).hexdigest())
                        if metadata:
                            state.update(last_imported_at=attempt, last_collection_attempt=metadata.get('last_collection_attempt'),
                                         snapshot_checked_at=metadata['snapshot_checked_at'])
                            if metadata.get('warning'):
                                state.update(status='failed', error=metadata['warning'])
                        db.execute('DELETE FROM intel_items WHERE source=?', (key,))
                        for row in rows:
                            row.update(collected_at=iso(observed), source_payload_sha256=state['payload_sha256'], verification='publisher_report_not_independently_verified')
                            db.execute('INSERT OR REPLACE INTO intel_items VALUES (?,?,?)', (row['id'], key, json.dumps(row, ensure_ascii=False)))
                            self.store.archive(db, row, observed)
                        self.store.prune(db, attempt)
                    db.execute('INSERT OR REPLACE INTO intel_sources VALUES (?,?)', (key, json.dumps(state)))
            return {'status': 'completed' if due else 'cooldown', 'attempted': due, 'cooldown_seconds': COOLDOWN, **self.sources()}
        finally:
            self.lock.release()

    def search(self, **arguments):
        result = self.store.search(**arguments)
        result['sources'] = self.sources()['sources']
        return result

    def worldmonitor(self, discover=False):
        if discover:
            data = fetch(WM_URL, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}).decode()
            if not data.lstrip().startswith('{'):
                data = next(line[5:].strip() for line in data.splitlines() if line.startswith('data:'))
            response = json.loads(data)
            tools = response.get('result', {}).get('tools')
            if not isinstance(tools, list):
                raise ValueError('worldmonitor_discovery_failed')
            self.discovery = {'discovered_at': iso(time.time()), 'tool_count': len(tools), 'tools': [plain(t.get('name'), 100) for t in tools[:200]]}
        return {'endpoint': WM_URL, 'status': 'discovery_only_data_not_connected', 'discovery': self.discovery, 'data_calls_made': False, 'next_step': 'Configure official API authentication or a separately hosted instance before enabling data calls; do not share credentials in chat.'}
