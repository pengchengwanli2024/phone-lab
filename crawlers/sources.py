"""Collect registered public feeds through two separately executed HTTP clients."""
import argparse
import json
from pathlib import Path
import sys
import uuid

from collect import collect, safe_summary
from setup import ROOT, STATE
sys.path.insert(0, str(ROOT / 'commerce'))
from crawler_feed_bridge import persist_collection, snapshot_status, atomic


def main():
    registry = json.loads((ROOT / 'crawlers/sources.json').read_text())['sources']
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['all', *[s['id'] for s in registry]], default='all')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--status', action='store_true', help='Read per-source cache status without fetching')
    args = parser.parse_args()
    if args.list:
        print(json.dumps(registry, ensure_ascii=False, indent=2))
        return 0
    if args.status:
        print(json.dumps(snapshot_status(), ensure_ascii=False, indent=2))
        return 0
    outcomes = []
    batch = STATE / 'results' / 'sources' / uuid.uuid4().hex
    batch.mkdir(parents=True, mode=0o700)
    for source in registry:
        if args.source not in ('all', source['id']):
            continue
        config = {'kind': source['kind'], 'max_pages': 1, 'min_records': 1,
                  'min_agreeing': 2, 'route_timeout': 35, 'total_timeout': 80,
                  'routes': [{'id': label, 'engine': engine, 'url': source['url'],
                              'source_id': source['id'], 'publisher': source['publisher']}
                             for label, engine in [('http-standard', 'feed-http'), ('http-scrapling', 'feed-scrapling'),
                                                   ('http-native', 'feed-native')]]}
        result = collect(config, batch / source['id'])
        result.update(source_id=source['id'], publisher=source['publisher'],
                      category=source['category'], coverage=source['scope'], reference=source['reference'])
        output = batch / (source['id'] + '.json')
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        output.chmod(0o600)
        persist_collection(source, result)
        summary = dict(safe_summary(result), source_id=source['id'], publisher=source['publisher'])
        outcomes.append(summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    report = {'schema': 'information-source-check-v1', 'sources': outcomes,
              'evidence_directory': str(batch.relative_to(ROOT))}
    atomic(batch / 'batch.json', report)
    latest = STATE / 'results' / 'source-validation.json'
    atomic(latest, {'schema': 'information-source-cache-index-v2', 'sources': snapshot_status(),
                    'last_batch': str((batch / 'batch.json').relative_to(ROOT))})
    return 0 if all(result['status'] == 'verified' for result in outcomes) else 1


if __name__ == '__main__':
    sys.exit(main())
