"""A replaced parent owner must fence all late domain writes, not only receipts.

Only synthetic temporary state is used. The fixture changes one running parent's
owner to model an executor takeover; it never starts a host, server or model.
"""
from copy import deepcopy
import time
import unittest

import test_market_research_contract as fixtures
from market_research import model as research_model


class HostParentFencing(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MarketResearchContract()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.invoke = self.fixture.invoke
        self.original = self.fixture.send_research(key='synthetic-parent-takeover')
        self.task_id = self.original['research_job']['task_id']
        self.run_id = self.original['latest_run']['id']
        self.successor_owner = 'synthetic-successor-owner'

    def tearDown(self):
        self.fixture.tearDown()

    def take_over_same_run(self):
        with self.app.core.atomic() as db:
            changed = db.execute("UPDATE agent_runs SET owner=?,expires=? WHERE id=? AND status='running'",
                                 (self.successor_owner, time.time() + 360, self.run_id)).rowcount
            self.assertEqual(changed, 1)
            document = db.execute('SELECT document FROM market_research_jobs WHERE task_id=?',
                                  (self.task_id,)).fetchone()[0]
        job = self.invoke('commerce_market_research_get', {'task_id': self.task_id}, 'hermes')
        self.assertEqual(job['run_id'], self.run_id)
        self.assertEqual(job['status'], 'running')
        return {'job': deepcopy(job), 'document': document, 'owner': self.successor_owner}

    def expire_current_parent(self):
        owner = self.app.agent_runtime.owner
        with self.app.core.atomic() as db:
            changed = db.execute("UPDATE agent_runs SET expires=0 WHERE id=? AND owner=? AND status='running'",
                                 (self.run_id, owner)).rowcount
            self.assertEqual(changed, 1)
            document = db.execute('SELECT document FROM market_research_jobs WHERE task_id=?',
                                  (self.task_id,)).fetchone()[0]
        job = self.invoke('commerce_market_research_get', {'task_id': self.task_id}, 'hermes')
        return {'job': deepcopy(job), 'document': document, 'owner': owner}

    def assert_successor_unchanged(self, before):
        current = self.invoke('commerce_market_research_get', {'task_id': self.task_id}, 'codex')
        self.assertEqual(current, before['job'], 'The old parent changed the successor business task')
        task = self.invoke('commerce_task_get', {'task_id': self.task_id}, 'harness')
        self.assertEqual(task['status'], before['job']['status'])
        self.assertEqual(self.fixture.task_count(), 1)
        with self.app.core.db() as db:
            after = db.execute('SELECT document FROM market_research_jobs WHERE task_id=?',
                               (self.task_id,)).fetchone()[0]
            self.assertEqual(after, before['document'],
                             'Internal plan, analysis, evidence or revision changed after parent replacement')
            self.assertEqual(db.execute('SELECT count(*) FROM org_cases').fetchone()[0], 0,
                             'An old parent must not publish candidates')
            parent = db.execute('SELECT owner,status,result FROM agent_runs WHERE id=?',
                                (self.run_id,)).fetchone()
            self.assertEqual(parent, (before['owner'], 'running', None))

    def delayed_model(self, target_phase, outcome, take_over=None):
        accepted = []

        def generate(phase, payload, cancelled, route):
            result = self.fixture.generate(phase, payload, cancelled, route)
            if phase == target_phase and not accepted:
                accepted.append((take_over or self.take_over_same_run)())
                if outcome == 'failed':
                    raise ValueError('agent_provider_failed_no_automatic_retry')
                if outcome == 'unknown':
                    raise ValueError('agent_provider_outcome_unknown')
                if outcome == 'cancelled':
                    raise research_model.transport.Cancelled()
            return result

        self.fixture.execute(generate=generate)
        self.assertEqual(len(accepted), 1)
        self.assert_successor_unchanged(accepted[0])

    def test_old_planning_success_cannot_change_new_parent(self):
        self.delayed_model('planning', 'success')

    def test_old_planning_failure_cannot_fail_new_parent(self):
        self.delayed_model('planning', 'failed')

    def test_old_planning_cancellation_cannot_cancel_new_parent(self):
        self.delayed_model('planning', 'cancelled')

    def test_old_analysis_success_cannot_publish_for_new_parent(self):
        self.delayed_model('analyzing', 'success')

    def test_old_analysis_failure_cannot_fail_new_parent(self):
        self.delayed_model('analyzing', 'failed')

    def test_old_analysis_unknown_cannot_replace_new_parent_status(self):
        self.delayed_model('analyzing', 'unknown')

    def test_old_analysis_cancellation_cannot_cancel_new_parent(self):
        self.delayed_model('analyzing', 'cancelled')

    def test_expired_parent_cannot_store_late_planning_result(self):
        self.delayed_model('planning', 'success', self.expire_current_parent)

    def test_expired_parent_cannot_store_late_analysis_result(self):
        self.delayed_model('analyzing', 'success', self.expire_current_parent)

    def test_old_capture_cannot_append_evidence_after_parent_replacement(self):
        accepted = []

        def capture(url, directory, cancelled):
            page = self.fixture.capture(url, directory, cancelled)
            if not accepted:
                accepted.append(self.take_over_same_run())
            return page

        self.fixture.execute(capture=capture)
        self.assertEqual(len(accepted), 1)
        self.assert_successor_unchanged(accepted[0])


if __name__ == '__main__':
    unittest.main()
