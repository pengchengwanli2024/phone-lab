"""Synthetic native IO over real public dialogue/research and lease boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import test_market_research_contract as fixtures


POLICY={'mode':'auto','enabled':True,'priority':['dsh','hermes','codex']}


class ProcessDeath(BaseException):pass


class AutoResearchContract(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.MarketResearchContract();self.f.setUp();self.app=self.f.app
        (Path(self.f.private.name)/'conversation-routing.json').write_text(json.dumps(POLICY))
        self.app.host_execution.register('hermes','codex','synthetic-hermes')
        self.app.host_execution.register('codex','codex','synthetic-codex')
        self.addCleanup(self.f.tearDown)
        for guard in [patch('host_execution.shutil.which',return_value=None),patch('agent_runtime.codex_provider.KNOWN_BINARIES',()),patch('host_native.hermes_command',side_effect=ValueError('host_unavailable'))]:
            guard.start();self.addCleanup(guard.stop)
        self.calls=[]

    def send(self,question='请调研俄罗斯市场并采集资料',key='send',thread=None):
        thread=thread or self.app.copilot.open({'module':'research','market':'RU','demo':False},key+':thread')
        return self.app.copilot.send(thread['id'],question,thread['context_sha256'],key)

    def native(self,lease,cancelled):
        self.calls.append(deepcopy(lease))
        if lease['phase']=='planning' and len(self.calls)==1:
            data={'query_ru':'','questions':['您希望调研哪个品类？']}
        else:data=self.f.generate(lease['phase'],lease['request']['payload'],cancelled,lease['request']['route'])['data']
        route=lease['request']['route']
        return {'data':data,'receipt':{'session_id':'synthetic-'+lease['attempt_id'],
            'provider':route['provider'],'model':route['model'],'finish_reason':'completed','tools_used':[]}}

    def execute(self,native=None):
        with patch('host_native.invoke',side_effect=native or self.native),patch('market_research.collector.capture',side_effect=self.f.capture),patch('market_research.model.generate',side_effect=AssertionError('Native plan must not use legacy model')):
            self.assertTrue(self.app.agent_runtime.run_once())

    def awaiting(self):
        first=self.send();self.execute()
        current=self.app.copilot.get(first['id']);self.assertEqual(current['research_job']['status'],'awaiting_input')
        return current

    def test_default_native_research_clarification_continues_one_task_and_one_host(self):
        first=self.awaiting();task=first['research_job']['task_id']
        following=self.send('厨房收纳盒',key='clarification',thread=first);self.execute()
        final=self.app.copilot.get(first['id'])['research_job']
        self.assertEqual(final['task_id'],task)
        self.assertEqual(final['status'],'partial')
        self.assertEqual(final['candidate_count'],1)
        self.assertEqual(self.f.task_count(),1)
        self.assertEqual([c['host_id'] for c in self.calls],['hermes','hermes','hermes'])
        self.assertEqual(following['latest_run']['parent_id'],first['latest_run']['id'])

    def test_frozen_native_research_rejects_changing_model_before_persisting_selection(self):
        current=self.awaiting();selection=current['model_selection']
        with self.assertRaisesRegex(ValueError,'host_plan_model_conflict'):
            self.app.models.select(current['id'],'project-default',selection['revision'])
        self.assertEqual(self.app.copilot.get(current['id'])['model_selection'],selection)

    def test_explicit_multi_host_plan_does_not_consume_a_host_for_missing_human_input(self):
        hosts=self.app.host_execution.listing()['hosts']
        plan=[{'host_id':name,'expected_route_sha256':next(r['route_sha256'] for r in hosts if r['host_id']==name)} for name in ['hermes','codex']]
        thread=self.app.copilot.open({'module':'research','market':'RU','demo':False},'explicit-clarification')
        sent=self.app.copilot.send(thread['id'],'请调研俄罗斯市场并采集资料',thread['context_sha256'],'explicit-send',execution_hosts=plan)
        self.execute()
        self.send('厨房收纳盒',key='explicit-followup',thread=self.app.copilot.get(thread['id']))
        self.execute()
        final=self.app.copilot.get(thread['id'])['research_job']
        self.assertEqual(final['task_id'],sent['research_job']['task_id'])
        self.assertEqual([(c['host_id'],c['phase']) for c in self.calls],[('hermes','planning'),('hermes','planning'),('codex','analyzing')])

    def test_send_rejects_conflicting_model_binding_left_by_an_older_client(self):
        current=self.awaiting()
        with self.app.core.db() as db:
            db.execute('INSERT INTO copilot_models VALUES(?,?,?)',(current['id'],'project-default',1))
        with self.assertRaisesRegex(ValueError,'host_plan_model_conflict'):
            self.send('厨房收纳盒',key='conflicting-followup',thread=current)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(self.app.copilot.get(current['id'])['turns']),1)

    def test_explicit_retry_does_not_reuse_a_native_plan_rejected_by_domain_validation(self):
        sent=self.send('请调研俄罗斯厨房收纳盒市场并采集资料')
        def native(lease,cancelled):
            self.calls.append(deepcopy(lease));route=lease['request']['route']
            data=({'query_ru':'x'*121,'questions':[]} if len(self.calls)==1 else
                  self.f.generate(lease['phase'],lease['request']['payload'],cancelled,route)['data'])
            return {'data':data,'receipt':{'session_id':'synthetic-'+lease['attempt_id'],'provider':route['provider'],
                'model':route['model'],'finish_reason':'completed','tools_used':[]}}
        self.execute(native)
        failed=self.app.market_research.get(sent['research_job']['task_id'])
        self.assertEqual(failed['error']['code'],'market_research_invalid_plan')
        self.app.market_research.resume(failed['task_id'],failed['revision'],'explicit-domain-retry')
        self.execute(native)
        final=self.app.market_research.get(failed['task_id'])
        self.assertEqual(final['status'],'partial')
        self.assertEqual([call['phase'] for call in self.calls],['planning','planning','analyzing'])
        self.assertEqual(self.f.task_count(),1)

    def test_other_context_does_not_inherit_the_old_research_execution_plan(self):
        current=self.awaiting()
        changed=self.app.copilot.context(current['id'],{'module':'orders','demo':False},current['context_sha256'])
        self.app.host_execution.register('dsh','synthetic-dsh','synthetic-dsh')
        sent=self.send('你好',key='new-context',thread=changed)
        self.assertEqual(sent['latest_run']['model_choice']['host_id'],'dsh')
        with self.app.core.db() as db:
            payload=json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?',(sent['latest_run']['id'],)).fetchone()[0])
        self.assertNotIn('execution_hosts',payload)
        self.assertEqual(self.f.task_count(),1)

    def test_generic_claimed_request_is_unknown_after_restart_and_old_lease_cannot_finish(self):
        sent=self.send('你好');leases=[]
        def die(lease,cancelled):leases.append(deepcopy(lease));raise ProcessDeath()
        with self.assertRaises(ProcessDeath):self.execute(die)
        from service import Commerce
        restarted=Commerce(self.f.private.name);self.addCleanup(restarted.agent_runtime.stop)
        with patch.object(restarted.agent_runtime,'run_once',return_value=False):
            restarted.agent_runtime.start(recover=True);restarted.agent_runtime.stop()
        current=restarted.agent_runtime.get(sent['latest_run']['id'])
        self.assertEqual(current['status'],'unknown')
        self.assertEqual(current['host_attempts'][0]['status'],'unknown')
        self.assertEqual(self.f.task_count(),0)
        lease=leases[0]
        with self.assertRaises(ValueError):
            restarted.host_execution.finish(lease['attempt_id'],lease['generation'],lease['worker_id'],lease['lease_token'],'completed',{},None)

    def test_generic_two_model_steps_share_one_frozen_host_and_real_read_scope(self):
        sent=self.send('当前后台运行状态如何？');calls=[]
        def native(lease,cancelled):
            calls.append(deepcopy(lease));context=lease['request']['payload'];route=lease['request']['route']
            if not context['observations']:
                self.assertIn('commerce_runtime_status',[t['tool'] for t in context['tools']])
                decision={'phase':'inspect','calls':[{'tool':'commerce_runtime_status','arguments_json':'{}'}]}
                self.app.host_execution.register('dsh','synthetic-dsh','synthetic-dsh')
            else:decision={'phase':'answer','answer':'已读取本机运行状态，未进行外部操作。','questions':[],'evidence_refs':['R1'],'proposals':[]}
            return {'data':{'decision':decision},'receipt':{'session_id':'synthetic-'+lease['attempt_id'],'provider':route['provider'],'model':route['model'],'finish_reason':'completed','tools_used':[]}}
        self.execute(native)
        run=self.app.agent_runtime.get(sent['latest_run']['id'])
        self.assertEqual(run['status'],'completed')
        self.assertEqual([c['host_id'] for c in calls],['hermes','hermes'])
        self.assertEqual([a['phase'] for a in run['host_attempts']],['dialogue_1','dialogue_2'])
        self.assertEqual(self.f.task_count(),0)

    def test_cancel_at_native_request_boundary_does_not_dispatch_or_report_failure(self):
        sent=self.send('你好');original=self.app.host_execution.request
        def cancel_then_request(*args,**kwargs):
            self.app.copilot.cancel(sent['id'],sent['latest_run']['id'])
            return original(*args,**kwargs)
        with patch.object(self.app.host_execution,'request',side_effect=cancel_then_request):
            self.execute()
        run=self.app.agent_runtime.get(sent['latest_run']['id'])
        self.assertEqual(run['status'],'cancelled')
        self.assertEqual(self.calls,[])
        self.assertEqual(run['host_attempts'],[])

    def test_failed_native_exit_preserves_unknown_parent_and_blocks_legacy_failed_record_reroute(self):
        sent=self.send('你好')
        def failed_exit(lease,cancelled):raise ValueError('agent_provider_failed_no_automatic_retry')
        self.execute(failed_exit)
        run=self.app.agent_runtime.get(sent['latest_run']['id'])
        self.assertEqual(run['host_attempts'][0]['status'],'unknown')
        self.assertEqual(run['status'],'unknown')
        # Older versions could already have persisted the inconsistent parent.
        with self.app.core.db() as db:db.execute("UPDATE agent_runs SET status='failed' WHERE id=?",(run['id'],))
        self.app.host_execution.register('dsh','synthetic-dsh','synthetic-dsh')
        with self.assertRaisesRegex(ValueError,'unknown'):
            self.send('继续',key='do-not-reroute',thread=self.app.copilot.get(sent['id']))

    def test_new_auto_chat_is_allowed_after_original_unknown_research_was_explicitly_recovered(self):
        sent=self.send('请调研俄罗斯厨房收纳盒市场并采集资料');failed=[False]
        def native(lease,cancelled):
            if lease['phase']=='analyzing' and not failed[0]:
                failed[0]=True;raise ValueError('agent_provider_outcome_unknown')
            route=lease['request']['route']
            return {'data':self.f.generate(lease['phase'],lease['request']['payload'],cancelled,route)['data'],
                'receipt':{'session_id':'synthetic-'+lease['attempt_id'],'provider':route['provider'],
                    'model':route['model'],'finish_reason':'completed','tools_used':[]}}
        self.execute(native)
        unknown=self.app.market_research.get(sent['research_job']['task_id'])
        self.assertEqual(unknown['status'],'unknown')
        self.app.market_research.resume(unknown['task_id'],unknown['revision'],'explicit-recovery')
        self.execute(native)
        self.assertEqual(self.app.market_research.get(unknown['task_id'])['status'],'partial')
        try:following=self.send('谢谢',key='after-success',thread=self.app.copilot.get(sent['id']))
        except ValueError as error:self.fail('Resolved research still blocks a new chat: '+str(error))
        self.assertEqual(following['latest_run']['status'],'queued')
        self.assertEqual(self.f.task_count(),1)
        with self.app.core.db() as db:
            payload=json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?',(following['latest_run']['id'],)).fetchone()[0])
        current=self.app.market_research.get(unknown['task_id'])
        self.assertEqual(payload['current_research']['task_id'],current['task_id'])
        self.assertEqual(payload['current_research']['status'],'partial')
        self.assertEqual(payload['current_research']['candidate_count'],1)
        self.assertEqual(payload['current_research']['questions'],[])
        self.assertEqual(following['latest_run']['parent_id'],current['run_id'])
        self.assertIn('已保存 1 个研究候选',payload['previous']['answer'])
        self.assertEqual(payload['conversation'][-1]['run_id'],current['run_id'])
        seen=[]
        def reply(lease,cancelled):
            seen.append(deepcopy(lease['request']['payload']));route=lease['request']['route']
            return {'data':{'decision':{'phase':'answer','answer':'不客气。','questions':[],
                    'evidence_refs':[],'proposals':[]}},'receipt':{
                    'session_id':'synthetic-'+lease['attempt_id'],'provider':route['provider'],
                    'model':route['model'],'finish_reason':'completed','tools_used':[]}}
        self.execute(reply)
        self.assertEqual(seen[0]['current_research'],payload['current_research'])
        original=self.app.copilot.get(sent['id'])
        changed=self.app.copilot.context(sent['id'],{'module':'orders','demo':False},original['context_sha256'])
        outside=self.send('谢谢',key='outside-recovered-scope',thread=changed)
        with self.app.core.db() as db:
            other=json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?',(outside['latest_run']['id'],)).fetchone()[0])
        self.assertNotIn('current_research',other)
        self.assertEqual(other['conversation'],[])
        self.assertIsNone(other.get('parent_id'))

    def test_explicit_cancellation_does_not_poison_subsequent_automatic_chat(self):
        sent=self.send('你好')
        from agent_runtime.model import Cancelled
        def cancel(lease,cancelled):
            self.app.copilot.cancel(sent['id'],sent['latest_run']['id']);raise Cancelled()
        self.execute(cancel)
        current=self.app.copilot.get(sent['id'])
        self.assertEqual(current['latest_run']['status'],'cancelled')
        following=self.send('谢谢',key='new-after-cancel',thread=current)
        self.assertEqual(following['latest_run']['status'],'queued')
        self.assertEqual(self.f.task_count(),0)

    def assert_unknown_survives_policy_change(self,remove):
        policy=Path(self.f.private.name)/'conversation-routing.json'
        sent=self.send('你好',key='unknown-policy')
        def fail(lease,cancelled):raise ValueError('agent_provider_outcome_unknown')
        self.execute(fail)
        self.assertEqual(self.app.copilot.get(sent['id'])['latest_run']['status'],'unknown')
        if remove:policy.unlink()
        else:policy.write_text(json.dumps({**POLICY,'enabled':False}))
        with self.assertRaisesRegex(ValueError,'unknown'):
            self.send('继续',key='disabled-policy-followup',thread=self.app.copilot.get(sent['id']))
        self.assertEqual(len(self.app.copilot.get(sent['id'])['turns']),1)

    def test_disabling_auto_policy_cannot_reroute_an_unknown_native_turn(self):
        self.assert_unknown_survives_policy_change(False)

    def test_removing_auto_policy_cannot_reroute_an_unknown_native_turn(self):
        self.assert_unknown_survives_policy_change(True)


if __name__=='__main__':unittest.main()
