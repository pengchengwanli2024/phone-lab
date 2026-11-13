"""Real startup recovery over temporary Core tasks, with only model IO doubled.

Process death is injected at a persisted boundary with BaseException so normal
failure finalizers cannot turn an unconfirmed submission into a known failure.
No native host, model, gateway or daily database is started by these tests.
"""
from collections import Counter
from copy import deepcopy
import unittest
from unittest.mock import patch

import test_market_research_contract as fixtures
from service import Commerce


class SimulatedProcessDeath(BaseException):
    pass


class HostRecoveryContract(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MarketResearchContract()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.restarted = []
        self.calls = Counter()
        self.routes = {
            host: self.app.host_execution.register(host, 'deepseek' if host == 'dsh' else 'codex',
                                                   'synthetic-' + host)
            for host in ('dsh', 'hermes', 'codex')
        }

    def tearDown(self):
        for app in self.restarted:
            app.agent_runtime.stop()
        self.fixture.tearDown()

    def send(self, hosts=None):
        thread = self.app.invoke('commerce_copilot_open', {
            'context': {'module': 'research', 'market': 'RU', 'demo': False},
            'idempotency_key': 'synthetic-recovery-thread',
        }, 'harness')
        args = {'thread_id': thread['id'], 'message': '请调研俄罗斯厨房收纳，采集资料并保存候选',
                'context_sha256': thread['context_sha256'], 'idempotency_key': 'synthetic-recovery-send'}
        if hosts:
            args['execution_hosts'] = [{'host_id': host,
                'expected_route_sha256': self.routes[host]['route_sha256']} for host in hosts]
        sent = self.app.invoke('commerce_copilot_send', args, 'harness')
        self.task_id, self.run_id, self.thread_id = sent['research_job']['task_id'], sent['latest_run']['id'], sent['id']
        return sent

    def job(self, app=None):
        return (app or self.app).invoke('commerce_market_research_get', {'task_id': self.task_id}, 'codex')

    def native_result(self, lease, cancelled):
        self.calls[(lease['host_id'], lease['phase'])] += 1
        request = lease['request']
        data = self.fixture.generate(lease['phase'], request['payload'], cancelled, request['route'])['data']
        return {'data': data, 'receipt': {'session_id': 'synthetic-native-' + lease['phase'],
            'provider': request['route']['provider'], 'model': request['route']['model'],
            'finish_reason': 'completed', 'tools_used': []}}

    def restart_quietly(self):
        app = Commerce(self.fixture.private.name)
        self.restarted.append(app)
        # Exercise the production startup sequence without letting its new
        # background runner infer, collect or claim any work during the assertion.
        with patch.object(app.agent_runtime, 'run_once', return_value=False), \
                patch('host_native.invoke', side_effect=AssertionError('Startup must not invoke a native model')), \
                patch('market_research.model.generate', side_effect=AssertionError('Startup must not invoke a legacy model')):
            app.agent_runtime.start(recover=True)
            app.agent_runtime.stop()
        return app

    def drive_successor(self, capture=None):
        app = Commerce(self.fixture.private.name)
        self.restarted.append(app)
        with patch('host_native.invoke', side_effect=self.native_result), \
                patch('market_research.collector.capture', side_effect=capture or self.fixture.capture):
            self.assertTrue(app.agent_runtime.run_once())
        return app

    def pending_crash(self, host='dsh'):
        self.send([host])
        if host == 'dsh':
            with patch('host_execution.time.sleep', side_effect=SimulatedProcessDeath()), \
                    patch('host_native.invoke', side_effect=AssertionError('Pending DSH work was not submitted')):
                with self.assertRaises(SimulatedProcessDeath):
                    self.app.agent_runtime.run_once()
        else:
            # Crash immediately before the real claim operation. The durable
            # request exists, but neither a worker nor provider accepted it.
            with patch.object(self.app.host_execution, 'claim', side_effect=SimulatedProcessDeath()):
                with self.assertRaises(SimulatedProcessDeath):
                    self.app.agent_runtime.run_once()
        attempts = self.app.host_execution.for_task(self.task_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]['status'], 'pending')
        return attempts[0]

    def completed_receipt_crash(self, phase):
        self.send(['codex'])
        checkpoint = self.app.market_research._checkpoint
        def stop_before_domain_checkpoint(*args, **changes):
            if ('_plan' if phase == 'planning' else '_analysis') in changes:
                raise SimulatedProcessDeath()
            return checkpoint(*args, **changes)
        with patch.object(self.app.market_research, '_checkpoint', side_effect=stop_before_domain_checkpoint), \
                patch('host_native.invoke', side_effect=self.native_result), \
                patch('market_research.collector.capture', side_effect=self.fixture.capture):
            with self.assertRaises(SimulatedProcessDeath):
                self.app.agent_runtime.run_once()
        attempt = self.app.host_execution.for_task(self.task_id)[-1]
        self.assertEqual(attempt['phase'], phase)
        self.assertEqual(attempt['status'], 'completed')
        return attempt

    def claimed_crash(self, phase='planning'):
        self.send(['hermes', 'codex'] if phase == 'planning' else ['codex', 'hermes', 'codex'])
        leases = []
        def stop_after_claim(lease, cancelled):
            if lease['phase'] == phase:
                leases.append(deepcopy(lease))
                raise SimulatedProcessDeath()
            return self.native_result(lease, cancelled)
        with patch('host_native.invoke', side_effect=stop_after_claim), \
                patch('market_research.collector.capture', side_effect=self.fixture.capture):
            with self.assertRaises(SimulatedProcessDeath):
                self.app.agent_runtime.run_once()
        self.assertEqual(len(leases), 1)
        self.assertEqual(self.app.host_execution.get(leases[0]['attempt_id'])['status'], 'claimed')
        return leases[0]

    def assert_one_business_task(self, app):
        with app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_threads').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_turns').fetchone()[0], 1)
        thread = app.invoke('commerce_copilot_get', {'thread_id': self.thread_id}, 'hermes')
        self.assertEqual(thread['research_job']['task_id'], self.task_id)

    def test_pending_unsubmitted_stage_is_queued_on_original_task_after_real_startup(self):
        self.pending_crash()
        app = self.restart_quietly()
        current = self.job(app)
        self.assertEqual(current['status'], 'queued')
        self.assertEqual(app.agent_runtime.get(current['run_id'])['status'], 'queued')
        self.assert_one_business_task(app)
        self.assertEqual(self.calls, {})

    def test_repeated_startup_does_not_duplicate_automatic_recovery(self):
        self.pending_crash()
        first = self.restart_quietly()
        first_job = self.job(first)
        self.assertEqual(first_job['status'], 'queued')
        with first.core.db() as db:
            count = db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]
        second = self.restart_quietly()
        self.assertEqual(self.job(second), first_job)
        with second.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], count)
        self.assert_one_business_task(second)

    def test_unsubmitted_stage_runs_on_authorized_host_after_startup(self):
        self.pending_crash('codex')
        app = self.restart_quietly()
        self.assertEqual(self.job(app)['status'], 'queued')
        done = self.drive_successor()
        self.assertEqual(self.job(done)['status'], 'partial')
        self.assertEqual(self.calls, {('codex', 'planning'): 1, ('codex', 'analyzing'): 1})
        self.assert_one_business_task(done)

    def test_completed_plan_receipt_is_reused_without_another_planning_call(self):
        original = self.completed_receipt_crash('planning')
        app = self.restart_quietly()
        self.assertEqual(self.job(app)['status'], 'queued')
        done = self.drive_successor()
        self.assertEqual(self.job(done)['status'], 'partial')
        self.assertEqual(self.calls[('codex', 'planning')], 1)
        plans = [a for a in done.host_execution.for_task(self.task_id) if a['phase'] == 'planning']
        self.assertEqual([a['attempt_id'] for a in plans], [original['attempt_id']])
        self.assert_one_business_task(done)

    def test_completed_analysis_receipt_retains_sources_and_never_recollects_or_reinfers(self):
        original = self.completed_receipt_crash('analyzing')
        sources = self.job()['sources']
        calls = self.calls.copy()
        app = self.restart_quietly()
        self.assertEqual(self.job(app)['status'], 'queued')
        def no_capture(*args):
            self.fail('Confirmed source collection was replayed after startup')
        done = self.drive_successor(capture=no_capture)
        self.assertEqual(self.job(done)['status'], 'partial')
        self.assertEqual(self.job(done)['sources'], sources)
        self.assertEqual(self.calls, calls)
        analysis = [a for a in done.host_execution.for_task(self.task_id) if a['phase'] == 'analyzing']
        self.assertEqual([a['attempt_id'] for a in analysis], [original['attempt_id']])
        self.assert_one_business_task(done)

    def test_claimed_unconfirmed_stage_becomes_unknown_and_does_not_requeue_itself(self):
        lease = self.claimed_crash()
        app = self.restart_quietly()
        self.assertEqual(self.job(app)['status'], 'unknown')
        self.assertEqual(app.host_execution.get(lease['attempt_id'])['status'], 'unknown')
        with app.core.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM agent_runs WHERE status='queued'").fetchone()[0], 0)
        self.assert_one_business_task(app)
        self.assertEqual(self.calls, {})

    def test_explicit_resume_after_unknown_uses_next_host_without_replaying_confirmed_sources(self):
        lease = self.claimed_crash('analyzing')
        sources = self.job()['sources']
        app = self.restart_quietly()
        unknown = self.job(app)
        self.assertEqual(unknown['status'], 'unknown')
        resumed = app.invoke('commerce_market_research_resume', {
            'task_id': self.task_id, 'expected_revision': unknown['revision'],
            'idempotency_key': 'synthetic-explicit-unknown-recovery'}, 'hermes')
        self.assertEqual(resumed['task_id'], self.task_id)
        def no_capture(*args):
            self.fail('Unknown recovery repeated confirmed collection')
        done = self.drive_successor(capture=no_capture)
        final = self.job(done)
        self.assertEqual(final['status'], 'partial')
        self.assertEqual(final['sources'], sources)
        self.assertEqual(self.calls[('codex', 'planning')], 1)
        self.assertEqual(self.calls[('codex', 'analyzing')], 1)
        self.assertEqual(self.calls[('hermes', 'analyzing')], 0)
        before = deepcopy(final)
        with self.assertRaises(ValueError) as failure:
            done.host_execution.finish(lease['attempt_id'], lease['generation'], lease['worker_id'],
                lease['lease_token'], 'completed', {'invented': True}, None)
        self.assertTrue(str(failure.exception).startswith('host_'))
        self.assertEqual(self.job(done), before)
        self.assert_one_business_task(done)

    def test_cancelled_host_plan_is_not_automatically_restarted(self):
        self.pending_crash()
        self.app.invoke('commerce_market_research_cancel', {'task_id': self.task_id}, 'codex')
        app = self.restart_quietly()
        self.assertEqual(self.job(app)['status'], 'cancelled')
        with app.core.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM agent_runs WHERE status='queued'").fetchone()[0], 0)
        self.assert_one_business_task(app)

    def test_legacy_task_without_host_plan_keeps_explicit_recovery_behavior(self):
        self.send()
        with patch('market_research.model.generate', side_effect=SimulatedProcessDeath()):
            with self.assertRaises(SimulatedProcessDeath):
                self.app.agent_runtime.run_once()
        app = self.restart_quietly()
        self.assertEqual(self.job(app)['status'], 'interrupted')
        self.assertEqual(app.agent_runtime.get(self.run_id)['status'], 'interrupted')
        self.assertEqual(app.host_execution.for_task(self.task_id), [])
        with app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], 1)
        self.assert_one_business_task(app)


if __name__ == '__main__':
    unittest.main()
