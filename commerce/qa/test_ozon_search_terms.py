"""Current-connection Ozon query snapshots; synthetic transport, no account calls."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from research import canonical, digest
import ozon_reader

BASE = 1794916800.0


class FakeLive:
    def __init__(self):
        self.config_lock = threading.RLock()
        self.value = {'connection_id': 'synthetic-connection', 'ozon_client_id': 'synthetic-id', 'ozon_api_key': 'synthetic-not-real'}
        self.data = {'kind': 'stock', 'complete': True, 'records': [
            {'product_id': '10', 'offer_id': 'SYNTHETIC-A', 'stocks': [{'type': 'fbs', 'sku': '101', 'present': 2, 'reserved': 0}]}]}
        self.available = True;self.fresh = True
    def config(self):return dict(self.value)
    def snapshot(self, connection, kind):
        if not self.available or connection != self.value['connection_id'] or kind != 'stock':return None
        return {'id': 'synthetic-stock', 'sha256': digest(canonical(self.data)), 'data': copy.deepcopy(self.data), 'observed_at': '2026-11-17T12:00:00+00:00'}
    def _fresh(self, snapshot, config):return self.fresh


class OzonSearchTermsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('ozon_search_terms'), 'current-store Ozon search terms are not implemented')
        from ozon_search_terms import OzonSearchTerms
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.core = Core(Path(self.tmp.name) / 'db.sqlite');self.live = FakeLive();self.calls = []
        self.clock = patch('ozon_search_terms.time.time', return_value=BASE);self.mock_clock = self.clock.start();self.addCleanup(self.clock.stop)
        self.app = OzonSearchTerms(SimpleNamespace(core=self.core, live=self.live), reader=self.reader)
        self.addCleanup(self.app.close)

    def reader(self, path, body, client, key):
        self.calls.append((path, copy.deepcopy(body)))
        period = {k: body[k].replace('T', ' ').replace('Z', ' +0000 UTC') for k in ('date_from', 'date_to')}
        product = {'sku': 101, 'name': '合成收纳 Synthetic', 'offer_id': 'SYNTHETIC-A', 'category': 'Synthetic',
                   'unique_search_users': 7, 'position': None, 'unique_view_users': None, 'view_conversion': None, 'gmv': 9.5, 'currency': '5'}
        query = {'sku': 101, 'currency': '5', 'gmv': 9, 'order_count': 0, 'position': None, 'query': 'кухонный органайзер 合成词',
                 'view_conversion': None, 'query_index': 1, 'unique_search_users': 7, 'unique_view_users': None}
        value = {'analytics_period': period, 'total': 1, 'page_count': 1,
                 'queries' if path.endswith('/details') else 'items': [query] if path.endswith('/details') else [product]}
        return value, digest(canonical(value))

    def settle(self):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            value = self.app.status()['refresh']
            if value and value['status'] not in ('queued', 'running'):return value
            time.sleep(.01)
        self.fail('bounded refresh did not settle')

    def test_complete_daily_snapshot_preserves_original_null_currency_and_order_count(self):
        first = self.app.refresh();result = self.settle()
        self.assertEqual(result['status'], 'succeeded');self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][1]['page'], 0)
        self.assertEqual(self.calls[0][1]['date_from'], '2026-11-07T00:00:00Z')
        self.assertEqual(self.calls[0][1]['date_to'], '2026-11-14T00:00:00Z')
        self.assertEqual(self.calls[1][1]['limit_by_sku'], 15)
        found = self.app.search('合成词', 20)
        self.assertEqual(found['items'][0]['currency'], '5');self.assertIsNone(found['items'][0]['position'])
        self.assertEqual(found['items'][0]['order_count'], 0);self.assertEqual(found['items'][0]['gmv'], 9)
        self.assertEqual(found['source'], 'own_store_product_queries_not_global_hotterms')
        self.assertEqual(self.app.search('ОРГАНАЙЗЕР', 20)['total'], 1)
        self.assertEqual(self.app.refresh()['id'], first['id']);self.assertEqual(len(self.calls), 2)
        self.assertFalse(found['external_execution_allowed'])

    def test_missing_or_stale_inventory_is_pending_not_empty_success(self):
        self.live.available = False
        self.assertEqual(self.app.status()['scope_status'], 'stock_pending')
        with self.assertRaises(ValueError):self.app.refresh()
        self.assertEqual(self.app.search('', 20)['availability'], 'not_collected')
        self.assertIsNone(self.app.search('', 20)['total']);self.assertEqual(self.calls, [])

    def test_empty_and_populated_read_receipts_bind_to_the_same_current_connection(self):
        status = self.app.status();empty = self.app.search('', 20)
        self.assertEqual(empty['connection_sha256'], status['connection_sha256'])
        self.assertEqual(empty['store_identity'], status['store_identity'])
        self.assertTrue(empty['not_global_hot_terms'])
        queued = self.app.refresh();self.assertEqual(queued['connection_sha256'], status['connection_sha256']);self.settle()
        found = self.app.search('', 20)
        self.assertEqual(found['connection_sha256'], status['connection_sha256'])
        self.assertEqual(found['scope_sha256'], self.app.status()['scope_sha256'])

    def test_multiple_platform_skus_for_one_product_do_not_inflate_product_count(self):
        self.live.data['records'][0]['stocks'].append({'type': 'fbo', 'sku': '102', 'present': 1, 'reserved': 0})
        status = self.app.status()
        self.assertEqual(status['product_count'], 1)
        self.assertEqual(status['sku_count'], 2)

    def test_complete_multiple_pages_preserve_each_query_without_unique_user_aggregation(self):
        self.live.data['records'] = [dict(product_id=str(i), offer_id='SYNTHETIC-' + str(i),
            stocks=[dict(type='fbs', sku=str(100 + i), present=1, reserved=0)]) for i in range(1, 9)]
        def multiple(path, body, *auth):
            raw, sha = self.reader(path, body, *auth)
            if path.endswith('/details'):
                template = raw['queries'][0]
                rows = [{**template, 'sku': 100 + i, 'query_index': index, 'query': '合成查询 ' + str(index)} for i in range(1, 9) for index in range(1, 16)]
                raw.update(queries=rows[body['page'] * 100:(body['page'] + 1) * 100], total=120, page_count=2)
            else:
                template = raw['items'][0];raw.update(items=[{**template, 'sku': 100 + i} for i in range(1, 9)], total=8, page_count=1)
            return raw, digest(canonical(raw))
        self.app.reader = multiple;self.app.refresh();self.assertEqual(self.settle()['status'], 'succeeded')
        found = self.app.search('', 100)
        self.assertEqual(found['total'], 120);self.assertEqual(found['returned'], 100);self.assertEqual(len(self.calls), 3)
        self.assertEqual(found['items'][0]['unique_search_users'], 7)
        self.assertTrue(found['unique_users_not_summed'])
        self.assertIn(' UTC', found['analytics_period']['details']['date_from'])

    def test_read_holds_connection_lock_until_current_snapshot_receipt_is_built(self):
        self.app.refresh();self.settle();original = self.app._snapshot
        entered = threading.Event();release = threading.Event();switched = threading.Event()
        def slow(connection):entered.set();release.wait(2);return original(connection)
        def switch():
            with self.live.config_lock:self.live.value['connection_id'] = 'synthetic-next';switched.set()
        output = []
        with patch.object(self.app, '_snapshot', side_effect=slow):
            reader = threading.Thread(target=lambda: output.append(self.app.search('', 20)));reader.start();self.assertTrue(entered.wait(2))
            changer = threading.Thread(target=switch);changer.start()
            try:self.assertFalse(switched.wait(.05))
            finally:release.set();reader.join(2);changer.join(2)
        self.assertTrue(switched.is_set());self.assertEqual(output[0]['availability'], 'snapshot')
        self.assertEqual(self.app.search('', 20)['availability'], 'not_collected')

    def test_permission_failure_does_not_retry_same_day_or_destroy_prior_snapshot(self):
        self.app.refresh();self.settle();before = self.app.search('', 20)['snapshot_sha256']
        self.mock_clock.return_value = BASE + 86400
        def forbidden(*args):
            self.calls.append(('forbidden', {}));raise ozon_reader.ConnectionIssue('ozon_auth_or_permission', 403)
        self.app.reader = forbidden;first = self.app.refresh();self.assertEqual(self.settle()['status'], 'failed')
        self.assertEqual(self.app.refresh()['id'], first['id']);self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.app.search('', 20)['snapshot_sha256'], before)

    def test_connection_switch_rejects_commit_and_hides_other_store_results(self):
        ready = threading.Event();release = threading.Event();original = self.app.reader
        def slow(*args):ready.set();release.wait(2);return original(*args)
        self.app.reader = slow;self.app.refresh();self.assertTrue(ready.wait(2))
        with self.live.config_lock:self.live.value['connection_id'] = 'synthetic-other'
        release.set();time.sleep(.05)
        self.assertIsNone(self.app.status()['refresh']);self.assertEqual(self.app.search('', 20)['availability'], 'not_collected')
        with self.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM ozon_query_snapshots').fetchone()[0], 0)

    def test_incomplete_pagination_never_publishes_partial_snapshot(self):
        def incomplete(path, body, *auth):
            raw, sha = self.reader(path, body, *auth);raw['total'] = 101;raw['page_count'] = 2
            return raw, digest(canonical(raw))
        self.app.reader = incomplete;self.app.refresh();self.assertEqual(self.settle()['status'], 'failed')
        self.assertEqual(self.app.search('', 20)['availability'], 'not_collected')

    def test_scope_mismatch_and_duplicate_query_rows_are_rejected(self):
        def outside(path, body, *auth):
            raw, sha = self.reader(path, body, *auth);key = 'queries' if path.endswith('/details') else 'items';raw[key][0]['sku'] = 999
            return raw, digest(canonical(raw))
        self.app.reader = outside;self.app.refresh();self.assertEqual(self.settle()['status'], 'failed')
        self.assertEqual(self.app.search('', 20)['availability'], 'not_collected')

    def test_duplicate_rows_changed_period_and_changed_sku_mapping_cannot_publish(self):
        original = self.app.reader
        def duplicate(path, body, *auth):
            raw, sha = original(path, body, *auth)
            if path.endswith('/details'):raw['queries'] *= 2;raw['total'] = 2
            return raw, digest(canonical(raw))
        self.app.reader = duplicate;self.app.refresh();self.assertEqual(self.settle()['status'], 'failed')
        self.mock_clock.return_value = BASE + 86400
        def wrong_period(path, body, *auth):
            raw, sha = original(path, body, *auth);raw['analytics_period']['date_to'] = '2020-01-01T00:00:00Z'
            return raw, digest(canonical(raw))
        self.app.reader = wrong_period;self.app.refresh();self.assertEqual(self.settle()['status'], 'failed')
        self.mock_clock.return_value = BASE + 172800
        def switch_scope(*args):
            result = original(*args);self.live.data['records'][0]['stocks'][0]['sku'] = '102';return result
        self.app.reader = switch_scope;self.app.refresh();self.assertEqual(self.settle()['status'], 'failed')
        self.assertEqual(self.app.search('', 20)['availability'], 'not_collected')

    def test_raw_payload_hashes_are_private_and_credentials_are_never_persisted(self):
        self.live.value['store_label'] = 'Synthetic Store'
        self.app.refresh();self.assertEqual(self.settle()['status'], 'succeeded')
        self.assertEqual(self.app.status()['store_identity']['label'], 'Synthetic Store')
        with self.core.db() as db:
            job = db.execute('SELECT document FROM ozon_query_jobs').fetchone()[0]
            snapshot = db.execute('SELECT document,sha256 FROM ozon_query_snapshots').fetchone()
        self.assertNotIn('synthetic-not-real', job + snapshot[0])
        self.assertNotIn('synthetic-id', job + snapshot[0])
        doc = json.loads(snapshot[0]);self.assertEqual(digest(snapshot[0]), snapshot[1])
        self.assertEqual(len(doc['responses']), 2)
        self.assertTrue(all(digest(canonical(r['payload'])) == r['payload_sha256'] for r in doc['responses']))

    def test_concurrent_refresh_claims_one_original_daily_job(self):
        entered = threading.Event();release = threading.Event();original = self.app.reader
        def slow(*args):entered.set();release.wait(2);return original(*args)
        self.app.reader = slow;first = self.app.refresh();self.assertTrue(entered.wait(2))
        second = self.app.refresh();self.assertEqual(first['id'], second['id']);release.set()
        self.assertEqual(self.settle()['status'], 'succeeded');self.assertEqual(len(self.calls), 2)

    def test_transport_unknown_and_recovery_never_reissue_original_request(self):
        def unknown(*args):self.calls.append(('unknown', {}));raise TimeoutError()
        self.app.reader = unknown;first = self.app.refresh();self.assertEqual(self.settle()['status'], 'unknown')
        self.app.close()
        from ozon_search_terms import OzonSearchTerms
        self.app = OzonSearchTerms(SimpleNamespace(core=self.core, live=self.live), reader=self.reader);self.addCleanup(self.app.close)
        self.assertEqual(self.app.refresh()['id'], first['id']);self.assertEqual(len(self.calls), 1)

    def test_real_service_validator_and_expected_connection_guard_precede_daily_replay(self):
        from service import Commerce
        from mcp_server import CONTROL_READ_ONLY
        from extension_runtime.contracts import SAFE_BUILTINS
        service = Commerce(Path(self.tmp.name) / 'service-fixture')
        service.live = self.live;service.ozon_search_terms.live = self.live
        service.ozon_search_terms.reader = self.reader;self.addCleanup(service.ozon_search_terms.close)
        call = lambda op, args=None: service.invoke('commerce_ozon_search_terms_' + op, args or {}, 'test')
        before = call('status')['connection_sha256']
        self.assertEqual(call('search')['connection_sha256'], before)
        for args in ({'expected_connection_sha256': '0' * 64}, {'expected_connection_sha256': True}, {'skus': ['999']}):
            with self.subTest(args=args), self.assertRaises(ValueError):call('refresh', args)
        self.assertEqual(self.calls, [])
        with service.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM ozon_query_jobs').fetchone()[0], 0)
        with self.live.config_lock:self.live.value['connection_id'] = 'synthetic-service-other'
        with self.assertRaisesRegex(ValueError, 'ozon_query_connection_changed'):call('refresh', {'expected_connection_sha256': before})
        after = call('status')['connection_sha256'];self.assertNotEqual(after, before)
        saved = call('refresh', {'expected_connection_sha256': after})
        end = time.monotonic() + 3
        while time.monotonic() < end:
            status = call('status')['refresh']
            if status['status'] not in ('queued', 'running'):break
            time.sleep(.01)
        self.assertEqual(status['status'], 'succeeded');self.assertEqual(status['connection_sha256'], after)
        self.assertEqual(call('refresh', {'expected_connection_sha256': after})['id'], saved['id'])
        with self.assertRaisesRegex(ValueError, 'ozon_query_connection_changed'):call('refresh', {'expected_connection_sha256': before})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(call('search')['snapshot_sha256'], status['snapshot_sha256'])
        for name in ('commerce_ozon_search_terms_status', 'commerce_ozon_search_terms_search'):
            self.assertIn(name, CONTROL_READ_ONLY);self.assertIn(name, SAFE_BUILTINS)
        self.assertNotIn('commerce_ozon_search_terms_refresh', CONTROL_READ_ONLY)
        self.assertIn('commerce_ozon_search_terms_refresh', SAFE_BUILTINS)


if __name__ == '__main__':unittest.main()
