"""Cross-client recovery must fence late work from a superseded attempt.

Only temporary synthetic state is used. Crash fixtures update the old runner's
status as startup recovery does; recovery requests and reads use public tools.
Native host scheduling and live process interruption require separate acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest

import test_market_research_contract as fixtures


class HostContinuationContract(unittest.TestCase):
    def setUp(self):
        # Compose the existing fixture without inheriting/re-running its 14 tests.
        self.fixture = fixtures.MarketResearchContract()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.invoke = self.fixture.invoke

    def tearDown(self):
        self.fixture.tearDown()

    def interrupt_and_resume(self, task_id, old_run_id):
        self.app.market_research.recover()
        with self.app.core.atomic() as db:
            db.execute("UPDATE agent_runs SET status='interrupted',expires=0 WHERE id=?", (old_run_id,))
        job = self.invoke('commerce_market_research_get', {'task_id': task_id}, 'hermes')
        self.assertEqual(job['status'], 'interrupted')
        resumed = self.invoke('commerce_market_research_resume', {
            'task_id': task_id, 'expected_revision': job['revision'],
            'idempotency_key': 'synthetic-cross-host-recovery',
        }, 'hermes')
        self.assertNotEqual(resumed['run_id'], old_run_id)
        self.assertEqual(resumed['task_id'], task_id)
        self.assertEqual(resumed['status'], 'queued')
        return deepcopy(resumed)

    def assert_current_attempt_unchanged(self, accepted):
        current = self.invoke('commerce_market_research_get', {'task_id': accepted['task_id']}, 'codex')
        self.assertEqual(current, accepted,
                         'A late old attempt changed the accepted successor status, revision or evidence')
        self.assertEqual(self.app.agent_runtime.get(accepted['run_id'])['status'], 'queued')
        self.assertEqual(self.fixture.task_count(), 1)
        self.assertEqual(self.invoke('commerce_task_get', {'task_id': accepted['task_id']})['status'], 'queued')
        self.assertEqual(current['candidates'], [])

    def late_capture(self, outcome):
        original = self.fixture.send_research()
        task_id, old_run_id = original['research_job']['task_id'], original['latest_run']['id']
        accepted = []

        def capture(url, directory, cancelled):
            page = self.fixture.capture(url, directory, cancelled)
            if not accepted:
                accepted.append(self.interrupt_and_resume(task_id, old_run_id))
                if outcome == 'failed':
                    raise ValueError('market_research_capture_failed')
            return page

        self.fixture.execute(capture=capture)
        self.assertEqual(len(accepted), 1)
        self.assert_current_attempt_unchanged(accepted[0])

    def test_late_capture_success_cannot_add_evidence_or_cancel_successor(self):
        self.late_capture('success')

    def test_late_capture_failure_cannot_cancel_successor(self):
        self.late_capture('failed')

    def late_model(self, target_phase, outcome):
        original = self.fixture.send_research()
        task_id, old_run_id = original['research_job']['task_id'], original['latest_run']['id']
        accepted = []

        def generate(phase, payload, cancelled, route):
            result = self.fixture.generate(phase, payload, cancelled, route)
            if phase == target_phase and not accepted:
                accepted.append(self.interrupt_and_resume(task_id, old_run_id))
                if outcome == 'unknown':
                    raise ValueError('agent_provider_outcome_unknown')
            return result

        self.fixture.execute(generate=generate)
        self.assertEqual(len(accepted), 1)
        self.assert_current_attempt_unchanged(accepted[0])

    def test_late_planning_success_cannot_write_plan_or_status_to_successor(self):
        self.late_model('planning', 'success')

    def test_late_analysis_success_cannot_write_analysis_or_publish_candidates(self):
        self.late_model('analyzing', 'success')

    def test_late_analysis_unknown_cannot_overwrite_successor_with_unknown(self):
        self.late_model('analyzing', 'unknown')

    def test_simultaneous_clients_replay_one_recovery_without_duplicate_attempt(self):
        thread, job = self.fixture.unknown_research()
        arguments = {'task_id': job['task_id'], 'expected_revision': job['revision'],
                     'idempotency_key': 'synthetic-shared-recovery-receipt'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: self.invoke(
                'commerce_market_research_resume', arguments, client), ('hermes', 'codex')))
        self.assertEqual(results[0]['task_id'], results[1]['task_id'])
        self.assertEqual(results[0]['run_id'], results[1]['run_id'])
        self.assertNotEqual(results[0]['run_id'], job['run_id'])
        self.assertEqual(self.fixture.task_count(), 1)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM market_research_retries').fetchone()[0], 1)
        same_thread = self.invoke('commerce_copilot_get', {'thread_id': thread['id']}, 'harness')
        self.assertEqual(same_thread['research_job']['run_id'], results[0]['run_id'])


if __name__ == '__main__':
    unittest.main()
