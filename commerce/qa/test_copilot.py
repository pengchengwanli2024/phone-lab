"""Durable contextual dialogue with synthetic model responses only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from copilot import Copilot
from test_agent_runtime import inspect,answer

class Dialogue(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name);self.chat=Copilot(self.app)
        self.thread=self.chat.invoke('commerce_copilot_open',dict(context={'module':'orders','demo':True},idempotency_key='open'))
    def tearDown(self):self.app.agent_runtime.stop();self.temp.cleanup()
    def send(self,**overrides):
        return self.chat.invoke('commerce_copilot_send',{**dict(thread_id=self.thread['id'],message='核对经营范围',context_sha256=self.thread['context_sha256'],idempotency_key='send'),**overrides})
    def complete(self,proposals=None):
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer(proposals=proposals)]):self.app.agent_runtime.run_once()
    def test_stale_model_binding_rejects_new_send_without_creating_a_run(self):
        with self.assertRaisesRegex(ValueError,'copilot_model_changed'):
            self.send(expected_model_sha256='0'*64)
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'],0)
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],0)

    def test_idempotent_send_returns_original_run_before_current_model_check(self):
        binding=self.chat.get(self.thread['id'])['model_selection']['sha256']
        first=self.send(expected_model_sha256=binding)
        # An independent window can publish a new model binding after enqueue.
        with self.app.core.db() as db:
            db.execute('INSERT OR REPLACE INTO copilot_models VALUES (?,?,?)',(self.thread['id'],'project-default',1))
        retried=self.send(expected_model_sha256=binding)
        self.assertEqual(retried['latest_run']['id'],first['latest_run']['id'])
        self.assertEqual(retried['total_turns'],1)
    def test_concurrent_idempotency_persistence_and_no_implicit_calls(self):
        with patch('agent_runtime.model.invoke') as model:
            with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(lambda _:self.send(),range(4)))
            self.assertEqual(len({v['latest_run']['id'] for v in values}),1)
            self.assertEqual(len(Copilot(self.app).get(self.thread['id'])['turns']),1);model.assert_not_called()
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.send(message='different')
        with self.assertRaisesRegex(ValueError,'active_run'):self.send(idempotency_key='another')
    def test_history_parent_and_context_invalidates_review(self):
        first=self.send();self.complete([{'operation':'report','reason':'审阅简报模板'}]);first=self.chat.get(self.thread['id'])
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        second=self.send(idempotency_key='second',message='继续解释');self.assertEqual(second['latest_run']['parent_id'],first['latest_run']['id'])
        with self.assertRaisesRegex(ValueError,'active_run'):self.chat.context(self.thread['id'],{'module':'products'},self.thread['context_sha256'])
        self.chat.cancel(self.thread['id'],second['latest_run']['id'])
        changed=self.chat.context(self.thread['id'],{'module':'products'},self.thread['context_sha256'])
        with self.assertRaisesRegex(ValueError,'context_changed'):self.chat.apply(self.thread['id'],first['latest_run']['id'],'P1',first['latest_run']['result_sha256'],changed['context_sha256'])
        self.assertEqual(len(changed['turns']),2)
    def test_direct_runtime_review_cannot_bypass_context_change_or_revision(self):
        self.send();self.complete([{'operation':'report','reason':'简报模板'}]);run=self.chat.get(self.thread['id'])['latest_run']
        changed=self.chat.context(self.thread['id'],{'module':'products'},self.thread['context_sha256'])
        self.chat.context(self.thread['id'],self.thread['context'],changed['context_sha256'])
        with self.assertRaisesRegex(ValueError,'context_changed'):
            self.app.agent_runtime.apply(run['id'],'P1',run['result_sha256'])

    def test_selected_intelligence_record_can_be_read_without_an_unrelated_search(self):
        from agent_runtime.policy import check_call,tool_menu
        ident='a'*24
        scope={'context':{'module':'intelligence','demo':False,'entity':{'kind':'intel','id':ident}}}
        call={'tool':'commerce_intel_item_get','arguments':{'item_id':ident}}
        self.assertEqual(check_call('workspace',scope,call,set()),('commerce_intel_item_get',{'item_id':ident}))
        menu=tool_menu('workspace',scope)
        self.assertIn({'tool':'commerce_intel_item_get','arguments':{'item_id':ident}},menu)
        for entity in ({'kind':'intel','id':'b'*24},{'kind':'case','id':ident}):
            with self.assertRaisesRegex(ValueError,'outside_read_scope'):
                check_call('workspace',{'context':{**scope['context'],'entity':entity}},call,set())
        with self.assertRaisesRegex(ValueError,'outside_scope'):
            check_call('workspace',{'context':{**scope['context'],'module':'orders'}},call,set())

    def test_live_intelligence_reads_are_bounded_read_only_and_secret_free(self):
        from agent_runtime.policy import check_call,project,tool_menu
        scope={'context':{'module':'intelligence','demo':False}}
        self.assertIn('commerce_intel_live_get',[t['tool'] for t in tool_menu('workspace',scope)])
        name,args=check_call('workspace',scope,{'tool':'commerce_intel_live_get','arguments':{}},set())
        self.assertEqual(name,'commerce_intel_live_get');self.assertEqual(args,{'limit':20})
        for bad in ({'limit':10000},{'query':'x'*65},{'bounds':{'west':190,'east':200,'south':0,'north':20}}):
            with self.assertRaises(ValueError):
                check_call('workspace',scope,{'tool':name,'arguments':bad},set())
        with self.assertRaisesRegex(ValueError,'outside_scope'):
            check_call('workspace',scope,{'tool':'commerce_intel_live_refresh','arguments':{}},set())
        sample={'generated_at':123,'coverage':'receiver coverage','secret':'PRIVATE_SENTINEL','sources':{'vessels':{'status':'ready','matched':1000,'observed_at':120,'credentials':'PRIVATE_SENTINEL','items':[{'id':str(i),'kind':'vessel','name':'PUBLIC','observed_at':120,'location':{'lat':1,'lon':2},'secret':'PRIVATE_SENTINEL'}for i in range(50)]}}}
        value=project(name,sample)
        self.assertEqual(value['sources']['vessels']['matched'],1000)
        self.assertEqual(len(value['sources']['vessels']['items']),20)
        self.assertEqual(value['sources']['vessels']['observed_at'],120)
        self.assertNotIn('PRIVATE_SENTINEL',str(value))
        self.assertFalse(value['facts_independently_verified'])

    def test_intelligence_times_are_formatted_without_model_epoch_arithmetic(self):
        from agent_runtime.policy import project
        stamp=1794789585
        live=project('commerce_intel_live_get',{'generated_at':stamp,'sources':{'vessels':{'observed_at':stamp,'last_success':stamp,'items':[{'observed_at':stamp}]}}})
        self.assertEqual(live['generated_at_utc'],'2026-11-16 00:39:45 UTC')
        source=live['sources']['vessels']
        self.assertEqual(source['observed_at_beijing'],'2026-11-16 08:39:45 +08:00')
        self.assertEqual(source['last_success_utc'],live['generated_at_utc'])
        self.assertEqual(source['items'][0]['observed_at_utc'],live['generated_at_utc'])
        item=project('commerce_intel_item_get',{'published':stamp})
        self.assertEqual(item['published_beijing'],source['observed_at_beijing'])
        for invalid in (None,True,float('inf'),float('nan'),10**30):
            self.assertNotIn('published_utc',project('commerce_intel_item_get',{'published':invalid}))

    def test_live_projection_fits_runtime_budget_with_all_three_sources(self):
        from agent_runtime.policy import canonical,project
        row={'id':'public','name':'公开名称'*100,'source_url':'https://example.test/'+('x'*180),'observed_at':1794789585}
        raw={'generated_at':1794789585,'sources':{key:{'matched':5000,'observed_at':1794789585,'items':[row]*20} for key in ('flights','vessels','markets')}}
        value=project('commerce_intel_live_get',raw)
        self.assertLessEqual(len(canonical(value)),14000)
        for source in value['sources'].values():
            self.assertEqual(source['matched'],5000)
            self.assertGreater(source['shown_to_model'],0)
            self.assertLess(source['shown_to_model'],20)
            self.assertTrue(source['truncated'])

    def test_workspace_read_scope_and_privacy_projection(self):
        from agent_runtime.policy import check_call,project
        scope={'context':{'module':'orders','demo':True,'platform':'ozon'}}
        with self.assertRaisesRegex(ValueError,'scope_changed'):
            check_call('workspace',scope,{'tool':'commerce_orders_list','arguments':{'demo':True,'platform':'all','store_id':'all','market':'all'}},set())
        with self.assertRaisesRegex(ValueError,'outside_scope'):
            check_call('workspace',scope,{'tool':'commerce_skills_execute','arguments':{}},set())
        with self.assertRaisesRegex(ValueError,'outside_read_scope'):
            check_call('workspace',scope,{'tool':'commerce_skills_get','arguments':{'skill_id':'sealeap-invented'}},set())
        value=project('commerce_orders_list',{'orders':[{'id':'PRIVATE_SENTINEL','customer':'PRIVATE_SENTINEL','store':'PRIVATE_SENTINEL','sku':'PRIVATE_SENTINEL','platform':'ozon','amount':2,'currency':'RUB'}]})
        self.assertNotIn('PRIVATE_SENTINEL',str(value));self.assertEqual(value['groups'][0]['amount_sum'],2)

    def test_a2a_message_identity_is_global_across_threads(self):
        self.send(idempotency_key='a2a:message-one')
        other=self.chat.open({'module':'orders','demo':True},'other')
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):
            self.chat.send(other['id'],'核对经营范围',other['context_sha256'],'a2a:message-one')
        self.assertEqual(self.chat.lookup_message('a2a:message-one')['id'],self.thread['id'])

    def test_bounded_history_metadata_list_and_old_a2a_retry(self):
        from protocols.a2a import dispatch
        self.app.copilot=self.chat
        request={'jsonrpc':'2.0','id':'request','method':'message/send','params':{'message':{'kind':'message','messageId':'old-message','contextId':self.thread['id'],'role':'user','parts':[{'kind':'text','text':'继续'}]}}}
        original=dispatch(self.app,request)
        self.assertIn('result',original)
        old_run=original['result']['id'];self.chat.cancel(self.thread['id'],old_run)
        with patch('agent_runtime.model.invoke') as model:
            for index in range(45):
                value=self.send(idempotency_key='history-'+str(index));self.chat.cancel(self.thread['id'],value['latest_run']['id'])
            latest=self.chat.get(self.thread['id'])
            self.assertEqual(len(latest['turns']),40);self.assertEqual(latest['total_turns'],46);self.assertTrue(latest['has_more'])
            older=self.chat.get(self.thread['id'],before=latest['next_cursor'])
            self.assertEqual(len(older['turns']),6);self.assertFalse(older['has_more']);self.assertIsNone(older['next_cursor'])
            self.assertEqual(older['latest_run']['id'],latest['latest_run']['id'])
            self.assertEqual(len({t['id'] for t in latest['turns']+older['turns']}),46)
            self.assertEqual(self.chat.lookup_run(old_run)['turns'][-1]['run']['id'],old_run)
            listed=self.chat.list()['threads'][0]
            self.assertNotIn('turns',listed);self.assertNotIn('latest_run',listed);self.assertNotIn('surfaces',listed)
            retry=dispatch(self.app,request);self.assertEqual(retry['result']['id'],old_run)
            model.assert_not_called()
        with self.assertRaisesRegex(ValueError,'cursor'):self.chat.get(self.thread['id'],before='invalid')

    def test_three_turn_memory_is_bounded_and_excludes_changed_context(self):
        import json
        self.send(message='最初预算1379',idempotency_key='memory-1');self.complete()
        self.send(message='先核对执行器状态',idempotency_key='memory-2');self.complete()
        self.send(message='回到最初预算',idempotency_key='memory-3')
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]) as provider:
            self.app.agent_runtime.run_once()
        payload=provider.call_args_list[0].args[0]
        self.assertIn('1379',json.dumps(payload['conversation'],ensure_ascii=False))
        self.assertLessEqual(len(payload['conversation']),6)
        changed=self.chat.context(self.thread['id'],{'module':'products'},self.thread['context_sha256'])
        self.chat.send(self.thread['id'],'新范围的问题',changed['context_sha256'],'memory-4')
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]) as provider:
            self.app.agent_runtime.run_once()
        self.assertNotIn('1379',json.dumps(provider.call_args_list[0].args[0].get('conversation',[])))

    def test_missing_model_route_is_actionable_without_secret_details(self):
        self.send(idempotency_key='missing-provider')
        with patch('agent_runtime.model.model_command',side_effect=ValueError('translation_hermes_unavailable')):
            self.app.agent_runtime.run_once()
        run=self.chat.get(self.thread['id'])['latest_run']
        self.assertEqual(run['status'],'failed')
        self.assertEqual(run['result']['error'],'agent_model_setup_required')
        self.assertFalse(run['result']['automatic_retry'])

    def test_bad_context_and_unknown_arguments(self):
        for context in ({'module':'unknown'},{'module':'orders','token':'secret'},{'module':'orders','demo':1},{'module':'orders','input':{'password':'x'}}):
            with self.assertRaises(ValueError):self.chat.open(context,'invalid')
        with self.assertRaisesRegex(ValueError,'arguments'):self.chat.invoke('commerce_copilot_get',{'thread_id':self.thread['id'],'execute':True})
    def test_hash_bound_review_and_membership(self):
        self.send();self.complete([{'operation':'report','reason':'简报模板'}]);run=self.chat.get(self.thread['id'])['latest_run']
        with self.assertRaisesRegex(ValueError,'context_changed'):self.chat.apply(self.thread['id'],run['id'],'P1',run['result_sha256'],'0'*64)
        a=self.chat.apply(self.thread['id'],run['id'],'P1',run['result_sha256'],self.thread['context_sha256'])
        b=self.chat.apply(self.thread['id'],run['id'],'P1',run['result_sha256'],self.thread['context_sha256'])
        self.assertEqual(a['task']['id'],b['task']['id'])
        with self.assertRaisesRegex(ValueError,'run_not_in_thread'):self.chat.cancel(self.thread['id'],'unknown')

if __name__=='__main__':unittest.main()
