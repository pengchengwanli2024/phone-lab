"""Persisted synthetic evidence: full text is searchable without fetching or models."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from article_binding import bind, text_hash
from service import Commerce
from translation import validate_response


class FullTextIntelligence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.item = self.publish(0)

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, number, title='Synthetic trade bulletin', latest=True):
        row = dict(id=f'{number:024x}', source='wto', source_key='synthetic-' + str(number),
                   title=title, url='https://example.org/bulletin/' + str(number),
                   published=1700000000 + number, category='trade', country=None,
                   country_code=None, location=None, publisher_alert=None,
                   collected_at='2026-01-01T00:00:00Z')
        with self.app.core.db() as db:
            self.app.intelligence.store.archive(db, row, time.time())
            if latest:
                db.execute('INSERT OR REPLACE INTO intel_items VALUES (?,?,?)',
                           (row['id'], row['source'], json.dumps(row)))
        return self.app.intelligence.store.item(row['id'])

    def article(self, item=None, text='Synthetic customs clearance 25 USD.', zh='合成跨境清关 25 USD。', ident=None):
        item = item or self.item
        article = dict(text=text, content_sha256=text_hash(text), source_url=item['url'],
                       record_sha256=item['record_sha256'], captured_at='2026-01-01T00:00:00Z',
                       routes=['synthetic-a', 'synthetic-b'])
        translated = None if zh is None else dict(zh=zh, original_sha256=text_hash(text), zh_sha256=text_hash(zh))
        doc = dict(id=ident or item['id'] + '0'*8, item_id=item['id'],
                   record_sha256=item['record_sha256'], status='ready', source=item['source'],
                   url=item['url'], translation_status='pending_review' if zh else 'not_requested',
                   article=bind(article, translated))
        self.write_article(doc)
        return doc

    def write_article(self, doc):
        with self.app.core.db() as db:
            db.execute('INSERT OR REPLACE INTO intel_articles VALUES (?,?,?,?,?)',
                       (doc['id'], 'synthetic-' + doc['id'], doc['item_id'], doc['record_sha256'], json.dumps(doc)))

    def search(self, query, **kwargs):
        with patch('intelligence.fetch', side_effect=AssertionError('search must not fetch')), \
                patch('translation.run_model', side_effect=AssertionError('search must not translate')):
            return self.app.invoke('commerce_intel_search', dict(query=query, **kwargs), 'test')

    def test_original_and_chinese_fulltext_have_bounded_versioned_evidence(self):
        doc = self.article(text=('Synthetic filler. '*60) + 'Customs clearance 25 USD. <script>unsafe</script>')
        for query, kind in [('customs clearance', 'article'), ('跨境清关', 'translation'), ('trade customs', 'article')]:
            with self.subTest(query=query):
                result = self.search(query)
                self.assertEqual(result['total'], 1)
                match = result['items'][0]['search_match']
                evidence = next(e for e in match['evidence'] if e['kind'] == kind)
                self.assertEqual(evidence['article_id'], doc['id'])
                self.assertEqual(evidence['record_sha256'], self.item['record_sha256'])
                self.assertFalse(evidence['independently_verified'])
                self.assertLessEqual(len(evidence['snippet']), 222)
                self.assertNotIn('Synthetic filler. Synthetic filler. Synthetic filler.', evidence['snippet'])
        self.assertEqual(self.search('clear')['total'], 0, 'Latin terms remain whole words')
        self.assertEqual(self.search("' OR 1=1 --")['total'], 0)
        result = self.search('customs')
        self.assertEqual(result['search_coverage']['records_with_body'], 1)
        self.assertFalse(result['search_coverage']['fetch_started'])
        self.assertNotIn('article', result['items'][0], 'do not return whole bodies in lists')

    def test_changed_source_and_tampered_body_or_translation_are_excluded(self):
        doc = self.article()
        self.publish(0, 'Changed source title')
        self.assertEqual(self.search('customs')['total'], 0)
        self.item = self.app.intelligence.store.item(self.item['id'])
        doc = self.article()
        doc['article']['translation']['zh'] = '被改写的清关'
        self.write_article(doc)
        self.assertEqual(self.search('清关')['total'], 0)
        self.assertEqual(self.search('customs')['total'], 1, 'valid original stays searchable')
        doc['article']['text'] += ' tampered'
        self.write_article(doc)
        self.assertEqual(self.search('customs')['total'], 0)

    def test_newest_capture_and_current_revision_replace_superseded_text(self):
        doc = self.article(zh='合成原始关税')
        record = self.app.article_reviews.record(doc['id'], 'revision', 'synthetic-revision',
            base_sha256=doc['article']['translation']['zh_sha256'], zh='人工修订的运费', note='Synthetic revision')
        result = self.search('运费')
        self.assertEqual(result['total'], 1)
        evidence = result['items'][0]['search_match']['evidence'][0]
        self.assertEqual(evidence['kind'], 'revision')
        self.assertEqual(evidence['revision_id'], record['id'])
        self.assertEqual(self.search('原始关税')['total'], 0)
        self.article(text='Replacement inspection.', zh=None, ident='f'*32)
        self.assertEqual(self.search('customs')['total'], 0)
        self.assertEqual(self.search('inspection')['total'], 1)

    def test_saved_watch_uses_fulltext_and_does_not_mark_or_create_tasks(self):
        self.article()
        tasks = self.app.invoke('commerce_task_list', {})['tasks']
        self.app.intelligence.store.save_watch('Synthetic clearance', query='跨境清关')
        watch = self.app.intelligence.store.watches()['watches'][0]
        self.assertEqual((watch['matches'], watch['unviewed']), (1, 1))
        self.assertFalse(watch['notification_enabled'])
        self.assertEqual(self.app.invoke('commerce_task_list', {})['tasks'], tasks)
        self.assertFalse(self.search('customs')['items'][0]['is_viewed'])

    def test_body_change_expires_query_cursor_even_if_same_records_match(self):
        for number in range(1, 22):
            self.article(self.publish(number))
        first = self.search('customs', limit='20')
        self.assertTrue(first['next_cursor'])
        self.article(self.app.intelligence.store.item(f'{21:024x}'), text='Updated customs inspection.', zh=None)
        with self.assertRaisesRegex(ValueError, 'intel_cursor_expired'):
            self.search('customs', limit='20', cursor=first['next_cursor'])

    def test_title_translation_is_searchable_only_for_current_verified_binding(self):
        def model(data):
            return validate_response(data, dict(translations=[{'id':x['id'], 'zh':'合成卖家平台政策'} for x in data['items']], provider='synthetic', model='synthetic'))
        with patch('translation.run_model', model):
            job = self.app.intel_reading.start({'records':[{'item_id':self.item['id'], 'record_sha256':self.item['record_sha256']}]}, 'synthetic-title')
            deadline = time.monotonic() + 5
            while job['status'] in ('queued', 'running') and time.monotonic() < deadline:
                time.sleep(.01)
                job = self.app.intel_reading.get(job['id'])
        self.assertEqual(job['status'], 'completed')
        result = self.search('卖家平台政策')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['search_match']['evidence'][0]['kind'], 'translated_title')
        self.publish(0, 'Changed source')
        self.assertEqual(self.search('卖家平台政策')['total'], 0)

    def test_archive_filter_and_metadata_search_still_work_without_articles(self):
        old = self.publish(90, latest=False)
        self.article(old)
        self.assertEqual(self.search('customs')['total'], 0)
        self.assertEqual(self.search('customs', scope='archive')['total'], 1)
        self.assertEqual(self.search('trade')['total'], 1)
        self.assertEqual(self.search('customs', source='fed', scope='archive')['total'], 0)

    def test_failed_new_capture_and_invalid_revision_never_fall_back_silently(self):
        doc = self.article()
        revision = self.app.article_reviews.record(doc['id'], 'revision', 'synthetic-tamper',
            base_sha256=doc['article']['translation']['zh_sha256'], zh='合成修订物流', note='Synthetic')
        with self.app.core.db() as db:
            revision['zh'] = '改写的清关'
            db.execute('UPDATE article_reviews SET document=? WHERE id=?', (json.dumps(revision), revision['id']))
        self.assertEqual(self.search('清关')['total'], 0)
        self.assertEqual(self.search('customs')['total'], 1)
        newer = deepcopy(doc)
        newer.update(id='f'*32, status='failed')
        self.write_article(newer)
        self.assertEqual(self.search('customs')['total'], 0)

    def test_search_and_watches_do_not_write_any_business_rows(self):
        self.article()
        self.app.intelligence.store.save_watch('Synthetic read audit', query='customs')
        def inventory():
            with self.app.core.db() as db:
                tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                # Standard invoke updates only the existing client heartbeat.
                return {name: db.execute('SELECT * FROM "' + name + '"').fetchall() for name in tables if name != 'clients'}
        before = inventory()
        self.search('customs')
        self.app.intelligence.store.watches()
        self.assertEqual(inventory(), before)

    def test_assistant_receives_bounded_hit_evidence_with_original_scope(self):
        from agent_runtime.policy import project, check_call
        self.article()
        result = self.search('customs')
        projected = project('commerce_intel_search', result)
        evidence = projected['items'][0]['search_match']['evidence'][0]
        self.assertEqual(evidence['kind'], 'article')
        self.assertIn('customs', evidence['snippet'])
        self.assertEqual(projected['source_trust'], 'untrusted_reference_data')
        self.assertFalse(evidence['independently_verified'])
        self.assertNotIn('article', projected['items'][0])
        with self.assertRaisesRegex(ValueError,'agent_invalid_tool_arguments'):
            check_call('intelligence', {}, {'tool':'commerce_intel_search','arguments':{'scope':'archive'}}, set())
        import test_agent_runtime as runtime
        run = self.app.invoke('commerce_agent_start', dict(question='检索合成清关证据', role='conductor',
            topic='intelligence', parameters={}, idempotency_key='synthetic-fulltext-agent'))
        with patch('agent_runtime.model.invoke', side_effect=[runtime.inspect('commerce_intel_search', {'query':'customs'}), runtime.answer()]):
            self.app.agent_runtime.run_once()
        finished = self.app.agent_runtime.get(run['id'])
        self.assertEqual(finished['status'], 'completed')
        observed = finished['result']['observations'][0]['data']['items'][0]['search_match']
        self.assertEqual(observed, projected['items'][0]['search_match'])

    def test_search_reuses_an_existing_core_transaction(self):
        self.article()
        with self.app.core.atomic():
            found = self.app.intelligence.store.search(query='customs')
            self.assertEqual(found['total'], 1)


if __name__ == '__main__':
    unittest.main()
