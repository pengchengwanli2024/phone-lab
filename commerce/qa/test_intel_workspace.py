"""Stateful information workflows; all feeds and records are synthetic."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from intel_store import query_groups


def feed(count=1, start=0, title='Earthquake in Mexico'):
    return json.dumps({'type': 'FeatureCollection', 'features': [
        {'id': 'synthetic-' + str(i), 'properties': {'title': title + ' ' + str(i), 'url': 'https://example.org/' + str(i), 'time': (1700000000 + i) * 1000}, 'geometry': {'coordinates': [-99, 19]}}
        for i in range(start, start + count)
    ]}).encode()


class InformationWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, name, args=None, client='test'):
        return self.app.invoke('commerce_intel_' + name, args or {}, client)

    def collect(self, data, stamp=1700001000):
        with patch('intelligence.fetch', return_value=data), patch('intelligence.time.time', return_value=stamp):
            return self.call('refresh', {'source':'usgs'})

    def test_local_history_survives_latest_snapshot_replacement(self):
        self.collect(feed(2)); self.collect(feed(1, 8), 1700001200)
        self.assertEqual(self.call('search')['total'], 1)
        archive = self.call('search', {'scope':'archive'})
        self.assertEqual(archive['total'], 3)
        self.assertEqual(sum(not r['in_latest_snapshot'] for r in archive['items']), 2)
        self.assertEqual(Commerce(self.temp.name).intelligence.store.stats()['archived'], 3)

    def test_snapshot_bound_pagination_and_mark_changes(self):
        self.collect(feed(45))
        first = self.call('search', {'limit':'20','include_map':True})
        self.assertEqual(len(first['markers']), 45)
        self.assertEqual(first['returned'], 20)
        item = first['items'][0]
        self.call('item_update', {'item_id':item['id'],'action':'viewed','record_sha256':item['record_sha256']})
        second = self.call('search', {'limit':'20','cursor':first['next_cursor']})
        self.assertEqual(second['offset'], 20)
        self.assertFalse(set(r['id'] for r in first['items']) & set(r['id'] for r in second['items']))
        with self.assertRaisesRegex(ValueError, 'intel_cursor_expired'):
            self.call('search', {'query':'trade','limit':'20','cursor':first['next_cursor']})
        self.collect(feed(1, 50), 1700001200)
        with self.assertRaisesRegex(ValueError, 'intel_cursor_expired'):
            self.call('search', {'limit':'20','cursor':first['next_cursor']})
        with self.assertRaises(ValueError):
            self.call('search', {'cursor':'not-json-or-valid-base64!'})

    def test_chinese_compound_and_accented_queries(self):
        self.collect(feed(1, title='Flood near México'))
        for query in ['墨西哥洪水', '墨西哥 洪水', 'México flood', 'inundación Mexico']:
            self.assertEqual(self.call('search', {'query':query})['total'], 1, query)
        self.assertEqual(self.call('search', {'country':'MEX'})['total'], 0, 'do not infer country metadata from title')

    def test_view_state_is_bound_to_revision_not_just_id(self):
        self.collect(feed())
        old = self.call('search')['items'][0]
        self.call('item_update', {'item_id':old['id'],'action':'viewed','record_sha256':old['record_sha256']}, 'hermes')
        self.assertEqual(self.call('search', {'view':'unviewed'})['total'], 0)
        self.collect(feed(title='Updated earthquake in Mexico'), 1700001200)
        changed = self.call('item_get', {'item_id':old['id']}, 'codex')
        self.assertFalse(changed['is_viewed'])
        self.assertEqual(changed['revision_count'], 2)
        self.call('item_update', {'item_id':old['id'],'action':'viewed','record_sha256':old['record_sha256']})
        self.assertFalse(self.call('item_get', {'item_id':old['id']})['is_viewed'])
        with self.assertRaisesRegex(ValueError, 'intel_record_hash_required'):
            self.call('item_update', {'item_id':old['id'],'action':'viewed'})

    def test_bookmarks_protect_old_records_and_share_across_clients(self):
        self.collect(feed(2))
        old = self.call('search')['items'][0]
        self.call('item_update', {'item_id':old['id'],'action':'bookmark'}, 'hermes')
        self.collect(feed(0), 1700001000 + 100 * 86400)
        self.assertEqual(self.call('search')['total'], 0)
        saved = self.call('search', {'scope':'archive','view':'bookmarked'}, 'codex')
        self.assertEqual(saved['total'], 1)
        self.assertEqual(saved['items'][0]['id'], old['id'])
        self.assertEqual(saved['archive']['archived'], 1)

    def test_saved_searches_are_idempotent_and_do_not_enable_push(self):
        self.collect(feed(3))
        first = self.call('watch_save', {'name':'Synthetic Mexico','query':'墨西哥地震'})
        second = self.call('watch_save', {'name':'Renamed synthetic topic','query':'墨西哥地震'})
        self.assertEqual(first['id'], second['id'])
        listing = self.call('watch_list')
        self.assertEqual(len(listing['watches']), 1)
        self.assertEqual(listing['watches'][0]['matches'], 3)
        self.assertFalse(listing['notification_enabled'])
        self.call('watch_remove', {'watch_id':first['id']})
        self.assertEqual(self.call('watch_list')['watches'], [])
        self.assertEqual(self.call('search')['total'], 3)

    def test_review_tasks_are_idempotent_and_frozen_to_displayed_revision(self):
        self.collect(feed())
        item = self.call('search')['items'][0]
        args = {'item_id':item['id'],'record_sha256':item['record_sha256']}
        first = self.call('review_create', args, 'hermes')
        second = self.call('review_create', args, 'codex')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['status'], 'queued')
        self.assertEqual(first['input']['evidence']['record_sha256'], item['record_sha256'])
        self.assertEqual(first['input']['store_impact'], 'unknown')
        self.assertEqual(self.call('item_get', {'item_id':item['id']})['review_task']['id'], first['id'])
        self.collect(feed(title='Changed earthquake'), 1700001200)
        with self.assertRaisesRegex(ValueError, 'intel_record_changed'):
            self.call('review_create', args)
        self.assertEqual(len(self.app.invoke('commerce_task_list', {})['tasks']), 1)

    def test_legacy_snapshot_migration_is_nondestructive(self):
        self.collect(feed())
        with self.app.core.db() as db:
            db.execute('DELETE FROM intel_archive'); db.execute('DELETE FROM intel_revisions')
        restored = Commerce(self.temp.name)
        result = restored.intelligence.search(scope='archive')
        self.assertEqual(result['total'], 1)
        self.assertEqual(len(result['items'][0]['source_payload_sha256']), 64)
        self.assertEqual(result['items'][0]['first_seen'], result['items'][0]['collected_at'])

    def test_iso3_filter_does_not_match_substring_of_another_country(self):
        from intel_store import IntelligenceStore
        row={'id':'a'*24,'record_sha256':'b'*64,'source':'gdacs','title':'Synthetic flood','url':'https://example.org/a','published':1700000000,'country':'Belarus','country_code':'BLR','category':'disaster','is_viewed':False,'is_bookmarked':False}
        self.assertEqual(IntelligenceStore.matches([row],IntelligenceStore.filters(country='RUS')),[])
        self.assertEqual(len(IntelligenceStore.matches([row],IntelligenceStore.filters(country='BLR'))),1)

    def test_same_content_refresh_reuses_frozen_task_payload(self):
        self.collect(feed())
        item=self.call('search')['items'][0]
        args={'item_id':item['id'],'record_sha256':item['record_sha256']}
        original=self.call('review_create',args)
        self.collect(feed(),1700001200)
        self.assertEqual(self.call('review_create',args),original)
        self.assertEqual(original['input']['evidence']['collected_at'],item['collected_at'])

    def test_current_revision_survives_retention_when_old_content_reappears(self):
        self.collect(feed())
        original=self.call('search')['items'][0]
        for number in range(22):
            self.collect(feed(title='Changed '+str(number)),1700001200+number*200)
        self.collect(feed(),1700006000)
        current=self.call('item_get',{'item_id':original['id']})
        self.assertEqual(current['record_sha256'],original['record_sha256'])
        self.assertLessEqual(current['revision_count'],20)
        self.assertTrue(current['revisions'][0]['is_current'])
        self.assertTrue(self.call('item_update',{'item_id':current['id'],'action':'viewed','record_sha256':current['record_sha256']})['is_viewed'])


if __name__ == '__main__':
    unittest.main()
