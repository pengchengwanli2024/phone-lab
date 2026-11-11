"""Exercise real subprocesses against deterministic failures and conflicting data."""
from datetime import datetime, timezone
import json
import threading
import uuid

from collect import collect, safe_summary
from fixture import PRODUCTS, server
from setup import ROOT, STATE


def main():
    fixture = server()
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{fixture.server_port}'
    batch = STATE / 'results' / 'resilience' / uuid.uuid4().hex

    def route(label, engine, path='/static', **extra):
        return dict(id=label, engine=engine, url=origin + path,
                    publisher='Synthetic fixture', source_id='synthetic-fixture', **extra)

    static = route('static-http', 'scrapling-http')
    api = route('json-api', 'json-http', '/api/products')
    cases = [
        ('dynamic-failover', 3, 6, 'verified', [
            route('empty-http', 'scrapy', '/dynamic'),
            route('browser', 'crawl4ai', '/dynamic'), api]),
        ('http-error-failover', 1, 3, 'verified', [route('failed-http', 'scrapy', '/broken'), static, api]),
        ('partial-fields-failover', 1, 3, 'verified', [route('partial', 'scrapy', '/partial'), static, api]),
        ('truncated-records-failover', 1, 3, 'verified', [route('truncated', 'scrapy', '/truncated'), static, api]),
        ('backend-unavailable-failover', 1, 3, 'verified', [
            route('service-down', 'firecrawl', env={'FIRECRAWL_API_URL': 'http://127.0.0.1:1'}), static, api]),
        ('timeout-failover', 1, 3, 'verified', [route('slow', 'scrapy', '/slow', timeout=1), static, api]),
        ('conflict-even-with-majority', 1, 3, 'conflict', [
            route('baseline', 'scrapy'), api, route('changed-price', 'scrapling-http', '/conflict')]),
        ('single-path-not-verified', 1, 3, 'unverified', [static, route('failed-api', 'json-http', '/broken')]),
        ('same-tool-not-independent', 1, 3, 'unverified', [
            route('http', 'crawlee-http'), route('browser', 'crawlee-browser')]),
        ('all-paths-failed', 1, 3, 'failed', [route('http', 'scrapy', '/broken'), route('api', 'json-http', '/broken')]),
    ]
    results = []
    try:
        for name, pages, count, expected_status, routes in cases:
            config = dict(kind='products', max_pages=pages, min_records=count, min_agreeing=2,
                          route_timeout=20, total_timeout=80, routes=routes)
            result = collect(config, batch / name)
            errors = []
            if result['status'] != expected_status:
                errors.append('unexpected_status')
            if expected_status == 'verified':
                expected = PRODUCTS if count == 6 else PRODUCTS[:3]
                if {r['sku']: r for r in result['rows']} != {r['sku']: r for r in expected}:
                    errors.append('ground_truth_mismatch')
                for record in result['records']:
                    sources = record['sources']
                    if len({source['route'] for source in sources}) < 2:
                        errors.append('missing_record_provenance')
                    if any(not source.get(key) for source in sources for key in
                           ('source_url', 'publisher', 'captured_at', 'locator', 'payload_sha256', 'record_sha256')):
                        errors.append('incomplete_provenance')
                if name == 'dynamic-failover':
                    evidence = {r['data']['sku']: r['sources'] for r in result['records']}
                    if len(evidence['SYN-C']) != 4 or len(evidence['SYN-A']) != 2:
                        errors.append('incorrect_per_page_provenance')
            elif result['rows'] or result['records']:
                errors.append('unverified_data_released')
            if name == 'timeout-failover' and 'worker_timeout' not in result['attempts'][0]['errors']:
                errors.append('timeout_not_exercised')
            if name == 'partial-fields-failover' and 'incomplete_fields' not in result['attempts'][0]['errors']:
                errors.append('partial_fields_not_rejected')
            if name == 'truncated-records-failover' and 'insufficient_records' not in result['attempts'][0]['errors']:
                errors.append('truncation_not_rejected')
            output = batch / (name + '.json')
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            output.chmod(0o600)
            entry = dict(case=name, passed=not errors, checks=errors, result=safe_summary(result))
            results.append(entry)
            print(json.dumps(entry), flush=True)
        normalized = collect(dict(kind='quotes', max_pages=1, min_records=1, routes=[
            route('html', 'scrapy', '/quote-static'), route('json', 'json-http', '/api/quotes')]), batch / 'normalized-source-join')
        passed = (normalized['status'] == 'verified' and len(normalized['records']) == 1
                  and len(normalized['records'][0]['sources']) == 2)
        results.append(dict(case='normalized-source-join', passed=passed, checks=[], result=safe_summary(normalized)))
        print(json.dumps(results[-1]), flush=True)
        exhausted = collect(dict(kind='products', max_pages=1, min_records=3, total_timeout=1, route_timeout=10,
                                 routes=[route('slow', 'scrapy', '/slow'), static, api]), batch / 'total-budget-exhaustion')
        passed = (exhausted['status'] == 'failed' and not exhausted['rows']
                  and all(a['status'] == 'not_attempted' for a in exhausted['attempts'][1:]))
        results.append(dict(case='total-budget-exhaustion', passed=passed, checks=[], result=safe_summary(exhausted)))
        print(json.dumps(results[-1]), flush=True)
    finally:
        fixture.shutdown()
        fixture.server_close()
    document = {'checked_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'synthetic integration faults with actual installed crawler subprocesses',
                'checks': len(results), 'passed': sum(r['passed'] for r in results), 'results': results,
                'evidence_directory': str(batch.relative_to(ROOT))}
    output = STATE / 'results' / 'resilience-validation.json'
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
    output.chmod(0o600)
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
