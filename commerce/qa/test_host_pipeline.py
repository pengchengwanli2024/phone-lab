"""Synthetic worker/provider fixtures verify the real shared domain wiring.

Native host execution, public network capture and live process failure are
separate acceptance. These tests never use daily state or real model accounts.
"""
from concurrent.futures import ThreadPoolExecutor
import time
import unittest
from unittest.mock import patch
import test_market_research_contract as fixtures


class HostPipeline(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.MarketResearchContract();self.fixture.setUp();self.app=self.fixture.app
        self.plan=[]
        for host,provider in [('dsh','synthetic'),('hermes','codex'),('codex','codex')]:
            route=self.app.host_execution.register(host,provider,'synthetic-model')
            self.plan.append({'host_id':host,'expected_route_sha256':route['route_sha256']})
        thread=self.app.copilot.open({'module':'research','market':'RU','demo':False},'synthetic-host-pipeline')
        self.original=self.app.copilot.send(thread['id'],'请调研俄罗斯厨房收纳用品并保存候选',
            thread['context_sha256'],'synthetic-host-send',execution_hosts=self.plan)
        self.task=self.original['research_job']['task_id'];self.native_calls=[]

    def tearDown(self):self.fixture.tearDown()

    def result(self,lease):
        request=lease['request'];route=request['route']
        data=self.fixture.generate(lease['phase'],request['payload'],lambda:False,route)['data']
        return {'data':data,'receipt':{'session_id':'synthetic-'+lease['attempt_id'],'provider':route['provider'],
            'model':route['model'],'finish_reason':'completed','tools_used':[]}}

    def execute(self,unknown_hermes=False):
        def native(lease,cancelled):
            self.native_calls.append(lease['host_id'])
            if lease['host_id']=='hermes' and unknown_hermes:raise ValueError('agent_provider_outcome_unknown')
            return self.result(lease)
        with patch('market_research.collector.capture',side_effect=self.fixture.capture),patch('host_native.invoke',side_effect=native),patch('market_research.model.generate',side_effect=AssertionError('Frozen host plan must not fall through to the default provider')):
            with ThreadPoolExecutor(max_workers=1) as pool:
                running=pool.submit(self.app.agent_runtime.run_once);end=time.monotonic()+5
                while not running.done() and time.monotonic()<end:
                    lease=self.app.host_execution.claim('dsh','synthetic-dsh-worker')
                    if lease:
                        result=self.result(lease)
                        self.app.host_execution.finish(lease['attempt_id'],lease['generation'],lease['worker_id'],lease['lease_token'],
                            'completed',result['data'],{**result['receipt'],'request_id':lease['request_id']})
                    time.sleep(.01)
                self.assertTrue(running.done(),'Shared host pipeline stalled')
                self.assertTrue(running.result())
        return self.app.market_research.get(self.task)

    def test_confirmed_planning_automatically_continues_to_next_host_and_original_candidate(self):
        job=self.execute()
        self.assertEqual(job['status'],'partial')
        self.assertEqual([a['host_id'] for a in job['host_attempts']],['dsh','hermes'])
        self.assertTrue(all(a['status']=='completed' for a in job['host_attempts']))
        self.assertEqual(job['candidate_count'],1)
        self.assertEqual(self.fixture.task_count(),1)
        case=self.app.product_workspace.get(job['candidates'][0]['case_id'])
        self.assertEqual(case['calculation']['status'],'HOLD')

    def test_unknown_host_pauses_and_explicit_recovery_uses_next_host_without_recapturing(self):
        unknown=self.execute(unknown_hermes=True)
        self.assertEqual(unknown['status'],'unknown')
        self.assertEqual(unknown['host_attempts'][-1]['status'],'unknown')
        captures=self.fixture.executed['capture'];calls=list(self.native_calls)
        for _ in range(3):self.app.copilot.get(self.original['id'])
        self.assertEqual(self.native_calls,calls)
        self.assertEqual(self.fixture.executed['capture'],captures)
        resumed=self.app.market_research.resume(self.task,unknown['revision'],'explicit-synthetic-recovery')
        final=self.execute()
        self.assertEqual(final['task_id'],self.task)
        self.assertEqual(final['run_id'],resumed['run_id'])
        self.assertEqual(final['status'],'partial')
        self.assertEqual(self.fixture.executed['capture'],captures)
        self.assertEqual([a['host_id'] for a in final['host_attempts']],['dsh','hermes','codex'])
        self.assertEqual([a['status'] for a in final['host_attempts']],['completed','unknown','completed'])
        self.assertEqual(self.fixture.task_count(),1)


if __name__=='__main__':unittest.main()
