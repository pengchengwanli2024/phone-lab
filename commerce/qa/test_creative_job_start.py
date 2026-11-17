"""Workers must observe the committed job and never execute rolled-back work."""
import threading
import time
import unittest
from unittest.mock import patch

import test_product_media as fixtures


class CreativeJobStart(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProductMediaTests()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.studio = self.app.creative

    def tearDown(self):
        self.app.autonomy.stop()
        self.fixture.tearDown()

    def args(self, key):
        return dict(project_id=self.fixture.pid, asset_id=self.fixture.asset['id'],
                    idempotency_key=key)

    def test_worker_waits_until_outer_transaction_commits(self):
        entered = threading.Event()
        release = threading.Event()

        def render(job, data):
            entered.set()
            if not release.wait(3):
                raise AssertionError('synthetic worker release timed out')
            self.studio.stage(job, 'synthetic_check')
            return {'synthetic': True}

        with patch.object(self.studio, 'image_layout', side_effect=render):
            try:
                with self.app.core.atomic():
                    job = self.studio.start('image_layout', self.args('commit'))
                    entered_before_commit = entered.wait(.2)
            finally:
                release.set()
            self.assertTrue(entered.wait(2), 'committed worker did not run')
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                result = self.studio.job_get(job['id'])
                if result['status'] not in ('queued', 'running'):
                    break
                time.sleep(.01)
        self.assertFalse(entered_before_commit, 'worker ran before its job was committed')
        self.assertEqual(result['status'], 'completed')

    def test_rolled_back_job_is_not_executed(self):
        workers = []
        actual_thread = threading.Thread

        def thread(*args, **kwargs):
            worker = actual_thread(*args, **kwargs)
            workers.append(worker)
            return worker

        with patch('creative_studio.threading.Thread', side_effect=thread), \
                patch.object(self.studio, 'image_layout', return_value={}) as render:
            with self.assertRaisesRegex(ValueError, 'synthetic_rollback'):
                with self.app.core.atomic():
                    self.studio.start('image_layout', self.args('rollback'))
                    raise ValueError('synthetic_rollback')
            for worker in workers:
                worker.join(2)
                self.assertFalse(worker.is_alive())
            render.assert_not_called()
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM creative_jobs').fetchone()[0], 0)
