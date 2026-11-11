"""Real subprocess queue checks with synthetic output; no network or model calls."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from collection_jobs import CollectionJobs, load, save, worker_valid
from collection_state import evolve
from service import Commerce
from test_crawler_feed_bridge import SOURCE, capsule
from crawler_feed_bridge import persist_collection


class CollectionQueue(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.core = Core(self.root / 'core.sqlite')
        self.slow = False
        self.imported = []
        def command(value, output):
            code = ('import time;time.sleep(60);' if self.slow else '')
            code += 'import pathlib;pathlib.Path(' + repr(str(output)) + ').write_text(' + repr(json.dumps({'status':'succeeded','completed_sources':[SOURCE['id']]})) + ')'
            return [sys.executable, '-c', code]
        self.jobs = CollectionJobs(self.core, self.root, self.imported.append, command)

    def tearDown(self):
        self.jobs.stop()
        self.temp.cleanup()

    def request(self):return self.jobs.request(SOURCE['id'], 'synthetic-job')

    def test_idempotency_overlap_success_and_import(self):
        job = self.request()
        self.assertEqual(job, self.request())
        with self.assertRaisesRegex(ValueError, 'already_active'):
            self.jobs.request(SOURCE['id'], 'another')
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.jobs.request('all', 'synthetic-job')
        self.jobs.work_once()
        self.assertEqual(self.jobs.get(job['id'])['status'], 'succeeded')
        self.assertEqual(self.imported, [SOURCE['id']])

    def test_queued_cancel_and_explicit_retry(self):
        job = self.request()
        self.assertEqual(self.jobs.cancel(job['id'])['status'], 'cancelled')
        self.assertFalse(self.jobs.work_once())
        retry = self.jobs.retry(job['id'])
        self.assertEqual((retry['attempt'], retry['status']), (2, 'queued'))
        self.jobs.work_once()
        self.assertEqual(self.jobs.get(job['id'])['status'], 'succeeded')

    def test_running_cancel_terminates_owned_subprocess(self):
        self.slow = True
        job = self.request()
        runner = threading.Thread(target=self.jobs.work_once)
        runner.start()
        end = time.monotonic()+5
        while self.jobs.get(job['id'])['status'] != 'running' and time.monotonic()<end:time.sleep(.02)
        self.jobs.cancel(job['id'])
        runner.join(8)
        self.assertFalse(runner.is_alive())
        self.assertEqual(self.jobs.get(job['id'])['status'], 'cancelled')
        self.assertEqual(self.imported, [])

    def test_restart_fences_old_owner_and_never_replays(self):
        job = self.request()
        with self.core.db() as db:
            running=evolve(job,'start',time.time(),attempt=1)
            save(db,running,'old-owner',time.time())
        self.jobs.start(recover=True)
        self.assertEqual(self.jobs.get(job['id'])['status'], 'interrupted')
        with self.core.db() as db:self.assertFalse(worker_valid(db,job['id'],1,'old-owner')[1])
        self.assertEqual(self.imported, [])

    def test_import_failure_is_not_success(self):
        self.jobs.importer=lambda ident: (_ for _ in ()).throw(ValueError('synthetic'))
        job=self.request();self.jobs.work_once()
        self.assertEqual(self.jobs.get(job['id'])['error'], 'collection_import_failed')
        self.assertEqual(self.jobs.get(job['id'])['status'], 'failed')

    def test_completed_snapshot_import_preserves_capture_and_bypasses_cooldown(self):
        cache=self.root/'cache';data=capsule()
        persist_collection(SOURCE,data,cache)
        service=Commerce(self.root/'service')
        with patch('crawler_feed_bridge.CACHE',cache):
            first=service.intelligence.import_collection(SOURCE['id'])
            second=service.intelligence.import_collection(SOURCE['id'])
        self.assertEqual(first['payload_sha256'],second['payload_sha256'])
        self.assertEqual(first['collected_at'],data['checked_at'])
        self.assertEqual(service.intelligence.sources()['sources'][3]['cached_items'],1)


if __name__=='__main__':unittest.main()
