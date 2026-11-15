"""Synthetic bindings: no remote upload, account write or paid generation."""
import importlib
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_product_media as media


class PluginConnections(unittest.TestCase):
    def setUp(self):
        self.fixture=media.ProductMediaTests();self.fixture.setUp();self.app=self.fixture.app
        try:module=importlib.import_module('media_plugin_connections')
        except ImportError:self.fixture.tearDown();self.fail('Private plugin binding and review plan service is missing')
        self.plugins=module.MediaPluginConnections(self.app)

    def tearDown(self):
        self.app.autonomy.stop();self.fixture.tearDown()

    def bind(self,provider='lovart',**changes):
        return self.plugins.configure({'provider':provider,'expected_revision':0,'account_label':'Synthetic account',
            'link_id':'link_synthetic_one' if provider=='lovart' else '', 'connection_status':'available_to_host' if provider=='lovart' else 'needs_reauthentication',
            'observed_at':time.time(),'model':'synthetic-image' if provider=='lovart' else 'heygen-video-1','model_parameters':{},**changes})

    def prepare(self,**changes):
        request=self.fixture.request()
        return self.plugins.prepare(request_id=request['id'],expected_revision=self.fixture.p['revision'],provider='lovart',
            asset_ids=[self.fixture.asset['id']],expected_connection_revision=1,idempotency_key='same-plan',**changes)

    def test_private_binding_survives_reopen_and_never_claims_backend_authorization(self):
        bound=self.bind();self.assertEqual(bound['account_label'],'Synthetic account')
        self.assertEqual(bound['account_suffix'],'…c_one');self.assertNotIn('link_synthetic_one',json.dumps(self.plugins.catalog()))
        other=type(self.plugins)(self.app);self.assertEqual(other.catalog()['connections'][0]['revision'],1)
        self.assertFalse(bound['backend_autonomous']);self.assertFalse(bound['generation_verified'])
        path=self.app.state/'media-plugin-routing.json';self.assertEqual(path.stat().st_mode&0o777,0o600)
        with self.assertRaisesRegex(ValueError,'revision_conflict'):self.bind()

    def test_plan_pins_real_product_inputs_and_selected_account_without_submitting(self):
        self.bind();plan=self.prepare()
        self.assertEqual(plan['stage'],'awaiting_host_review');self.assertFalse(plan['external_generation_submitted'])
        self.assertEqual(plan['tool_call']['arguments']['link_id'],'link_synthetic_one')
        self.assertEqual(plan['tool_call']['name'],'lovart.generate_image');self.assertNotIn('ref_images',plan['tool_call']['arguments'])
        self.assertIn('500',plan['tool_call']['arguments']['prompt']);self.assertEqual(plan['sources'][0]['sha256'],self.fixture.asset['sha256'])
        self.assertEqual(plan['sources'][0]['read']['name'],'commerce_creative_asset_read')
        self.assertEqual(plan['transfer']['name'],'lovart.upload_asset');self.assertEqual(plan['generation_count'],1)
        self.assertEqual(self.plugins.get(plan['id'])['plan_sha256'],plan['plan_sha256'])
        self.assertEqual(self.plugins.prepare(request_id=plan['request_id'],expected_revision=self.fixture.p['revision'],provider='lovart',asset_ids=[self.fixture.asset['id']],expected_connection_revision=1,idempotency_key='same-plan')['id'],plan['id'])
        self.assertTrue(self.plugins.validate(plan['id'],plan['plan_sha256'])['current'])
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM media_provider_jobs').fetchone()[0],0)

    def test_rebinding_account_invalidates_existing_plan_and_cannot_silently_reuse_it(self):
        self.bind();plan=self.prepare();self.bind(expected_revision=1,link_id='link_synthetic_two')
        self.assertTrue(self.plugins.get(plan['id'])['stale'])
        with self.assertRaisesRegex(ValueError,'connection_changed'):self.plugins.validate(plan['id'],plan['plan_sha256'])

    def test_changed_product_blocks_plan_execution_validation(self):
        self.bind();plan=self.prepare();p=self.app.creative.get(self.fixture.pid);brief=p['brief'];brief['target']['country']='synthetic changed'
        self.app.creative.save(p['id'],brief,p['revision'],allow_direction=True)
        with self.assertRaisesRegex(ValueError,'creative_request_stale'):self.plugins.validate(plan['id'],plan['plan_sha256'])

    def test_reauthentication_is_a_blocker_but_not_a_fake_generation_failure(self):
        self.bind('heygen');request=self.fixture.request('ugc_video')
        plan=self.plugins.prepare(request_id=request['id'],expected_revision=self.fixture.p['revision'],provider='heygen',asset_ids=[self.fixture.asset['id']],expected_connection_revision=1,idempotency_key='video-plan')
        self.assertEqual(plan['tool_call']['name'],'heygen.reference_to_video')
        self.assertIn('needs_reauthentication',plan['blockers']);self.assertFalse(plan['external_generation_submitted'])
        self.assertEqual(plan['tool_call']['arguments']['duration'],30);self.assertNotIn('referenceImages',plan['tool_call']['arguments'])
        self.assertIn('person_script_storyboard_approval_required',plan['blockers'])

    def test_unbound_or_expired_connection_cannot_be_presented_as_ready(self):
        self.assertEqual(self.plugins.catalog()['connections'][0]['status'],'unbound')
        with self.assertRaisesRegex(ValueError,'unknown_field'):self.bind(api_key='synthetic-not-accepted')
        self.bind(observed_at=time.time()-90000)
        self.assertEqual(self.plugins.catalog()['connections'][0]['status'],'recheck_required')

    def test_completed_request_cannot_be_sent_for_another_plugin_generation(self):
        self.bind();plan=self.prepare()
        self.app.media.request_attach(plan['request_id'],self.fixture.p['revision'],[self.fixture.asset['id']])
        with self.assertRaisesRegex(ValueError,'creative_result_immutable'):
            self.plugins.validate(plan['id'],plan['plan_sha256'])

    def test_remote_submission_requires_reconciliation_before_plugin_continuation(self):
        self.bind();plan=self.prepare()
        with self.app.core.db() as db:
            receipt={'id':'synthetic-unknown','request_id':plan['request_id'],'status':'unknown','stage':'unknown','external_generation_submitted':True}
            db.execute('INSERT INTO media_provider_jobs VALUES(?,?,?,?,?)',(receipt['id'],'synthetic-unknown',plan['request_id'],plan['project_id'],json.dumps(receipt)))
        with self.assertRaisesRegex(ValueError,'already_submitted'):
            self.plugins.validate(plan['id'],plan['plan_sha256'])

    def test_local_cancellation_stays_blocked_until_remote_terminality_is_confirmed(self):
        self.bind();plan=self.prepare()
        receipt={'id':'synthetic-cancelled','request_id':plan['request_id'],'status':'cancelled','stage':'cancelled_locally',
                 'external_generation_submitted':True,'provider_status':'running','provider_terminal':False,'remote_task_id':'synthetic-remote'}
        with self.app.core.db() as db:
            db.execute('INSERT INTO media_provider_jobs VALUES(?,?,?,?,?)',(receipt['id'],'synthetic-cancelled',plan['request_id'],plan['project_id'],json.dumps(receipt)))
        with self.assertRaisesRegex(ValueError,'already_submitted'):
            self.plugins.validate(plan['id'],plan['plan_sha256'])
        receipt.update(provider_status='succeeded',provider_terminal=True)
        with self.app.core.db() as db:db.execute('UPDATE media_provider_jobs SET document=? WHERE id=?',(json.dumps(receipt),receipt['id']))
        self.assertTrue(self.plugins.validate(plan['id'],plan['plan_sha256'])['current'])


if __name__=='__main__':unittest.main()
