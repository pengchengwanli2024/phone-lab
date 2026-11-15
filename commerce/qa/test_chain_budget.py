"""Persisted local allowances charge reservations before synthetic dispatch."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import time
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce,TOOLS
from test_agent_runtime import answer,inspect


class ChainBudget(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('chain_budget'),'durable chain allowance is missing')
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
    def tearDown(self):self.app.agent_runtime.stop();self.temp.cleanup()
    def limits(self,**values):
        (Path(self.temp.name)/'chain-limits.json').write_text(json.dumps(values))
    def create(self,key='first',parent=None,question='你好'):
        if question=='你好':return self.app.agent_runtime.create(question,'conductor','workspace',key,parent_id=parent,parameters={'context':{'module':'overview'}})
        return self.app.agent_runtime.create(question,'conductor','runtime',key,parent_id=parent)
    def summary(self,run):return self.app.invoke('commerce_chain_budget_get',{'run_id':run['id']})
    def process(self,result):
        with patch('agent_runtime.model.invoke',return_value=result):self.app.agent_runtime.run_once()

    def test_reading_unmetered_history_creates_no_budget_or_model_request(self):
        self.assertIn('commerce_chain_budget_get',{name for name,_,_ in TOOLS})
        run=self.create();value=self.summary(run)
        self.assertIsNone(value['recorded_since']);self.assertEqual(value['usage']['model_steps'],0)
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM chain_budgets').fetchone()[0],0)

    def test_successor_cannot_reset_model_allowance_or_dispatch_after_exhaustion(self):
        self.limits(model_steps=1);first=self.create();self.process(answer(refs=[]))
        child=self.create('child',first['id'])
        with patch('agent_runtime.model.invoke') as generate:self.app.agent_runtime.run_once()
        generate.assert_not_called()
        value=self.app.agent_runtime.get(child['id'])
        self.assertEqual(value['result']['error'],'agent_chain_budget_exhausted')
        self.assertEqual(self.summary(first)['usage']['model_steps'],1)
        self.assertEqual(self.summary(first)['chain_id'],self.summary(child)['chain_id'])

    def test_read_allowance_is_checked_before_the_second_read_dispatch(self):
        self.limits(read_steps=1);run=self.create(question='检查本机运行状态')
        seen=[];original=self.app.invoke
        def invoke(name,*args,**kwargs):seen.append(name);return original(name,*args,**kwargs)
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),inspect('commerce_live_status')]),patch.object(self.app,'invoke',side_effect=invoke):
            self.app.agent_runtime.run_once()
        self.assertEqual(seen.count('commerce_runtime_status'),1);self.assertNotIn('commerce_live_status',seen)
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_chain_budget_exhausted')
        self.assertEqual(self.summary(run)['usage']['read_steps'],1)

    def test_unknown_reservation_remains_charged_after_a_new_service(self):
        self.limits(model_seconds=90);run=self.create()
        with patch('agent_runtime.model.invoke',side_effect=ValueError('agent_provider_outcome_unknown')):self.app.agent_runtime.run_once()
        other=Commerce(self.temp.name);value=other.chain_budget.summary(run['id'])
        self.assertEqual(value['usage']['model_steps'],1);self.assertEqual(value['usage']['model_seconds'],90)
        self.assertEqual(value['unconfirmed_steps'],1)
        self.assertEqual(other.agent_runtime.get(run['id'])['status'],'unknown')

    def test_research_resume_keeps_original_task_allowance(self):
        self.limits(model_steps=1)
        thread=self.app.copilot.open({'module':'research','market':'RU','demo':False},'research')
        sent=self.app.copilot.send(thread['id'],'请调研俄罗斯市场并采集资料保存候选',thread['context_sha256'],'research-send')
        with patch('market_research.model.generate',side_effect=ValueError('agent_provider_outcome_unknown')):self.app.agent_runtime.run_once()
        job=self.app.market_research.get(sent['research_job']['task_id'])
        self.app.market_research.resume(job['task_id'],job['revision'],'resume-after-limit')
        with patch('market_research.model.generate') as generate:self.app.agent_runtime.run_once()
        generate.assert_not_called()
        self.assertEqual(self.app.market_research.get(job['task_id'])['error']['code'],'agent_chain_budget_exhausted')
        self.assertEqual(self.summary(sent['latest_run'])['usage']['model_steps'],1)

    def test_exhausted_allowance_does_not_break_service_startup_recovery(self):
        from test_host_recovery_contract import HostRecoveryContract
        helper=HostRecoveryContract();helper.setUp()
        try:
            (Path(helper.fixture.private.name)/'chain-limits.json').write_text(json.dumps({'model_steps':1}))
            helper.pending_crash();restarted=helper.restart_quietly()
            self.assertEqual(helper.job(restarted)['status'],'queued')
        finally:helper.tearDown()

    def test_confirmed_native_analysis_can_be_published_without_another_model_allowance(self):
        from test_host_recovery_contract import HostRecoveryContract
        helper=HostRecoveryContract();helper.setUp()
        try:
            (Path(helper.fixture.private.name)/'chain-limits.json').write_text(json.dumps({'model_steps':2}))
            helper.completed_receipt_crash('analyzing');helper.restart_quietly()
            app=helper.drive_successor(capture=lambda *args:(_ for _ in ()).throw(AssertionError('do not recollect')))
            self.assertEqual(helper.job(app)['status'],'partial')
            self.assertEqual(sum(helper.calls.values()),2)
            self.assertEqual(app.chain_budget.summary(helper.job(app)['run_id'])['usage']['model_steps'],2)
        finally:helper.tearDown()

    def test_depth_fuse_pauses_only_its_task_instead_of_breaking_service_startup(self):
        from test_host_recovery_contract import HostRecoveryContract
        helper=HostRecoveryContract();helper.setUp()
        try:
            (Path(helper.fixture.private.name)/'chain-limits.json').write_text(json.dumps({'max_depth':1}))
            helper.pending_crash();restarted=helper.restart_quietly();job=helper.job(restarted)
            self.assertEqual(job['status'],'interrupted')
            self.assertEqual(job['error']['code'],'agent_chain_depth_exhausted')
        finally:helper.tearDown()

    def test_two_competing_reservations_cannot_overspend_one_remaining_step(self):
        self.limits(model_steps=1);run=self.create();barrier=Barrier(2)
        with self.app.core.db() as db:db.execute("UPDATE agent_runs SET status='running',owner=?,expires=? WHERE id=?",(self.app.agent_runtime.owner,time.time()+300,run['id']))
        def work(index):
            barrier.wait()
            try:
                with self.app.chain_budget.model_step(run['id'],'model:'+str(index),lambda:False):return 'admitted'
            except ValueError as error:return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(work,range(2)))
        self.assertEqual(results.count('admitted'),1);self.assertEqual(results.count('agent_chain_budget_exhausted'),1)

    def test_a_direct_child_of_a_research_run_cannot_escape_into_a_fresh_allowance(self):
        thread=self.app.copilot.open({'module':'research','market':'RU'},'bound-child')
        sent=self.app.copilot.send(thread['id'],'请调研俄罗斯市场并采集资料保存候选',thread['context_sha256'],'first')
        with patch('market_research.model.generate',return_value={'data':{'query_ru':'','questions':['请补齐品类']}}):self.app.agent_runtime.run_once()
        parent=self.app.agent_runtime.get(sent['latest_run']['id'])
        child=self.app.agent_runtime.create('你好','conductor',parent['topic'],'direct-child',parameters=parent['parameters'],parent_id=parent['id'])
        self.assertEqual(self.summary(parent)['chain_id'],self.summary(child)['chain_id'])
        self.assertEqual(self.summary(child)['usage']['model_steps'],1)

    def test_natural_clarification_binding_research_keeps_frozen_ancestor_allowance(self):
        self.limits(model_steps=1)
        thread=self.app.copilot.open({'module':'overview'},'clarification-chain')
        first=self.app.copilot.send(thread['id'],'请帮我调研市场',thread['context_sha256'],'first')
        with patch('agent_runtime.model.invoke',return_value=answer(questions=['请问哪个国家？'],refs=[])):self.app.agent_runtime.run_once()
        parent=self.summary(first['latest_run']);self.assertEqual(parent['usage']['model_steps'],1)
        self.limits(model_steps=100,max_depth=100)
        reply=self.app.copilot.send(thread['id'],'俄罗斯市场',thread['context_sha256'],'reply')
        child=self.summary(reply['latest_run'])
        self.assertEqual(child['chain_id'],parent['chain_id'])
        self.assertEqual(child['limits'],parent['limits'])
        self.assertGreater(child['depth'],parent['depth'])
        with patch('market_research.model.generate') as generate:self.app.agent_runtime.run_once()
        generate.assert_not_called()
        self.assertEqual(self.app.market_research.get(reply['research_job']['task_id'])['error']['code'],'agent_chain_budget_exhausted')

    def test_research_recovery_still_uses_the_external_ancestor_root_and_depth(self):
        thread=self.app.copilot.open({'module':'overview'},'ancestor-resume')
        first=self.app.copilot.send(thread['id'],'请帮我调研市场',thread['context_sha256'],'first')
        with patch('agent_runtime.model.invoke',return_value=answer(questions=['请问哪个国家？'],refs=[])):self.app.agent_runtime.run_once()
        reply=self.app.copilot.send(thread['id'],'俄罗斯市场',thread['context_sha256'],'reply')
        with patch('market_research.model.generate',side_effect=ValueError('agent_provider_outcome_unknown')):self.app.agent_runtime.run_once()
        job=self.app.market_research.get(reply['research_job']['task_id'])
        resumed=self.app.market_research.resume(job['task_id'],job['revision'],'resume')
        value=self.app.chain_budget.summary(resumed['run_id'])
        self.assertEqual(value['chain_id'],self.summary(first['latest_run'])['chain_id'])
        self.assertEqual(value['usage']['model_steps'],2)
        self.assertGreaterEqual(value['depth'],3)

    def test_depth_limit_remains_frozen_when_clarification_enters_research(self):
        self.limits(max_depth=2)
        thread=self.app.copilot.open({'module':'overview'},'depth-transition')
        self.app.copilot.send(thread['id'],'请帮我调研市场',thread['context_sha256'],'first')
        with patch('agent_runtime.model.invoke',return_value=answer(questions=['请问哪个国家？'],refs=[])):self.app.agent_runtime.run_once()
        self.limits(max_depth=100)
        reply=self.app.copilot.send(thread['id'],'俄罗斯市场',thread['context_sha256'],'reply')
        with patch('market_research.model.generate',return_value={'data':{'query_ru':'','questions':['请补齐品类']}}):self.app.agent_runtime.run_once()
        self.assertEqual(self.summary(reply['latest_run'])['depth'],2)
        with self.assertRaisesRegex(ValueError,'agent_chain_depth_exhausted'):
            self.app.copilot.send(thread['id'],'厨房收纳',thread['context_sha256'],'third')

    def test_prior_split_accounting_is_folded_without_deleting_or_rewriting_steps(self):
        self.limits(model_steps=1)
        thread=self.app.copilot.open({'module':'overview'},'old-accounting')
        first=self.app.copilot.send(thread['id'],'请帮我调研市场',thread['context_sha256'],'first')
        with patch('agent_runtime.model.invoke',return_value=answer(questions=['请问哪个国家？'],refs=[])):self.app.agent_runtime.run_once()
        reply=self.app.copilot.send(thread['id'],'俄罗斯市场',thread['context_sha256'],'reply')
        # The pre-fix version created a separate allowance when research bound.
        alias='task:'+reply['research_job']['task_id'];run_id=reply['latest_run']['id']
        old_limits={**self.summary(first['latest_run'])['limits'],'model_steps':100}
        with self.app.core.db() as db:
            db.execute('INSERT INTO chain_budgets VALUES(?,?,?,?)',(alias,json.dumps(old_limits),time.time(),0))
            db.execute('INSERT INTO chain_steps VALUES(?,?,?,?,?,?,?,?)',(alias,run_id,'research:planning','model','unknown',time.time(),time.time(),90))
            before=db.execute('SELECT * FROM chain_steps ORDER BY rowid').fetchall()
        replacement=Commerce(self.temp.name);value=replacement.chain_budget.summary(run_id)
        self.assertEqual(value['chain_id'],self.summary(first['latest_run'])['chain_id'])
        self.assertEqual(value['usage']['model_steps'],2)
        self.assertEqual(value['limits']['model_steps'],1)
        with replacement.core.db() as db:
            self.assertEqual(db.execute('SELECT * FROM chain_steps ORDER BY rowid').fetchall(),before)
            self.assertEqual(db.execute('SELECT count(*) FROM chain_budget_aliases').fetchone()[0],1)

    def test_bulk_allowance_projection_matches_individual_reads_without_creating_rows(self):
        first=self.create();self.process(answer(refs=[]));child=self.create('bulk-child',first['id'])
        before=self.summary(child)
        with self.app.core.db() as db:
            db.execute('BEGIN');values=self.app.chain_budget.summaries(db,[first['id'],child['id']])
        self.assertEqual(values,[before])

    def test_waiting_for_human_input_does_not_charge_elapsed_wall_time(self):
        self.limits(model_seconds=90);run=self.create();self.process(answer(questions=['请补齐资料'],refs=[]))
        before=self.summary(run)['usage']['model_seconds']
        self.assertFalse(self.summary(run)['historical_usage_unrecorded'])
        with patch('chain_budget.time.time',return_value=time.time()+86400):after=self.summary(run)['usage']['model_seconds']
        self.assertEqual(before,after);self.assertLess(after,1)

    def test_elapsed_step_budget_stops_the_owned_model_and_retains_uncertain_occupancy(self):
        from agent_runtime.model import Cancelled
        self.limits(model_seconds=2);run=self.create();clock=[10.0]
        def generate(context,cancelled,**kwargs):
            clock[0]=13.0;self.assertTrue(cancelled());raise Cancelled()
        with patch('chain_budget.time.monotonic',side_effect=lambda:clock[0]),patch('agent_runtime.model.invoke',side_effect=generate):
            self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_chain_budget_exhausted')
        self.assertEqual(self.summary(run)['unconfirmed_steps'],1)
        self.assertGreaterEqual(self.summary(run)['usage']['model_seconds'],2)

    def test_excess_parent_depth_is_rejected_before_a_new_run_is_queued(self):
        self.limits(max_depth=1);first=self.create();self.process(answer(refs=[]))
        with self.assertRaisesRegex(ValueError,'agent_chain_depth_exhausted'):self.create('too-deep',first['id'])
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],1)


if __name__=='__main__':unittest.main()
