"""Shared task and alternate-provider boundaries use isolated synthetic state."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_media_plugin_execution as fixtures
from capability_lifecycle import CapabilityLifecycle
from media_providers.adapters import GENERIC


class PluginExecutionSeams(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PluginExecutionTests();self.fixture.setUp()
        self.app=self.fixture.app;self.execution=self.fixture.execution
        self.app.media_plugin_execution=self.execution

    def tearDown(self):self.fixture.tearDown()

    def profile(self):
        p=self.app.media_providers.configure({'label':'Synthetic boundary','provider':'local','adapter':'generic_json_async',
            'base_url':'http://127.0.0.1:9','model':'synthetic-image','media_kind':'image','enabled':True,
            'capabilities':{'image_input':True},'protocol':GENERIC})
        with patch('media_providers.adapters.probe',return_value='passed'):
            self.app.media_providers.test_profile(p['id'],p['revision'])
        return p

    def generate(self,p):
        return self.app.media_providers.generate(self.fixture.plan['request_id'],p['id'],p['revision'],
            [self.fixture.plan['sources'][0]['asset_id']],'native-attempt')

    def test_unknown_plugin_blocks_new_native_job_without_network(self):
        p=self.profile();c,_=self.fixture.begun();self.execution.recover()
        with self.assertRaisesRegex(ValueError,'media_plugin_generation_already_submitted'):
            self.generate(p)
        self.assertEqual(self.execution.get(c['id'])['status'],'unknown')
        self.assertEqual(self.app.media_providers.jobs(request_id=self.fixture.plan['request_id'])['jobs'],[])

    def test_native_queued_before_plugin_begin_rechecks_inside_submission_claim(self):
        p=self.profile();job=self.generate(p);self.fixture.begun()
        with patch('media_providers.adapters.submit') as submit:
            self.app.media_providers.tick()
        submit.assert_not_called()
        current=self.app.media_providers.get(job['id'])
        self.assertFalse(current['external_generation_submitted'])
        self.assertEqual(current['error'],'media_plugin_generation_already_submitted')

    def test_shared_task_cannot_bypass_plugin_approval_and_preserves_input(self):
        x=self.fixture.start();task=self.app.invoke('commerce_task_get',{'task_id':x['task_id']})
        original=task['input']
        for tool in ('commerce_task_continue','commerce_task_execute'):
            with self.assertRaisesRegex(ValueError,'media_plugin_task_use_execution_controls'):
                self.app.invoke(tool,{'task_id':x['task_id'],'operation':'report',**({'input':{},'idempotency_key':'bypass'} if tool=='commerce_task_continue' else {})})
        self.execution.approve(x['id'],self.fixture.plan['plan_sha256'],'approve')
        result=self.app.invoke('commerce_task_result',{'task_id':x['task_id']})
        self.assertEqual(result['execution']['operation'],'media_plugin')
        self.assertEqual(result['execution']['result']['status'],'awaiting_host')
        self.assertIsNone(result['execution']['attempt'])
        self.assertEqual(result['task']['input'],original)
        self.assertEqual(result['task']['status'],'queued')
        self.app.invoke('commerce_task_cancel',{'task_id':x['task_id']})
        self.assertTrue(self.execution.get(x['id'])['cancel_requested'])
        with self.assertRaisesRegex(ValueError,'download_retry_not_available'):
            self.app.invoke('commerce_task_retry',{'task_id':x['task_id']})

    def test_request_projection_keeps_unknown_plugin_receipt_visible(self):
        c,_=self.fixture.begun();self.execution.recover()
        request=self.app.invoke('commerce_media_request_get',{'request_id':self.fixture.plan['request_id']})
        self.assertTrue(request['external_generation_submitted'])
        self.assertEqual(request['plugin_executions'][0]['id'],c['id'])
        self.assertEqual(request['plugin_executions'][0]['status'],'unknown')
        with self.assertRaisesRegex(ValueError,'already_submitted'):
            self.app.media_plugins.validate(self.fixture.plan['id'],self.fixture.plan['plan_sha256'])


class PluginWorkerSeams(unittest.TestCase):
    def test_plugin_io_uses_single_nonblocking_worker_and_lifecycle(self):
        started=threading.Event();release=threading.Event();calls=[];events=[]
        def plugin_tick(at=None):calls.append(at);started.set();release.wait(2)
        service=SimpleNamespace(extensions=SimpleNamespace(tick=lambda at=None:events.append('extension'),recover=lambda:events.append('recover-ext'),stop=lambda:events.append('stop-ext')),
            media_providers=SimpleNamespace(tick=lambda at=None:None,recover=lambda:events.append('recover-native'),stop=lambda:None),
            media_plugin_execution=SimpleNamespace(tick=plugin_tick,recover=lambda:events.append('recover-plugin'),stop=lambda:release.set()))
        runtime=CapabilityLifecycle(service)
        try:
            runtime.recover();runtime.tick(at=1);self.assertTrue(started.wait(1))
            runtime.tick(at=2);self.assertEqual(calls,[1]);self.assertEqual(events.count('extension'),2)
        finally:runtime.stop()
        self.assertIn('recover-plugin',events);self.assertTrue(release.is_set())


if __name__=='__main__':unittest.main()
