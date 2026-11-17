"""Synthetic SQLite behavior: money, original identities and uncertain outcomes."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class OperatingBudgetTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('operating_budget'), 'operating budget implementation missing')
        from operating_budget import OperatingBudget
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = Core(Path(self.temp.name) / 'test.sqlite')
        self.budget = OperatingBudget(self.core)
        self.seq = 0
        self.bindings = [self.task('purchase', 'sourcing'), self.task('advertising', 'growth')]

    def key(self):
        self.seq += 1
        return 'synthetic-' + str(self.seq)

    def task(self, kind='purchase', role='sourcing', demo=True):
        action = {'id': 'original-action', 'kind': kind, 'role': role, 'input': {'sku': 'SYN-SKU', 'version': 1}}
        data = {'demo': demo, 'budget_actions': [action]}
        task = self.core.invoke('commerce_task_create', {'kind': 'draft', 'input': data, 'idempotency_key': self.key()})
        return {'task_id': task['id'], 'action_id': action['id'], 'task_input_sha256': sha(data), 'action_input_sha256': sha(action['input'])}

    def configure(self, cap='20.00', revision=0, mode='synthetic', bindings=None, key=None, **overrides):
        task_ids = sorted(b['task_id'] for b in (bindings or self.bindings))
        confirmation = {'kind': 'local_operator', 'name': 'synthetic-admin', 'confirmed': True,
                        'expected_revision': revision, 'policy_sha256': sha({'mode': mode, 'cap_minor': int(Decimal(cap) * 100), 'task_ids': task_ids})}
        return self.budget.policy_save(mode, cap, task_ids, revision, key or self.key(), overrides.get('operator_confirmation', confirmation))

    def reserve(self, amount='8.00', binding=None, key=None, mode='synthetic', revision=1, **kw):
        return self.budget.reserve(mode, binding or self.bindings[0], amount, revision, key or self.key(), **kw)

    def event(self, r, event, *, binding=None, key=None, mode='synthetic', **kw):
        return self.budget.transition(mode, r['record']['id'], binding or self.bindings[0], event,
                                      r['record']['revision'], key or self.key(), **kw)

    def evidence(self, ref='SYN-PAYMENT'):
        return {'source': 'synthetic-fixture', 'external_id': ref, 'record_sha256': 'a' * 64}

    def paid(self, amount='8.00', reserved='8.00', binding=None):
        r = self.reserve(reserved, binding)
        i = self.event(r, 'intent', binding=binding, expected_policy_revision=1)
        return self.event(i, 'paid', binding=binding, amount_cny=amount, evidence=self.evidence(self.key()))

    def test_unconfigured_restart_and_reads_do_not_create_or_reset_a_policy(self):
        self.assertFalse(self.budget.policy_get('synthetic')['policy']['configured'])
        with self.assertRaisesRegex(ValueError, 'policy_unconfigured'):
            self.reserve()
        self.configure(); self.reserve()
        from operating_budget import OperatingBudget
        other = OperatingBudget(self.core)
        self.assertEqual(other.policy_get('synthetic')['usage']['held_minor'], 800)
        self.assertEqual(other.policy_get('synthetic')['policy']['revision'], 1)

    def test_cross_role_concurrent_reservations_share_one_total_cap(self):
        self.configure('10.00'); barrier = Barrier(2)
        def work(index):
            barrier.wait()
            try:
                return self.reserve('7.00', self.bindings[index], key='race-' + str(index))['record']['status']
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, range(2)))
        self.assertEqual(sorted(results), ['RESERVED', 'budget_cap_exceeded'])
        self.assertEqual(self.budget.ledger('synthetic')['usage']['held_minor'], 700)

    def test_same_key_returns_original_receipt_after_later_events_and_conflicts_on_changed_input(self):
        self.configure(); r = self.reserve(key='stable-reserve')
        i = self.event(r, 'intent', key='stable-intent', expected_policy_revision=1)
        self.event(i, 'unknown', evidence={'reason': 'timeout'})
        self.assertEqual(self.reserve(key='stable-reserve'), r)
        self.assertEqual(self.event(r, 'intent', key='stable-intent', expected_policy_revision=1), i)
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.reserve('9.00', key='stable-reserve')
        with self.assertRaisesRegex(ValueError, 'action_already_bound'):
            self.reserve(key='fresh-key')

    def test_unknown_holds_budget_cannot_release_or_repeat_intent_but_can_record_paid(self):
        self.configure('10.00'); r = self.reserve()
        i = self.event(r, 'intent', expected_policy_revision=1)
        u = self.event(i, 'unknown', evidence={'reason': 'timeout'})
        for action in ('release', 'intent'):
            with self.assertRaisesRegex(ValueError, 'invalid_transition'):
                self.event(u, action, expected_policy_revision=1)
        with self.assertRaisesRegex(ValueError, 'budget_cap_exceeded'):
            self.reserve('3.00', self.bindings[1])
        p = self.event(u, 'paid', amount_cny='7.00', evidence=self.evidence())
        self.assertEqual(p['usage']['gross_paid_minor'], 700)
        self.assertEqual(p['usage']['held_minor'], 0)

    def test_over_reserved_actual_is_recorded_and_halts_new_money_even_if_cap_would_fit(self):
        self.configure('20.00'); p = self.paid('9.00', '8.00')
        self.assertEqual(p['record']['paid_minor'], 900)
        self.assertTrue(p['policy']['halted'])
        self.assertEqual(p['usage']['over_reservation_minor'], 100)
        with self.assertRaisesRegex(ValueError, 'budget_halted'):
            self.reserve('1.00', self.bindings[1])
        self.configure('30.00', revision=1)
        self.assertTrue(self.budget.policy_get('synthetic')['policy']['halted'])

    def test_over_cap_actual_is_not_suppressed(self):
        self.configure('10.00'); p = self.paid('12.00')
        self.assertEqual(p['usage']['over_cap_minor'], 200)
        self.assertEqual(p['usage']['available_minor'], 0)

    def test_refund_binds_original_paid_receipt_and_cannot_recycle_or_duplicate(self):
        self.configure('10.00'); p = self.paid()
        args = {'amount_cny': '3.00', 'paid_receipt_id': p['receipt_id'], 'evidence': self.evidence('SYN-REFUND')}
        refund = self.event(p, 'refund', key='stable-refund', **args)
        self.assertEqual(self.event(p, 'refund', key='stable-refund', **args), refund)
        self.assertEqual(refund['usage']['available_minor'], 200)
        self.assertEqual(refund['usage']['net_paid_minor'], 500)
        with self.assertRaisesRegex(ValueError, 'duplicate_external_record'):
            self.event(refund, 'refund', **args)
        with self.assertRaisesRegex(ValueError, 'refund_exceeds_paid'):
            self.event(refund, 'refund', amount_cny='6.00', paid_receipt_id=p['receipt_id'], evidence=self.evidence('SYN-REFUND-2'))
        with self.assertRaisesRegex(ValueError, 'paid_receipt_mismatch'):
            self.event(refund, 'refund', amount_cny='1.00', paid_receipt_id='unrelated', evidence=self.evidence('SYN-REFUND-3'))
        with self.assertRaisesRegex(ValueError, 'budget_cap_exceeded'):
            self.reserve('3.00', self.bindings[1])

    def test_only_undispatched_reservation_can_release(self):
        self.configure('10.00'); r = self.reserve(); released = self.event(r, 'release', evidence={'reason': 'not sent'})
        self.assertEqual(released['usage']['held_minor'], 0)
        r2 = self.reserve('9.00', self.bindings[1]); i = self.event(r2, 'intent', binding=self.bindings[1], expected_policy_revision=1)
        with self.assertRaisesRegex(ValueError, 'invalid_transition'):
            self.event(i, 'release', binding=self.bindings[1], evidence={'reason': 'cancel'})

    def test_lower_cap_preserves_holds_and_blocks_new_intent(self):
        self.configure(); r = self.reserve()
        lower = self.configure('5.00', revision=1)
        self.assertEqual(lower['usage']['held_minor'], 800)
        self.assertEqual(lower['usage']['over_cap_minor'], 300)
        with self.assertRaisesRegex(ValueError, 'policy_version_conflict'):
            self.event(r, 'intent', expected_policy_revision=1)
        with self.assertRaisesRegex(ValueError, 'budget_cap_exceeded'):
            self.event(r, 'intent', expected_policy_revision=2)
        self.event(r, 'release', evidence={'reason': 'not sent'})

    def test_policy_requires_exact_local_declaration_and_stale_save_conflicts(self):
        with self.assertRaisesRegex(ValueError, 'local_operator_confirmation_required'):
            self.configure(operator_confirmation={'kind': 'agent', 'confirmed': True})
        one = self.configure(key='policy-once')
        self.assertEqual(self.configure(key='policy-once'), one)
        with self.assertRaisesRegex(ValueError, 'policy_version_conflict'):
            self.configure('25.00', revision=0)
        with self.assertRaisesRegex(ValueError, 'local_operator_confirmation_required'):
            self.configure('25.00', revision=1, operator_confirmation={'kind': 'local_operator', 'name': 'synthetic-admin', 'confirmed': True, 'expected_revision': 1, 'policy_sha256': '0' * 64})

    def test_cap_never_changes_original_task_or_grants_execution_permission(self):
        before = self.core.invoke('commerce_task_list', {})
        self.configure(); self.configure('40.00', revision=1)
        r = self.reserve(revision=2)
        self.assertFalse(r['enforcement']['external_execution_authorized'])
        self.assertFalse(r['enforcement']['all_external_executors_gated'])
        self.assertEqual(self.core.invoke('commerce_task_list', {}), before)

    def test_synthetic_live_and_task_scope_are_isolated_and_cannot_be_forged(self):
        self.configure(); live = self.task(demo=False)
        self.configure('10.00', mode='live', bindings=[live])
        self.reserve(); self.reserve('6.00', live, mode='live')
        self.assertEqual(self.budget.ledger('live')['usage']['held_minor'], 600)
        self.assertEqual(self.budget.ledger('synthetic')['usage']['held_minor'], 800)
        with self.assertRaisesRegex(ValueError, 'task_mode_mismatch'):
            self.reserve(binding=live)
        outside = self.task()
        with self.assertRaisesRegex(ValueError, 'task_out_of_scope'):
            self.reserve(binding=outside)
        forged = dict(self.bindings[1], action_id='invented')
        with self.assertRaisesRegex(ValueError, 'action_not_found'):
            self.reserve(binding=forged)

    def test_binding_version_and_cancellation_checked_before_intent_but_settlement_keeps_financial_truth(self):
        self.configure(); r = self.reserve(); b = self.bindings[0]
        with self.core.db() as db:
            raw = json.loads(db.execute('SELECT payload FROM tasks WHERE id=?', (b['task_id'],)).fetchone()[0])
            raw['input']['changed'] = True
            db.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(raw), b['task_id']))
        with self.assertRaisesRegex(ValueError, 'task_input_changed'):
            self.event(r, 'intent', expected_policy_revision=1)
        self.event(r, 'release', evidence={'reason': 'not sent'})
        i = self.event(self.reserve(binding=self.bindings[1]), 'intent', binding=self.bindings[1], expected_policy_revision=1)
        self.core.invoke('commerce_task_cancel', {'task_id': self.bindings[1]['task_id']})
        paid = self.event(i, 'paid', binding=self.bindings[1], amount_cny='8.00', evidence=self.evidence())
        self.assertEqual(paid['record']['status'], 'PAID')

    def test_cross_task_record_binding_and_event_version_cannot_be_substituted(self):
        self.configure(); r = self.reserve()
        with self.assertRaisesRegex(ValueError, 'binding_mismatch'):
            self.event(r, 'release', binding=self.bindings[1], evidence={'reason': 'wrong task'})
        self.event(r, 'intent', expected_policy_revision=1)
        with self.assertRaisesRegex(ValueError, 'record_version_conflict'):
            self.event(r, 'release', evidence={'reason': 'stale'})
        with self.assertRaisesRegex(ValueError, 'record_not_found'):
            self.event(r, 'release', mode='live', evidence={'reason': 'wrong mode'})

    def test_invalid_money_never_writes_and_precision_is_exact(self):
        self.configure('10.00')
        for amount in (True, False, float('nan'), 1.2, 'NaN', 'Infinity', '-0.01', '-0', '1.001', Decimal('1.000'), '1e2', '', ' 1.00'):
            with self.subTest(amount=str(amount)), self.assertRaisesRegex(ValueError, 'invalid_money'):
                self.reserve(amount)
        self.assertEqual(self.budget.ledger('synthetic')['records'], [])
        self.assertEqual(self.reserve('0.01')['record']['reserved_minor'], 1)
        self.assertEqual(self.reserve(Decimal('0.29'), self.bindings[1])['usage']['held_minor'], 30)

    def test_missing_or_unsafe_conversion_rejected_and_conservative_upper_bound_accepted(self):
        self.configure('10.00')
        with self.assertRaisesRegex(ValueError, 'conversion_required'):
            self.reserve('3.00', source_currency='USD')
        conversion = {'original_amount': '1.00', 'rate_cny_upper': '7.201', 'observed_at': '2026-01-01T00:00:00+00:00', 'evidence_ref': 'SYN-FX-QUOTE'}
        with self.assertRaisesRegex(ValueError, 'conversion_upper_bound'):
            self.reserve('7.20', source_currency='USD', conversion=conversion)
        r = self.reserve('7.21', source_currency='USD', conversion=conversion)
        self.assertEqual(r['record']['source_currency'], 'USD')
        self.assertEqual(r['record']['conversion'], conversion)

    def test_money_does_not_round_when_callers_decimal_context_has_low_precision(self):
        self.configure('200.00')
        with localcontext() as context:
            context.prec = 2
            r = self.reserve('123.45')
        self.assertEqual(r['record']['reserved_minor'], 12345)

    def test_external_payment_record_cannot_be_counted_again_under_another_task(self):
        self.configure(); p = self.paid()
        original = p['evidence']
        i = self.event(self.reserve('2.00', self.bindings[1]), 'intent', binding=self.bindings[1], expected_policy_revision=1)
        with self.assertRaisesRegex(ValueError, 'duplicate_external_record'):
            self.event(i, 'paid', binding=self.bindings[1], amount_cny='2.00', evidence=original)
        self.assertEqual(self.budget.policy_get('synthetic')['usage']['gross_paid_minor'], 800)

    def test_unknown_survives_reinstantiation_and_source_change_without_new_reservation(self):
        self.configure('10.00')
        r = self.event(self.reserve(), 'intent', expected_policy_revision=1)
        self.event(r, 'unknown', evidence={'reason': 'lost response'})
        from operating_budget import OperatingBudget
        self.budget = OperatingBudget(Core(self.core.path))
        self.assertEqual(self.budget.ledger('synthetic')['records'][0]['status'], 'UNKNOWN')
        with self.assertRaisesRegex(ValueError, 'action_already_bound'):
            self.reserve()
        self.assertEqual(self.budget.policy_get('synthetic')['usage']['held_minor'], 800)

    def test_cancelled_and_ambiguous_tasks_cannot_reserve(self):
        self.configure(); b = self.bindings[0]
        self.core.invoke('commerce_task_cancel', {'task_id': b['task_id']})
        with self.assertRaisesRegex(ValueError, 'task_cancelled'):
            self.reserve()
        with self.core.db() as db:
            row = json.loads(db.execute('SELECT payload FROM tasks WHERE id=?', (self.bindings[1]['task_id'],)).fetchone()[0])
            del row['input']['demo']
            db.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(row), self.bindings[1]['task_id']))
        with self.assertRaisesRegex(ValueError, 'task_mode_required'):
            self.reserve(binding=self.bindings[1])

    def test_ledger_pagination_and_original_events_survive_restart(self):
        self.configure(); p = self.paid(); self.reserve('2.00', self.bindings[1])
        first = self.budget.ledger('synthetic', limit=1)
        second = self.budget.ledger('synthetic', offset=1, limit=1)
        self.assertEqual(first['total'], 2)
        self.assertNotEqual(first['records'][0]['id'], second['records'][0]['id'])
        filtered = self.budget.ledger('synthetic', task_id=self.bindings[0]['task_id'])
        self.assertEqual(filtered['total'], 1)
        self.assertEqual([e['operation'] for e in filtered['events']], ['reserve', 'intent', 'paid'])
        self.assertEqual(filtered['records'][0]['paid_receipt_id'], p['receipt_id'])

    def test_definitions_are_invokable_and_policy_save_is_not_an_agent_tool(self):
        from operating_budget import definitions
        defs = definitions(lambda properties, required=(): {'type': 'object', 'properties': properties, 'required': list(required)}, {'type': 'string'})
        names = {name for name, _, _ in defs}
        self.assertEqual(names, {'commerce_operating_budget_policy_get', 'commerce_operating_budget_reserve', 'commerce_operating_budget_transition', 'commerce_operating_budget_ledger'})
        self.assertFalse(self.budget.invoke('commerce_operating_budget_policy_get', {'mode': 'live'})['policy']['configured'])
        with self.assertRaisesRegex(ValueError, 'unknown_budget_tool'):
            self.budget.invoke('commerce_operating_budget_policy_save', {})


if __name__ == '__main__':
    unittest.main()
