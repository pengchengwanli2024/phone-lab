"""Queued tasks are classified by their actual executor; unassigned ones are never called running."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class TaskDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.app = Commerce(self.tmp.name)
    def tearDown(self):
        self.app.autonomy.stop();self.tmp.cleanup()
    def task(self, key, kind='draft', data=None):
        return self.app.core.invoke('commerce_task_create', {'kind': kind, 'idempotency_key': key, 'input': data or {'title': key, 'demo': True}})
    def view(self):
        return self.app.invoke('commerce_task_dispatch_get', {}, 'test')

    def test_queued_without_any_executor_is_unassigned_and_reading_dispatches_nothing(self):
        parked = self.task('parked')
        calc = self.task('calc', 'analysis', {'title': 'calc', 'demo': True, 'parameters': {'currency': 'CNY'}})
        self.app.autonomy.request(calc['id'], 'unit_economics')
        value = self.view()
        self.assertEqual(value['items'][parked['id']], 'unassigned')
        self.assertEqual(value['items'][calc['id']], 'local_executor')
        self.assertEqual(value['unassigned'], 1);self.assertFalse(value['dispatches'])
        self.assertEqual(self.app.core.invoke('commerce_task_get', {'task_id': parked['id']})['status'], 'queued')
        with self.app.core.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM task_runs WHERE task_id=?', (parked['id'],)).fetchone())

    def test_cancelled_or_finished_tasks_are_not_listed(self):
        gone = self.task('gone');self.app.core.invoke('commerce_task_cancel', {'task_id': gone['id']})
        self.assertNotIn(gone['id'], self.view()['items'])

    def test_registered_read_only(self):
        import mcp_server, task_dispatch, service
        self.assertIn('commerce_task_dispatch_get', {n for n, _, _ in service.TOOLS})
        self.assertEqual(task_dispatch.READ_ONLY, {'commerce_task_dispatch_get'})
        self.assertIn('commerce_task_dispatch_get', mcp_server.CONTROL_READ_ONLY)


if __name__ == '__main__':
    unittest.main()
