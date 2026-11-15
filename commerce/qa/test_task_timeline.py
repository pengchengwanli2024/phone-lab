"""Unified history is a read projection, never a reconstruction of missing facts."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce,TOOLS
from test_agent_runtime import answer,inspect
import test_followups as followups_fixture


class TaskTimeline(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('task_timeline'),'unified read history is missing')
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
    def tearDown(self):self.app.agent_runtime.stop();self.temp.cleanup()
    def read(self,kind,ident,**args):return self.app.invoke('commerce_task_timeline_get',{'kind':kind,'id':ident,**args})
    def snapshot(self):
        with self.app.core.db() as db:
            return {name:db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall()for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='clients'")}

    def test_task_execution_reads_original_receipts_without_state_or_model_changes(self):
        self.assertIn('commerce_task_timeline_get',{n for n,_,_ in TOOLS})
        task=self.app.core.invoke('commerce_task_create',{'kind':'report','input':{'demo':True},'idempotency_key':'timeline-task'})
        self.app.autonomy.request(task['id'],'report');self.app.autonomy.work(1800000000)
        before=self.snapshot()
        with patch('agent_runtime.model.invoke') as model:
            value=self.read('task',task['id'])
        self.assertEqual(self.snapshot(),before);model.assert_not_called()
        self.assertTrue(value['demo']);self.assertTrue(value['read_only'])
        self.assertIn('local_execution_finished',{e['event']for e in value['events']})
        current=next(e for e in value['events']if e['event']=='task_current')
        self.assertIsNone(current['at'])

    def test_parent_requests_decision_and_model_budget_share_the_original_chain(self):
        first=self.app.agent_runtime.create('检查本机运行状态','conductor','runtime','first')
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer(questions=['请补充资料'])]):self.app.agent_runtime.run_once()
        second=self.app.agent_runtime.create('补充合成资料','conductor','runtime','second',parent_id=first['id'])
        value=self.read('run',second['id'])
        self.assertEqual(set(value['run_ids']),{first['id'],second['id']})
        self.assertIn('human_request',{e['event']for e in value['events']})
        self.assertIn('model_step',{e['event']for e in value['events']})
        self.assertEqual(value['budgets'][0]['usage']['model_steps'],2)
        self.assertEqual(value['budgets'][0]['depth'],2)

    def test_run_history_includes_the_actual_local_task_created_by_its_proposal(self):
        import test_attention
        helper=test_attention.Attention();helper.app=self.app;helper.counter=0
        run=helper.run_record(proposals=[helper.proposal()])
        applied=self.app.agent_runtime.apply(run['id'],'P1',run['result_sha256'])
        self.app.autonomy.work(1800000000)
        value=self.read('run',run['id'])
        self.assertTrue(any(e['event']=='local_execution_finished' and e['source_id']==applied['task']['id']for e in value['events']))
        self.assertFalse(value['demo'])
        self.assertTrue(value['mixed_modes'])
        self.assertFalse(next(e for e in value['events']if e['event']=='human_request')['demo'])
        self.assertTrue(next(e for e in value['events']if e['event']=='task_current')['demo'])

    def test_a_recovery_run_is_not_presented_as_another_human_question(self):
        thread=self.app.copilot.open({'module':'research','market':'RU'},'recovery')
        sent=self.app.copilot.send(thread['id'],'请调研俄罗斯市场并采集资料保存候选',thread['context_sha256'],'first')
        with patch('market_research.model.generate',side_effect=ValueError('agent_provider_outcome_unknown')):self.app.agent_runtime.run_once()
        job=self.app.market_research.get(sent['research_job']['task_id'])
        resumed=self.app.market_research.resume(job['task_id'],job['revision'],'recover')
        events=self.read('task',job['task_id'])['events']
        self.assertTrue(any(e['event']=='run_recovery_created' and e['source_id']==resumed['run_id']for e in events))
        self.assertFalse(any(e['event']=='human_request' and e['source_id']==resumed['run_id']for e in events))

    def test_followup_scope_change_keeps_history_bound_to_its_original_revision(self):
        helper=followups_fixture.Followups();helper.app=self.app
        import test_attention
        helper.fixture=test_attention.Attention();helper.fixture.app=self.app;helper.fixture.counter=0
        thread=helper.fixture.thread();run=helper.fixture.run_record(thread=thread,questions=['原范围问题'])
        target=next(t['target']for t in helper.targets()['targets']if t['target']['kind']=='attention')
        saved=self.app.followups.create(target,followups_fixture.date(1900000000),'timeline-followup')
        self.app.copilot.context(thread['id'],{'module':'products'},thread['context_sha256'])
        value=self.read('followup',saved['id'])
        self.assertFalse(value['scope_current']);self.assertEqual(value['run_ids'],[run['id']])
        self.assertIn('followup_current',{e['event']for e in value['events']})
        created=next(e for e in value['events']if e['event']=='followup_created')
        self.assertEqual(created['detail']['source_version_sha256'],target['version_sha256'])

    def test_legacy_trace_facts_are_retained_without_inventing_model_times_or_usage(self):
        run=self.app.agent_runtime.create('检查本机运行状态','conductor','runtime','legacy')
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]):self.app.agent_runtime.run_once()
        with self.app.core.db() as db:
            db.execute('DELETE FROM chain_steps');db.execute('DELETE FROM chain_budgets')
        value=self.read('run',run['id'])
        self.assertEqual(sum(e['event']=='model_step_legacy'for e in value['events']),2)
        self.assertTrue(all(e['at'] is None for e in value['events']if e['event']=='model_step_legacy'))
        self.assertTrue(any(e['event']=='read_evidence'for e in value['events']))
        self.assertTrue(value['budgets'][0]['historical_usage_unrecorded'])

    def test_demo_research_context_is_authoritative_for_its_task_events(self):
        thread=self.app.copilot.open({'module':'research','market':'RU','demo':True},'demo-research')
        sent=self.app.copilot.send(thread['id'],'请调研俄罗斯市场并采集资料保存候选',thread['context_sha256'],'demo-send')
        value=self.read('task',sent['research_job']['task_id'])
        self.assertTrue(value['demo']);self.assertFalse(value['mixed_modes'])
        self.assertTrue(all(event['demo'] is True for event in value['events']))

    def test_event_pagination_has_no_duplicates_and_does_not_silently_drop_old_history(self):
        run=self.app.agent_runtime.create('检查本机运行状态','conductor','runtime','pages')
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]):self.app.agent_runtime.run_once()
        first=self.read('run',run['id'],limit=2)
        self.assertTrue(first['has_more']);second=self.read('run',run['id'],limit=2,cursor=first['next_cursor'])
        self.assertFalse(set(e['id']for e in first['events'])&set(e['id']for e in second['events']))
        all_events=self.read('run',run['id'],limit=100)['events']
        self.assertGreater(len(all_events),2)

    def test_invalid_or_missing_references_are_rejected_without_expanding_the_scope(self):
        for kind,ident in [('shell','ls'),('task','../private'),('run','f'*32)]:
            with self.assertRaises(ValueError):self.read(kind,ident)


if __name__=='__main__':unittest.main()
