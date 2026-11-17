"""Real registry reads and bounded selection; no model or external dispatch."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from copilot.capabilities import CopilotCapabilities
from copilot.activity import CopilotActivity
from test_agent_runtime import inspect,answer


class Capabilities(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
        self.scope={'module':'overview','demo':True};self.choices=CopilotCapabilities(self.app.copilot)
    def tearDown(self):self.app.agent_runtime.stop();self.app.extensions.stop();self.temp.cleanup()

    def test_catalog_uses_installed_skill_and_registered_module_identities(self):
        value=self.choices.catalog(self.scope,limit=30)
        self.assertIn('intelligence',[m['id'] for m in value['modules']])
        self.assertTrue(any(row['kind']=='skill' for row in value['items']))
        self.assertIn('mcp:commerce',[row['id'] for row in value['items']])
        self.assertFalse(value['external_execution_allowed'])

    def test_check_and_freeze_bind_exact_scope_and_registry_versions(self):
        selected=self.choices.check(self.scope,['mcp:commerce'])
        self.assertTrue(selected['available'])
        frozen=self.choices.freeze(self.scope,['mcp:commerce'],selected['selection_sha256'])
        self.assertEqual(frozen['selection_sha256'],selected['selection_sha256'])
        self.assertFalse(frozen['external_execution_allowed'])
        with self.assertRaisesRegex(ValueError,'capability_changed'):
            self.choices.freeze({**self.scope,'module':'orders'},['mcp:commerce'],selected['selection_sha256'])

    def test_unconfigured_plugin_is_visible_but_cannot_be_claimed_as_available(self):
        value=self.choices.check(self.scope,['plugin:lovart'])
        self.assertFalse(value['available']);self.assertTrue(value['issues'])
        with self.assertRaisesRegex(ValueError,'capability_unavailable'):
            self.choices.freeze(self.scope,['plugin:lovart'],value['selection_sha256'])

    def test_unknown_duplicate_and_oversized_selections_are_rejected(self):
        for ids in (['bad:tool'],['mcp:commerce']*2,['mcp:commerce']*7,'mcp:commerce'):
            with self.assertRaises(ValueError):self.choices.check(self.scope,ids)
        self.assertIsNone(self.choices.freeze(self.scope,None,None))

    def test_skill_freeze_reads_only_the_selected_pinned_source(self):
        entry=next(iter(self.app.skills.entries.values()));ident='skill:'+entry['id']
        with patch.object(self.app.skills,'get',return_value={**entry,'integrity':True,'skill_text':'Synthetic method; not permission'}) as read:
            value=self.choices.check(self.scope,[ident]);self.assertTrue(value['available'])
            self.assertEqual(value['capabilities'][0]['method_text'],'Synthetic method; not permission')
            self.assertTrue(value['capabilities'][0]['instructions_are_untrusted_data'])
            read.assert_called_once_with(entry['id'])
        with patch.object(self.app.skills,'get',return_value={**entry,'integrity':False,'skill_text':None}):
            self.assertFalse(self.choices.check(self.scope,[ident])['available'])

    def test_plugin_projection_does_not_expose_connection_secrets(self):
        sample={'connections':[{'provider':'lovart','label':'Lovart','revision':4,'status':'available_to_host','account_label':'PRIVATE_SENTINEL','link_id':'PRIVATE_SENTINEL','account_suffix':'PRIVATE_SENTINEL','model_parameters':{'key':'PRIVATE_SENTINEL'}}]}
        with patch.object(self.app.media_plugins,'catalog',return_value=sample):
            value=self.choices.check(self.scope,['plugin:lovart'])
        self.assertTrue(value['available']);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(value))
        self.assertEqual(value['capabilities'][0]['selection_effect'],'host_preference_only')

    def test_catalog_pagination_and_inputs_are_bounded(self):
        first=self.choices.catalog(self.scope,limit=2);second=self.choices.catalog(self.scope,offset=2,limit=2)
        self.assertEqual(first['next_offset'],2)
        self.assertFalse(set(r['id'] for r in first['items']) & set(r['id'] for r in second['items']))
        for args in ({'limit':0},{'offset':-1},{'query':'x'*101}):
            with self.assertRaises(ValueError):self.choices.catalog(self.scope,**args)

    def test_actual_send_freezes_selected_capabilities_and_returns_original_receipt(self):
        thread=self.app.copilot.open(self.scope,'capability-thread')
        selected=self.app.copilot.invoke('commerce_copilot_capability_check',{'context':self.scope,'capability_ids':['mcp:commerce']})
        args=dict(thread_id=thread['id'],message='核对当前范围',context_sha256=thread['context_sha256'],idempotency_key='capability-send',capability_ids=selected['capability_ids'],expected_capability_sha256=selected['selection_sha256'])
        sent=self.app.copilot.send(**args)
        self.assertEqual(sent['capability_selection']['selection_sha256'],selected['selection_sha256'])
        self.assertEqual(sent['latest_run']['id'],self.app.copilot.send(**args)['latest_run']['id'])
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]) as model:
            self.app.agent_runtime.run_once()
        self.assertEqual(model.call_args_list[0].args[0]['capability_selection']['selection_sha256'],selected['selection_sha256'])

    def test_changed_selection_is_rejected_before_creating_a_run(self):
        thread=self.app.copilot.open(self.scope,'reject-thread')
        with self.assertRaisesRegex(ValueError,'capability_changed'):
            self.app.copilot.send(thread['id'],'核对当前范围',thread['context_sha256'],'reject-send',capability_ids=['mcp:commerce'],expected_capability_sha256='0'*64)
        with self.app.core.db() as db:self.assertEqual(0,db.execute('SELECT count(*) FROM agent_runs').fetchone()[0])

    def test_registered_tool_contracts_are_read_only_and_reject_extra_arguments(self):
        self.assertTrue(self.app.invoke('commerce_copilot_activity',{})['read_only'])
        with self.assertRaises(ValueError):self.app.copilot.invoke('commerce_copilot_activity',{'unauthorized':'anything'})
        with self.assertRaises(ValueError):self.app.copilot.invoke('commerce_copilot_capability_check',{'context':self.scope,'capability_ids':[],'unauthorized':True})

    def test_plugin_revoked_while_queued_never_reaches_a_model(self):
        sample={'connections':[{'provider':'lovart','revision':1,'status':'available_to_host'}]}
        thread=self.app.copilot.open(self.scope,'revocation-thread')
        with patch.object(self.app.media_plugins,'catalog',return_value=sample):
            selected=self.choices.check(self.scope,['plugin:lovart'])
            self.app.copilot.send(thread['id'],'核对范围',thread['context_sha256'],'revocation-send',capability_ids=selected['capability_ids'],expected_capability_sha256=selected['selection_sha256'])
        with patch('agent_runtime.model.invoke',side_effect=AssertionError('must not invoke')) as model:
            self.app.agent_runtime.run_once();model.assert_not_called()
        result=self.app.copilot.get(thread['id'])['latest_run']
        self.assertEqual(result['status'],'failed');self.assertEqual(result['result']['error'],'copilot_capability_unavailable')

    def test_multibyte_skill_references_share_a_bounded_total_budget(self):
        entries=list(self.app.skills.entries.values())[:6]
        def source(ident):return {**self.app.skills.entries[ident],'integrity':True,'skill_text':'合成方法资料'*10000}
        with patch.object(self.app.skills,'get',side_effect=source):value=self.choices.check(self.scope,['skill:'+entry['id'] for entry in entries])
        self.assertLessEqual(sum(len(item['method_text'].encode()) for item in value['capabilities']),12000)
        self.assertTrue(all(item['method_truncated'] for item in value['capabilities']))


class Activity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name);self.activity=CopilotActivity(self.app.copilot)
    def tearDown(self):self.app.agent_runtime.stop();self.app.extensions.stop();self.temp.cleanup()
    def send(self,module,key,message):
        thread=self.app.copilot.open({'module':module,'demo':True},'thread-'+key,title='Synthetic '+key)
        return self.app.copilot.send(thread['id'],message,thread['context_sha256'],'send-'+key)

    def test_running_original_request_remains_in_task_view_after_another_scope_opens(self):
        original=self.send('overview','one','原运营问题')
        self.app.copilot.open({'module':'intelligence','demo':True},'other-page')
        value=self.activity.list(status='active')
        self.assertEqual(value['items'][0]['thread_id'],original['id'])
        self.assertEqual(value['items'][0]['run_id'],original['latest_run']['id'])
        self.assertEqual(value['items'][0]['status'],'queued')
        self.assertEqual(value['items'][0]['total_turns'],1)

    def test_finished_history_survives_new_instance_and_searches_older_turns(self):
        original=self.send('orders','two','查找独有旧问题')
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]):self.app.agent_runtime.run_once()
        later=self.app.copilot.send(original['id'],'较新的问题',original['context_sha256'],'later')
        value=CopilotActivity(self.app.copilot).list(query='独有旧问题')
        self.assertEqual(value['items'][0]['thread_id'],later['id']);self.assertEqual(value['items'][0]['total_turns'],2)
        self.assertEqual(self.activity.list(module='intelligence')['total'],0)
        self.assertEqual(self.activity.list(demo=False)['total'],0)

    def test_activity_queries_do_not_write_or_invoke_models(self):
        self.send('overview','three','只读任务')
        with self.app.core.db() as db:before=db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]
        with patch('agent_runtime.model.invoke',side_effect=AssertionError('no model')):
            self.activity.list();self.assertEqual(self.activity.list(query="%' OR 1=1 --")['total'],0)
        with self.app.core.db() as db:self.assertEqual(before,db.execute('SELECT count(*) FROM agent_runs').fetchone()[0])
        for args in ({'status':'anything'},{'module':'invalid'},{'limit':1000},{'query':'x'*101}):
            with self.assertRaises(ValueError):self.activity.list(**args)
