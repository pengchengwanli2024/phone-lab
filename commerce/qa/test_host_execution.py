"""Lease, request pin and receipt boundaries use synthetic temporary state only."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class HostExecutionContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.assertTrue(hasattr(self.app, 'host_execution'), 'Shared backend lacks host execution leases')
        self.hosts = self.app.host_execution
        self.route = self.hosts.register('dsh', 'deepseek', 'synthetic-model')
        self.plan = [{'host_id': 'dsh', 'expected_route_sha256': self.route['route_sha256']}]

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.tmp.cleanup()

    def send(self, key='research'):
        thread = self.app.copilot.open({'module': 'research', 'market': 'RU', 'demo': False}, key)
        result = self.app.copilot.send(thread['id'], '请调研俄罗斯厨房收纳用品并保存候选',
                                       thread['context_sha256'], key, execution_hosts=self.plan)
        run = result['latest_run']['id']
        with self.app.core.atomic() as db:
            db.execute("UPDATE agent_runs SET status='running',owner=?,expires=? WHERE id=?",
                       (self.app.agent_runtime.owner, time.time() + 360, run))
        return result['research_job']['task_id'], run, thread

    def request(self, task, run, phase='planning'):
        schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                  'required': ['ok'], 'additionalProperties': False}
        return self.hosts.request(task, run, phase, {'synthetic': True}, schema, 'Return supplied JSON only.')

    def claim(self, request):
        return self.hosts.claim('dsh', 'worker-one', request['attempt_id'])

    def finish(self, lease, **changes):
        arguments = {'attempt_id': lease['attempt_id'], 'generation': lease['generation'],
                     'worker_id': lease['worker_id'], 'lease_token': lease['lease_token'],
                     'outcome': 'completed', 'result': {'ok': True},
                     'receipt': {'session_id': 'synthetic-native-session', 'provider': 'deepseek',
                                 'model': 'synthetic-model', 'request_id': lease['request_id'],
                                 'finish_reason': 'completed', 'tools_used': []}}
        arguments.update(changes)
        return self.hosts.finish(**arguments)

    def test_catalog_read_does_not_create_or_execute_tasks(self):
        self.assertEqual(self.hosts.listing()['hosts'][0]['model'], 'synthetic-model')
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], 0)

    def test_original_idempotent_send_replays_frozen_plan_after_catalog_change(self):
        task, run, thread = self.send()
        self.hosts.register('dsh', 'deepseek', 'changed-model')
        replay = self.app.copilot.send(thread['id'], '请调研俄罗斯厨房收纳用品并保存候选',
                                       thread['context_sha256'], 'research', execution_hosts=self.plan)
        self.assertEqual(replay['latest_run']['id'], run)
        self.assertEqual(replay['research_job']['task_id'], task)
        with self.assertRaisesRegex(ValueError, 'host_route_changed'):
            self.send('another-task')

    def test_concurrent_workers_cannot_claim_same_attempt(self):
        task, run, _ = self.send(); request = self.request(task, run)
        with ThreadPoolExecutor(max_workers=2) as pool:
            leases = list(pool.map(lambda worker: self.hosts.claim('dsh', worker, request['attempt_id']),
                                   ('worker-one', 'worker-two')))
        self.assertEqual(sum(lease is not None for lease in leases), 1)

    def test_completed_receipt_replay_is_idempotent_and_secret_not_projected(self):
        task, run, _ = self.send(); request = self.request(task, run); lease = self.claim(request)
        done = self.finish(lease)
        self.assertEqual(self.finish(lease), done)
        replay = self.request(task, run)
        self.assertEqual(replay['attempt_id'], request['attempt_id'])
        self.assertEqual(replay['status'], 'completed')
        self.assertNotIn(lease['lease_token'], json.dumps(self.hosts.for_task(task)))
        with self.assertRaisesRegex(ValueError, 'host_finish_conflict'):
            self.finish(lease, result={'ok': False})

    def test_expired_lease_cannot_finish_or_be_silently_reclaimed(self):
        task, run, _ = self.send(); request = self.request(task, run); lease = self.claim(request)
        with self.app.core.atomic() as db:
            db.execute('UPDATE agent_host_attempts SET expires=0 WHERE id=?', (request['attempt_id'],))
        with self.assertRaisesRegex(ValueError, 'host_lease_expired'):
            self.finish(lease)
        self.assertIsNone(self.hosts.claim('dsh', 'worker-two', request['attempt_id']))
        self.assertEqual(self.hosts.for_task(task)[0]['status'], 'unknown')

    def test_parent_owner_change_fences_late_host_result(self):
        task, run, _ = self.send(); request = self.request(task, run); lease = self.claim(request)
        with self.app.core.atomic() as db:
            db.execute("UPDATE agent_runs SET owner='successor-owner' WHERE id=?", (run,))
        with self.assertRaisesRegex(ValueError, 'host_parent_superseded'):
            self.finish(lease)
        self.assertNotEqual(self.hosts.for_task(task)[0]['status'], 'completed')

    def test_wrong_generation_model_or_request_receipt_is_rejected(self):
        task, run, _ = self.send(); lease = self.claim(self.request(task, run))
        with self.assertRaisesRegex(ValueError, 'host_lease_conflict'):
            self.finish(lease, generation=lease['generation'] + 1)
        for key, value in [('model', 'unrequested-model'), ('request_id', 'another-request'),
                           ('tools_used', ['write'])]:
            receipt = {'session_id': 'synthetic-native-session', 'provider': 'deepseek',
                       'model': 'synthetic-model', 'request_id': lease['request_id'],
                       'finish_reason': 'completed', 'tools_used': []}
            receipt[key] = value
            with self.assertRaisesRegex(ValueError, 'host_invalid_receipt'):
                self.finish(lease, receipt=receipt)

    def test_invalid_model_result_is_not_a_completed_attempt(self):
        task, run, _ = self.send(); lease = self.claim(self.request(task, run))
        with self.assertRaisesRegex(ValueError, 'host_invalid_result'):
            self.finish(lease, result={'invented': True})
        self.assertNotEqual(self.hosts.for_task(task)[0]['status'], 'completed')

    def test_cancelled_parent_cannot_accept_late_native_completion(self):
        task, run, _ = self.send(); lease = self.claim(self.request(task, run))
        self.app.market_research.cancel(task)
        with self.assertRaisesRegex(ValueError, 'host_parent_superseded'):
            self.finish(lease)

    def test_changed_business_context_cannot_accept_native_completion(self):
        task, run, thread = self.send(); lease = self.claim(self.request(task, run))
        with self.app.core.atomic() as db:
            db.execute("UPDATE copilot_threads SET context='{}' WHERE id=?", (thread['id'],))
        with self.assertRaisesRegex(ValueError, 'host_context_changed'):
            self.finish(lease)

    def test_confirmed_host_receipt_survives_crash_before_domain_checkpoint(self):
        task, run, _ = self.send(); lease = self.claim(self.request(task, run)); done = self.finish(lease)
        self.app.market_research.recover()
        successor = self.app.market_research.get(task)
        self.assertEqual(successor['status'],'queued')
        self.assertNotEqual(successor['run_id'],run)
        with self.app.core.atomic() as db:
            db.execute("UPDATE agent_runs SET status='running',owner=?,expires=? WHERE id=?",
                       (self.app.agent_runtime.owner, time.time() + 360, successor['run_id']))
        reused = self.request(task, successor['run_id'])
        self.assertEqual(reused['attempt_id'], done['attempt_id'])
        self.assertEqual(len(self.hosts.for_task(task)), 1, 'Confirmed model work must not be resubmitted')

    def test_public_send_contract_accepts_frozen_host_plan(self):
        thread = self.app.copilot.open({'module': 'research', 'market': 'RU', 'demo': False}, 'public')
        result = self.app.invoke('commerce_copilot_send', {
            'thread_id': thread['id'], 'message': '请调研俄罗斯厨房收纳用品并保存候选',
            'context_sha256': thread['context_sha256'], 'idempotency_key': 'public',
            'execution_hosts': self.plan,
        }, 'harness')
        self.assertEqual(result['latest_run']['execution_hosts'][0]['host_id'], 'dsh')

    def test_known_not_submitted_failure_does_not_consume_next_host_route(self):
        second=self.hosts.register('hermes','codex','synthetic-model')
        self.plan.append({'host_id':'hermes','expected_route_sha256':second['route_sha256']})
        task,run,_=self.send();lease=self.claim(self.request(task,run))
        self.hosts.finish(**{k:lease[k] for k in ('attempt_id','generation','worker_id','lease_token')},outcome='failed')
        with self.app.core.atomic() as db:
            job=self.app.market_research._load(db,task);job['status']='failed';self.app.market_research._save(db,job)
            db.execute("UPDATE agent_runs SET status='failed',expires=0 WHERE id=?",(run,))
        job=self.app.market_research.get(task)
        resumed=self.app.market_research.resume(task,job['revision'],'explicit-pre-admission-recovery')
        with self.app.core.atomic() as db:
            db.execute("UPDATE agent_runs SET status='running',owner=?,expires=? WHERE id=?",(self.app.agent_runtime.owner,time.time()+360,resumed['run_id']))
        retry=self.request(task,resumed['run_id'])
        self.assertEqual(retry['host_id'],'dsh','Known pre-admission failure must not skip the requested host')
        self.assertEqual(retry['generation'],2)

    def test_native_admission_is_not_completion_and_cannot_change_session_identity(self):
        task, run, _ = self.send(); lease = self.claim(self.request(task, run))
        self.assertTrue(hasattr(self.hosts, 'admit'), 'Native admission receipt is missing')
        args = {k: lease[k] for k in ('attempt_id', 'generation', 'worker_id', 'lease_token')}
        acknowledged = self.hosts.admit(**args, session_id='synthetic-native-session')
        self.assertEqual(acknowledged['status'], 'claimed')
        self.assertIsNone(acknowledged['result'])
        self.assertEqual(self.hosts.admit(**args, session_id='synthetic-native-session'), acknowledged)
        with self.assertRaisesRegex(ValueError, 'host_admission_conflict'):
            self.hosts.admit(**args, session_id='another-session')
        done = self.finish(lease)
        self.assertEqual(done['receipt']['session_id'], 'synthetic-native-session')

    def test_completion_cannot_replace_an_acknowledged_native_session(self):
        task, run, _ = self.send(); lease = self.claim(self.request(task, run))
        self.assertTrue(hasattr(self.hosts, 'admit'), 'Native admission receipt is missing')
        self.hosts.admit(**{k: lease[k] for k in ('attempt_id', 'generation', 'worker_id', 'lease_token')},
                         session_id='accepted-session')
        with self.assertRaisesRegex(ValueError, 'host_invalid_receipt'):
            self.finish(lease)

    def test_public_catalog_and_task_projection_exclude_private_worker_control(self):
        from service import TOOLS
        self.assertIn('commerce_execution_hosts', [t[0] for t in TOOLS])
        self.assertFalse(any(t[0].startswith('commerce_host_worker') for t in TOOLS))
        self.assertEqual(self.app.invoke('commerce_execution_hosts', {})['hosts'][0]['host_id'], 'dsh')
        task, run, _ = self.send(); attempt = self.request(task, run)
        job = self.app.invoke('commerce_market_research_get', {'task_id': task})
        self.assertEqual(job['host_attempts'][0]['attempt_id'], attempt['attempt_id'])


if __name__ == '__main__':
    unittest.main()
