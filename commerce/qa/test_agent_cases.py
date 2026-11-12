"""Case-scoped model reads, atomic existing handoff, real artifact recheck.

All connector snapshots, identities, model outputs and documents are synthetic.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from agent_runtime.policy import project
from research import template
from live_connections import now
from test_live_connections import batch, SECRET


def inspect(case,stage='S3',tool='commerce_organization_brief'):
    return {'decision':{'phase':'inspect','calls':[{'tool':tool,'arguments':{'case_id':case,**({'stage_id':stage} if tool.endswith('_brief') else {})}}]},'provider':'synthetic','model':'synthetic'}


def answer(operation='organization_handoff'):
    return {'decision':{'phase':'answer','answer':'当前选定工作项仍需补齐岗位资料，待复验。','questions':[],
                        'evidence_refs':['R1'],'proposals':[{'operation':operation,'reason':'补齐当前岗位产物','evidence_ref':'R1'}]},
            'provider':'synthetic','model':'synthetic'}


class AgentCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name);self.org=self.app.organization
        self.app.live.configure({'ozon_client_id':'123456','ozon_api_key':SECRET,'fulfillment_modes':['OGL']})
        config=self.app.live.config()
        for kind in ('orders','stock'):self.app.live._publish(config['connection_id'],kind,batch(kind),config,False)
        self.case=self.org.import_inventory()['cases'][0];self.cid=self.case['id']
    def tearDown(self):self.temp.cleanup()
    def create(self,**changes):
        args=dict(question='检查该工作项供应链缺项',role='conductor',topic='organization_case',parameters={'case_id':self.cid,'stage_id':'S3'},idempotency_key='synthetic-case')
        args.update(changes)
        return self.app.agent_runtime.create(**args)
    def propose(self,stage='S3'):
        run=self.create(parameters={'case_id':self.cid,'stage_id':stage})
        with patch('agent_runtime.model.invoke',side_effect=[inspect(self.cid,stage),answer()]):self.app.agent_runtime.run_once()
        return self.app.agent_runtime.get(run['id'])
    def apply(self,run):return self.app.agent_runtime.apply(run['id'],'P1',run['result_sha256'])
    def check(self,run):return self.app.invoke('commerce_agent_case_check',{'run_id':run['id'],'proposal_id':'P1'})
    def prepare_research(self):
        record=template('ozon')['record'];record.update(market='RU',language='en',source_url='https://example.org/synthetic',captured_at=now(),raw_excerpt='Synthetic item.',category_rules_url='https://example.org/rules',category_rules_checked=True)
        for value in record['fields'].values():value.update(original='Synthetic item.',zh='合成资料。',reviewed=True,locator='synthetic paragraph')
        self.org.record(self.cid,'research',{'record':record,'sku':self.case['scope']['sku'],'row_key':self.case['scope']['row_key']},'synthetic-research')

    def test_case_selection_is_explicit_and_never_imports(self):
        with self.assertRaisesRegex(ValueError,'agent_explicit_case_required'):self.create(parameters={})
        with self.assertRaisesRegex(ValueError,'agent_case_unavailable'):self.create(parameters={'case_id':'not-present'})
        with self.assertRaisesRegex(ValueError,'agent_invalid_case_stage'):self.create(parameters={'case_id':self.cid,'stage_id':'outside'})
        before=len(self.org.cases());listing=self.app.invoke('commerce_agent_cases',{})
        self.assertFalse(listing['automatic_import']);self.assertEqual(len(self.org.cases()),before)

    def test_case_reads_do_not_send_other_cases_or_paths(self):
        config=self.app.live.config();data=batch('stock');data['records'].append({'product_id':'999','offer_id':'PRIVATE_OTHER_SKU','stocks':[{'type':'fbs','present':8,'reserved':0,'sku':'999'}]})
        self.app.live._publish(config['connection_id'],'stock',data,config,True);self.org.import_inventory()
        value=project('commerce_organization_board',self.org.board(self.cid));encoded=json.dumps(value)
        self.assertNotIn('cases',value);self.assertNotIn('PRIVATE_OTHER_SKU',encoded);self.assertNotIn(self.temp.name,encoded);self.assertNotIn(SECRET,encoded)
        self.assertNotIn('row_key',value['case']['scope']);self.assertEqual(value['case']['id'],self.cid)

    def test_model_cannot_switch_case_or_selected_stage(self):
        run=self.create()
        with patch('agent_runtime.model.invoke',return_value=inspect('another-case')):self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_case_outside_scope')
        run=self.create(idempotency_key='stage-change')
        with patch('agent_runtime.model.invoke',return_value=inspect(self.cid,'S2')):self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_case_stage_outside_scope')

    def test_scope_change_while_queued_does_not_call_model(self):
        run=self.create();self.org.set_currency(self.cid,'CNY')
        with patch('agent_runtime.model.invoke') as model:self.app.agent_runtime.run_once();model.assert_not_called()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_case_scope_changed')

    def test_board_reference_is_not_a_stage_brief_or_approval(self):
        run=self.create()
        with patch('agent_runtime.model.invoke',side_effect=[inspect(self.cid,tool='commerce_organization_board'),answer()]):self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_case_brief_required')
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_generic_report_cannot_escape_case_scope(self):
        run=self.create()
        with patch('agent_runtime.model.invoke',side_effect=[inspect(self.cid),answer('report')]):self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_case_proposal_requires_handoff')

    def test_handoff_reuses_existing_domain_contract_and_deduplication(self):
        run=self.propose();self.assertEqual(run['status'],'awaiting_review')
        original=self.org.handoff(self.cid,'S3')['task']
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.apply(run),range(4)))
        self.assertEqual({r['task']['id'] for r in results},{original['id']})
        self.assertEqual(len(self.app.core.invoke('commerce_task_list',{})['tasks']),1)
        self.assertEqual(self.org.handoff(self.cid,'S3')['task']['id'],original['id'])
        self.assertEqual(results[0]['task']['input']['execution'],'not_requested')
        self.assertFalse(results[0]['gate_closed'])

    def test_changed_evidence_rejects_confirmation_without_creating_task(self):
        run=self.propose();self.org.set_currency(self.cid,'CNY')
        with self.assertRaisesRegex(ValueError,'agent_case_evidence_changed'):self.apply(run)
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        self.assertEqual(self.app.agent_runtime.get(run['id'])['actions'],[])

    def test_nested_handoff_change_rolls_back_task_and_intermediate_write(self):
        run=self.propose();original=self.org.handoff
        def change_then_handoff(case_id,stage_id):
            self.org.set_currency(case_id,'CNY')
            return original(case_id,stage_id)
        with patch.object(self.org,'handoff',side_effect=change_then_handoff):
            with self.assertRaisesRegex(ValueError,'agent_case_evidence_changed'):self.apply(run)
        self.assertIsNone(self.org.case(self.cid)['currency'])
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        self.assertEqual(self.app.agent_runtime.get(run['id'])['actions'],[])

    def test_completed_task_does_not_close_gate(self):
        run=self.propose();task=self.apply(run)['task']
        with self.app.core.db() as db:db.execute("UPDATE tasks SET status='completed' WHERE id=?",(task['id'],))
        result=self.check(run)
        self.assertEqual(result['task']['status'],'completed');self.assertFalse(result['gate_passed']);self.assertTrue(result['current']['stage']['gaps'])
        self.assertFalse(result['business_closed'])

    def test_actual_artifact_updates_are_rechecked_without_changing_task(self):
        self.prepare_research();self.org.set_currency(self.cid,'CNY');run=self.propose();task=self.apply(run)['task']
        self.org.record(self.cid,'supply',{'currency':'CNY','purchase_cost':30,'lead_time_days':14,'supplier':'synthetic supplier','source_ref':'synthetic:quote'},'synthetic-supply')
        result=self.check(run);self.assertTrue(result['gate_passed']);self.assertTrue(result['evidence_changed']);self.assertFalse(result['business_closed'])
        self.assertEqual(result['task']['id'],task['id']);self.assertEqual(result['task']['status'],'queued')
        self.assertEqual(self.apply(run)['task']['id'],task['id']) # historical retry, no new dispatch

    def test_connection_change_withdraws_case_without_substitution(self):
        run=self.propose();self.app.live.configure({'ozon_client_id':'654321'})
        self.assertEqual(self.app.invoke('commerce_agent_cases',{})['cases'],[])
        with self.assertRaisesRegex(ValueError,'agent_case_unavailable'):self.apply(run)
        self.assertEqual(self.check(run)['gate_status'],'UNKNOWN')
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_atomic_context_is_thread_scoped_and_rolls_back_audit(self):
        with self.assertRaisesRegex(ValueError,'synthetic rollback'):
            with self.app.core.atomic():
                self.app.invoke('commerce_task_create',{'kind':'analysis','idempotency_key':'rolled-back'},'test')
                raise ValueError('synthetic rollback')
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        task=self.app.core.invoke('commerce_task_create',{'kind':'analysis','idempotency_key':'after-rollback'})
        self.assertEqual(task['status'],'queued')

    def test_reply_cannot_reuse_prior_context_for_another_stage(self):
        run=self.propose()
        with self.assertRaisesRegex(ValueError,'agent_case_reply_scope_changed'):
            self.create(parameters={'case_id':self.cid,'stage_id':'S2'},parent_id=run['id'],idempotency_key='different-stage-reply')


class CaseTransport(unittest.TestCase):
    def test_cross_tool_case_review_handoff_artifact_and_recheck(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary);(state/'auth.token').write_text('synthetic-case-transport')
            with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            env=dict(os.environ,COMMERCE_STATE=str(state),COMMERCE_PORT=str(port))
            server=subprocess.Popen([sys.executable,str(root/'qa/fixture_agent_cases.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            def rpc(client,name,args):
                messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}}, {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':args}}]
                done=subprocess.run([sys.executable,str(root/'mcp_server.py'),client],env=env,input=''.join(json.dumps(m)+'\n' for m in messages),capture_output=True,text=True,timeout=12)
                value=json.loads(done.stdout.splitlines()[-1])['result'];self.assertFalse(value.get('isError'),name);return value['structuredContent']
            try:
                for _ in range(100):
                    with socket.socket() as sock:
                        if sock.connect_ex(('127.0.0.1',port))==0:break
                    time.sleep(.05)
                cid=rpc('codex','commerce_agent_cases',{})['cases'][0]['id']
                run=rpc('codex','commerce_agent_start',{'question':'检查该工作项S3缺项','role':'conductor','topic':'organization_case','parameters':{'case_id':cid,'stage_id':'S3'},'idempotency_key':'case-transport'})
                for _ in range(40):
                    result=rpc('hermes','commerce_agent_get',{'run_id':run['id']})
                    if result['status']=='awaiting_review':break
                    time.sleep(.05)
                self.assertEqual(result['status'],'awaiting_review')
                task=rpc('harness','commerce_agent_apply',{'run_id':run['id'],'proposal_id':'P1','result_sha256':result['result_sha256']})['task']
                self.assertEqual(task['input']['organization_case'],cid);self.assertEqual(task['input']['execution'],'not_requested')
                rpc('hermes','commerce_organization_record',{'case_id':cid,'kind':'supply','payload':{'currency':'CNY','purchase_cost':30,'lead_time_days':14,'supplier':'synthetic supplier','source_ref':'synthetic:quote'},'idempotency_key':'transport-supply'})
                outcome=rpc('codex','commerce_agent_case_check',{'run_id':run['id'],'proposal_id':'P1'})
                self.assertTrue(outcome['gate_passed']);self.assertFalse(outcome['business_closed']);self.assertEqual(outcome['task']['id'],task['id']);self.assertEqual(outcome['task']['status'],'queued')
            finally:server.terminate();server.wait(timeout=8)


if __name__=='__main__':unittest.main(verbosity=2)
