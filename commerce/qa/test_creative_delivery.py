"""Opt-in sample approval is bound to exact local inputs and output bytes."""
import copy
import json
import time
import unittest
from unittest.mock import patch
import test_product_media as fixtures


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProductMediaTests();self.fixture.setUp()
        self.app=self.fixture.app;self.p=self.fixture.direction();self.pid=self.p['id']
        original=self.app.media.request_create(self.pid,self.p['revision'],'showcase_video','new-base')
        edit={'aspect_ratio':'16:9','keep_source_audio':False,'shots':[{'source_index':i,'source_start_ms':0,'duration_ms':500,'caption':'合成样片 '+str(i)}for i in range(5)]}
        self.base=self.app.media.request_edit(request_id=original['id'],expected_request_sha256=original['request_sha256'],editing=edit,idempotency_key='new-edit')
        self.ids=[self.fixture.asset['id']]*5
        self.requirements={'source_policy':'allow_stills','audio_policy':'no_audio','allow_looping':False,'sample_duration_ms':1000}

    def tearDown(self):
        self.app.autonomy.stop();self.fixture.tearDown()

    def prepare(self,key='new-commitment',**kw):
        return self.app.invoke('commerce_media_delivery_prepare',{'request_id':self.base['id'],'expected_request_sha256':self.base['request_sha256'],'asset_ids':self.ids,'requirements':self.requirements,'idempotency_key':key,**kw})

    def render(self,request):
        ids=request['delivery']['asset_ids']
        self.app.media.request_execute(request['id'],self.p['revision'],ids)
        end=time.monotonic()+35
        while time.monotonic()<end:
            d=self.app.media.request_get(request['id'])
            if d['status']not in ('queued','running'):break
            time.sleep(.05)
        self.assertEqual(d['status'],'awaiting_review',d)
        return d

    def approve(self,sample,**kw):
        return self.app.media.request_review(sample['id'],sample['result_sha256'],'approved','合成验收已观看样片并核对要求',sample_review={'watched':True,'matches_commitment':True,'commitment_sha256':sample['delivery']['commitment_sha256']},**kw)

    def test_prepare_pins_two_fresh_versions_without_jobs_and_is_idempotent(self):
        pair=self.prepare();full=pair['full'];sample=pair['sample']
        self.assertNotEqual(full['id'],self.base['id']);self.assertNotEqual(full['id'],sample['id'])
        self.assertEqual(sample['spec']['duration_ms'],1000)
        self.assertEqual(sample['spec']['editing']['shots'],full['spec']['editing']['shots'][:2])
        self.assertEqual(full['delivery']['sample_request_id'],sample['id'])
        self.assertEqual(full['delivery']['gate'],'sample_required')
        self.assertIsNone(full['job_id']);self.assertIsNone(sample['job_id'])
        self.assertEqual(self.prepare()['full']['id'],full['id'])
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):
            self.prepare(requirements={**self.requirements,'sample_duration_ms':1500})
        self.assertEqual(self.app.media.request_get(self.base['id'])['job_id'],None)

    def test_full_is_blocked_until_exact_sample_watched_and_approved_then_still_needs_review(self):
        pair=self.prepare();full=pair['full'];sample=pair['sample']
        with self.assertRaisesRegex(ValueError,'sample_approval_required'):
            self.app.media.request_execute(full['id'],self.p['revision'],self.ids)
        self.assertIsNone(self.app.media.request_get(full['id'])['job_id'])
        sample=self.render(sample)
        with self.assertRaisesRegex(ValueError,'sample_review_required'):
            self.app.media.request_review(sample['id'],sample['result_sha256'],'approved','no acknowledgement')
        self.approve(sample)
        self.assertEqual(self.app.media.request_get(full['id'])['delivery']['gate'],'ready')
        result=self.render(full)
        self.assertEqual(result['quality_report']['delivery_commitment_check']['status'],'passed')
        self.assertIsNone(result['review']);self.assertEqual(result['status'],'awaiting_review')
        self.assertIn('delivery_commitment',result['spec'])

    def test_selection_manual_attach_and_edit_cannot_bypass_frozen_requirements(self):
        pair=self.prepare();sample=pair['sample']
        with self.assertRaisesRegex(ValueError,'delivery_selection_changed'):
            self.app.media.request_execute(sample['id'],self.p['revision'],self.ids[:2],audio_asset_id=self.fixture.asset['id'])
        with self.assertRaisesRegex(ValueError,'delivery_local_render_required'):
            self.app.media.request_attach(sample['id'],self.p['revision'],[self.fixture.asset['id']])
        with self.assertRaisesRegex(ValueError,'delivery_immutable'):
            self.app.media.request_edit(request_id=sample['id'],expected_request_sha256=sample['request_sha256'],editing=sample['spec']['editing'],idempotency_key='forbidden')

    def test_video_only_and_no_audio_constraints_reject_before_creating_versions(self):
        with self.assertRaisesRegex(ValueError,'delivery_video_required'):
            self.prepare(requirements={**self.requirements,'source_policy':'video_only'})
        with self.assertRaisesRegex(ValueError,'delivery_audio_required'):
            self.prepare(requirements={**self.requirements,'audio_policy':'audible_required'})
        with self.assertRaisesRegex(ValueError,'delivery_requirements_invalid'):
            self.prepare(requirements={**self.requirements,'allow_looping':1})

    def test_rejection_does_not_unlock_full_and_cannot_be_overwritten(self):
        pair=self.prepare();sample=self.render(pair['sample'])
        self.app.media.request_review(sample['id'],sample['result_sha256'],'rejected','合成验收退回')
        self.assertEqual(self.app.media.request_get(pair['full']['id'])['delivery']['gate'],'sample_rejected')
        with self.assertRaisesRegex(ValueError,'review_record_immutable'):self.approve(sample)

    def test_renderer_or_sample_bytes_change_invalidates_approval(self):
        pair=self.prepare();sample=self.render(pair['sample']);self.approve(sample)
        with patch('creative_delivery.renderer_sha256',return_value='0'*64):
            with self.assertRaisesRegex(ValueError,'delivery_renderer_changed'):
                self.app.media.request_execute(pair['full']['id'],self.p['revision'],self.ids)
        self.app.creative.asset(self.pid,sample['assets'][0]['id'])[0].write_bytes(b'changed sample')
        with self.assertRaisesRegex(ValueError,'asset_changed'):
            self.app.media.request_execute(pair['full']['id'],self.p['revision'],self.ids)

    def test_uncontracted_request_keeps_existing_edit_and_execution_behavior(self):
        result=self.render({**self.base,'delivery':{'asset_ids':self.ids}})
        self.assertNotIn('delivery_commitment_check',result['quality_report'])
        self.assertNotIn('delivery',self.app.media.request_get(self.base['id']))

    def test_unedited_plan_sample_preserves_prefix_captions_without_changing_root(self):
        root=self.app.media.request_create(self.pid,self.p['revision'],'showcase_video','new-unedited')
        pair=self.prepare('unedited-family',request_id=root['id'],expected_request_sha256=root['request_sha256'])
        self.assertEqual(pair['sample']['spec']['delivery_captions'],pair['full']['spec']['delivery_captions'][:1])
        self.assertNotIn('delivery_commitment',self.app.media.request_get(root['id'])['spec'])
        self.assertEqual(pair['full']['spec']['duration_ms'],root['spec']['duration_ms'])

    def test_inaudible_or_unavailable_observation_fails_required_audio(self):
        import creative_delivery as delivery
        c={'requirements':{**self.requirements,'audio_policy':'audible_required'},'sha256':'a'*64}
        spec={'delivery_commitment':c,'duration_ms':2500,'width':1280,'height':720,'delivery_role':'full'}
        media={'duration_seconds':2.5,'width':1280,'height':720,'has_audio':True,'format':'mov,mp4'}
        for observation in [{'status':'unavailable'},{'status':'completed','audio':{'status':'analyzed','peak_dbfs':-91}}]:
            self.assertEqual(delivery.output_check(spec,media,observation)['status'],'failed')
        self.assertEqual(delivery.output_check(spec,media,{'status':'completed','audio':{'status':'analyzed','peak_dbfs':-12}})['status'],'passed')
