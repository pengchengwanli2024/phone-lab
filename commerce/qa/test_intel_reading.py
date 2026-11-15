"""Chinese reading uses real persisted translation jobs and frozen public titles."""
from pathlib import Path
import json
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from translation import validate_response


class ChineseReading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        self.publish()

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self, title='Trade bulletin 25 USD'):
        row=dict(id='a'*24, source='wto', source_key='synthetic-reading', title=title,
                 url='https://example.org/bulletin', published=1700000000, category='trade',
                 country=None, country_code=None, location=None, publisher_alert=None,
                 collected_at='2026-01-01T00:00:00Z', source_payload_sha256='b'*64)
        with self.app.core.db() as db:
            db.execute('INSERT OR REPLACE INTO intel_items VALUES (?,?,?)', (row['id'],'wto',json.dumps(row)))
            self.app.intelligence.store.archive(db, row, time.time())
        self.item=self.app.intelligence.store.item(row['id'])

    def start(self, key='synthetic-title'):
        return self.app.invoke('commerce_intel_reading_start', {
            'input':{'records':[{'item_id':self.item['id'],'record_sha256':self.item['record_sha256']}]},
            'idempotency_key':key}, 'test')

    def wait(self, job):
        end=time.monotonic()+5
        while job['status'] in ('queued','running') and time.monotonic()<end:
            time.sleep(.02)
            job=self.app.invoke('commerce_intel_reading_get',{'job_id':job['id']},'test')
        self.assertNotIn(job['status'],('queued','running'))
        return job

    @staticmethod
    def model(data):
        return validate_response(data, {'provider':'synthetic','model':'synthetic',
            'translations':[{'id':x['id'],'zh':'贸易公告 25 USD'} for x in data['items']]})

    def test_explicit_translation_is_persistent_version_bound_and_idempotent(self):
        with patch('translation.run_model',self.model):
            job=self.wait(self.start())
            again=self.start()
        self.assertEqual(job['status'],'completed')
        self.assertEqual(again['id'],job['id'])
        self.assertEqual(job['readings'][0]['zh_title'],'贸易公告 25 USD')
        self.assertFalse(job['readings'][0]['source_record_changed'])
        restored=Commerce(self.tmp.name)
        row=restored.invoke('commerce_intel_search',{},'test')['items'][0]
        self.assertEqual(row['reading']['zh_title'],'贸易公告 25 USD')
        self.assertEqual(row['reading']['status'],'pending_review')
        self.assertEqual(restored.invoke('commerce_intel_item_get',{'item_id':row['id']})['title'],
                         'Trade bulletin 25 USD')
        self.publish('Updated bulletin 30 USD')
        self.assertNotIn('reading',self.app.invoke('commerce_intel_search',{})['items'][0])
        old=self.app.invoke('commerce_intel_reading_get',{'job_id':job['id']})
        self.assertTrue(old['readings'][0]['source_record_changed'])

    def test_rejects_stale_versions_and_unbounded_or_duplicate_inputs(self):
        for records in ([],[{'item_id':self.item['id'],'record_sha256':'f'*64}],
                        [{'item_id':self.item['id'],'record_sha256':self.item['record_sha256']}]*21,
                        [{'item_id':self.item['id'],'record_sha256':self.item['record_sha256']}]*2):
            with self.subTest(records=len(records)), self.assertRaises(ValueError):
                self.app.invoke('commerce_intel_reading_start',{'input':{'records':records},
                                'idempotency_key':'invalid'},'test')
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM translations').fetchone()[0],0)

    def test_translation_failure_is_visible_and_reads_never_retry(self):
        with patch('translation.run_model',side_effect=ValueError('translation_provider_failed')):
            job=self.wait(self.start())
        self.assertEqual(job['status'],'failed')
        with patch('translation.run_model',side_effect=AssertionError('read triggered a model')):
            for unused in range(2):
                self.app.invoke('commerce_intel_search',{})
                self.app.invoke('commerce_intel_reading_get',{'job_id':job['id']})
        self.assertNotIn('reading',self.app.invoke('commerce_intel_search',{})['items'][0])
        with patch('translation.run_model',self.model):
            self.assertEqual(self.wait(self.start('explicit-retry'))['status'],'completed')

    def test_reopening_same_revision_with_a_new_ui_key_reuses_completed_translation(self):
        with patch('translation.run_model',self.model):
            first=self.wait(self.start())
            second=self.wait(self.start('reopened-page'))
        self.assertEqual(first['id'],second['id'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM translations').fetchone()[0],1)

    def test_bookmark_and_view_responses_keep_the_current_chinese_title(self):
        with patch('translation.run_model',self.model):
            self.wait(self.start())
        for action in ('bookmark','viewed','unviewed','unbookmark'):
            args={'item_id':self.item['id'],'action':action}
            if action=='viewed':args['record_sha256']=self.item['record_sha256']
            result=self.app.invoke('commerce_intel_item_update',args)
            self.assertEqual(result.get('reading',{}).get('zh_title'),'贸易公告 25 USD',action)


if __name__=='__main__':
    unittest.main()
