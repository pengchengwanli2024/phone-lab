"""Main control projection and original task intake, entirely local."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from operating_budget import OperatingBudget, digest
from operating_control import OperatingControl


class OperatingControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.core = Core(self.state / 'db.sqlite')
        self.budget = OperatingBudget(self.core)
        self.app = SimpleNamespace(core=self.core, state=self.state, operating_budget=self.budget)
        self.control = OperatingControl(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, **extra):
        args = dict(synthetic=False, kind='research', title='Synthetic market research', details='Check product evidence.', idempotency_key='one')
        return self.control.task_submit(**{**args, **extra})

    def test_unconfigured_money_stays_unknown_and_remote_not_connected(self):
        value = self.control.get(False)
        self.assertIsNone(value['budget']['cap'])
        self.assertIsNone(value['budget']['available'])
        self.assertFalse(value['mobile']['commands_ready'])
        self.assertFalse(value['autonomy']['external_business_enabled'])
        self.assertEqual(self.core.invoke('commerce_task_list', {})['tasks'], [])

    def test_same_intake_returns_original_task_and_changed_payload_conflicts(self):
        first = self.submit()
        self.assertEqual(self.submit()['task_id'], first['task_id'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.submit(details='Different scope')
        self.assertEqual(len(self.core.invoke('commerce_task_list', {})['tasks']), 1)
        saved = self.core.invoke('commerce_task_get', {'task_id': first['task_id']})
        self.assertEqual(saved['status'], 'queued')
        self.assertFalse(saved['input']['external_execution_allowed'])

    def test_live_and_synthetic_lists_do_not_mix(self):
        live = self.submit()
        sample = self.submit(synthetic=True, idempotency_key='sample')
        self.assertEqual([r['id'] for r in self.control.get(False)['tasks']], [live['task_id']])
        self.assertEqual([r['id'] for r in self.control.get(True)['tasks']], [sample['task_id']])

    def test_configured_budget_reads_exact_shared_amount_without_spending(self):
        task = self.submit()
        candidate = {'mode': 'live', 'cap_minor': 1000000, 'task_ids': [task['task_id']]}
        self.budget.policy_save('live', '10000.00', [task['task_id']], 0, 'policy',
            {'kind': 'local_operator', 'name': 'synthetic owner', 'confirmed': True, 'expected_revision': 0, 'policy_sha256': digest(candidate)})
        budget = self.control.get(False)['budget']
        self.assertEqual((budget['cap'], budget['occupied'], budget['spent'], budget['available']), ('10000.00', '0.00', '0.00', '10000.00'))
        self.assertEqual(budget['period'], 'cumulative_pilot')
        self.assertFalse(self.control.get(False)['autonomy']['external_business_enabled'])

    def test_profile_declarations_are_bounded_and_not_execution_grants(self):
        (self.state / 'operating-control.json').write_text(json.dumps({'revision': 1, 'fulfillment': 'OGL', 'inventory_location': 'company_local', 'sku_status': 'pending_user', 'logistics_status': 'deferred'}))
        value = self.control.get(False)
        self.assertEqual(value['scope']['fulfillment'], 'OGL')
        self.assertEqual(value['configuration_revision'], 1)
        self.assertFalse(value['autonomy']['external_business_enabled'])
        (self.state / 'operating-control.json').write_text('{"revision":true}')
        with self.assertRaisesRegex(ValueError, 'operating_control_profile_invalid'):
            self.control.get(False)

    def test_replay_reads_actual_original_status_and_does_not_resume(self):
        first = self.submit()
        self.core.invoke('commerce_task_cancel', {'task_id': first['task_id']})
        replay = self.submit()
        self.assertEqual(replay['status'], 'cancelled')
        self.assertEqual(replay['task_id'], first['task_id'])
        self.assertEqual(len(self.core.invoke('commerce_task_list', {})['tasks']), 1)

    def test_mode_and_command_types_are_strict(self):
        with self.assertRaises(ValueError):
            self.control.get('false')
        with self.assertRaises(ValueError):
            self.submit(kind='shell')
        with self.assertRaises(ValueError):
            self.submit(title='')

    def test_real_store_projection_never_appears_in_synthetic_mode(self):
        snap = {'available': True, 'fresh': True, 'count': 3, 'observed_at': 'synthetic', 'sha256': 'a'*64}
        self.app.live = SimpleNamespace(status=lambda: dict(store_label='Synthetic Store', configured=True,
            orders=snap, stock=snap, sales=snap, orders_scope_confirmed=False, sync_enabled=False))
        value = self.control.get(False)
        self.assertEqual(value['store']['orders']['count'], 3)
        self.assertFalse(value['store']['business_writes_enabled'])
        self.assertTrue(any('平台SKU已读取' in line for line in value['autonomy']['blockers']))
        self.assertIsNone(self.control.get(True)['store'])


if __name__ == '__main__':
    unittest.main()
