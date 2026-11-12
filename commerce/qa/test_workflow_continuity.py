"""Synthetic regression cases for scope-preserving reports and task continuation."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class Continuity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_scope_matches_filtered_dashboard_and_survives_reload(self):
        args = {'demo': True, 'store_id': 'ozon-demo', 'market': 'RU', 'idempotency_key': 'scope'}
        report = self.app.invoke('commerce_report_create', args)
        self.assertIn('39,200', report['content'])
        self.assertNotIn('128,640', report['content'])
        self.assertEqual(report['scope']['store_id'], 'ozon-demo')
        self.assertEqual(Commerce(self.tmp.name).invoke('commerce_report_create', args), report)
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.app.invoke('commerce_report_create', {**args, 'store_id': 'all'})

    def test_order_task_carries_server_source_and_not_only_title(self):
        args = {'demo': True, 'store_id': 'ozon-demo', 'entity_kind': 'order', 'entity_id': 'SIM-1001', 'idempotency_key': 'order'}
        task = self.app.invoke('commerce_workflow_task_create', args)
        self.assertEqual(task['input']['source_context']['store_id'], 'ozon-demo')
        self.assertEqual(task['input']['source_record']['id'], 'SIM-1001')
        self.assertEqual(len(task['input']['source_context']['record_sha256']), 64)
        self.assertEqual(self.app.invoke('commerce_workflow_task_create', args)['id'], task['id'])
        with self.assertRaisesRegex(ValueError, 'source_changed'):
            self.app.invoke('commerce_workflow_task_create', {**args, 'idempotency_key': 'changed', 'expected_source_sha256': '0' * 64})

    def test_followup_is_idempotent_and_does_not_modify_original(self):
        old = self.app.invoke('commerce_task_create', {'kind': 'analysis', 'input': {'title': 'synthetic task', 'demo': True}, 'idempotency_key': 'old'})
        args = {'task_id': old['id'], 'operation': 'report', 'input': {}, 'idempotency_key': 'followup'}
        result = self.app.invoke('commerce_task_continue', args)
        self.assertEqual(result['input']['predecessor_task_id'], old['id'])
        self.assertEqual(result['kind'], 'report')
        self.assertTrue(result['input']['demo'])
        self.assertEqual(self.app.invoke('commerce_task_continue', args), result)
        self.assertEqual(self.app.invoke('commerce_task_get', {'task_id': old['id']}), old)
        self.assertIsNone(self.app.invoke('commerce_task_result', {'task_id': result['id']})['execution'])

    def test_scope_and_operation_fail_closed(self):
        with self.assertRaises(ValueError):
            self.app.invoke('commerce_report_create', {'demo': True, 'period': '365', 'idempotency_key': 'bad'})
        with self.assertRaises(ValueError):
            self.app.invoke('commerce_workflow_task_create', {'demo': False, 'entity_kind': 'order', 'entity_id': 'SIM-1001', 'idempotency_key': 'not-real'})


if __name__ == '__main__':
    unittest.main()
