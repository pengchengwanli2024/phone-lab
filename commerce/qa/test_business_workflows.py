"""Synthetic behavioral checks: no platform, credentials, buyer identity or model."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import copy
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce,TOOLS
from business_workflows.store import SPECS

class Workflows(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.w=self.app.business
    def tearDown(self):self.tmp.cleanup()
    def call(self,name,**args):return self.app.invoke('commerce_business_'+name,args,'test')
    def source(self,kind='reviews',key='source',**changes):
        doc=self.w.template(kind)['document'];doc.update(changes)
        r=self.call('import',document=doc,idempotency_key=key)
        return r,doc
    def price(self,key='price'):
        source,doc=self.source('price',key+'source')
        content={'fields':{r['key']:r['value'] for r in doc['records']},'citations':{r['key']:{'source_id':source['source_id'],'key':r['key']} for r in doc['records']}}
        d=self.call('draft',kind='price',source_ids=[source['source_id']],content=content,idempotency_key=key)
        return d,source,doc,content

    def test_real_intake_is_not_seeded_and_modes_never_mix(self):
        self.assertEqual(self.call('list',synthetic=False)['sources'],[])
        s,d=self.source();self.assertEqual(len(self.call('list',synthetic=True)['sources']),1)
        self.assertEqual(self.call('list',synthetic=False)['sources'],[])
        self.assertEqual(self.call('source_get',source_id=s['source_id'])['document'],d)
        self.assertFalse(self.call('list',synthetic=False)['automatic_platform_intake'])

    def test_import_revision_cas_atomicity_and_idempotency(self):
        s,doc=self.source();again=self.call('import',document=doc,idempotency_key='source');self.assertEqual(s,again)
        changed=copy.deepcopy(doc);changed['records'][0]['text']='包装破损，需要核对。'
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.call('import',document=changed,idempotency_key='source')
        s2=self.call('import',document=changed,source_id=s['source_id'],expected_version=1,idempotency_key='update')
        self.assertEqual(s2['version'],2)
        with self.assertRaisesRegex(ValueError,'version_conflict'):self.call('import',document=changed,source_id=s['source_id'],expected_version=1,idempotency_key='old')
        self.assertEqual(self.call('source_get',source_id=s['source_id'],version=1)['document'],doc)
        changed['scope']['store_ref']='different-store'
        with self.assertRaisesRegex(ValueError,'scope_immutable'):self.call('import',document=changed,source_id=s['source_id'],expected_version=2,idempotency_key='scope')

    def test_analysis_evidence_rules_missing_ratings_and_no_sentiment_claim(self):
        t=self.w.template('reviews')['document'];t['records']=[{'id':'r1','text':'包装破损，尺寸不适用','rating':1},{'id':'r2','text':'неизвестно','rating':None}]
        s=self.call('import',document=t,idempotency_key='r');d=self.call('analyze',source_ids=[s['source_id']],idempotency_key='a')
        c=d['draft']['content'];self.assertEqual(c['total_records'],2);self.assertEqual(c['missing_rating'],1);self.assertEqual(c['unmatched'],1)
        self.assertEqual(c['topics'][0]['evidence'][0]['quote'],t['records'][0]['text']);self.assertEqual(c['rating_counts']['1'],1)
        self.assertEqual(d['draft']['sources'][0]['sha256'],s['sha256']);self.assertFalse(d['external_execution_allowed'])
        self.assertFalse(d['preflight']['semantic_accuracy_verified'])

    def test_scope_and_synthetic_mix_rejected(self):
        s,d=self.source();d2=copy.deepcopy(d);d2['synthetic']=False
        s2=self.call('import',document=d2,idempotency_key='real')
        with self.assertRaisesRegex(ValueError,'scope_mismatch'):self.call('analyze',source_ids=[s['source_id'],s2['source_id']],idempotency_key='mix')
        d2['scope']['store_ref']='different';s3=self.call('import',document=d2,idempotency_key='scope')
        with self.assertRaisesRegex(ValueError,'scope_mismatch'):self.call('analyze',source_ids=[s2['source_id'],s3['source_id']],idempotency_key='mix2')

    def test_preflight_fields_and_citations_and_unknown_scope(self):
        d,s,doc,c=self.price();self.assertTrue(d['preflight']['ready_for_local_review'])
        c['fields']['price']='99.00';d2=self.call('draft',kind='price',source_ids=[s['source_id']],content=c,idempotency_key='wrong')
        self.assertIn('price',d2['preflight']['uncited_fields']);self.assertEqual(d2['status'],'needs_input')
        c['fields']['price']='NaN';c['fields']['currency']='usd';del c['fields']['sku']
        d3=self.call('draft',kind='price',source_ids=[s['source_id']],content=c,idempotency_key='bad')
        self.assertEqual(d3['preflight']['missing_fields'],['sku']);self.assertIn('price',d3['preflight']['invalid_fields']);self.assertIn('currency',d3['preflight']['invalid_fields'])
        doc['scope']['store_ref']=None;s2=self.call('import',document=doc,idempotency_key='unknown')
        c['fields']={r['key']:r['value'] for r in doc['records']};c['citations']={r['key']:{'source_id':s2['source_id'],'key':r['key']} for r in doc['records']}
        d4=self.call('draft',kind='price',source_ids=[s2['source_id']],content=c,idempotency_key='unknown-draft');self.assertFalse(d4['preflight']['store_scope_known']);self.assertFalse(d4['preflight']['ready_for_local_review'])

    def test_every_business_recipe_and_explicit_local_review(self):
        for kind in SPECS:
            with self.subTest(kind=kind):
                s,doc=self.source(kind,kind+'source');ids=[s['source_id']]
                c={'fields':{r['key']:r['value'] for r in doc['records']},'citations':{r['key']:{'source_id':s['source_id'],'key':r['key']} for r in doc['records']}}
                if kind=='support':conv,_=self.source('conversation','conv');ids.append(conv['source_id'])
                d=self.call('draft',kind=kind,source_ids=ids,content=c,idempotency_key=kind)
                self.assertTrue(d['preflight']['ready_for_local_review'],d['preflight'])
                args=dict(draft_id=d['id'],expected_sha256=d['draft']['draft_sha256'],decision='reviewed',confirmed=True,idempotency_key=kind+'review')
                bad=dict(args,confirmed=False)
                with self.assertRaisesRegex(ValueError,'explicit_local_review'):self.call('review',**bad)
                r=self.call('review',**args);self.assertFalse(r['external_execution_allowed']);self.assertEqual(r['approval_scope'],'local_draft_only')
                self.assertEqual(self.call('get',draft_id=d['id'])['status'],'local_review_recorded')
                self.assertEqual(self.call('review',**args),r)
                self.assertFalse(self.call('get',draft_id=d['id'])['preflight']['platform_rules_verified'])

    def test_source_change_invalidates_review_and_export_retains_old_evidence(self):
        d,s,doc,c=self.price();args=dict(draft_id=d['id'],expected_sha256=d['draft']['draft_sha256'],decision='reviewed',confirmed=True,idempotency_key='review')
        self.call('review',**args);doc['records'][0]['value']='different-sku'
        self.call('import',document=doc,source_id=s['source_id'],expected_version=1,idempotency_key='v2')
        stale=self.call('get',draft_id=d['id']);self.assertEqual(stale['status'],'stale');self.assertEqual(stale['preflight']['changed_ids'],[s['source_id']])
        with self.assertRaisesRegex(ValueError,'preflight_incomplete'):self.call('review',**dict(args,idempotency_key='late'))
        artifact=json.loads(self.call('export',draft_id=d['id'])['content']);self.assertEqual(artifact['sources'][0]['version'],1);self.assertEqual(artifact['sources'][0]['document']['records'][0]['value'],c['fields']['sku'])
        self.assertFalse(artifact['external_execution_allowed']);self.assertEqual(len(stale['receipts']),1)

    def test_expiration_rejects_current_hash(self):
        d,s,doc,c=self.price();now=datetime.now(timezone.utc)
        doc['observed_at']=(now-timedelta(days=2)).isoformat();doc['valid_until']=(now-timedelta(days=1)).isoformat()
        s2=self.call('import',document=doc,idempotency_key='expired');c['citations']={k:{'source_id':s2['source_id'],'key':k} for k in c['fields']}
        stale=self.call('draft',kind='price',source_ids=[s2['source_id']],content=c,idempotency_key='stale');self.assertEqual(stale['status'],'stale')

    def test_restart_and_concurrent_idempotency(self):
        s,doc=self.source();args=dict(kind='review',source_ids=[s['source_id']],content={})
        def make(_):return self.w.analyze([s['source_id']],'same')
        with ThreadPoolExecutor(max_workers=5) as pool:ids=[x['id'] for x in pool.map(make,range(10))]
        self.assertEqual(len(set(ids)),1);restarted=Commerce(self.tmp.name)
        self.assertEqual(restarted.business.get(ids[0])['draft'],self.w.get(ids[0])['draft'])

    def test_invalid_batch_rolls_back_and_errors_never_echo_payload(self):
        doc=self.w.template('reviews')['document'];doc['records'].append({'id':'bad','text':'PRIVATE_SENTINEL','rating':True})
        with self.assertRaises(ValueError) as cm:self.call('import',document=doc,idempotency_key='bad')
        self.assertNotIn('PRIVATE_SENTINEL',str(cm.exception));self.assertEqual(self.call('list',synthetic=True)['sources'],[])
        doc=self.w.template('facts')['document'];doc['origin_ref']='https://example.com/?token=PRIVATE_SENTINEL'
        with self.assertRaisesRegex(ValueError,'invalid_origin'):self.call('import',document=doc,idempotency_key='private-url')
        self.assertFalse(any(n.startswith('commerce_business_execute') for n,_,_ in TOOLS))

if __name__=='__main__':unittest.main()
