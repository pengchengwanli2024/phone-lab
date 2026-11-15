"""Durable media handoff: one approved submit, then poll a pinned job."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_extension_runtime import RuntimeCase

class Media:
    def request_get(self,ident):return {'id':ident,'project_id':'project-fixture','status':'ready','stale':False}
    def request_execute(self,**args):return {'id':args['request_id'],'project_id':'project-fixture','job_id':'local-job-fixture','status':'queued','assets':[]}
    def project(self,ident):return {'id':ident,'brief':{'product_binding':{'case_id':'case-fixture'}}}

class Providers:
    def __init__(self):self.submits=0;self.status='running';self.gets=0
    def generate(self,**args):self.submits+=1;return {'id':'job-fixture','request_id':args['request_id'],'status':'queued','assets':[]}
    def get(self,job_id):self.gets+=1;return {'id':job_id,'request_id':'request-fixture','status':self.status,'assets':[{'id':'asset-fixture'}] if self.status=='awaiting_review' else []}
    def catalog(self):return {'profiles':[]}

class MediaRuntime(RuntimeCase):
    def setUp(self):super().setUp();self.service.media=Media();self.service.media_providers=Providers()
    def test_readiness_builtin_is_small_read_only_and_checks_project_and_case(self):
        readiness={'project_id':'project-fixture','plugin_inputs_ready':True,'formats':{},'generation_authorized':False}
        from unittest.mock import patch
        with patch.object(self.service,'invoke',return_value=readiness) as invoke:
            ext=self.save(spec={'steps':[{'id':'readiness','uses':{'builtin':'commerce_media_readiness'},'input':{'project_id':{'$ref':'scope.project_id'}}}],'output':{'$ref':'steps.readiness'}})
            tested=self.call('test',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},idempotency_key='readiness-test')
            self.assertEqual(self.drain(tested)['status'],'succeeded')
            ext=self.call('enable',extension_id=ext['id'],expected_version=ext['version'],enabled=True)
            self.service.calls.clear()
            good=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},budget={'max_output_bytes':1000,'allow_model_calls':False},idempotency_key='small-readiness')
            self.assertEqual(self.drain(good)['output'],readiness)
            invoke.reset_mock()
            bad=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'another'},idempotency_key='wrong-case-readiness')
            self.assertEqual(self.drain(bad)['error'],'extension_scope_mismatch');invoke.assert_not_called()
        self.assertEqual(self.service.media_providers.submits,0)
    def test_image_plan_options_reach_scoped_request_creation_after_approval(self):
        options={'profile_id':'ozon_ru','set_size':6,'label':'刷头细节','focus':'原图可见的绿色刷毛'}
        ext=self.ready(spec={'steps':[{'id':'plan','uses':{'builtin':'commerce_media_request_create'},'input':{'project_id':'project-fixture','expected_revision':'1','kind':'product_detail','image_options':options}}],'output':{'$ref':'steps.plan'}})
        run=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},idempotency_key='image-plan')
        pending=self.drain(run);self.assertEqual(pending['status'],'awaiting_approval');a=pending['approval']
        self.assertEqual(self.service.calls,[])
        self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve')
        from unittest.mock import patch
        with patch.object(self.service,'invoke',return_value={'id':'image-request','spec':{'image_options':options}}) as invoke:
            result=self.drain(run)
        self.assertEqual(result['status'],'succeeded');invoke.assert_called_once()
        self.assertEqual(invoke.call_args.args[1]['image_options'],options)
        self.assertEqual(self.service.media_providers.submits,0)
        wrong=self.call('run',extension_id=ext['id'],scope={'project_id':'other'},idempotency_key='wrong-plan')
        self.assertEqual(self.drain(wrong)['error'],'extension_scope_mismatch')
    def media_skill(self):
        return self.ready(spec={'steps':[{'id':'generate','uses':{'builtin':'commerce_media_provider_generate'},'input':{'request_id':'request-fixture','profile_id':'profile-fixture','expected_profile_revision':'1','asset_ids':['input-fixture'],'idempotency_key':'runtime-owned'}}],'output':{'$ref':'steps.generate'}})
    def test_media_needs_approval_then_checkpoints_polls_without_resubmit(self):
        ext=self.media_skill();self.assertEqual(self.service.media_providers.submits,0)
        run=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},idempotency_key='media')
        pending=self.drain(run);self.assertEqual(pending['status'],'awaiting_approval');approval=pending['approval']
        self.call('run_approve',run_id=run['id'],step_id=approval['step_id'],input_sha256=approval['input_sha256'],decision='approve')
        for _ in range(30):
            self.app.tick()
            import time;time.sleep(.01)
            if self.service.media_providers.submits:break
        self.assertEqual(self.service.media_providers.submits,1)
        self.service.media_providers.status='awaiting_review';result=self.drain(run)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['output']['id'],'job-fixture');self.assertEqual(self.service.media_providers.submits,1);self.assertTrue(result['output']['assets'])
    def test_media_scope_and_declared_effect_cannot_be_downgraded(self):
        with self.assertRaisesRegex(ValueError,'effect_mismatch'):self.ready(kind='plugin',spec={'transport':'builtin','tool':'commerce_media_provider_generate','effect':'read'})
        ext=self.media_skill();run=self.call('run',extension_id=ext['id'],scope={'project_id':'wrong'},idempotency_key='wrong-media')
        self.assertEqual(self.drain(run)['error'],'extension_scope_mismatch');self.assertEqual(self.service.media_providers.submits,0)

    def test_media_graph_test_does_not_evaluate_missing_real_asset_mapping(self):
        ext=self.call('save',definition={'kind':'workflow','name':'Video graph','output_schema':{'type':'object','properties':{'assets':{'type':'array'}},'required':['assets']},'spec':{'steps':[{'id':'generate','uses':{'builtin':'commerce_media_provider_generate'},'input':{'request_id':'request-fixture','profile_id':'profile-fixture','expected_profile_revision':'1','asset_ids':['source']}},{'id':'assemble','uses':{'builtin':'commerce_media_request_execute'},'input':{'request_id':'request-fixture','expected_revision':'1','asset_ids':{'$ref':'steps.generate.assets'}}}],'output':{'$ref':'steps.assemble'}}})
        result=self.drain(self.call('test',extension_id=ext['id'],idempotency_key='graph-structure'))
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['output']['status'],'validation_only');self.assertEqual(self.service.media_providers.submits,0)
    def test_local_render_has_same_approval_scope_and_pinned_job_polling(self):
        ext=self.ready(spec={'steps':[{'id':'assemble','uses':{'builtin':'commerce_media_request_execute'},'input':{'request_id':'request-fixture','expected_revision':'1','asset_ids':['shot-a','shot-b']}}],'output':{'$ref':'steps.assemble'}})
        run=self.call('run',extension_id=ext['id'],scope={'project_id':'project-fixture','case_id':'case-fixture'},idempotency_key='assemble')
        pending=self.drain(run);self.assertEqual(pending['status'],'awaiting_approval');a=pending['approval']
        self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve')
        from unittest.mock import patch
        queued={'id':'request-fixture','project_id':'project-fixture','job_id':'local-job-fixture','status':'queued','assets':[]}
        with patch.object(self.service,'invoke',return_value=queued) as invoke:
            self.app._process(run['id'])
            self.assertEqual(invoke.call_count,1)
            finished={**queued,'status':'awaiting_review','assets':[{'id':'assembled-video'}]}
            with patch.object(self.service.media,'request_get',return_value=finished):result=self.drain(run)
            self.assertEqual(invoke.call_count,1)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['output']['job_id'],'local-job-fixture')

if __name__=='__main__':unittest.main()
