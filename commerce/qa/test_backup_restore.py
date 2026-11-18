"""Restore drill on synthetic state; no network, no real service, no live writes."""
from pathlib import Path
import hashlib
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
import backup_restore


def tree_digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.state = Path(self.tmp.name)
        self.app = Commerce(self.state)
        for index in range(3):
            self.app.core.invoke('commerce_task_create', {'kind': 'draft', 'idempotency_key': 'r' + str(index),
                                                         'input': {'title': 'row ' + str(index)}})
    def tearDown(self):
        self.app.autonomy.stop();self.app.agent_runtime.stop();self.tmp.cleanup()
    def guard(self):
        return patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden'))

    def test_a_recorded_backup_restores_and_serves_real_reads(self):
        self.assertEqual(self.app.operating_health.backup_now()['status'], 'backed_up')
        before = tree_digest(self.state / 'backups')
        live = backup_restore._counts(self.state / 'commerce.sqlite')
        with self.guard():
            receipt = backup_restore.drill(self.state)
        self.assertEqual(receipt['status'], 'passed', receipt.get('code'))
        self.assertEqual(receipt['scope'], 'database_only')
        self.assertFalse(receipt['live_state_written']);self.assertFalse(receipt['network_used'])
        self.assertEqual(set(receipt['restored_reads']), {'commerce_runtime_status', 'commerce_operating_loop_get',
                                                          'commerce_operating_health_get', 'commerce_task_list'})
        self.assertEqual(receipt['row_counts_match']['tasks'], True)
        self.assertEqual(backup_restore._counts(self.state / 'commerce.sqlite'), live)
        self.assertEqual(tree_digest(self.state / 'backups'), before, 'the backup itself must not change')

    def test_without_a_backup_the_drill_says_so_instead_of_passing(self):
        receipt = backup_restore.drill(self.state)
        self.assertEqual((receipt['status'], receipt['code']), ('unavailable', 'no_backup_recorded'))
        self.assertFalse(receipt['service_started'])

    def test_a_corrupt_backup_fails_the_drill(self):
        self.app.operating_health.backup_now()
        newest = backup_restore.backups(self.state)[0]
        newest.write_bytes(b'not a database')
        receipt = backup_restore.drill(self.state)
        self.assertEqual(receipt['status'], 'failed');self.assertEqual(receipt['code'], 'integrity')
        self.assertFalse(receipt['service_started'])

    def test_a_backup_outside_the_backup_folder_is_refused(self):
        outside = self.state / 'elsewhere.sqlite';outside.write_bytes(b'x')
        receipt = backup_restore.drill(self.state, backup=outside)
        self.assertEqual(receipt['status'], 'failed');self.assertEqual(receipt['code'], 'backup_path_not_allowed')

    def test_only_auto_backups_are_considered_by_default(self):
        folder = self.state / 'backups';folder.mkdir(exist_ok=True)
        (folder / 'commerce-1700000000000000000.sqlite').write_bytes(b'manual')
        self.assertEqual(backup_restore.backups(self.state), [])
        self.assertEqual(len(backup_restore.backups(self.state, backup_restore.MANUAL)), 1)


if __name__ == '__main__':
    unittest.main()
