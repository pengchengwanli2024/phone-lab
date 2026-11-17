"""Actual SQLite preview rollback, all-or-none import and version observations."""
import sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_product_media as fixtures

class Feedback(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.ProductMediaTests();self.fixture.setUp();self.app=self.fixture.app;self.pid=self.fixture.pid
 def tearDown(self):self.app.autonomy.stop();self.fixture.tearDown()
 def report(self,text,**extra):return self.app.invoke('commerce_media_performance_import',{'project_id':self.pid,'csv_text':text,'source_ref':'synthetic:export',**extra})
 def rows(self):
  with self.app.core.db()as db:return db.execute('SELECT count(*)FROM creative_performance').fetchone()[0]
 def test_preview_rolls_back_and_confirmation_is_idempotent(self):
  text='period_start,period_end,impressions,clicks\n2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,1000,30\n'
  p=self.report(text);self.assertFalse(p['committed']);self.assertEqual(self.rows(),0)
  r=self.report(text,commit=True,expected_preview_sha256=p['preview_sha256']);self.assertEqual(self.rows(),1);self.assertEqual(self.report(text,commit=True,expected_preview_sha256=p['preview_sha256'])['record_ids'],r['record_ids'])
  with self.assertRaisesRegex(ValueError,'preview_changed'):self.report(text.replace('1000','2000'),commit=True,expected_preview_sha256=p['preview_sha256'])
 def test_invalid_later_row_cannot_commit_earlier_row(self):
  text='period_start,period_end,impressions,clicks\n2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,1000,30\n2026-11-01T00:00:00Z,2026-11-02T00:00:00Z,10,30\n'
  with self.assertRaisesRegex(ValueError,'count_conflict'):self.report(text)
  self.assertEqual(self.rows(),0)
 def test_review_records_only_the_observation_it_used(self):
  for i in (1,2):self.app.media.performance_save(self.pid,{'period_start':f'2026-11-0{i}T00:00:00Z','period_end':f'2026-11-0{i+1}T00:00:00Z','source_ref':'synthetic:report-'+str(i),'impressions':1000,'clicks':20},str(i))
  r=self.app.media.review_now(self.pid,'latest');self.assertEqual(len(r['performance_ids']),1);self.assertEqual(r['observed_media'][0]['source_ref'],'synthetic:report-2')

if __name__=='__main__':unittest.main()
