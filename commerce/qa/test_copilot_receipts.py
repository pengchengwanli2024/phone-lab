"""Assistant receipts project the original local task; reads never execute it."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_copilot


class Receipts(unittest.TestCase):
    setUp = test_copilot.Dialogue.setUp
    tearDown = test_copilot.Dialogue.tearDown
    send = test_copilot.Dialogue.send
    complete = test_copilot.Dialogue.complete
    def test_original_task_progress_and_minimal_receipt(self):
        self.send(); self.complete([{'operation': 'report', 'reason': '简报模板'}])
        run = self.chat.get(self.thread['id'])['latest_run']
        applied = self.chat.apply(self.thread['id'], run['id'], 'P1', run['result_sha256'], self.thread['context_sha256'])
        task_id = applied['task']['id']
        with patch.object(self.app.autonomy, 'request', side_effect=AssertionError('read must not execute')):
            receipt = self.chat.get(self.thread['id'])['latest_run']['actions'][0]['receipt']
        self.assertEqual(receipt['task_id'], task_id)
        self.assertEqual(receipt['outcome'], 'pending')
        self.assertEqual(receipt['status'], 'queued')
        self.assertNotIn('input', receipt)
        self.assertTrue(self.app.autonomy.work(1000))
        final = self.chat.get(self.thread['id'])['turns'][0]['run']['actions'][0]['receipt']
        self.assertEqual(final['outcome'], 'succeeded')
        self.assertEqual(final['status'], 'completed')
        self.assertEqual(len(final['result_sha256']), 64)
        self.assertFalse(final['external_operations_executed'])
        self.assertNotIn('result', final)
        self.assertEqual(len(self.app.core.invoke('commerce_task_list', {})['tasks']), 1)
        with self.app.core.db() as db:
            db.execute('UPDATE task_runs SET result=NULL WHERE task_id=?', (task_id,))
        uncertain = self.chat.get(self.thread['id'])['latest_run']['actions'][0]['receipt']
        self.assertEqual(uncertain['outcome'], 'unknown')

    def test_missing_task_is_unknown_without_recreation(self):
        self.send(); self.complete([{'operation': 'report', 'reason': '简报模板'}])
        run = self.chat.get(self.thread['id'])['latest_run']
        with self.app.core.db() as db:
            db.execute('INSERT INTO agent_actions VALUES (?,?,?,?)', (run['id'], 'P1', 'missing-task', 1))
        receipt = self.chat.get(self.thread['id'])['latest_run']['actions'][0]['receipt']
        self.assertEqual(receipt['outcome'], 'unknown')
        self.assertEqual(receipt['task_id'], 'missing-task')
        self.assertEqual(self.app.core.invoke('commerce_task_list', {})['tasks'], [])

    def test_created_task_without_action_ack_remains_original_unknown_receipt(self):
        self.send(); self.complete([{'operation': 'report', 'reason': '简报模板'}])
        run = self.chat.get(self.thread['id'])['latest_run']
        # A process can stop between committing the task and recording approval.
        task = self.app.core.invoke('commerce_task_create', {'kind': 'report', 'input': {'demo': True}, 'idempotency_key': 'agent:' + run['id'] + ':P1'})
        with patch.object(self.app.autonomy, 'request', side_effect=AssertionError('read must not schedule')):
            action = self.chat.get(self.thread['id'])['latest_run']['actions'][0]
        self.assertEqual(action['task_id'], task['id'])
        self.assertTrue(action['submission_unknown'])
        self.assertEqual(action['receipt']['outcome'], 'unknown')
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_actions').fetchone()[0], 0)


if __name__ == '__main__': unittest.main()
