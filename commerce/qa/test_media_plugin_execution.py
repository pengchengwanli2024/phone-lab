"""Isolated synthetic execution journal; no native provider calls or credentials."""
import importlib
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_media_plugin_connections as fixtures


class PluginExecutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PluginConnections();self.fixture.setUp();self.app=self.fixture.app
        self.app.media_plugins=self.fixture.plugins
        self.fixture.bind();self.plan=self.fixture.prepare()
        self.execution=importlib.import_module('media_plugin_execution').MediaPluginExecution(self.app)
    def tearDown(self):self.execution.stop() if hasattr(self,'execution') else None;self.fixture.tearDown()
    def start(self):return self.execution.start(self.plan['id'],self.plan['plan_sha256'],'start')
    def claim(self):
        d=self.start();self.execution.approve(d['id'],self.plan['plan_sha256'],'approve')
        return self.execution.claim(d['id'],'codex','claim')
    def begun(self):
        d=self.claim();self.execution.record_transfer(d['id'],d['claim_token'],self.plan['sources'][0]['asset_id'],{'type':'url','url':'https://assets.lovart.ai/synthetic.png'},'upload')
        packet=self.execution.begin(d['id'],d['claim_token']);return d,packet
    def test_approval_exclusive_token_and_one_time_generation_packet(self):
        d=self.start();self.assertEqual(d['status'],'awaiting_approval');self.assertEqual(self.start()['id'],d['id'])
        with self.assertRaisesRegex(ValueError,'approval'):self.execution.claim(d['id'],'codex','claim')
        c,p=self.begun();self.assertEqual(p['tool_call']['arguments']['ref_images'],['https://assets.lovart.ai/synthetic.png'])
        with self.assertRaisesRegex(ValueError,'already_begun'):self.execution.begin(c['id'],c['claim_token'])
        with self.assertRaisesRegex(ValueError,'claimed'):self.execution.claim(c['id'],'hermes','second')
        with self.app.core.db() as db:raw=db.execute('SELECT document FROM media_plugin_executions').fetchone()[0]
        self.assertNotIn(c['claim_token'],raw);self.assertNotIn('https://',json.dumps(self.execution.get(c['id'])))
    def test_wrong_token_and_untransferred_sources_fail_closed(self):
        c=self.claim()
        with self.assertRaisesRegex(ValueError,'token'):self.execution.begin(c['id'],'forged')
        with self.assertRaisesRegex(ValueError,'transfer'):self.execution.begin(c['id'],c['claim_token'])
    def test_remote_receipt_reconciliation_and_cancel_never_adopts(self):
        c,_=self.begun();self.execution.cancel(c['id'])
        self.assertTrue(any(self.execution._occupies_capacity(d) for d in self.execution.summary(self.plan['request_id'])))
        self.execution.receipt(c['id'],c['claim_token'],{'status':'pending','task_ids':['task-one'],'project_id':'remote-project'},'pending')
        p=self.execution.poll_packet(c['id']);self.assertEqual(p['tool_call']['name'],'lovart.get_task_status')
        self.execution.receipt(c['id'],c['claim_token'],{'status':'completed','task_ids':['task-one'],'project_id':'remote-project','outputs':[{'url':'https://assets.lovart.ai/result.png'}]},'done')
        d=self.execution.get(c['id']);self.assertEqual(d['review_status'],'not_adopted');self.assertFalse(self.execution._occupies_capacity(d))
        self.assertEqual(self.app.media.request_get(self.plan['request_id'])['assets'],[])
    def test_restart_turns_ambiguous_submission_unknown_and_revokes_unbegun_claim(self):
        c,_=self.begun();self.execution.recover();self.assertEqual(self.execution.get(c['id'])['status'],'unknown')
        with self.assertRaisesRegex(ValueError,'already_begun'):self.execution.begin(c['id'],c['claim_token'])
    def test_source_and_account_drift_block_begin(self):
        c=self.claim();self.fixture.bind(expected_revision=1,link_id='link_synthetic_two')
        with self.assertRaisesRegex(ValueError,'connection_changed'):self.execution.begin(c['id'],c['claim_token'])
    def test_strict_receipts_and_remote_ids_cannot_change(self):
        c,_=self.begun()
        with self.assertRaisesRegex(ValueError,'receipt'):self.execution.receipt(c['id'],c['claim_token'],{'status':'completed','unknown':True},'bad')
        self.execution.receipt(c['id'],c['claim_token'],{'status':'pending','task_ids':['one']},'pending')
        with self.assertRaisesRegex(ValueError,'remote_identity'):self.execution.receipt(c['id'],c['claim_token'],{'status':'pending','task_ids':['two']},'pending2')
    def test_completed_provider_report_is_not_verified_media(self):
        c,_=self.begun();self.execution.receipt(c['id'],c['claim_token'],{'status':'completed','task_ids':['one'],'outputs':[{'url':'https://assets.lovart.ai/result.png'}]},'done')
        self.assertEqual(self.execution.get(c['id'])['status'],'retrieving');self.assertFalse(self.execution.get(c['id'])['actual_bytes_verified'])
    def complete(self,c):return self.execution.receipt(c['id'],c['claim_token'],{'status':'completed','task_ids':['one'],'outputs':[{'url':'https://assets.lovart.ai/result.png'}]},'done')
    def png(self):return self.app.creative.asset(self.plan['project_id'],self.plan['sources'][0]['asset_id'])[0].read_bytes()
    def test_actual_png_is_probed_registered_and_attached_for_review(self):
        c,_=self.begun();self.complete(c)
        with patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        d=self.execution.get(c['id']);self.assertEqual(d['status'],'awaiting_review');self.assertTrue(d['actual_bytes_verified'])
        request=self.app.media.request_get(self.plan['request_id']);self.assertEqual(request['status'],'awaiting_review')
        self.assertEqual(len(d['assets']),1);self.assertEqual(d['assets'][0]['id'],request['assets'][0]['id'])
        self.assertEqual(d['assets'][0]['generation_verified'],'actual_media_bytes_and_probe_only')
        self.assertTrue((self.app.state/'plugin-results'/c['id']/'0.png').is_file())
        with self.app.core.db() as db:task=self.app.core.present(db.execute('SELECT * FROM tasks WHERE id=?',(d['task_id'],)).fetchone())
        self.assertEqual(task['status'],'completed');self.assertEqual(task['input']['media_plugin_execution_id'],c['id'])
    def test_empty_and_malformed_bytes_never_report_verified_and_retry_is_download_only(self):
        c,_=self.begun();self.complete(c)
        for raw in (b'',b'not media',b'\x89PNG\r\n\x1a\ninvalid'):
            with patch('media_outputs.request',return_value=raw):self.execution.tick()
            d=self.execution.get(c['id']);self.assertEqual(d['status'],'download_failed');self.assertFalse(d['actual_bytes_verified'])
            self.assertEqual(self.app.media.request_get(self.plan['request_id'])['assets'],[])
            self.execution.retry_download(c['id'])
        with patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        self.assertEqual(self.execution.get(c['id'])['status'],'awaiting_review')
        with self.assertRaisesRegex(ValueError,'already_begun'):self.execution.begin(c['id'],c['claim_token'])
    def test_cancelled_actual_results_are_retained_without_adoption(self):
        c,_=self.begun();self.execution.cancel(c['id']);self.complete(c)
        with patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        d=self.execution.get(c['id']);self.assertEqual(d['status'],'result_held');self.assertTrue(d['actual_bytes_verified']);self.assertEqual(d['review_status'],'not_adopted')
        self.assertEqual(self.app.media.request_get(self.plan['request_id'])['assets'],[])
    def test_source_drift_after_remote_completion_retains_actual_assets(self):
        c,_=self.begun();self.complete(c);raw=self.png()
        self.fixture.bind(expected_revision=1,link_id='link_synthetic_two')
        with patch('media_outputs.request',return_value=raw):self.execution.tick()
        d=self.execution.get(c['id']);self.assertEqual(d['status'],'result_held');self.assertTrue(d['actual_bytes_verified'])
        self.assertEqual(d['error_code'],'media_plugin_connection_changed');self.assertEqual(self.app.media.request_get(self.plan['request_id'])['assets'],[])
    def test_expired_claim_is_revoked_and_forged_receipt_rejected(self):
        c=self.claim();self.execution.tick(at=time.time()+1000)
        newer=self.execution.claim(c['id'],'hermes','second')
        with self.assertRaisesRegex(ValueError,'token'):self.execution.record_transfer(c['id'],c['claim_token'],self.plan['sources'][0]['asset_id'],{'type':'url','url':'https://lovart.ai/old.png'},'old')
        self.assertNotEqual(newer['claim_token'],c['claim_token'])
        self.execution.record_transfer(c['id'],newer['claim_token'],self.plan['sources'][0]['asset_id'],{'type':'url','url':'https://lovart.ai/new.png'},'new');self.execution.begin(c['id'],newer['claim_token'])
        with self.assertRaisesRegex(ValueError,'token'):self.execution.receipt(c['id'],c['claim_token'],{'status':'pending','task_ids':['one']},'old-receipt')
    def test_cancel_before_begin_cannot_authorize_submission(self):
        c=self.claim();self.execution.cancel(c['id'])
        with self.assertRaisesRegex(ValueError,'cancelled'):self.execution.begin(c['id'],c['claim_token'])
        self.assertFalse(self.execution.get(c['id'])['external_generation_submitted'])
    def test_recover_retrieval_keeps_canonical_files_and_reuses_registered_asset(self):
        c,_=self.begun();self.complete(c)
        original=self.app.media.request_attach
        with patch.object(self.app.media,'request_attach',side_effect=ValueError('synthetic_attach_failure')),patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        d=self.execution.get(c['id']);self.assertTrue(d['actual_bytes_verified']);self.assertEqual(d['status'],'result_held')
        # Interrupted after durable registration can resume without moving canonical bytes.
        with self.app.core.atomic():
            raw=self.execution._load(c['id']);raw.update(status='retrieving',actual_bytes_verified=False);self.execution._save(raw)
        self.execution.recover()
        with patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        d2=self.execution.get(c['id']);self.assertEqual(d2['assets'][0]['id'],d['assets'][0]['id']);self.assertEqual(d2['status'],'awaiting_review')
    def test_parallel_claims_are_exclusive_across_instances(self):
        from concurrent.futures import ThreadPoolExecutor
        d=self.start();self.execution.approve(d['id'],self.plan['plan_sha256'],'approve')
        other=type(self.execution)(self.app)
        def claim(pair):
            try:return pair[0].claim(d['id'],pair[1],pair[1])
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(claim,[(self.execution,'codex'),(other,'hermes')]))
        self.assertEqual(sum(r is not None for r in results),1)
    def test_heygen_reauth_and_storyboard_blockers_are_never_cleared(self):
        self.fixture.bind('heygen');request=self.fixture.fixture.request('ugc_video')
        plan=self.app.media_plugins.prepare(request_id=request['id'],expected_revision=self.fixture.fixture.p['revision'],provider='heygen',asset_ids=[self.fixture.fixture.asset['id']],expected_connection_revision=1,idempotency_key='video')
        d=self.execution.start(plan['id'],plan['plan_sha256'],'video-start')
        with self.assertRaisesRegex(ValueError,'requires_attention'):self.execution.approve(d['id'],plan['plan_sha256'],'approve')
        self.fixture.bind('heygen',expected_revision=1,connection_status='available_to_host')
        with self.assertRaisesRegex(ValueError,'connection_changed'):self.execution.approve(d['id'],plan['plan_sha256'],'approve')
    def test_cannot_cancel_already_attached_result_and_mislabel_review_state(self):
        c,_=self.begun();self.complete(c)
        with patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        with self.assertRaisesRegex(ValueError,'not_cancellable'):self.execution.cancel(c['id'])
        self.assertEqual(self.execution.get(c['id'])['status'],'awaiting_review')
    def test_tagged_transfer_shape_and_long_receipt_urls_pass_real_service_validation(self):
        c=self.claim()
        transfer={'execution_id':c['id'],'claim_token':c['claim_token'],'asset_id':self.plan['sources'][0]['asset_id'],
            'remote_reference':{'type':'url','url':'https://assets.lovart.ai/source.png'},'idempotency_key':'transfer'}
        result=self.app.invoke('commerce_media_plugin_execution_record_transfer',transfer)
        self.assertEqual(result['status'],'claimed')
        self.app.invoke('commerce_media_plugin_execution_begin',{'execution_id':c['id'],'claim_token':c['claim_token']})
        long_url='https://assets.lovart.ai/result.png?signature='+'x'*500
        result=self.app.invoke('commerce_media_plugin_execution_receipt',{'execution_id':c['id'],'claim_token':c['claim_token'],
            'receipt':{'status':'completed','outputs':[{'url':long_url}]},'idempotency_key':'receipt'})
        self.assertEqual(result['status'],'retrieving')
    def test_historical_completed_video_receipt_checks_real_mp4_and_never_attaches_single_shot(self):
        import subprocess
        self.fixture.bind('heygen');request=self.fixture.fixture.request('ugc_video')
        plan=self.app.media_plugins.prepare(request_id=request['id'],expected_revision=self.fixture.fixture.p['revision'],provider='heygen',asset_ids=[self.fixture.fixture.asset['id']],expected_connection_revision=1,idempotency_key='shot',shot_index=0)
        d=self.execution.start(plan['id'],plan['plan_sha256'],'shot-start')
        duration=plan['tool_call']['arguments']['duration'];path=Path(self.fixture.fixture.tmp.name)/'synthetic-received-shot.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:size=64x64:rate=1','-t',str(duration),'-c:v','libx264',str(path)],capture_output=True,timeout=15,check=True)
        # Seed only a historical provider completion, without granting a host generation.
        # Live HeyGen approval remains blocked by reauthentication and storyboard.
        with self.app.core.atomic():
            stored=self.execution._load(d['id']);stored.update(status='retrieving',external_generation_submitted=True,provider_status='completed',provider_terminal=True,outputs=[{'url':'https://media.heygen.com/synthetic.mp4'}]);self.execution._save(stored)
        with patch('media_outputs.request',return_value=path.read_bytes()):self.execution.tick()
        result=self.execution.get(d['id']);self.assertTrue(result['actual_bytes_verified']);self.assertEqual(result['status'],'result_held')
        self.assertEqual(result['assets'][0]['kind'],'generated_video');self.assertFalse(result['assets'][0]['complete_request_output'])
        self.assertEqual(result['assets'][0]['shot_index'],0);self.assertEqual(self.app.media.request_get(request['id'])['assets'],[])
    def test_changed_source_bytes_and_wrong_review_hash_reject_execution(self):
        d=self.start()
        with self.assertRaisesRegex(ValueError,'plan_changed'):self.execution.approve(d['id'],'0'*64,'approve')
        c=self.claim();path=self.app.creative.asset(self.plan['project_id'],self.plan['sources'][0]['asset_id'])[0]
        path.write_bytes(b'synthetic altered source')
        with self.assertRaisesRegex(ValueError,'asset_changed'):self.execution.begin(c['id'],c['claim_token'])
        self.assertFalse(self.execution.get(c['id'])['external_generation_submitted'])
    def test_transfer_accepts_only_tagged_lovart_https_reference_and_pinned_source(self):
        c=self.claim();asset=self.plan['sources'][0]['asset_id']
        for ref in ('https://lovart.ai/a',{'type':'url','url':'https://elsewhere.example/a'},
                {'type':'url','url':'http://lovart.ai/a'},{'type':'url','url':'https://@lovart.ai/a'},
                {'type':'asset_id','asset_id':'synthetic-id'},{'type':'url','url':'https://lovart.ai/a','extra':True}):
            with self.subTest(reference=ref),self.assertRaisesRegex(ValueError,'remote_reference'):self.execution.record_transfer(c['id'],c['claim_token'],asset,ref,'invalid')
        with self.assertRaisesRegex(ValueError,'source_not_pinned'):self.execution.record_transfer(c['id'],c['claim_token'],'other-source',{'type':'url','url':'https://lovart.ai/a'},'wrong-source')
    def test_terminal_receipt_cannot_regress_and_public_views_never_expose_remote_urls_or_token(self):
        c,_=self.begun();self.complete(c)
        with self.assertRaisesRegex(ValueError,'terminal_receipt'):self.execution.receipt(c['id'],c['claim_token'],{'status':'pending','task_ids':['one']},'regress')
        public=json.dumps(self.execution.get(c['id']))+json.dumps(self.execution.list(request_id=self.plan['request_id']))
        self.assertNotIn('https://',public);self.assertNotIn(c['claim_token'],public);self.assertNotIn('link_synthetic_one',public)
        self.assertTrue(self.execution.get(c['id'])['provider_reported_complete']);self.assertFalse(self.execution.get(c['id'])['actual_bytes_verified'])
    def test_result_folder_symlink_is_rejected_without_writing_target(self):
        c,_=self.begun();self.complete(c)
        root=self.app.state/'plugin-results';root.mkdir(mode=0o700);outside=self.app.state/'synthetic-outside';outside.mkdir();(root/c['id']).symlink_to(outside,target_is_directory=True)
        with patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        self.assertEqual(self.execution.get(c['id'])['status'],'download_failed');self.assertEqual(list(outside.iterdir()),[])
    def test_background_tick_survives_execution_whose_project_scope_is_unreadable(self):
        # A case owned by a previous store connection must not fail every background tick.
        c=self.claim()
        with patch.object(self.app.media,'project',side_effect=ValueError('organization_case_not_found')):
            self.assertEqual(self.execution.tick(at=time.time()+1000),[])
            with self.assertRaisesRegex(ValueError,'organization_case_not_found'):self.execution.get(c['id'])
        self.assertEqual(self.execution.get(c['id'])['status'],'awaiting_host')
    def test_terminal_completed_replay_preserves_attached_review_and_never_redownloads(self):
        c,_=self.begun();self.complete(c)
        with patch('media_outputs.request',return_value=self.png()):self.execution.tick()
        before=self.execution.get(c['id']);self.assertEqual(before['status'],'awaiting_review')
        receipt={'status':'completed','task_ids':['one'],'project_id':'late-project','outputs':[{'url':'https://assets.lovart.ai/result.png'}]}
        replay=self.execution.receipt(c['id'],c['claim_token'],receipt,'same-truth-new-key')
        self.assertEqual(replay['status'],'awaiting_review');self.assertEqual(replay['assets'],before['assets'])
        with patch('media_outputs.request',side_effect=AssertionError('Verified result must never be redownloaded')) as network:self.execution.tick()
        network.assert_not_called()
        after=self.execution.get(c['id']);self.assertEqual(after['result_sha256'],before['result_sha256']);self.assertTrue(after['actual_bytes_verified'])
        self.assertEqual(self.execution.poll_packet(c['id'])['tool_call']['arguments']['project_id'],'late-project')
        task=self.app.core.invoke('commerce_task_get',{'task_id':after['task_id']});self.assertEqual(task['status'],'completed')
        self.assertEqual(self.app.media.request_get(self.plan['request_id'])['assets'][0]['id'],before['assets'][0]['id'])
    def test_safe_historical_video_shot_is_reviewable_without_attaching_full_request(self):
        import subprocess
        self.fixture.bind('heygen',connection_status='available_to_host');request=self.fixture.fixture.request('ugc_video')
        plan=self.app.media_plugins.prepare(request_id=request['id'],expected_revision=self.fixture.fixture.p['revision'],provider='heygen',asset_ids=[self.fixture.fixture.asset['id']],expected_connection_revision=1,idempotency_key='reviewable-shot',shot_index=0)
        d=self.execution.start(plan['id'],plan['plan_sha256'],'reviewable-shot-start')
        duration=plan['tool_call']['arguments']['duration'];path=Path(self.fixture.fixture.tmp.name)/'synthetic-approved-shot.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:size=64x64:rate=1','-t',str(duration),'-c:v','libx264',str(path)],capture_output=True,timeout=15,check=True)
        # Model an already-reviewed historical storyboard solely for receipt adoption.
        # Real product, source and account guards remain active; no host grant is made.
        with self.app.core.atomic() as db:
            plan['blockers']=[];db.execute('UPDATE media_plugin_plans SET document=? WHERE id=?',(json.dumps(plan),plan['id']))
            stored=self.execution._load(d['id']);stored.update(status='retrieving',external_generation_submitted=True,provider_status='completed',provider_terminal=True,outputs=[{'url':'https://media.heygen.com/synthetic-reviewed.mp4'}]);self.execution._save(stored)
        with patch('media_outputs.request',return_value=path.read_bytes()):self.execution.tick()
        result=self.execution.get(d['id']);self.assertEqual(result['status'],'awaiting_review');self.assertEqual(result['review_status'],'awaiting_review')
        self.assertTrue(result['actual_bytes_verified']);self.assertFalse(result['assets'][0]['complete_request_output'])
        self.assertEqual(result['assets'][0]['kind'],'generated_video');self.assertEqual(result['assets'][0]['shot_index'],0)
        self.assertNotIn('attached_request_id',result);self.assertEqual(self.app.media.request_get(request['id'])['assets'],[])
