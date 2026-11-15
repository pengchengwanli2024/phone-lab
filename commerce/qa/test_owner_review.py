"""A responsible owner's signoff is version-bound and never independent certification."""
import copy,json,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_delivery_review as delivery_fixtures

class OwnerReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture=delivery_fixtures.DeliveryReview();self.fixture.setUp();self.app=self.fixture.app;self.cid=self.fixture.cid
        self.fixture.media();self.fixture.record('reviewed')
        self.target=dict(case_id=self.cid,platform='ozon',store_ref='ozon-live',market='RU')
        from fixture_listing_schema import seed
        seed(self.app,self.app.listing_schema.connection(self.app.live.config()))
        p=self.app.listings.get(**self.target);payload=copy.deepcopy(p['payload']);payload['fields']['category_id']='10'
        payload['ozon']={'type_id':20,'attributes':[{'id':101,'values':[{'dictionary_value_id':8,'value':'Synthetic brand'}],'source_ref':'synthetic:brand'},{'id':102,'values':[{'dictionary_value_id':0,'value':'3'}],'source_ref':'synthetic:count'}]}
        self.app.listings.save(**self.target,payload=payload,expected_revision=p['revision'],expected_source_sha256=p['source_sha256'])
    def tearDown(self):self.fixture.tearDown()
    def get(self):return self.app.invoke('commerce_owner_review_get',self.target)
    def record(self,v,decision='owner_confirmed',key='sign',**extra):
        args=dict(**self.target,expected_binding_sha256=v['binding_sha256'],expected_review_sha256=v['review_sha256'],checks={k:dict(status='confirmed',source_ref='synthetic:'+k,note='Synthetic owner statement, not independent certification')for k in v['requirements']},decision=decision,reviewer='Synthetic responsible owner',confirmed=True,idempotency_key=key);args.update(extra)
        return self.app.invoke('commerce_owner_review_record',args)
    def test_owner_signoff_is_explicit_scoped_and_invalidated_by_saved_changes(self):
        view=self.get();self.assertEqual(view['policy'],'owner_attested_not_independently_verified')
        self.assertFalse(view['independent_certification']);self.assertFalse(view['external_execution_allowed'])
        with self.assertRaisesRegex(ValueError,'owner_review_confirmation_required'):self.record(view,confirmed=False)
        self.assertTrue(all(c['ready']for c in view['automatic_checks']),view['automatic_checks'])
        result=self.record(view);self.assertEqual(result['decision'],'owner_confirmed');self.assertTrue(result['current'])
        self.assertEqual(self.record(view)['review_sha256'],result['review_sha256'])
        self.assertEqual(next(s for s in self.app.organization.board(self.cid)['stages']if s['id']=='S6')['status'],'PASS')
        other_plan=self.app.listings.get(**{**self.target,'store_ref':'another-store'})
        self.assertEqual(next(c for c in other_plan['checks']if c['id']=='professional_gate')['status'],'blocked')
        p=self.app.listings.get(**self.target);q=copy.deepcopy(p['payload']);q['fields']['title']='Changed listing content'
        self.app.listings.save(**self.target,payload=q,expected_revision=p['revision'],expected_source_sha256=p['source_sha256'])
        newer=self.get();self.assertFalse(newer['current']);self.assertEqual(newer['status'],'stale')
        with self.assertRaisesRegex(ValueError,'owner_review_binding_changed'):self.record(view,key='old-packet')
        withdrawn=self.record(newer,decision='withdrawn',key='withdraw');self.assertEqual(withdrawn['decision'],'withdrawn');self.assertFalse(withdrawn['external_execution_allowed'])
    def test_missing_prerequisite_or_evidence_never_signs_and_other_store_cannot_reuse_it(self):
        v=self.get()
        with patch.object(self.app.owner_reviews,'prerequisites',return_value=[dict(id='blocked',label='Missing actual cost',ready=False)]):
            with self.assertRaisesRegex(ValueError,'owner_review_prerequisites_missing'):self.record(v)
        checks={k:dict(status='pending',source_ref='',note='')for k in v['requirements']}
        with self.assertRaisesRegex(ValueError,'owner_review_incomplete'):self.record(v,checks=checks)
        other=self.app.invoke('commerce_owner_review_get',{**self.target,'store_ref':'another-store'})
        self.assertFalse(other['supported']);self.assertFalse(other['current'])
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_signed_application_freezes_exact_owner_proof_and_safe_readable_report(self):
        signed=self.record(self.get(),reviewer='Synthetic <owner> & operator')
        p=self.app.listings.get(**self.target)
        self.assertTrue(p['owner_review']['current']);self.assertEqual(p['owner_review']['review_sha256'],signed['review_sha256'])
        created=self.app.listing_releases.create(**self.target,expected_preview_sha256=p['preview_sha256'],note='Synthetic local application',confirmed=True,idempotency_key='owner-freeze')
        view=self.app.listing_releases.get(**self.target)['request']
        self.assertEqual(view['frozen']['owner_review']['review_sha256'],signed['review_sha256'])
        self.assertFalse(view['platform_submission_verified']);self.assertIn('platform_adapter',view['missing'])
        report=self.app.listing_releases.export(created['id'],view['event_sha256'],format='html')['content']
        self.assertIn('经营负责人签收（非独立认证）',report);self.assertIn('Synthetic &lt;owner&gt; &amp; operator',report);self.assertIn('synthetic:rights',report)
        self.record(signed,decision='withdrawn',key='withdraw-frozen')
        old=self.app.listing_releases.get(**self.target)['request']
        self.assertTrue(old['frozen']['owner_review']['current']);self.assertFalse(old['current'])
        self.assertFalse(self.app.listings.get(**self.target)['owner_review']['current'])

    def test_compare_and_swap_idempotency_and_corruption_are_enforced(self):
        v=self.get();saved=self.record(v,decision='save')
        with self.assertRaisesRegex(ValueError,'owner_review_conflict'):self.record(v,key='late')
        with self.assertRaisesRegex(ValueError,'owner_review_idempotency_conflict'):self.record(v,reviewer='Other owner')
        checks=copy.deepcopy(saved['checks']);checks['rights']['source_ref']=''
        with self.assertRaisesRegex(ValueError,'owner_review_evidence_required'):self.record(saved,key='no-proof',checks=checks)
        with self.app.core.db()as db:db.execute("UPDATE org_artifacts SET sha='broken' WHERE id=?",(saved['review_id'],))
        with self.assertRaisesRegex(ValueError,'owner_review_integrity'):self.get()
        self.assertEqual(next(s for s in self.app.organization.board(self.cid)['stages']if s['id']=='S6')['status'],'FAIL')

    def test_expired_receipt_schema_and_credentials_invalidate_signoff(self):
        v=self.record(self.get())
        with patch('owner_review.time.time',return_value=time.time()+60*60*24*365):
            self.assertFalse(self.get()['current']);self.assertNotEqual(self.app.owner_reviews.case_gate(self.cid)['status'],'PASS')
        self.assertTrue(self.get()['current'])
        schema=self.app.listing_schema.evaluate
        with patch.object(self.app.listing_schema,'evaluate',side_effect=lambda *a,**kw:{**schema(*a,**kw),'synthetic_evidence_change':True}):
            self.assertEqual(self.get()['status'],'stale')
        self.app.live.configure({'ozon_api_key':'synthetic-rotated-key'})
        self.assertFalse(self.get()['current']);self.assertEqual(self.get()['status'],'stale')
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_not_applicable_is_limited_and_real_sources_invalidate(self):
        v=self.get();checks={k:dict(status='confirmed',source_ref='synthetic:'+k,note='')for k in v['requirements']}
        checks['rights'].update(status='not_applicable',note='Synthetic rationale')
        with self.assertRaisesRegex(ValueError,'owner_review_not_applicable_requires_reason'):self.record(v,checks=checks)
        checks['rights']['status']='confirmed';checks['qualifications'].update(status='not_applicable',note='Synthetic rule states no certificate required')
        self.assertTrue(self.record(v,checks=checks)['current'])
        research=self.app.organization.artifact(self.cid,'research')['payload'];research['record']['raw_excerpt']='Changed synthetic evidence'
        self.app.organization.record(self.cid,'research',research,'owner-upstream-change')
        self.assertEqual(self.get()['status'],'stale');self.assertFalse(self.get()['current'])

    def test_normalized_store_identity_does_not_orphan_drafts_or_duplicate_a_retry(self):
        view=self.get();saved=self.record(view,decision='save',store_ref=' ozon-live ')
        self.assertIsNotNone(saved['review_id'])
        self.assertEqual(saved['review_sha256'],self.get()['review_sha256'])
        self.assertEqual(self.record(view,decision='save')['review_sha256'],saved['review_sha256'])
        self.assertEqual(len(self.get()['history']),1)
