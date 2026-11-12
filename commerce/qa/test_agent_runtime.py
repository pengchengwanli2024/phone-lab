"""Synthetic bounded-role acceptance. No provider or external side effects."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from agent_runtime.policy import check_call,project
from agent_runtime import AgentRuntime
from test_intel_workspace import feed


def inspect(tool='commerce_runtime_status',args=None):
    return {'decision':{'phase':'inspect','calls':[{'tool':tool,'arguments':args or {}}]},'provider':'synthetic','model':'synthetic'}


def answer(questions=None,proposals=None,refs=None):
    return {'decision':{'phase':'answer','answer':'按已读取资料整理，影响仍待核对。','questions':questions or [],'proposals':proposals or [],'evidence_refs':['R1'] if refs is None else refs},'provider':'synthetic','model':'synthetic'}


class RoleRuntime(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name);self.agent=self.app.agent_runtime
    def tearDown(self):self.agent.stop();self.temp.cleanup()
    def create(self,**extra):
        return self.app.invoke('commerce_agent_start',{'question':'检查本机运行状态','role':'conductor','topic':'runtime','idempotency_key':'synthetic',**extra})
    def process_decisions(self,decisions):
        with patch('agent_runtime.model.invoke',side_effect=decisions):self.agent.run_once()

    def test_role_aliases_no_role_contract_rewrite(self):
        rolepath=Path(__file__).resolve().parents[1]/'agents/roles.json';before=rolepath.read_bytes()
        run=self.create(role='commerce-chief')
        self.assertEqual(run['role']['id'],'conductor')
        self.assertEqual(rolepath.read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'unknown_agent_role'):self.create(role='root-approval',idempotency_key='other')

    def test_shared_idempotency_and_actual_read_receipt_survives_restart(self):
        with ThreadPoolExecutor(max_workers=4) as pool:runs=list(pool.map(lambda _:self.create(),range(4)))
        self.assertEqual(len({r['id'] for r in runs}),1)
        self.process_decisions([inspect(),answer()])
        result=AgentRuntime(self.app).get(runs[0]['id'])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['result']['observations'][0]['tool'],'commerce_runtime_status')
        self.assertEqual(len(result['result_sha256']),64)
        self.assertFalse(result['independently_verified'])
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.create(question='不同问题')

    def test_forbidden_tool_never_dispatched(self):
        run=self.create()
        with patch.object(self.app,'invoke',wraps=self.app.invoke) as invoke:
            self.process_decisions([inspect('commerce_live_sync')])
            self.assertFalse(any(c.args[0]=='commerce_live_sync' for c in invoke.call_args_list))
        self.assertEqual(self.agent.get(run['id'])['result']['error'],'agent_tool_outside_scope')

    def test_unreferenced_answer_and_unseen_item_rejected(self):
        run=self.create();self.process_decisions([answer(refs=[])])
        self.assertEqual(self.agent.get(run['id'])['result']['error'],'agent_current_evidence_required')
        with self.assertRaisesRegex(ValueError,'agent_item_outside_read_scope'):
            check_call('intelligence',{}, {'tool':'commerce_intel_item_get','arguments':{'item_id':'synthetic-not-seen'}},set())

    def test_calculator_exact_values_and_missing_values_hold(self):
        with self.assertRaisesRegex(ValueError,'agent_calculation_input_changed'):
            check_call('calculation',{'calculator':'unit_economics','input':{'price':20}},{'tool':'commerce_unit_economics','arguments':{'input':{'price':200}}},set())
        run=self.create(topic='calculation',parameters={'calculator':'unit_economics','input':{}})
        self.process_decisions([inspect('commerce_unit_economics',{'input':{}}),answer(questions=['还缺商品成本和币种，请先补齐。'])])
        result=self.agent.get(run['id']);self.assertEqual(result['status'],'awaiting_input')
        self.assertEqual(result['result']['observations'][0]['data']['status'],'HOLD')

    def test_runtime_projection_excludes_private_labels_and_keys(self):
        value=self.app.live.status();value.update(store_label='PRIVATE_SENTINEL',credentials_present={'key':'PRIVATE_SENTINEL'},private_path='PRIVATE_SENTINEL')
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(project('commerce_live_status',value)))

    def test_model_proposal_is_not_self_approval_and_apply_is_idempotent(self):
        run=self.create(parameters={'demo':True})
        self.process_decisions([inspect(),answer(proposals=[{'operation':'report','reason':'生成可审阅模板简报'}])])
        result=self.agent.get(run['id']);self.assertEqual(result['status'],'awaiting_review')
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        args={'run_id':run['id'],'proposal_id':'P1','result_sha256':result['result_sha256']}
        with self.assertRaisesRegex(ValueError,'agent_result_changed'):self.agent.apply(**dict(args,result_sha256='0'*64))
        first=self.agent.apply(**args);second=self.agent.apply(**args)
        self.assertEqual(first['task']['id'],second['task']['id']);self.assertEqual(first['task']['status'],'queued')
        self.app.autonomy.tick(1000,collect=False)
        self.assertEqual(self.app.autonomy.result(first['task']['id'])['execution']['result']['mode'],'demo')
        self.assertFalse(first['external_operations_executed'])

    def test_proposal_cannot_invent_calculation_input_or_platform_writes(self):
        run=self.create()
        self.process_decisions([inspect(),answer(proposals=[{'operation':'restock_plan','reason':'缺少明确测算资料'}])])
        self.assertEqual(self.agent.get(run['id'])['status'],'failed')
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_cancel_queued_and_running_no_hidden_result(self):
        queued=self.create();self.agent.cancel(queued['id'])
        with patch('agent_runtime.model.invoke') as invoke:self.agent.run_once();invoke.assert_not_called()
        live=self.create(idempotency_key='running')
        def cancel_model(*args):self.agent.cancel(live['id']);return answer(questions=['取消后不会保留回答。'],refs=[])
        with patch('agent_runtime.model.invoke',side_effect=cancel_model):self.agent.run_once()
        value=self.agent.get(live['id']);self.assertEqual(value['status'],'cancelled');self.assertNotIn('answer',value['result'])

    def test_unknown_model_outcome_not_automatically_retried(self):
        run=self.create()
        with patch('agent_runtime.model.invoke',side_effect=ValueError('agent_provider_outcome_unknown')) as invoke:
            self.agent.run_once();self.agent.run_once();self.assertEqual(invoke.call_count,1)
        self.assertEqual(self.agent.get(run['id'])['status'],'unknown')
        self.assertEqual(self.create()['id'],run['id'])

    def test_budget_and_unknown_citations_are_not_success(self):
        run=self.create();self.process_decisions([inspect(),inspect(),inspect()])
        self.assertEqual(self.agent.get(run['id'])['result']['error'],'agent_budget_exhausted')
        other=self.create(idempotency_key='bad-reference');self.process_decisions([inspect(),answer(refs=['R999'])])
        self.assertEqual(self.agent.get(other['id'])['result']['error'],'agent_unknown_evidence_reference')

    def test_explicit_reply_links_only_reviewable_matching_role(self):
        parent=self.create(topic='calculation');self.process_decisions([answer(questions=['请提供币种和成本。'],refs=[])])
        follow=self.create(topic='calculation',parent_id=parent['id'],question='补充了币种，先检查缺项',parameters={'calculator':'unit_economics','input':{'currency':'USD'}},idempotency_key='reply')
        self.assertEqual(follow['parent_id'],parent['id'])
        with self.assertRaisesRegex(ValueError,'agent_parent_not_replyable'):self.create(parent_id=parent['id'],idempotency_key='wrong-scope')

    def test_intelligence_review_preserves_frozen_evidence_not_model_values(self):
        with patch('intelligence.fetch',return_value=feed()),patch('intelligence.time.time',return_value=1700001000):self.app.intelligence.refresh(source='usgs')
        item=self.app.intelligence.search()['items'][0]
        run=self.create(topic='intelligence',parameters={'item_id':item['id']})
        self.process_decisions([inspect('commerce_intel_item_get',{'item_id':item['id']}),answer(proposals=[{'operation':'intel_review','reason':'整理影响核查材料','evidence_ref':'R1'}])])
        result=self.agent.get(run['id']);self.assertEqual(result['status'],'awaiting_review')
        proposal=result['result']['proposals'][0]
        self.assertEqual(proposal['input']['evidence']['record_sha256'],item['record_sha256'])
        task=self.agent.apply(run['id'],'P1',result['result_sha256'])['task'];self.app.autonomy.tick(1700001001,collect=False)
        self.assertEqual(self.app.autonomy.result(task['id'])['execution']['result']['store_impact'],'unknown')

    def test_process_recovery_retains_interrupted_and_never_resubmits(self):
        run=self.create()
        with self.app.core.db() as db:db.execute("UPDATE agent_runs SET status='running',owner='dead-process',expires=9999999999 WHERE id=?",(run['id'],))
        fresh=AgentRuntime(self.app)
        with patch('agent_runtime.model.invoke') as invoke:
            fresh.start(recover=True);fresh.stop();invoke.assert_not_called()
        result=fresh.get(run['id']);self.assertEqual(result['status'],'interrupted')
        self.assertFalse(self.agent.run_once())

    def test_source_menu_preserves_current_registered_sources(self):
        from intelligence import SOURCES
        from agent_runtime.policy import tool_menu
        self.assertEqual(set(tool_menu('intelligence',{})[0]['arguments']['source']),{'all',*SOURCES})


class AgentTransport(unittest.TestCase):
    def test_three_stdio_clients_share_agent_proposal_and_local_result(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary);(state/'auth.token').write_text('synthetic-role-transport')
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env=dict(os.environ,COMMERCE_STATE=str(state),COMMERCE_PORT=str(port))
            server=subprocess.Popen([sys.executable,str(root/'qa/fixture_agent_runtime.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            def rpc(client,name,args):
                messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}}, {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':args}}]
                done=subprocess.run([sys.executable,str(root/'mcp_server.py'),client],env=env,input=''.join(json.dumps(m)+'\n' for m in messages),capture_output=True,text=True,timeout=12)
                result=json.loads(done.stdout.splitlines()[-1])['result'];self.assertFalse(result.get('isError'),name)
                return result['structuredContent']
            try:
                for _ in range(100):
                    with socket.socket() as sock:
                        if sock.connect_ex(('127.0.0.1',port))==0:break
                    time.sleep(.05)
                run=rpc('codex','commerce_agent_start',{'question':'synthetic report','role':'conductor','topic':'runtime','parameters':{'demo':True},'idempotency_key':'shared-role-request'})
                for _ in range(40):
                    result=rpc('hermes','commerce_agent_get',{'run_id':run['id']})
                    if result['status']=='awaiting_review':break
                    time.sleep(.05)
                self.assertEqual(result['status'],'awaiting_review')
                task=rpc('harness','commerce_agent_apply',{'run_id':run['id'],'proposal_id':'P1','result_sha256':result['result_sha256']})['task']
                for _ in range(40):
                    receipt=rpc('codex','commerce_task_result',{'task_id':task['id']})
                    if receipt['task']['status']=='completed':break
                    time.sleep(.05)
                self.assertEqual(receipt['task']['status'],'completed')
                self.assertEqual(receipt['execution']['result']['mode'],'demo')
                self.assertEqual(rpc('hermes','commerce_agent_get',{'run_id':run['id']})['actions'][0]['task_id'],task['id'])
            finally:
                server.terminate();server.wait(timeout=8)


if __name__=='__main__':unittest.main(verbosity=2)
