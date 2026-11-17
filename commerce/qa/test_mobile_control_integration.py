"""Exercise mobile contracts through the actual shared service validator."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class MobileIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Commerce(self.tmp.name)
        self.addCleanup(self.app.agent_runtime.stop)

    def call(self, name, **args):
        return self.app.invoke(name, args, 'test')

    def test_projection_uses_real_service_validation_and_rejects_bad_identity(self):
        for reference in ('attention_' + 'a' * 64, ['not-an-id']):
            with self.assertRaises(ValueError):
                self.call('commerce_mobile_project', kind='attention', reference=reference)
        with self.assertRaises(ValueError):
            self.call('commerce_mobile_project', kind='listing', reference={'case_id': 'synthetic-missing', 'platform': 'ozon', 'store_ref': 'synthetic-store', 'market': True})

    def test_new_mobile_intake_has_explicit_live_mode_and_no_spend(self):
        receipt = self.call('commerce_mobile_command', command={'schema': 'commerce-mobile-command-v1', 'intent': 'new_task', 'text': 'Synthetic intake in a temporary database'}, idempotency_key='one')
        task = self.app.core.invoke('commerce_task_get', {'task_id': receipt['task_id']})
        self.assertIs(task['input'].get('demo'), False)
        self.assertEqual(task['status'], 'queued')
        self.assertFalse(receipt['external_operations_executed'])

    def test_mobile_budget_reads_shared_unknown_without_fabricating_zero(self):
        receipt = self.call('commerce_mobile_command', command={'schema': 'commerce-mobile-command-v1', 'intent': 'budget_query', 'text': ''}, idempotency_key='budget')
        self.assertEqual(receipt['result']['status'], 'unknown')
        self.assertIsNone(receipt['result']['remaining'])
        self.assertFalse(receipt['external_operations_executed'])

    def test_control_tasks_are_original_tasks_and_no_sdk_entry_is_exposed(self):
        receipt = self.call('commerce_operating_control_task_submit', synthetic=True, kind='feature', title='Synthetic feature', details='Acceptance criteria', idempotency_key='feature')
        self.assertEqual(self.app.core.invoke('commerce_task_get', {'task_id': receipt['task_id']})['status'], 'queued')
        self.assertEqual(self.call('commerce_operating_control_get', synthetic=True)['tasks'][0]['id'], receipt['task_id'])
        with self.assertRaisesRegex(ValueError, 'unknown_tool'):
            self.call('commerce_mobile_sdk_event', actor='owner', verified=True)


if __name__ == '__main__':
    unittest.main()
