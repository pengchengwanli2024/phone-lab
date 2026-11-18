"""Unattended-run health checks on an isolated state; no network."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class OperatingHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.app = Commerce(self.tmp.name);self.health = self.app.operating_health
    def tearDown(self):
        self.app.autonomy.stop();self.tmp.cleanup()
    def check(self, ident, **kw):
        return next(c for c in self.health.get(**kw)['checks'] if c['id'] == ident)
    def backups(self):
        return sorted(p.name for p in (Path(self.tmp.name) / 'backups').glob('*.sqlite'))

    def test_stopped_worker_is_critical_and_a_live_heartbeat_is_ok(self):
        self.assertEqual(self.check('worker')['status'], 'critical')
        self.assertEqual(self.health.get()['status'], 'critical')
        self.app.autonomy.tick(collect=False)
        self.assertEqual(self.check('worker')['status'], 'ok')
        self.assertEqual(self.check('worker', at=time.time() + 600)['status'], 'critical')

    def test_background_fault_work_without_executor_and_unconfirmed_results_are_reported(self):
        self.assertEqual([self.check(i)['status'] for i in ('background', 'unassigned', 'unconfirmed')], ['ok', 'ok', 'ok'])
        self.app.capability_lifecycle._media_error = 'media_background_tick_failed'
        self.app.core.invoke('commerce_task_create', {'kind': 'draft', 'idempotency_key': 'parked', 'input': {'title': 'parked'}})
        with self.app.core.db() as db:
            db.execute("INSERT INTO agent_runs (id,idem,request,payload,status,created,updated) VALUES ('r','k','{}','{}','unknown',1,1)")
        self.assertEqual(self.check('background')['status'], 'critical');self.assertIn('媒体制作', self.check('background')['detail'])
        self.assertEqual((self.check('unassigned')['status'], self.check('unassigned')['target']), ('warning', 'tasks'))
        self.assertEqual(self.check('unconfirmed')['status'], 'warning')

    def test_an_outcome_the_operator_checked_and_closed_no_longer_counts(self):
        run = self.app.agent_runtime.create('合成事项', 'conductor', 'runtime', 'health-run', parameters={'demo': False})
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='unknown',result=? WHERE id=?", ('{"error":"agent_provider_outcome_unknown"}', run['id']))
        self.assertEqual(self.check('unconfirmed')['status'], 'warning')
        item = self.app.invoke('commerce_attention_list', {}, 'test')['items'][0]
        self.app.invoke('commerce_attention_close', {'item_id': item['id']}, 'test')
        self.assertEqual(self.check('unconfirmed')['status'], 'ok')
        self.assertEqual(self.app.agent_runtime.get(run['id'])['status'], 'unknown')
        # The same request ending differently is a new outcome and counts again.
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='interrupted',result=? WHERE id=?", ('{"error":"agent_interrupted_no_automatic_resubmit"}', run['id']))
        self.assertEqual(self.check('unconfirmed')['status'], 'warning')

    def test_unconnected_store_is_unknown_not_ok(self):
        self.assertEqual(self.check('snapshots')['status'], 'unknown')

    def test_backup_is_off_by_default_and_reading_never_creates_one(self):
        value = self.health.get();self.health.tick(at=time.time() + 10 * 86400)
        self.assertFalse(value['auto_backup']);self.assertFalse(value['business_acceptance'])
        self.assertEqual(self.check('backup')['status'], 'warning');self.assertEqual(self.backups(), [])

    def test_backup_is_readable_and_retention_only_removes_its_own_files(self):
        folder = Path(self.tmp.name) / 'backups';folder.mkdir()
        manual = folder / 'commerce-1700000000000000000.sqlite';manual.write_bytes(b'manual');other = folder / 'notes.txt';other.write_text('keep')
        self.app.core.invoke('commerce_task_create', {'kind': 'draft', 'idempotency_key': 'row', 'input': {'title': 'row'}})
        for _ in range(9): self.assertEqual(self.health.backup_now()['status'], 'backed_up')
        names = self.backups()
        self.assertEqual(sum(n.startswith('auto-') for n in names), 7)
        self.assertTrue(manual.exists());self.assertTrue(other.exists())
        newest = max(folder.glob('auto-*.sqlite'), key=lambda p: p.stat().st_mtime)
        self.assertEqual(oct(newest.stat().st_mode & 0o777), '0o600')
        with sqlite3.connect(newest) as copy:
            self.assertEqual(copy.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
        self.assertEqual(self.check('backup')['status'], 'ok');self.assertEqual(self.health.get()['auto_backup_count'], 7)

    def test_stale_backup_warns_and_enabled_tick_runs_once_a_day(self):
        self.health.backup_now(at=time.time() - 5 * 86400)
        newest = max((Path(self.tmp.name) / 'backups').iterdir());old = time.time() - 5 * 86400;os.utime(newest, (old, old))
        self.assertEqual(self.check('backup')['status'], 'warning')
        self.assertTrue(self.health.configure(True)['auto_backup'])
        self.health.tick();self.health._thread.join(timeout=10)
        self.assertEqual(len(self.backups()), 2);self.assertEqual(self.check('backup')['status'], 'ok')
        self.health.tick()
        self.assertEqual(len(self.backups()), 2)
        with self.assertRaisesRegex(ValueError, 'operating_health_invalid_setting'): self.health.configure('yes')

    def test_failed_backup_is_recorded_and_leaves_no_partial_file(self):
        folder = Path(self.tmp.name) / 'backups';folder.mkdir();folder.chmod(0o500)
        try: self.assertEqual(self.health.backup_now()['status'], 'failed')
        finally: folder.chmod(0o700)
        self.assertEqual(self.backups(), []);self.assertIn('失败', self.check('backup')['detail'])

    def test_registration_marks_only_the_read_as_read_only(self):
        import mcp_server, operating_health, service
        names = {n for n, _, _ in service.TOOLS}
        self.assertTrue({'commerce_operating_health_get', 'commerce_operating_health_configure'} <= names)
        self.assertIn('commerce_operating_health_get', mcp_server.CONTROL_READ_ONLY)
        self.assertNotIn('commerce_operating_health_configure', mcp_server.CONTROL_READ_ONLY)
        self.assertEqual(self.app.invoke('commerce_operating_health_get', {}, 'test')['schema'], 'commerce-operating-health-v1')


if __name__ == '__main__':
    unittest.main()
