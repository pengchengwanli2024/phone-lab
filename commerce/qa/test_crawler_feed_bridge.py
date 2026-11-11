"""Synthetic-only persistence, failure retention and shared intelligence checks."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crawler_feed_bridge import REGISTRY, persist_collection, load_snapshot, snapshot_status
from service import Commerce

SOURCE = REGISTRY['federal-reserve-press']


def capsule(at=None, title='Synthetic policy publication'):
    at = time.time() - 7 * 3600 if at is None else at
    iso = datetime.fromtimestamp(at, timezone.utc).isoformat()
    row = {'id': 'synthetic-policy', 'title': title, 'url': 'https://example.org/synthetic-policy', 'published': iso}
    refs = [{'route': ident, 'source_url': SOURCE['url'], 'publisher': SOURCE['publisher'],
             'source_id': SOURCE['id'], 'captured_at': iso, 'locator': 'rss:record[1]',
             'payload_sha256': 'a' * 64, 'record_sha256': 'b' * 64}
            for ident in ('standard', 'native')]
    return {'status': 'verified', 'checked_at': iso, 'rows': [row],
            'records': [{'data': deepcopy(row), 'sources': refs}],
            'attempts': [{'id': 'standard', 'engine': 'feed-http', 'status': 'complete'},
                         {'id': 'native', 'engine': 'feed-native', 'status': 'complete'}]}


class SnapshotIntegrity(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.cache = Path(self.folder.name) / 'cache'
        self.data = capsule()

    def tearDown(self):
        self.folder.cleanup()

    def save(self, data=None):
        return persist_collection(SOURCE, data or self.data, self.cache)

    def test_failure_and_single_source_update_keep_previous_good_snapshot(self):
        self.save()
        self.save({'status': 'failed', 'checked_at': datetime.now(timezone.utc).isoformat()})
        _, rows, metadata = load_snapshot('fed', self.cache)
        self.assertEqual(rows[0]['title'], self.data['rows'][0]['title'])
        self.assertEqual(metadata['warning'], 'crawler_latest_attempt_failed_using_previous')
        self.assertEqual(len(rows[0]['collection_provenance']), 2)
        self.assertEqual((self.cache / (SOURCE['id'] + '.json')).stat().st_mode & 0o777, 0o600)

    def test_out_of_order_and_crash_window_do_not_replace_newer_success(self):
        newer = capsule(time.time() - 10, 'Newer synthetic publication')
        self.save(newer)
        (self.cache / (SOURCE['id'] + '.attempt.json')).unlink()
        self.assertEqual(self.save()['status'], 'older_run_ignored')
        self.assertEqual(load_snapshot('fed', self.cache)[1][0]['title'], newer['rows'][0]['title'])
        state = next(s for s in snapshot_status(self.cache) if s['source_id'] == SOURCE['id'])
        self.assertEqual(state['status'], 'verified')
        self.assertEqual(state['last_attempt'], newer['checked_at'])

    def test_single_source_updates_preserve_other_source_status(self):
        self.save()
        ecb = REGISTRY['ecb-press']
        value = deepcopy(self.data)
        for evidence in value['records'][0]['sources']:
            evidence.update(source_id=ecb['id'], publisher=ecb['publisher'], source_url=ecb['url'])
        persist_collection(ecb, value, self.cache)
        self.save({'status': 'failed', 'checked_at': datetime.now(timezone.utc).isoformat()})
        status = {r['source_id']: r for r in snapshot_status(self.cache)}
        self.assertEqual(status[SOURCE['id']]['status'], 'failed')
        self.assertEqual(status[SOURCE['id']]['cached_records'], 1)
        self.assertEqual(status[ecb['id']]['status'], 'verified')
        self.assertEqual(status[ecb['id']]['cached_records'], 1)
        self.assertEqual(len(status), len(REGISTRY))

    def test_concurrent_writers_keep_latest_source_and_no_pending_files(self):
        start = time.time() - 100
        values = [capsule(start + n, 'Synthetic revision ' + str(n)) for n in range(10)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(self.save, reversed(values)))
        self.assertEqual(load_snapshot('fed', self.cache)[1][0]['title'], 'Synthetic revision 9')
        self.assertEqual(list(self.cache.glob('.pending-*')), [])

    def test_corruption_symlink_and_missing_artifacts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'crawler_snapshot_missing'):
            load_snapshot('fed', self.cache)
        self.save()
        path = self.cache / (SOURCE['id'] + '.json')
        value = json.loads(path.read_text()); value['payload']['rows'][0]['title'] = 'Altered synthetic data'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'crawler_snapshot_invalid'):
            load_snapshot('fed', self.cache)
        path.unlink(); path.symlink_to(self.cache / (SOURCE['id'] + '.attempt.json'))
        with self.assertRaisesRegex(ValueError, 'crawler_snapshot_invalid'):
            load_snapshot('fed', self.cache)

    def test_single_path_incomplete_or_wrong_source_evidence_cannot_publish(self):
        for change in ('single', 'incomplete', 'wrong_source'):
            value = deepcopy(self.data)
            if change == 'single':
                value['records'][0]['sources'] = value['records'][0]['sources'][:1]
            elif change == 'incomplete':
                value['rows'][0]['url'] = ''
            else:
                value['records'][0]['sources'][0]['source_url'] = 'https://example.org/other'
            with self.assertRaisesRegex(ValueError, 'crawler_snapshot_invalid'):
                self.save(value)
        self.assertFalse((self.cache / (SOURCE['id'] + '.json')).exists())

    def test_shared_service_preserves_age_provenance_history_and_failure(self):
        self.save()
        with patch('crawler_feed_bridge.CACHE', self.cache):
            app = Commerce(Path(self.folder.name) / 'service')
            with patch('intelligence.fetch') as network:
                result = app.invoke('commerce_intel_refresh', {'source': 'fed'}, 'test')
                network.assert_not_called()
            source = next(s for s in result['sources'] if s['id'] == 'fed')
            self.assertEqual(source['freshness'], 'stale', 'importing an old snapshot must not make it fresh')
            self.assertGreater(source['last_imported_at'], source['last_success'] + 6 * 3600)
            item = app.invoke('commerce_intel_search', {'source': 'fed', 'category': 'macro'})['items'][0]
            self.assertEqual(item['publisher'], SOURCE['publisher'])
            self.assertEqual(len(item['collection_provenance']), 2)
            self.assertEqual(item['collected_at'], self.data['checked_at'])
            for run in (self.data, {'status': 'failed', 'checked_at': datetime.now(timezone.utc).isoformat()}):
                self.save(run)
                with app.core.db() as db:
                    db.execute("DELETE FROM intel_sources WHERE id='fed'")
                app.invoke('commerce_intel_refresh', {'source': 'fed'})
            self.assertEqual(app.invoke('commerce_intel_search', {'source': 'fed'})['total'], 1)
            self.assertEqual(app.intelligence.store.stats()['archived'], 1)
            source = next(s for s in app.intelligence.sources()['sources'] if s['id'] == 'fed')
            self.assertEqual(source['error'], 'crawler_latest_attempt_failed_using_previous')
            (self.cache / (SOURCE['id'] + '.json')).write_text('invalid-json')
            with app.core.db() as db:db.execute("DELETE FROM intel_sources WHERE id='fed'")
            result = app.invoke('commerce_intel_refresh', {'source': 'fed'})
            self.assertEqual(next(s for s in result['sources'] if s['id'] == 'fed')['error'], 'crawler_snapshot_invalid')
            self.assertEqual(app.invoke('commerce_intel_search', {'source': 'fed'})['total'], 1)


if __name__ == '__main__':
    unittest.main()
