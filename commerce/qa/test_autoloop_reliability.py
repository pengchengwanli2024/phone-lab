"""Synthetic combinations of lost responses, crashes and competing clients."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Barrier
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_followups as fixture
from service import Commerce


class Reliability(unittest.TestCase):
    setUp=fixture.Followups.setUp
    tearDown=fixture.Followups.tearDown
    targets=fixture.Followups.targets
    source=fixture.Followups.source
    create=fixture.Followups.create
    task=fixture.Followups.task
    def test_lost_create_response_then_restart_and_explicit_retry_reuses_original(self):
        target=self.source();saved=self.create(target)
        replacement=Commerce(self.temp.name)
        with patch('followups.time.time',return_value=fixture.NOW+120):
            replacement.followups.tick(at=fixture.NOW+120)
            replay=replacement.followups.create(target,fixture.date(fixture.NOW+60),'create')
        self.assertEqual(replay['id'],saved['id']);self.assertEqual(replay['state'],'checked')
        with replacement.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM followup_checks').fetchone()[0],1)

    def test_due_and_cancel_have_one_serialized_outcome_without_touching_the_original(self):
        task,target=self.task();saved=self.create(target);barrier=Barrier(2)
        def cancel():
            barrier.wait()
            try:return self.app.followups.cancel(saved['id'],saved['revision'])['state']
            except ValueError:return 'conflict'
        def due():barrier.wait();return self.app.followups.tick(at=fixture.NOW+61)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(cancel);second=pool.submit(due);a,b=first.result(),second.result()
        current=self.app.followups.get(saved['id'])
        self.assertIn((a,b,current['state']),[('cancelled',0,'cancelled'),('conflict',1,'checked')])
        self.assertEqual(self.app.core.invoke('commerce_task_get',{'task_id':task['id']})['status'],'queued')

    def test_crash_before_proposal_link_and_two_client_retry_keep_one_task(self):
        run=self.fixture.run_record(proposals=[self.fixture.proposal()])
        args={'run_id':run['id'],'proposal_id':'P1','result_sha256':run['result_sha256']}
        with patch.object(self.app.autonomy,'request',side_effect=RuntimeError('synthetic crash after task creation')):
            with self.assertRaises(RuntimeError):self.app.agent_runtime.apply(**args)
        pending=self.app.attention.listing()['items']
        self.assertEqual(pending[0]['kind'],'unknown')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.app.agent_runtime.apply(**args),range(2)))
        self.assertEqual(results[0]['task']['id'],results[1]['task']['id'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM task_runs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM agent_actions').fetchone()[0],1)


if __name__=='__main__':unittest.main()
