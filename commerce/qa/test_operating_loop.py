"""Operating loop: synthetic store, mocked model; no network or external action."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from test_agent_cases import inspect, answer


class OperatingLoopTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests();self.fixture.setUp();self.app = self.fixture.app
        self.loop = self.app.operating_loop;self.cid = self.fixture.cid
        self.target = {'case_id': self.cid, 'platform': 'ozon', 'store_ref': 'ozon-live', 'market': 'RU'}

    def tearDown(self):
        self.app.agent_runtime.stop();self.app.autonomy.stop();self.fixture.tearDown()

    def grant(self, level='prepare', stages=('research', 'sourcing', 'economics'), enable=True, **extra):
        args = dict(target=self.target, goal='launch', stages=list(stages), level=level, max_runs_per_day=6, expected_revision=0)
        args.update(extra)
        value = self.loop.grant_save(**args)
        if enable: value = self.loop.grant_enable(value['id'], value['revision'], True)
        return value

    def runs(self):
        with self.app.core.db() as db: return db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]

    def tasks(self):
        with self.app.core.db() as db: return db.execute('SELECT count(*) FROM tasks').fetchone()[0]

    def model(self, stage='S1', final=None):
        return patch('agent_runtime.model.invoke', side_effect=[inspect(self.cid, stage), final or answer()])

    def proposed(self):
        grant = self.grant();first = self.loop.advance(grant['id'])
        with self.model(): self.app.agent_runtime.run_once()
        self.loop.advance(grant['id'])
        return grant, self.loop.get(grant['id'])['work'][0], first

    def test_saved_grant_is_disabled_and_dispatches_nothing(self):
        grant = self.grant(enable=False)
        self.assertFalse(grant['enabled']);self.assertFalse(grant['external_execution_allowed'])
        self.loop.tick(at=time.time() + 600)
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'grant_disabled')
        self.assertEqual((self.runs(), self.loop.get()['work']), (0, []))

    def test_grant_rejects_unknown_stage_other_case_and_stale_revision(self):
        with self.assertRaisesRegex(ValueError, 'operating_loop_invalid_stages'): self.grant(stages=('payments',))
        with self.assertRaisesRegex(ValueError, 'operating_loop_invalid_grant'): self.grant(level='execute')
        with self.assertRaisesRegex(ValueError, 'organization_case_not_found'):
            self.grant(target={**self.target, 'case_id': 'missing'})
        grant = self.grant(enable=False)
        with self.assertRaisesRegex(ValueError, 'operating_loop_revision_conflict'): self.grant(enable=False)
        with self.assertRaisesRegex(ValueError, 'operating_loop_revision_conflict'):
            self.loop.grant_enable(grant['id'], grant['revision'] + 1, True)

    def test_editing_a_grant_disables_it_until_enabled_again(self):
        grant = self.grant()
        edited = self.loop.grant_save(target=self.target, goal='launch', stages=['research'], level='observe',
                                      max_runs_per_day=1, expected_revision=grant['revision'])
        self.assertFalse(edited['enabled']);self.assertEqual(edited['id'], grant['id'])

    def test_first_eligible_stage_becomes_one_bounded_request_for_its_owner(self):
        grant = self.grant();outcome = self.loop.advance(grant['id'])
        work = outcome['dispatched']
        self.assertEqual((work['stage_id'], work['owner'], work['status']), ('research', 'scout', 'dispatched'))
        run = self.app.agent_runtime.get(work['run_id'])
        self.assertEqual((run['topic'], run['role']['id'], run['parameters']), ('organization_case', 'scout', {'case_id': self.cid, 'stage_id': 'S1'}))
        self.assertEqual(self.runs(), 1);self.assertEqual(self.tasks(), 0)

    def test_repeated_events_and_restart_never_duplicate_work_or_model_requests(self):
        grant = self.grant();self.loop.advance(grant['id'])
        for _ in range(3): self.assertEqual(self.loop.advance(grant['id'])['reason'], 'work_in_flight')
        self.loop.tick(at=time.time() + 600)
        restarted = type(self.loop)(self.app);restarted.tick(at=time.time() + 1200)
        self.assertEqual((self.runs(), len(self.loop.get()['work'])), (1, 1))

    def test_blocked_dependency_is_not_dispatched_ahead_of_its_upstream(self):
        grant = self.grant(stages=('economics',))
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'nothing_eligible')
        self.assertEqual(self.runs(), 0)

    def test_proposal_waits_for_decision_and_unchanged_evidence_stays_idle(self):
        grant, work, _ = self.proposed()
        self.assertEqual(work['status'], 'awaiting_decision');self.assertEqual(len(work['proposals']), 1)
        self.assertEqual(self.loop.get()['needs_attention'][0]['id'], work['id'])
        self.assertEqual(self.tasks(), 0)
        with patch('agent_runtime.model.invoke') as model:
            for _ in range(3): self.assertEqual(self.loop.advance(grant['id'])['reason'], 'awaiting_your_decision')
            self.app.agent_runtime.run_once();model.assert_not_called()
        self.assertEqual(self.runs(), 1)

    def test_approval_requires_exact_result_and_resumes_original_handoff_once(self):
        _, work, _ = self.proposed()
        with self.assertRaisesRegex(ValueError, 'operating_loop_result_changed'):
            self.loop.decide(work['id'], 'approve', 'f' * 64, 'P1')
        with self.assertRaisesRegex(ValueError, 'operating_loop_proposal_not_found'):
            self.loop.decide(work['id'], 'approve', work['result_sha256'], 'P9')
        done = self.loop.decide(work['id'], 'approve', work['result_sha256'], 'P1')
        again = self.loop.decide(work['id'], 'approve', work['result_sha256'], 'P1')
        self.assertTrue(again['reused']);self.assertFalse(done['external_operations_executed'])
        self.assertEqual(done['work']['status'], 'completed');self.assertEqual(self.tasks(), 1)
        task = self.app.core.invoke('commerce_task_get', {'task_id': done['work']['decision']['task_id']})
        self.assertEqual((task['input']['organization_case'], task['input']['organization_stage']), (self.cid, 'S1'))
        with self.assertRaisesRegex(ValueError, 'operating_loop_already_decided'):
            self.loop.decide(work['id'], 'reject', work['result_sha256'])

    def test_rejection_creates_no_task(self):
        _, work, _ = self.proposed()
        self.assertEqual(self.loop.decide(work['id'], 'reject', work['result_sha256'])['work']['status'], 'rejected')
        self.assertEqual(self.tasks(), 0)

    def test_evidence_changed_before_approval_is_refused_by_original_review(self):
        _, work, _ = self.proposed();self.fixture.org.set_currency(self.cid, 'CNY')
        with self.assertRaisesRegex(ValueError, 'agent_case_evidence_changed'):
            self.loop.decide(work['id'], 'approve', work['result_sha256'], 'P1')
        self.assertEqual(self.tasks(), 0)
        self.assertEqual(self.loop.get()['work'][0]['status'], 'awaiting_decision')

    def test_new_evidence_creates_a_new_work_item_and_upstream_completion_unblocks_next_stage(self):
        grant, work, _ = self.proposed();self.loop.decide(work['id'], 'reject', work['result_sha256'])
        self.fixture.prepare_research()
        outcome = self.loop.advance(grant['id'])
        self.assertEqual(outcome['dispatched']['stage_id'], 'sourcing')
        self.assertEqual(outcome['dispatched']['owner'], 'sourcer');self.assertEqual(self.runs(), 2)

    def test_unknown_result_blocks_further_dispatch_until_explicitly_resolved(self):
        grant = self.grant();work = self.loop.advance(grant['id'])['dispatched']
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='interrupted' WHERE id=?", (work['run_id'],))
        self.fixture.prepare_research()
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'unknown_requires_check')
        self.assertEqual(self.runs(), 1)
        with self.assertRaisesRegex(ValueError, 'operating_loop_not_awaiting_decision'):
            self.loop.decide(work['id'], 'approve', 'a' * 64, 'P1')
        resolved = self.loop.resolve(work['id'], '已核对原请求，未产生结果')
        self.assertFalse(resolved['resubmitted']);self.assertEqual(self.runs(), 1)
        self.assertEqual(self.loop.advance(grant['id'])['dispatched']['stage_id'], 'sourcing')

    def test_disabling_stops_later_dispatch_but_keeps_issued_work_readable(self):
        grant = self.grant();work = self.loop.advance(grant['id'])['dispatched']
        current = self.loop.get(grant['id'])['grants'][0]
        self.loop.grant_enable(grant['id'], current['revision'], False)
        with self.model(): self.app.agent_runtime.run_once()
        self.fixture.prepare_research();self.loop.tick(at=time.time() + 600)
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'grant_disabled')
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.loop.get(grant['id'])['work'][0]['id'], work['id'])

    def test_expired_grant_and_daily_limit_stop_dispatch(self):
        grant = self.grant(expires_at=time.time() + 1)
        self.assertEqual(self.loop._advance(grant['id'], time.time() + 5)['reason'], 'grant_expired')
        with self.assertRaisesRegex(ValueError, 'operating_loop_invalid_expiry'): self.grant(expires_at=1.0, expected_revision=2)
        self.assertEqual(self.runs(), 0)

    def test_daily_limit_holds_new_evidence_until_next_window(self):
        grant = self.grant(max_runs_per_day=1);work = self.loop.advance(grant['id'])['dispatched']
        with self.model(): self.app.agent_runtime.run_once()
        self.loop.advance(grant['id']);pending = self.loop.get(grant['id'])['work'][0]
        self.loop.decide(pending['id'], 'reject', pending['result_sha256']);self.fixture.prepare_research()
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'daily_limit')
        self.assertEqual(self.loop._advance(grant['id'], time.time() + 90000)['dispatched']['stage_id'], 'sourcing')

    def test_three_consecutive_failures_halt_the_grant(self):
        grant = self.grant()
        with patch.object(self.app.agent_runtime, 'create', side_effect=ValueError('agent_case_unavailable')):
            self.loop.advance(grant['id'])
            for index in range(2):
                self.fixture.org.set_currency(self.cid, ('CNY', 'RUB')[index]);self.loop.advance(grant['id'])
            self.assertEqual(self.loop.advance(grant['id'])['reason'], 'halted_consecutive_failures')
        view = self.loop.get(grant['id'])
        self.assertEqual((view['grants'][0]['enabled'], view['grants'][0]['halted_reason']), (False, 'consecutive_failures'))
        self.assertEqual(self.runs(), 0)

    def test_observe_level_records_the_gap_and_owner_without_any_model_request(self):
        grant = self.grant(level='observe');outcome = self.loop.advance(grant['id'])
        self.assertEqual(outcome['reason'], 'recorded_gap_without_executor')
        self.assertEqual((outcome['dispatched']['status'], outcome['dispatched']['owner']), ('waiting_input', 'scout'))
        self.assertTrue(outcome['dispatched']['missing']);self.assertEqual(self.runs(), 0)
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'no_new_evidence')

    def statuses(self, grant):
        return sorted((w['stage_id'], w['status']) for w in self.loop.get(grant['id'])['work'])

    def test_a_gap_record_is_closed_when_its_evidence_moves_on(self):
        grant = self.grant(level='observe');self.loop.advance(grant['id'])
        self.assertEqual(self.statuses(grant), [('research', 'waiting_input')])
        self.fixture.prepare_research();self.loop.advance(grant['id'])
        # The research gap no longer describes the product; only the current gap is outstanding.
        self.assertEqual(self.statuses(grant), [('research', 'superseded'), ('sourcing', 'waiting_input')])
        self.assertEqual([w['stage_id'] for w in self.loop.get(grant['id'])['needs_attention']], ['sourcing'])

    def test_an_unchanged_gap_record_stays_open(self):
        grant = self.grant(level='observe');self.loop.advance(grant['id']);self.loop.advance(grant['id'])
        self.assertEqual(self.statuses(grant), [('research', 'waiting_input')])

    def test_a_stage_with_a_proposal_awaiting_the_operator_is_not_dispatched_again(self):
        grant, work, _ = self.proposed()
        self.fixture.org.set_currency(self.cid, 'CNY')  # evidence moved while the person has not decided
        with patch('agent_runtime.model.invoke') as model:
            outcome = self.loop.advance(grant['id']);self.app.agent_runtime.run_once();model.assert_not_called()
        self.assertEqual(outcome['reason'], 'awaiting_your_decision')
        self.assertEqual(self.runs(), 1);self.assertEqual(self.statuses(grant), [('research', 'awaiting_decision')])
        self.loop.decide(work['id'], 'reject', work['result_sha256'])
        self.assertEqual(self.loop.advance(grant['id'])['dispatched']['stage_id'], 'research')
        self.assertEqual(self.runs(), 2)

    def test_re_enabling_a_halted_grant_does_not_halt_again_on_the_old_failures(self):
        grant = self.grant()
        with patch.object(self.app.agent_runtime, 'create', side_effect=ValueError('agent_case_unavailable')):
            self.loop.advance(grant['id'])
            for currency in ('CNY', 'RUB'):
                self.fixture.org.set_currency(self.cid, currency);self.loop.advance(grant['id'])
            self.assertEqual(self.loop.advance(grant['id'])['reason'], 'halted_consecutive_failures')
        halted = self.loop.get(grant['id'])['grants'][0]
        self.loop.grant_enable(grant['id'], halted['revision'], True)
        outcome = self.loop.advance(grant['id'])
        self.assertNotEqual(outcome['reason'], 'halted_consecutive_failures')
        current = self.loop.get(grant['id'])['grants'][0]
        self.assertEqual((current['enabled'], current['halted_reason']), (True, None))

    def test_a_pending_decision_on_one_stage_does_not_hold_back_an_independent_stage(self):
        # In this fixture sourcing is the only open stage with an executor; policy is open and independent.
        self.fixture.prepare_research()
        grant = self.grant(stages=('research', 'sourcing', 'policy'))
        self.assertEqual(self.loop.advance(grant['id'])['dispatched']['stage_id'], 'sourcing')
        with self.model('S3'): self.app.agent_runtime.run_once()
        outcome = self.loop.advance(grant['id'])
        self.assertEqual((outcome['reason'], outcome['dispatched']['stage_id']), ('recorded_gap_without_executor', 'policy'))
        self.assertEqual(dict(self.statuses(grant)), {'sourcing': 'awaiting_decision', 'policy': 'waiting_input'})
        self.assertEqual(self.runs(), 1)

    def test_daily_limit_still_records_gaps_and_is_reported_only_when_it_is_the_reason(self):
        self.fixture.prepare_research()
        grant = self.grant(stages=('sourcing', 'policy'), max_runs_per_day=1)
        self.loop.advance(grant['id'])
        with self.model('S3'): self.app.agent_runtime.run_once()
        # Sourcing now waits for a decision; the policy gap is still recorded, and no limit is blamed.
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'recorded_gap_without_executor')
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'awaiting_your_decision')
        pending = next(w for w in self.loop.get(grant['id'])['work'] if w['stage_id'] == 'sourcing')
        self.loop.decide(pending['id'], 'reject', pending['result_sha256']);self.fixture.org.set_currency(self.cid, 'CNY')
        self.loop.advance(grant['id'])
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'daily_limit')
        self.assertEqual(self.runs(), 1)

    def test_raising_a_grant_from_observe_to_prepare_dispatches_the_gap_it_only_recorded(self):
        grant = self.grant(level='observe');self.loop.advance(grant['id'])
        self.assertEqual(self.statuses(grant), [('research', 'waiting_input')])
        raised = self.loop.grant_save(target=self.target, goal='launch', stages=['research', 'sourcing'], level='prepare',
                                      max_runs_per_day=3, expected_revision=grant['revision'])
        self.loop.grant_enable(raised['id'], raised['revision'], True)
        outcome = self.loop.advance(grant['id'])
        self.assertEqual((outcome['reason'], outcome['dispatched']['stage_id'], outcome['dispatched']['executor']), ('dispatched', 'research', 'agent_runtime'))
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.statuses(grant), [('research', 'dispatched'), ('research', 'superseded')])
        self.assertEqual(self.loop.advance(grant['id'])['reason'], 'work_in_flight');self.assertEqual(self.runs(), 1)

    def test_lowering_a_grant_to_observe_never_dispatches(self):
        grant = self.grant();self.loop.advance(grant['id'])
        with self.model(): self.app.agent_runtime.run_once()
        self.loop.advance(grant['id']);work = self.loop.get(grant['id'])['work'][0]
        self.loop.decide(work['id'], 'reject', work['result_sha256'])
        current = self.loop.get(grant['id'])['grants'][0]
        lowered = self.loop.grant_save(target=self.target, goal='launch', stages=['research'], level='observe', max_runs_per_day=3, expected_revision=current['revision'])
        self.loop.grant_enable(lowered['id'], lowered['revision'], True)
        self.fixture.org.set_currency(self.cid, 'CNY');self.loop.advance(grant['id'])
        self.assertEqual(self.runs(), 1)

    def stale_calculation(self):
        values = self.fixture.prepare_cost();view = self.app.product_workspace.get(self.cid)
        values = {**values, 'price': values['price'] + 1}
        self.app.product_workspace.save(self.cid, 'cost', {'input': values}, 0, view['source_sha256'])
        return values

    def economics(self):
        return self.app.product_workspace.org.artifact(self.cid, 'economics')['payload']

    def test_changed_cost_inputs_are_recalculated_deterministically_without_a_model_request(self):
        values = self.stale_calculation();self.assertNotEqual(self.economics()['price'], values['price'])
        grant = self.grant(stages=('economics',))
        with patch('agent_runtime.model.invoke') as model:
            outcome = self.loop.advance(grant['id']);model.assert_not_called()
        work = outcome['dispatched']
        self.assertEqual(outcome['reason'], 'calculated_locally')
        self.assertEqual((work['stage_id'], work['executor'], work['status'], work['run_id']), ('economics', 'local_calculator', 'completed', None))
        self.assertEqual(self.economics()['price'], values['price'])
        self.assertEqual(self.runs(), 0)
        again = self.loop.advance(grant['id'])
        self.assertNotEqual(again['reason'], 'calculated_locally')
        self.assertEqual(sum(w['executor'] == 'local_calculator' for w in self.loop.get()['work']), 1)

    def test_observe_level_never_recalculates(self):
        values = self.stale_calculation();grant = self.grant(level='observe', stages=('economics',))
        self.loop.advance(grant['id'])
        self.assertNotEqual(self.economics()['price'], values['price'])
        self.assertFalse(any(w['executor'] == 'local_calculator' for w in self.loop.get()['work']))

    def test_recalculation_refused_by_the_original_guard_is_recorded_not_retried(self):
        self.stale_calculation();grant = self.grant(stages=('economics',))
        with patch.object(self.app.product_workspace, 'calculate', side_effect=ValueError('workspace_source_changed')) as calc:
            outcome = self.loop.advance(grant['id']);self.loop.advance(grant['id'])
            self.assertEqual(calc.call_count, 1)
        self.assertEqual((outcome['dispatched']['status'], outcome['dispatched']['error']), ('failed', 'workspace_source_changed'))

    def test_recalculation_is_limited_to_the_granted_stage(self):
        values = self.stale_calculation();grant = self.grant(stages=('research',))
        self.loop.advance(grant['id'])
        self.assertNotEqual(self.economics()['price'], values['price'])

    def test_service_and_mcp_registration_keep_only_the_read_annotated(self):
        import operating_loop, service
        names = {name for name, _, _ in service.TOOLS if name.startswith('commerce_operating_loop_')}
        self.assertEqual(len(names), 6);self.assertEqual(operating_loop.READ_ONLY, {'commerce_operating_loop_get'})
        grant = self.grant(enable=False)
        view = self.app.invoke('commerce_operating_loop_get', {}, 'test')
        self.assertFalse(view['external_execution_allowed'])
        self.assertEqual((view['grants'][0]['id'], view['grants'][0]['case_available'], view['grants'][0]['synthetic']), (grant['id'], True, False))
        # A real inventory case has no label; it is named like the product workspace names it.
        self.assertIsNone(self.fixture.case['scope'].get('label'))
        self.assertEqual(view['grants'][0]['case_label'], self.app.product_workspace.label(self.fixture.case))
        self.assertEqual(view['grants'][0]['case_label'], self.fixture.case['scope']['sku'])
        catalog = {row['id']: row for row in view['stage_catalog']}
        self.assertTrue(catalog['research']['executable']);self.assertFalse(catalog['listing']['executable'])
        self.assertEqual(catalog['economics']['depends_on'], ['sourcing'])
        with self.assertRaisesRegex(ValueError, 'unknown_tool'): self.loop.invoke('commerce_operating_loop_pay', {})


if __name__ == '__main__':
    unittest.main()
