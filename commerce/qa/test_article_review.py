"""Synthetic review declarations and conservative multilingual numeric checks."""
from copy import deepcopy
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from seed_intel_workspace import seed
from research import drift

class Reviews(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=seed(self.tmp.name)
        self.doc=self.app.articles.get('a'*32);self.hash=self.doc['article']['translation']['zh_sha256']
    def tearDown(self):self.tmp.cleanup()
    def record(self,operation,key='synthetic-record',**data):return self.app.article_reviews.record(self.doc['id'],operation,key,client='synthetic',base_sha256=data.pop('base_sha256',self.hash),**data)
    def test_cjk_calendar_time_and_adjacent_units(self):
        self.assertEqual(drift('November 09, 2026 at 4:00 p.m. EST, 25 kg, 50 %','2026年11月09日 下午4:00 EST，25kg，50%'),[])
        self.assertTrue(drift('November 09, 2026, 25 USD','2026年11月10日，25EUR'))
        self.assertTrue(drift('25 USD','金额26USD'))
        self.assertTrue(drift('1,000 USD','金额1000USD'))
    def test_recheck_append_only_and_idempotent(self):
        first=self.record('recheck');self.assertEqual(first,self.record('recheck'))
        self.assertEqual(first['status'],'pending_review')
        self.assertEqual(self.app.articles.get(self.doc['id'])['article'],self.doc['article'])
    def test_revision_conflicts_and_explicit_declaration(self):
        revision=self.record('revision',zh='修订后的合成文章 25 USD。',note='合成修改')
        with self.assertRaisesRegex(ValueError,'conflict'):self.record('revision','stale',zh='过期编辑')
        with self.assertRaisesRegex(ValueError,'confirmation'):self.record('review','no-confirm',base_sha256=revision['zh_sha256'],decision='approved',note='合成检查')
        receipt=self.record('review','confirmed',base_sha256=revision['zh_sha256'],decision='approved',confirmed=True,note='合成测试声明')
        self.assertFalse(receipt['declaration_is_identity_proof'])
        self.assertEqual(self.app.articles.get(self.doc['id'])['article']['translation']['status'],'pending_review')
    def test_changed_source_rejects_new_review(self):
        item=self.app.intelligence.store.item(self.doc['item_id'])
        with self.app.core.db() as db:self.app.intelligence.store.archive(db,dict(item,title='Changed synthetic source'),1700001300)
        with self.assertRaisesRegex(ValueError,'record_changed'):self.record('recheck')

if __name__=='__main__':unittest.main()
