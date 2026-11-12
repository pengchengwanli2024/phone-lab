"""Persistent-domain acceptance using synthetic captures and no platform traffic."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from commerce_core import Core
from social_intel.store import SocialStore
from social_intel import package as p
from test_package import fixture


def seal(bundle):
    for r in bundle['records']:
        r['content_sha256']=p.content_hash(r);r['record_sha256']=p.record_hash(r)
        for e in bundle['events']:
            if e['record_id']==r['record_id']:e.update(content_sha256=r['content_sha256'],record_sha256=r['record_sha256'])


class PersistentContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.input=self.root/'input';self.input.mkdir()
        self.bundle=fixture(self.input);self.bundle['records'][0]['source']['url']='https://www.tiktok.com/@synthetic/video/1234567890123456789';seal(self.bundle)
        self.service=SimpleNamespace(state=self.root/'state',core=Core(self.root/'state/test.sqlite'))
        self.store=SocialStore(self.service)
    def tearDown(self):self.tmp.cleanup()
    def upload(self,bundle=None,key='stage-1'):
        bundle=bundle or self.bundle;s=self.store.stage(bundle,key)
        for a in bundle['assets']:
            data=(self.input/a['path']).read_bytes()
            self.store.upload(s['stage_id'],a['evidence_id'],'0',base64.b64encode(data).decode())
        return s['stage_id']
    def commit(self,bundle=None,key='stage-1',heads=None):
        return self.store.commit(self.upload(bundle,key),key,heads or {})
    def test_import_replay_and_private_asset_roundtrip(self):
        r=self.commit();stage=self.store.stage(self.bundle,'stage-1')['stage_id']
        self.assertEqual(r,self.store.commit(stage,'stage-1',{}))
        v=self.store.get('synthetic-01');self.assertEqual(len(v['assets']),1);self.assertNotIn('path',v['assets'][0])
        a=self.store.asset(r['batch_id'],'asset-01');self.assertEqual(base64.b64decode(a['content_base64']),(self.input/'evidence/synthetic.txt').read_bytes())
        self.assertEqual(json.loads(self.store.export(r['batch_id'])['content']),self.bundle)
        self.assertEqual(self.store.search(view='top')['total'],1)
    def test_stage_and_chunk_conflicts(self):
        stage=self.store.stage(self.bundle,'same')['stage_id'];changed=copy.deepcopy(self.bundle);changed['scope']['limitations']='changed'
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.store.stage(changed,'same')
        chunk=base64.b64encode(b'abc').decode();self.store.upload(stage,'asset-01','0',chunk)
        self.assertTrue(self.store.upload(stage,'asset-01','0',chunk)['replayed'])
        with self.assertRaisesRegex(ValueError,'chunk_conflict'):self.store.upload(stage,'asset-01','0',base64.b64encode(b'xyz').decode())
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):self.store.commit(stage,'bad',{})
        self.assertEqual(self.store.search()['total'],0)
    def test_old_head_refuses_overwrite_and_keeps_history(self):
        self.commit();old=self.store.get('synthetic-01')['record']
        self.store.mark(old['record_id'],old['record_sha256'],'viewed')
        newer=copy.deepcopy(self.bundle);newer['batch_id']='synthetic-next';newer['records'][0]['summary_zh']='新的合成摘要';seal(newer)
        stage=self.upload(newer,'next')
        with self.assertRaisesRegex(ValueError,'record_conflict'):self.store.commit(stage,'next',{})
        self.store.commit(stage,'next',{'synthetic-01':old['record_sha256']})
        item=self.store.get('synthetic-01');self.assertEqual(len(item['versions']),2);self.assertEqual(len(item['events']),2)
        self.assertTrue(item['is_viewed']);self.assertFalse(self.store.get('synthetic-01',old['record_sha256'])['is_current'])
        with self.assertRaisesRegex(ValueError,'record_conflict'):self.store.mark('synthetic-01',old['record_sha256'],'viewed')
    def test_changed_source_resets_view_but_preserves_bookmark(self):
        self.commit();old=self.store.get('synthetic-01')['record'];self.store.mark(old['record_id'],old['record_sha256'],'viewed');self.store.mark(old['record_id'],old['record_sha256'],'bookmark')
        b=copy.deepcopy(self.bundle);b['batch_id']='source-change';b['records'][0]['original']['text']='New synthetic source.';b['records'][0]['translation']['original_sha256']=p.digest(b['records'][0]['original']['text']);seal(b)
        self.commit(b,'source-change',{'synthetic-01':old['record_sha256']});item=self.store.get('synthetic-01');self.assertFalse(item['is_viewed']);self.assertTrue(item['is_bookmarked'])
    def test_review_deduplicates_across_client_keys(self):
        self.commit();r=self.store.get('synthetic-01')['record']
        a=self.store.review(r['record_id'],r['record_sha256'],'codex-key');b=self.store.review(r['record_id'],r['record_sha256'],'hermes-key')
        self.assertEqual(a['id'],b['id']);self.assertEqual(a['status'],'queued');self.assertEqual(len(self.service.core.invoke('commerce_task_list',{})['tasks']),1)
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.store.review(r['record_id'],'0'*64,'codex-key')
    def test_declared_profile_link_never_commits(self):
        self.bundle['records'][0]['source']['url']='https://www.tiktok.com/@synthetic';seal(self.bundle)
        with self.assertRaisesRegex(ValueError,'invalid_social_permalink'):self.commit()
    def test_batch_and_receipt_identity_conflicts(self):
        self.commit();b=copy.deepcopy(self.bundle);b['scope']['limitations']='different batch content'
        s=self.upload(b,'another')
        with self.assertRaisesRegex(ValueError,'batch_conflict'):self.store.commit(s,'another',{})
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.store.commit(s,'stage-1',{})
    def test_cursor_does_not_mix_changed_snapshots(self):
        self.commit();result=self.store.search(limit='1')
        self.store.mark('synthetic-01',self.bundle['records'][0]['record_sha256'],'bookmark')
        with self.assertRaisesRegex(ValueError,'cursor_expired'):self.store.search(limit='1',offset='1',revision=result['revision'])
    def test_reopen_persists(self):
        self.commit();other=SocialStore(self.service);self.assertEqual(other.get('synthetic-01')['record'],self.bundle['records'][0])
    def test_latest_top_batch_does_not_accumulate_old_rankings(self):
        self.commit();new=copy.deepcopy(self.bundle);new['batch_id']='new-curation';new['records'][0]['record_id']='synthetic-02';new['records'][0]['source']['url']='https://www.tiktok.com/@synthetic/video/2234567890123456789'
        new['events'][0]['record_id']='synthetic-02';seal(new);self.commit(new,'new-curation')
        self.assertEqual(self.store.search()['total'],2)
        result=self.store.search(view='top');self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['record_id'],'synthetic-02');self.assertEqual(result['top_batch_id'],'new-curation')


if __name__=='__main__':unittest.main()
