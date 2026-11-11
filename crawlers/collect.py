"""Bounded multi-route collection with failover and explicit content agreement."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import unicodedata
from urllib.parse import urlsplit
import uuid

from setup import ROOT, STATE, environment
from worker import ENGINES, KIND_FIELDS, identity

KINDS = KIND_FIELDS
ALLOWED_ENV = {'FIRECRAWL_API_URL', 'FIRECRAWL_FIXTURE_ORIGIN', 'CRAWLER_BROWSER_EXECUTABLE'}


def validate(config):
    if not isinstance(config, dict) or config.get('kind') not in KINDS:
        raise ValueError('invalid_collection_kind')
    for key, default, low, high in [('max_pages', 1, 1, 10), ('min_records', 1, 1, 10000),
                                   ('min_agreeing', 2, 2, 8), ('route_timeout', 50, 1, 120),
                                   ('total_timeout', 180, 1, 600)]:
        value = config.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError('invalid_' + key)
        config[key] = value
    routes = config.get('routes', [])
    if not isinstance(routes, list) or not 2 <= len(routes) <= 8:
        raise ValueError('invalid_route_count')
    seen = set()
    for route in routes:
        if not isinstance(route, dict) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', route.get('id', '')):
            raise ValueError('invalid_route_id')
        if route['id'] in seen or route.get('engine') not in ENGINES:
            raise ValueError('invalid_or_duplicate_route')
        seen.add(route['id'])
        parsed = urlsplit(route.get('url', ''))
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('invalid_route_url')
        extra = route.get('env', {})
        if 'timeout' in route and (type(route['timeout']) is not int or not 1 <= route['timeout'] <= 120):
            raise ValueError('invalid_route_timeout')
        if not isinstance(extra, dict) or set(extra) - ALLOWED_ENV or any(not isinstance(v, str) for v in extra.values()):
            raise ValueError('invalid_route_environment')
    return config


def normalized(value):
    return ' '.join(unicodedata.normalize('NFC', value).split())


def fingerprint(result, kind, min_records):
    """Reject partial/error results before comparing all required fields, not counts."""
    if result.get('status') != 'ok' or result.get('errors'):
        return None, 'route_failed'
    rows = result.get('rows')
    if not isinstance(rows, list) or len(rows) < min_records:
        return None, 'insufficient_records'
    canonical, seen = [], {}
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or
                (not row[k].strip() and not (kind == 'news' and k == 'published')) for k in KINDS[kind]):
            return None, 'incomplete_fields'
        data = {key: normalized(row[key]) for key in KINDS[kind]}
        key = identity(data)
        if key in seen:
            return None, 'duplicate_record_identity'
        seen[key] = data
        evidence = result.get('record_evidence', {}).get(identity(row), [])
        if not evidence or any(not e.get('source_url') or not e.get('captured_at') or
                               not e.get('payload_sha256') or not e.get('locator') for e in evidence):
            return None, 'missing_provenance'
        canonical.append(data)
    canonical.sort(key=identity)
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest(), None


def execute(route, config, directory, timeout, cancelled=None):
    from rate_limit import wait_for, outcome
    from resource_limits import group_rss_kib
    deadline=time.monotonic()+timeout
    try:wait_for(route['url'],deadline,cancelled)
    except ValueError as error:return {'status':'failed','errors':[str(error)],'rows':[]}
    output = directory / (route['id'] + '.json')
    command = [sys.executable, str(ROOT / 'crawlers/route_worker.py'), '--engine', route['engine'],
               '--url', route['url'], '--kind', config['kind'],
               '--max-pages', str(config['max_pages']), '--output', str(output)]
    env = environment()
    env.update(route.get('env', {}))
    started = time.monotonic()
    with (directory / (route['id'] + '.log')).open('w') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True)
        reason = None; sampled=0; peak=0
        while process.poll() is None:
            if cancelled and cancelled():
                reason = 'collection_cancelled';break
            if time.monotonic() >= deadline:
                reason = 'worker_timeout';break
            if time.monotonic()-sampled>=1:
                try:peak=max(peak,group_rss_kib(process.pid))
                except Exception:reason='resource_observation_unavailable';break
                sampled=time.monotonic()
                if peak>1024*1024:reason='worker_memory_limit';break
            time.sleep(.1)
        if reason:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            except ProcessLookupError:
                pass
            return {'status': 'failed', 'errors': [reason], 'rows': []}
    if not output.exists():
        return {'status': 'failed', 'errors': ['worker_no_result'], 'rows': []}
    try:
        result = json.loads(output.read_text())
    except (ValueError, OSError):
        return {'status': 'failed', 'errors': ['worker_invalid_result'], 'rows': []}
    if process.returncode and result.get('status') == 'ok':
        result.update(status='failed', errors=['worker_exit_failed'])
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    result['peak_group_rss_kib']=peak
    outcome(route['url'],any(code in ('http_429','http_503') for code in result.get('errors',[])))
    return result


def collect(config, directory, executor=execute, cancelled=None, progress=None):
    config = validate(config)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    attempts, candidates = [], []
    started = time.monotonic()
    for route in config['routes']:
        if cancelled and cancelled():
            attempts.append({'id': route['id'], 'engine': route['engine'], 'status': 'not_attempted',
                             'errors': ['collection_cancelled']})
            continue
        remaining = config['total_timeout'] - (time.monotonic() - started)
        if remaining <= 0:
            attempts.append({'id': route['id'], 'engine': route['engine'], 'status': 'not_attempted',
                             'errors': ['total_timeout']})
            continue
        try:
            arguments = (route, config, directory, min(route.get('timeout', config['route_timeout']), remaining))
            result = executor(*arguments, cancelled=cancelled) if executor is execute else executor(*arguments)
            digest, rejection = fingerprint(result, config['kind'], config['min_records'])
        except Exception as error:
            result = {'status': 'failed', 'errors': [type(error).__name__], 'rows': []}
            digest, rejection = None, 'route_failed'
        errors = [code for code in result.get('errors', [])
                  if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_]{1,80}', code)]
        attempt = {'id': route['id'], 'engine': route['engine'],
                   'family': {'json-http': 'stdlib', 'feed-http': 'stdlib',
                              'feed-scrapling': 'scrapling', 'feed-native': 'native-curl'}.get(route['engine'], route['engine'].split('+')[0].split('-')[0]),
                   'publisher': route.get('publisher') or urlsplit(route['url']).hostname,
                   'source_id': route.get('source_id') or urlsplit(route['url']).hostname,
                   'status': 'complete' if digest else 'rejected',
                   'errors': errors + ([rejection] if rejection and rejection not in errors else []),
                   'records': len(result.get('rows', [])), 'content_sha256': digest,
                   'captured_at': result.get('captured_at'), 'elapsed_seconds': result.get('elapsed_seconds'),
                   'peak_group_rss_kib': result.get('peak_group_rss_kib'),
                   'pages': result.get('pages', [])}
        attempts.append(attempt)
        if progress:
            progress(len(attempts), len(config['routes']))
        if digest:
            candidates.append((attempt, result))
    groups = {}
    for attempt, result in candidates:
        groups.setdefault(attempt['content_sha256'], []).append((attempt, result))
    status, selected, agreeing = 'failed', [], []
    if len(groups) > 1:
        status = 'conflict'
    elif groups:
        group = next(iter(groups.values()))
        agreeing = [attempt['id'] for attempt, _ in group]
        families = {attempt['family'] for attempt, _ in group}
        status = 'verified' if len(families) >= config['min_agreeing'] else 'unverified'
        if any(attempt['status'] == 'not_attempted' for attempt in attempts):
            status = 'unverified'
        if status == 'verified':
            selected = group[0][1]['rows']
    if cancelled and cancelled():
        status, selected, agreeing = 'cancelled', [], []
    records = []
    if selected:
        for row in selected:
            sources = []
            for attempt, candidate in candidates:
                matched = next((other for other in candidate.get('rows', [])
                                if normalized(identity(other)) == normalized(identity(row))), None)
                key = identity(matched) if matched else identity(row)
                for evidence in candidate.get('record_evidence', {}).get(key, []):
                    sources.append(dict(evidence, route=attempt['id'], engine=attempt['engine'],
                                        publisher=attempt['publisher'], source_id=attempt['source_id'],
                                        item_url=row.get('url'), published_at=row.get('published') or None))
            records.append({'data': row, 'sources': sources,
                            'source_claim_status': 'publisher_statement_not_independently_fact_checked'})
    return {'schema': 'multi-route-collection-v1', 'status': status,
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'kind': config['kind'], 'required_agreeing_families': config['min_agreeing'],
            'agreeing_routes': agreeing, 'candidate_groups': len(groups),
            'attempts': attempts, 'rows': selected, 'unique_records': len(selected),
            'records': records, 'evidence_directory': str(directory.relative_to(ROOT)) if directory.is_relative_to(ROOT) else 'private_external_directory',
            'scope': 'configured_routes_and_fields_only_not_independent_fact_verification',
            'elapsed_seconds': round(time.monotonic() - started, 3)}


def safe_summary(result):
    return {'status': result['status'], 'unique_records': result['unique_records'],
            'agreeing_routes': result['agreeing_routes'], 'candidate_groups': result['candidate_groups'],
            'attempts': [{key: a[key] for key in ('id', 'engine', 'status', 'errors', 'records') if key in a}
                         for a in result['attempts']]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        directory = STATE / 'results' / 'collections' / uuid.uuid4().hex
        result = collect(config, directory)
    except (ValueError, OSError):
        print('{"status":"failed","errors":["invalid_collection_configuration"]}')
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    args.output.chmod(0o600)
    print(json.dumps(safe_summary(result), ensure_ascii=False))
    return {'verified': 0, 'unverified': 2, 'conflict': 3, 'failed': 1}[result['status']]


if __name__ == '__main__':
    sys.exit(main())
