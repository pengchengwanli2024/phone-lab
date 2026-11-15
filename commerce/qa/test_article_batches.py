"""Explicit bounded body collection reuses the original article snapshots."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[2]/'crawlers')]
from article_binding import text_hash
from service import Commerce


class ArticleBatches(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name)
        for i,source in enumerate(['fed','ecb','eia','wto','hmrc','transport']):
            from article import PUBLISHERS
            host,prefix,_=PUBLISHERS[source]
            if isinstance(prefix,tuple):prefix=prefix[0]
            row=dict(id=f'{i:024x}',source=source,source_key='synthetic-'+source,title='Synthetic bulletin '+source,
                url='https://'+host+prefix+'synthetic-'+str(i),published=1700000000+i,category='trade',country=None,country_code=None,location=None,publisher_alert=None,collected_at='2026-01-01T00:00:00Z')
            with self.app.core.db()as db:
                self.app.intelligence.store.archive(db,row,time.time());db.execute('INSERT INTO intel_items VALUES (?,?,?)',(row['id'],source,json.dumps(row)))
        self.app.articles.fetcher=self.capture

    def tearDown(self):
        if hasattr(self.app,'article_batches'):self.app.article_batches.stop()
        self.tmp.cleanup()

    def capture(self,doc):
        text='Synthetic customs clearance 25 USD. '*8
        return dict(text=text,content_sha256=text_hash(text),source_url=doc['url'],captured_at='2026-01-01T00:00:00Z',routes=['synthetic-a','synthetic-b'])

    def call(self,name,**args):return self.app.invoke('commerce_intel_article_'+name,args,'test')
    def plan(self,limit=6,**filters):return self.call('plan',filters=filters,limit=limit)
    def start(self,plan=None,key='synthetic-batch'):
        plan=plan or self.plan()
        return self.call('batch_start',filters=plan['filters'],limit=plan['limit'],expected_plan_sha256=plan['sha256'],idempotency_key=key)
    def wait(self,job):
        end=time.monotonic()+6
        while job['status']in('queued','running','cancel_requested')and time.monotonic()<end:
            time.sleep(.02);job=self.call('batch_get',batch_id=job['id'])
        self.assertNotIn(job['status'],('queued','running','cancel_requested'));return job

    def test_plan_is_readonly_and_balances_sources_then_captures_real_child_records(self):
        plan=self.plan();self.assertEqual(len(plan['records']),6)
        self.assertEqual(len({r['source']for r in plan['records']}),6)
        with self.app.core.db()as db:self.assertEqual(db.execute('SELECT count(*)FROM intel_articles').fetchone()[0],0)
        job=self.wait(self.start(plan));self.assertEqual(job['status'],'completed')
        self.assertEqual(job['counts']['current_ready'],6)
        self.assertEqual(self.plan()['records'],[])
        result=self.app.invoke('commerce_intel_search',{'query':'customs'})
        self.assertEqual(result['total'],6)
        self.assertEqual(self.start(plan)['id'],job['id'],'idempotency reads the same batch despite coverage growth')

    def test_preview_change_and_invalid_filters_are_rejected(self):
        plan=self.plan()
        row=self.app.intelligence.store.item(plan['records'][0]['item_id'])
        with self.app.core.db()as db:self.app.intelligence.store.archive(db,dict(row,title='Changed synthetic title'),time.time())
        with self.assertRaisesRegex(ValueError,'article_batch_plan_changed'):self.start(plan)
        for args in ({'filters':{},'limit':True},{'filters':{'scope':'remote'},'limit':6}):
            with self.assertRaises(ValueError):self.call('plan',**args)

    def test_partial_failures_are_explicit_and_retry_only_failed_records(self):
        calls=[]
        def fetch(doc):
            calls.append(doc['item_id'])
            if doc['source']=='eia':raise ValueError('article_body_unavailable')
            return self.capture(doc)
        self.app.articles.fetcher=fetch
        job=self.wait(self.start());self.assertEqual(job['status'],'partial')
        self.assertEqual(job['counts']['failed'],1)
        with self.assertRaisesRegex(ValueError,'article_batch_invalid_retry_selection'):
            self.call('batch_resume',batch_id=job['id'],expected_revision=job['revision'],retry_failed=True,retry_item_ids=['f'*24])
        self.app.articles.fetcher=lambda doc:(calls.append(doc['item_id'])or self.capture(doc))
        failed=[r['item_id']for r in job['records']if r['status']=='failed']
        job=self.wait(self.call('batch_resume',batch_id=job['id'],expected_revision=job['revision'],retry_failed=True,retry_item_ids=failed))
        self.assertEqual(job['counts']['current_ready'],6);self.assertEqual(len(calls),7)
        self.assertFalse(job['translation_started'])

    def test_cancel_preserves_finished_work_and_resume_never_duplicates_active_capture(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def fetch(doc):
            calls.append(doc['item_id']);entered.set();release.wait(3);return self.capture(doc)
        self.app.articles.fetcher=fetch
        job=self.start();self.assertTrue(entered.wait(2))
        cancelled=self.call('batch_cancel',batch_id=job['id']);self.assertEqual(cancelled['status'],'cancel_requested')
        release.set();job=self.wait(cancelled);self.assertEqual(job['status'],'cancelled')
        self.assertEqual(job['counts']['current_ready'],1)
        job=self.wait(self.call('batch_resume',batch_id=job['id'],expected_revision=job['revision'],retry_failed=False))
        self.assertEqual(job['counts']['current_ready'],6);self.assertEqual(len(calls),6)

    def test_restart_requires_explicit_resume_and_source_drift_is_not_silently_rebound(self):
        job=self.wait(self.start())
        with self.app.core.db()as db:
            doc=json.loads(db.execute('SELECT document FROM intel_article_batches WHERE id=?',(job['id'],)).fetchone()[0]);doc['status']='running'
            db.execute('UPDATE intel_article_batches SET status=?,document=? WHERE id=?',('running',json.dumps(doc),job['id']))
        self.app.article_batches.recover();job=self.call('batch_get',batch_id=job['id'])
        self.assertEqual(job['status'],'interrupted')
        row=self.app.intelligence.store.item(job['records'][0]['item_id'])
        with self.app.core.db()as db:self.app.intelligence.store.archive(db,dict(row,title='Changed source'),time.time())
        self.assertEqual(self.call('batch_get',batch_id=job['id'])['counts']['current_ready'],5)

    def test_concurrent_idempotency_and_queued_cancel_keep_one_original_batch(self):
        plan=self.plan()
        with patch.object(self.app.article_batches,'launch'):
            with ThreadPoolExecutor(max_workers=2)as pool:
                jobs=list(pool.map(lambda _:self.start(plan),range(2)))
        self.assertEqual(len({j['id']for j in jobs}),1)
        job=self.call('batch_cancel',batch_id=jobs[0]['id']);self.assertEqual(job['status'],'cancelled')
        job=self.wait(self.call('batch_resume',batch_id=job['id'],expected_revision=job['revision'],retry_failed=False))
        self.assertEqual(job['counts']['current_ready'],6)


if __name__=='__main__':unittest.main()
