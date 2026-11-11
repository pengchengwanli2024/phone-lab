"""Compare actual tool runs; score against synthetic ground truth, not exit codes."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from fixture import PRODUCTS, server
from setup import ROOT, STATE, environment
from worker import ENGINES, FIELDS


def score(result, expected):
    actual = {row.get('sku'): row for row in result.get('rows', [])}
    correct = sum(actual.get(row['sku'], {}).get(key) == row[key]
                  for row in expected for key in FIELDS)
    complete = (result.get('status') == 'ok' and len(actual) == len(expected)
                and correct == len(expected) * len(FIELDS)
                and len(result.get('pages', [])) == 3
                and result.get('duplicates_removed') == 2)
    return {'passed': complete, 'correct_fields': correct,
            'expected_fields': len(expected) * len(FIELDS),
            'field_accuracy': round(correct / (len(expected) * len(FIELDS)), 4)}


def run(engine, case, url, kind, pages, env):
    key = engine.replace('+', '-') + '-' + case
    run_directory = Path(env.get('CRAWLER_RUN_DIRECTORY', STATE / 'results'))
    output = run_directory / (key + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / 'crawlers/worker.py'), '--engine', engine,
               '--url', url, '--kind', kind, '--max-pages', str(pages), '--output', str(output)]
    timed_out = False
    with (run_directory / (key + '.log')).open('w') as log:
        try:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                                       start_new_session=True)
            try:
                process.wait(timeout=150)
            except subprocess.TimeoutExpired:
                import signal
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=10)
                timed_out = True
        except OSError:
            return {'engine': engine, 'case': case, 'status': 'failed', 'errors': ['worker_start_failed']}
    if timed_out:
        return {'engine': engine, 'case': case, 'status': 'failed', 'errors': ['worker_timeout']}
    if not output.exists():
        return {'engine': engine, 'case': case, 'status': 'failed', 'errors': ['worker_no_result']}
    result = json.loads(output.read_text())
    result['case'] = case
    return result


def summary(result):
    # Never publish extracted text, machine paths, tokens, or local fixture addresses.
    keys = ('engine', 'case', 'status', 'errors', 'elapsed_seconds', 'unique_records',
            'raw_records', 'duplicates_removed', 'rendered_pages', 'markdown_chars', 'quality')
    return {key: result[key] for key in keys if key in result}


def main():
    parser = argparse.ArgumentParser()
    # Firecrawl's Docker fixture/proxy modes are validated in separate explicit runs.
    parser.add_argument('--engines', nargs='+', choices=ENGINES,
                        default=[engine for engine in ENGINES if engine not in
                                 ('firecrawl', 'json-http', 'feed-http', 'feed-scrapling', 'feed-native')])
    parser.add_argument('--public', action='store_true', help='Also fetch the public Quotes to Scrape sandbox')
    parser.add_argument('--cases', nargs='+', choices=('static', 'dynamic', 'http-error', 'public-static', 'public-dynamic'))
    parser.add_argument('--report', type=Path, default=STATE / 'results' / 'validation.json')
    args = parser.parse_args()
    (STATE / 'logs').mkdir(parents=True, exist_ok=True)
    env = environment()
    env['CRAWLER_RUN_DIRECTORY'] = str(STATE / 'results' / 'runs' /
                                      datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    fixture = server()
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{fixture.server_port}'
    results = []
    try:
        for engine in args.engines:
            for case in ('static', 'dynamic'):
                if args.cases and case not in args.cases:
                    continue
                result = run(engine, case, origin + '/' + case, 'products', 3, env)
                result['quality'] = score(result, PRODUCTS)
                results.append(summary(result))
                print(json.dumps(summary(result), ensure_ascii=False), flush=True)
            # HTTP failures must never be reported as successful empty collections.
            if not args.cases or 'http-error' in args.cases:
                result = run(engine, 'http-error', origin + '/broken', 'products', 1, env)
                result['quality'] = {'passed': result.get('status') == 'failed'
                                     and not result.get('rows') and 'http_503' in result.get('errors', [])}
                results.append(summary(result))
                print(json.dumps(summary(result)), flush=True)
            if args.public:
                for case, path in [('public-static', '/'), ('public-dynamic', '/js/')]:
                    if args.cases and case not in args.cases:
                        continue
                    result = run(engine, case, 'https://quotes.toscrape.com' + path, 'quotes', 1, env)
                    rows = result.get('rows', [])
                    result['quality'] = {'passed': result.get('status') == 'ok' and len(rows) == 10
                                         and all(row.get('text') and row.get('author') for row in rows)}
                    results.append(summary(result))
                    print(json.dumps(summary(result)), flush=True)
    finally:
        fixture.shutdown()
        fixture.server_close()
    packages = ('scrapy', 'crawl4ai', 'crawlee', 'scrapling', 'firecrawl-py', 'playwright')
    versions = {name: importlib.metadata.version(name) for name in packages}
    document = {'schema': 'desktop-crawler-validation-v1', 'checked_at': datetime.now(timezone.utc).isoformat(),
                'versions': versions, 'scope': 'synthetic fixture and optional public scraping sandbox',
                'timing': 'single cold-process observation; includes engine/browser startup; not a throughput ranking',
                'synthetic_records': len(PRODUCTS), 'fields_per_record': len(FIELDS), 'results': results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'report_written': True, 'checks': len(results),
                      'passed': sum(r['quality']['passed'] for r in results)}))


if __name__ == '__main__':
    main()
