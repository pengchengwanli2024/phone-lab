"""Bounded agent/draft behavior using the real runner and synthetic inference."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_extension_runtime import RuntimeCase

class Models:
    def snapshot(self,db,model_id=None):return {'provider':'compatible','profile_id':model_id or 'fixture','profile_revision':'1','model':'synthetic','base_url':'http://127.0.0.1:1'}
    def runtime_route(self,value):return value

class Agents(RuntimeCase):
    def setUp(self):super().setUp();self.service.models=Models()
    def agent(self,tools=None):return self.ready(kind='agent',spec={'instructions':'Use only evidence.','model_id':'fixture','tools':tools or [],'max_turns':4})
    def test_agent_default_approval_and_explicit_model_budget(self):
        ext=self.agent();run=self.call('run',extension_id=ext['id'],input={'q':'fixture'},idempotency_key='agent-default')
        with patch.object(self.app,'_model',return_value={'action':'finish','output':{'answer':'synthetic'}}) as model:
            pending=self.drain(run);self.assertEqual(pending['status'],'awaiting_approval');self.assertFalse(model.called)
            a=pending['approval'];self.call('run_approve',run_id=run['id'],step_id=a['step_id'],input_sha256=a['input_sha256'],decision='approve');result=self.drain(run)
        self.assertEqual(result['output'],{'answer':'synthetic'});self.assertEqual(result['usage']['model_calls'],1)
        second=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True,'max_model_calls':1,'max_seconds':86400},idempotency_key='preauthorized')
        self.assertEqual(second['budget']['max_seconds'],86400)
        with patch.object(self.app,'_model',return_value={'action':'finish','output':{'answer':'second'}}):self.assertEqual(self.drain(second)['status'],'succeeded')
    def test_agent_uses_only_granted_plugin_and_persists_observations(self):
        tool=self.ready(kind='plugin',spec={'transport':'builtin','tool':'commerce_runtime_status','effect':'read'});ext=self.agent([tool['id']]);run=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True},idempotency_key='tools')
        def respond(payload,*args):
            if not payload['observations']:return {'action':'call','tool':tool['id'],'input':{}}
            return {'action':'finish','output':{'observed':payload['observations'][0]['output']['mode']}}
        with patch.object(self.app,'_model',side_effect=respond):result=self.drain(run)
        self.assertEqual(result['output'],{'observed':'unconfigured'});self.assertEqual(result['usage']['model_calls'],2)
        invalid=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True},idempotency_key='ungranted')
        with patch.object(self.app,'_model',return_value={'action':'call','tool':'commerce_task_create','input':{}}):result=self.drain(invalid)
        self.assertEqual(result['error'],'extension_agent_tool_not_granted')
    def test_assist_produces_validated_unsaved_draft(self):
        run=self.call('assist',kind='skill',instructions='Create a read-only status helper',model_id='fixture',budget={'allow_model_calls':True},idempotency_key='assist')
        draft={'kind':'skill','name':'Draft','spec':{'steps':[{'id':'status','uses':{'builtin':'commerce_runtime_status'}}]}}
        with patch.object(self.app,'_model',return_value={'action':'finish','output':{'definition':draft}}):result=self.drain(run)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['output']['status'],'draft_not_saved');self.assertEqual(self.call('list')['items'],[]);self.assertEqual(self.service.calls,[])
    def test_paid_test_is_structure_only_and_never_calls_model(self):
        with patch.object(self.app,'_model') as model:ext=self.agent()
        self.assertFalse(model.called);self.assertEqual(ext['test_status'],'passed')

    def test_zero_model_budget_cannot_be_overridden_by_permission(self):
        ext=self.agent();run=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True,'max_model_calls':0},idempotency_key='zero-models')
        with patch.object(self.app,'_model') as model:result=self.drain(run)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'extension_budget_exhausted');self.assertFalse(model.called)
    def test_changed_model_route_stops_before_call(self):
        ext=self.agent();run=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True},idempotency_key='model-drift')
        with patch.object(self.service.models,'snapshot',return_value={'provider':'compatible','profile_id':'fixture','profile_revision':'2','model':'changed'}),patch.object(self.app,'_model') as model:
            result=self.drain(run)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error'],'extension_model_route_revoked');self.assertFalse(model.called)

class CompatibleOutputMode(RuntimeCase):
    def test_agent_honors_profile_without_provider_json_mode(self):
        from unittest.mock import patch
        from extension_runtime import ExtensionRuntime
        for enabled in (False,True):
            with self.subTest(json_mode=enabled),patch('model_providers.inference.invoke_json',return_value={'decision':{'action':'finish','output':{'synthetic':True}}}) as invoke:
                value=ExtensionRuntime._model({},lambda:False,{'provider':'compatible','json_mode':enabled},'Synthetic agent')
                self.assertTrue(value['output']['synthetic'])
                self.assertEqual(invoke.call_args.kwargs['output_schema'] is not None,enabled)


class WorkerShutdown(RuntimeCase):
    def test_stop_signals_inflight_model_without_waiting_for_result(self):
        import threading,time
        self.service.models=Models()
        ext=self.ready(kind='agent',spec={'instructions':'Synthetic.','tools':[]})
        entered=threading.Event();release=threading.Event();run=self.call('run',extension_id=ext['id'],budget={'allow_model_calls':True},idempotency_key='shutdown')
        def pending(*args):entered.set();release.wait(2);return {'action':'finish','output':{'late':True}}
        with patch.object(self.app,'_model',side_effect=pending):
            self.app.tick();self.assertTrue(entered.wait(1));started=time.monotonic();result=self.app.stop();elapsed=time.monotonic()-started;release.set()
            self.assertLess(elapsed,.5)
            for future in list(self.app._futures.values()):future.result(timeout=2)
        self.assertTrue(result['stopped']);self.assertIn(self.call('run_get',run_id=run['id'])['status'],('interrupted','unknown'))

if __name__=='__main__':unittest.main()
