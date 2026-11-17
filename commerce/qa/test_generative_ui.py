"""Controlled composition and original-run recovery; synthetic local state only."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_copilot import Dialogue
from test_agent_runtime import answer, inspect


class GenerativeUI(unittest.TestCase):
    setUp=Dialogue.setUp
    tearDown=Dialogue.tearDown
    send=Dialogue.send
    def test_catalog_selection_cannot_introduce_data_or_actions(self):
        from generative.catalog import select
        observations = [{'id':'R1','tool':'commerce_workspace_get','sha256':'a'*64,
            'data':{'case_id':'case-a','source_sha256':'b'*64,'quotes':{'items':[]},'delivery_review':{'status':'HOLD'}}}]
        selected = select([{'component':'DeliveryReview','reference':'R1'}], observations)
        self.assertEqual(selected[0]['component'], 'DeliveryReview')
        for bad in ([{'component':'Script','reference':'R1'}],
                    [{'component':'DeliveryReview','reference':'R2'}],
                    [{'component':'DeliveryReview','reference':'R1','data':{'status':'PASS'}}],
                    [{'component':'DeliveryReview','reference':'R1','action':'publish'}]):
            with self.assertRaises(ValueError): select(bad, observations)

    def test_component_must_match_observation_and_unique_identity(self):
        from generative.catalog import select
        obs=[{'id':'R1','tool':'commerce_runtime_status','data':{},'sha256':'a'*64}]
        with self.assertRaises(ValueError):select([{'component':'QuoteComparison','reference':'R1'}],obs)
        with self.assertRaises(ValueError):select([{'component':'Evidence','reference':'R1'}]*2,obs)

    def test_listing_read_requires_exact_case_platform_store_and_market(self):
        from copilot.reads import check
        context={'module':'organization','demo':False,'platform':'ozon','store_id':'store-a','market':'RU','entity':{'kind':'case','id':'case-a'}}
        args={'case_id':'case-a','platform':'ozon','store_ref':'store-a','market':'RU'}
        self.assertEqual(check(context,'commerce_listing_get',args,set()),('commerce_listing_get',args))
        with self.assertRaises(ValueError):check(context,'commerce_listing_get',{**args,'store_ref':'store-b'},set())
        with self.assertRaises(ValueError):check({**context,'store_id':'all'},'commerce_listing_get',args,set())
        with self.assertRaises(ValueError):check(context,'commerce_skills_readiness',{'skill_id':'sealeap-unseen'},set())

    def test_partial_json_only_exposes_answer_and_complete_validated_selections(self):
        from generative.streaming import Preview
        events=[];preview=Preview(events.append,[])
        raw=json.dumps({'phase':'answer','answer':'第一行\n第二行 😀','questions':[], 'ui':[]},ensure_ascii=True)
        for char in raw:preview.feed(char)
        self.assertEqual(''.join(e['delta'] for e in events if e['type']=='answer_delta'),'第一行\n第二行 😀')
        self.assertFalse(any(e['type']=='component' for e in events))
        events=[];preview=Preview(events.append,[])
        preview.feed('{"phase":"inspect","calls":[{"tool":"answer","arguments":{"answer":"SECRET"}}]}')
        self.assertEqual(events,[])

    def test_journal_cursor_is_bound_to_thread_and_survives_reopen(self):
        from generative.journal import Journal
        sent=self.send();run_id=sent['latest_run']['id'];journal=Journal(self.app.core)
        journal.append(run_id,{'type':'reset','turn':1,'mode':'provider_deltas'})
        journal.append(run_id,{'type':'answer_delta','delta':'合成增量'})
        out=self.app.copilot.events(self.thread['id'],run_id,after=0,limit=1)
        self.assertEqual(out['cursor'],1);self.assertTrue(out['has_more'])
        out=self.app.copilot.events(self.thread['id'],run_id,after=1)
        self.assertEqual([e['type'] for e in out['events']],['answer_delta'])
        self.assertEqual(out['snapshot']['answer'],'合成增量')
        other=self.app.copilot.open({'module':'overview','demo':False},'other-ui')
        with self.assertRaisesRegex(ValueError,'stream_scope'):self.app.copilot.events(other['id'],run_id)
        with self.assertRaises(ValueError):self.app.copilot.events(self.thread['id'],run_id,after=99)
        self.assertEqual(Journal(self.app.core).snapshot(run_id)['answer'],'合成增量')

    def test_run_finalizes_and_invalid_layout_falls_back_without_discarding_answer(self):
        result=answer();result['decision']['ui']=[{'component':'Script','reference':'R1'}]
        self.send()
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),result]):self.app.agent_runtime.run_once()
        run=self.app.copilot.get(self.thread['id'])['latest_run']
        self.assertEqual(run['status'],'completed')
        self.assertEqual(run['presentation']['layout_status'],'fallback')
        self.assertTrue(run['result']['answer'])
        self.assertFalse(run['stream']['provisional'])
        self.assertEqual(run['stream']['answer'],'')

    def test_model_composition_is_retained_and_reference_identity_is_stable(self):
        result=answer();result['decision']['ui']=[{'component':'Evidence','reference':'R1'}]
        self.send()
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),result]):self.app.agent_runtime.run_once()
        first=self.app.copilot.get(self.thread['id'])['latest_run']['presentation']
        again=self.app.copilot.get(self.thread['id'])['latest_run']['presentation']
        self.assertEqual(first,again)
        self.assertEqual(first['layout_status'],'model_selected')
        self.assertEqual(first['components'][0]['binding']['reference'],'R1')
        self.assertFalse(first['external_execution_allowed'])

    def test_live_preview_uses_same_run_and_is_retracted_after_invalid_final(self):
        from generative.streaming import emit
        self.send();observed=[]
        def provider(payload,cancelled,**kwargs):
            emit('{"phase":"answer","answer":"未完成的合成预览')
            run=self.app.copilot.get(self.thread['id'])['latest_run']
            observed.append(run['stream']['answer'])
            return {'decision':{'phase':'answer','answer':'x','questions':[],'evidence_refs':['invented'],'proposals':[]}}
        with patch('agent_runtime.model.invoke',side_effect=provider):self.app.agent_runtime.run_once()
        self.assertEqual(observed,['未完成的合成预览'])
        final=self.app.copilot.get(self.thread['id'])['latest_run']
        self.assertEqual(final['status'],'failed');self.assertFalse(final['stream']['provisional'])
        self.assertEqual(final['stream']['answer'],'')
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],1)

    def test_valid_multibyte_evidence_does_not_abort_optional_preview(self):
        from generative.streaming import Preview
        from generative.journal import Journal
        sent=self.send();run_id=sent['latest_run']['id'];journal=Journal(self.app.core)
        obs=[{'id':'R1','tool':'commerce_runtime_status','data':{'note':'中'*8000},'sha256':'a'*64}]
        preview=Preview(lambda e:journal.append(run_id,e),obs,run_id)
        preview.feed(json.dumps({'phase':'answer','answer':'正常','ui':[{'component':'Evidence','reference':'R1'}]},ensure_ascii=False))
        self.assertEqual(journal.snapshot(run_id)['components'][0]['binding']['reference'],'R1')

    def test_preview_limit_is_explicit_and_reserves_authoritative_settlement(self):
        from generative.journal import Journal
        run_id=self.send()['latest_run']['id'];journal=Journal(self.app.core)
        for _ in range(520):journal.append(run_id,{'type':'answer_delta','delta':'x'})
        self.assertTrue(journal.snapshot(run_id).get('truncated'))
        journal.append(run_id,{'type':'settled','status':'completed'})
        snapshot=journal.snapshot(run_id)
        self.assertFalse(snapshot['provisional']);self.assertEqual(snapshot['answer'],'')
        with self.app.core.db()as db:self.assertLessEqual(db.execute('SELECT count(*) FROM agent_ui_events WHERE run_id=?',(run_id,)).fetchone()[0],512)

    def test_real_workspace_listing_projection_is_read_only_and_has_product_fields(self):
        import test_organization as fixtures
        from generative.reads import listing
        fixture=fixtures.OrganizationTests();fixture.setUp()
        try:
            result=listing(fixture.app,{'case_id':fixture.cid,'platform':'ozon','store_ref':'ozon-live','market':'RU'})
            self.assertIn('title',result['product']);self.assertIn('image_count',result['product'])
            self.assertIsNone(result['image_binding']);self.assertFalse(result['external_execution_allowed'])
            self.assertEqual(fixture.app.core.invoke('commerce_task_list',{})['tasks'],[])
        finally:fixture.app.agent_runtime.stop();fixture.tearDown()

    def test_saved_listing_image_uses_original_owner_version_and_becomes_stale(self):
        from test_owner_review import OwnerReviewTests
        from generative.reads import listing,revalidate
        fixture=OwnerReviewTests();fixture.setUp()
        try:
            data=listing(fixture.app,fixture.target)
            self.assertGreater(data['image_binding']['count'],0)
            import base64
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')
            with patch('catalog_media.fetch',return_value=png):
                image=fixture.app.invoke('commerce_owner_review_image',{**data['image_binding']['target'],
                    'expected_binding_sha256':data['image_binding']['expected_binding_sha256'],'index':0})
            self.assertTrue(image['content_base64'])
            old=fixture.app.listings.get(**fixture.target);payload=json.loads(json.dumps(old['payload']))
            payload['fields']['title']+=' changed'
            fixture.app.listings.save(**fixture.target,payload=payload,expected_revision=old['revision'],expected_source_sha256=old['source_sha256'])
            with self.assertRaisesRegex(ValueError,'evidence_changed'):revalidate(fixture.app,{'tool':'commerce_listing_get','data':data})
            with self.assertRaisesRegex(ValueError,'binding_changed'):fixture.app.invoke('commerce_owner_review_image',{**data['image_binding']['target'],
                'expected_binding_sha256':data['image_binding']['expected_binding_sha256'],'index':0})
        finally:fixture.app.agent_runtime.stop();fixture.tearDown()


if __name__=='__main__':unittest.main()
