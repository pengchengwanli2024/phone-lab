"""Parent cancellation owns child jobs, including the generate/associate race."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_extension_runtime import RuntimeCase
from test_extension_runtime_agents import Models
from test_extension_runtime_media import Media,Providers

class OwnedProviders(Providers):
    def __init__(self):super().__init__();self.cancelled=[];self.billed=0;self.status='queued';self.owner=None
    def generate(self,**args):self.owner=args.get('owner_run_id');return super().generate(**args)
    def cancel(self,job_id):
        self.cancelled.append(job_id);self.status='cancelled'
        return {'id':job_id,'status':'cancelled','cancel_scope':'local_result_adoption','remote_cancel_status':'not_submitted'}
    def tick(self):
        if self.status=='queued':self.billed+=1;self.status='running'

class ChildCancellation(RuntimeCase):
    def setUp(self):super().setUp();self.service.media=Media();self.service.media_providers=OwnedProviders()
    def skill(self):return self.ready(spec={'steps':[{'id':'generate','uses':{'builtin':'commerce_media_provider_generate'},'input':{'request_id':'request-fixture','profile_id':'profile-fixture','expected_profile_revision':'1','asset_ids':['source']}}]})
    def queued_child(self,ext,key='owned'):
        run=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},idempotency_key=key)
        pending=self.drain(run);a=pending['approval'];self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve');self.app._process(run['id']);return run
    def test_cancel_parent_cancels_queued_owned_job_before_provider_tick(self):
        ext=self.skill();run=self.queued_child(ext);result=self.call('run_cancel',run_id=run['id']);self.service.media_providers.tick()
        self.assertEqual(self.service.media_providers.billed,0);self.assertEqual(self.service.media_providers.cancelled,['job-fixture']);self.assertEqual(result['status'],'cancelled');self.assertEqual(result['owned_job_cancellations'][0]['receipt']['remote_cancel_status'],'not_submitted')
    def test_version_revocation_cancels_child_before_future_billing(self):
        ext=self.skill();run=self.queued_child(ext);self.call('save',definition={**ext['definition'],'name':'Revised'},expected_version=ext['version']);self.service.media_providers.tick()
        self.assertEqual(self.service.media_providers.billed,0);self.assertEqual(self.call('run_get',run_id=run['id'])['status'],'cancelled')
    def test_schedule_revocation_cancels_owned_child(self):
        ext=self.skill();plan=self.call('schedule_save',schedule={'extension_id':ext['id'],'trigger':'manual','scope':{'project_id':'project-fixture','case_id':'case-fixture'}});plan=self.call('schedule_enable',schedule_id=plan['id'],expected_revision=plan['revision'],enabled=True)
        run=self.call('schedule_run',schedule_id=plan['id'],expected_revision=plan['revision'],idempotency_key='manual-child');pending=self.drain(run);a=pending['approval'];self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve');self.app._process(run['id'])
        self.call('schedule_enable',schedule_id=plan['id'],expected_revision=plan['revision'],enabled=False);self.service.media_providers.tick();self.assertEqual(self.service.media_providers.billed,0)
    def test_cancel_between_generate_and_association_does_not_lose_child(self):
        ext=self.skill();run=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},idempotency_key='association-race');pending=self.drain(run);a=pending['approval'];self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve')
        original=self.service.media_providers.generate
        def generate(**args):
            value=original(**args);self.call('run_cancel',run_id=run['id']);return value
        with patch.object(self.service.media_providers,'generate',side_effect=generate):self.app._process(run['id'])
        self.service.media_providers.tick();result=self.call('run_get',run_id=run['id'])
        self.assertEqual(self.service.media_providers.owner,run['id']);self.assertEqual(self.service.media_providers.billed,0);self.assertEqual(result['media_jobs']['root.generate']['id'],'job-fixture');self.assertEqual(self.service.media_providers.cancelled,['job-fixture'])
    def test_cancel_outbox_survives_recovery_before_queued_child_can_submit(self):
        ext=self.skill();run=self.queued_child(ext)
        with patch.object(self.app,'_drain_owned_cancels'):self.call('run_cancel',run_id=run['id'])
        self.assertEqual(self.service.media_providers.cancelled,[])
        self.app.recover();self.service.media_providers.tick()
        self.assertEqual(self.service.media_providers.cancelled,['job-fixture']);self.assertEqual(self.service.media_providers.billed,0)
    def test_cancel_local_render_uses_owned_creative_checkpoint(self):
        ext=self.ready(spec={'steps':[{'id':'render','uses':{'builtin':'commerce_media_request_execute'},'input':{'request_id':'request-fixture','expected_revision':'1','asset_ids':['shot']}}]})
        run=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},idempotency_key='local-cancel');pending=self.drain(run);a=pending['approval'];self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve')
        queued={'id':'request-fixture','job_id':'local-owned-job','project_id':'project-fixture','status':'queued','assets':[]}
        with patch.object(self.service,'invoke',return_value=queued):self.app._process(run['id'])
        class Creative:
            def invoke(self,name,args):
                if name!='commerce_creative_job_cancel' or args!={'job_id':'local-owned-job'}:raise ValueError('wrong_owned_job')
                return {'status':'queued','cancel_requested':True}
        self.service.creative=Creative();result=self.call('run_cancel',run_id=run['id'])
        self.assertEqual(result['owned_job_cancellations'][0]['receipt']['cancel_scope'],'local_checkpoint');self.assertTrue(result['owned_job_cancellations'][0]['receipt']['cancel_requested']);self.assertEqual(self.service.media_providers.cancelled,[])
    def test_pure_database_owner_guard_rejects_cancelled_run(self):
        from extension_runtime import guard_media_owner
        ext=self.skill();run=self.queued_child(ext);self.call('run_cancel',run_id=run['id'])
        with self.service.core.db() as db:
            with self.assertRaisesRegex(ValueError,'owner'):guard_media_owner(db,run['id'],'job-fixture')

class ModelCancellation(RuntimeCase):
    def setUp(self):super().setUp();self.service.models=Models()
    def test_inflight_model_cancel_and_definition_revoke_are_unknown(self):
        for action in ('run_cancel','enable'):
            ext=self.ready(kind='agent',spec={'instructions':'Synthetic only.','tools':[]});run=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True},idempotency_key='model-'+action)
            def model(*args):
                if action=='run_cancel':self.call('run_cancel',run_id=run['id'])
                else:self.call('enable',extension_id=ext['id'],expected_version=ext['version'],enabled=False)
                return {'action':'finish','output':{'late':True}}
            with patch.object(self.app,'_model',side_effect=model):self.app._process(run['id'])
            result=self.call('run_get',run_id=run['id']);self.assertEqual(result['status'],'unknown');self.assertEqual(result['usage']['model_calls'],1)

if __name__=='__main__':unittest.main()
