"""Public dialogue contracts with synthetic native I/O and temporary state only.

These checks do not activate a daily worker or prove native host compatibility.
They exercise the actual shared Copilot/AgentRuntime/journal, not a second queue.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


POLICY = {'mode': 'auto', 'enabled': True, 'priority': ['dsh', 'hermes', 'codex']}


def answer(text='你好', questions=None):
    return {'decision': {'phase': 'answer', 'answer': text, 'questions': questions or [],
                         'evidence_refs': [], 'proposals': []}}


class AutoRoutingContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        (self.state / 'agent-model.json').write_text(json.dumps(
            {'provider': 'codex', 'model': 'synthetic-fixed-model'}))
        self.app = Commerce(self.state)
        self.addCleanup(self.app.agent_runtime.stop)
        self.calls = []
        self.native_response = answer()
        self.native_error = None
        # Native availability is supplied only by explicit synthetic registrations.
        # No installed command, credential, model or endpoint may be invoked.
        for guard in (
            patch('host_execution.shutil.which', return_value=None),
            patch('agent_runtime.codex_provider.KNOWN_BINARIES', ()),
            patch('host_native.hermes_command', side_effect=ValueError('agent_host_unavailable_use_workbench')),
            patch('agent_runtime.model.invoke', side_effect=AssertionError('Auto must not invoke the legacy provider')),
            patch('host_native.invoke', side_effect=self.native),
        ):
            guard.start()
            self.addCleanup(guard.stop)

    def enable(self, **updates):
        (self.state / 'conversation-routing.json').write_text(json.dumps({**POLICY, **updates}))

    def register(self, *hosts):
        for host in hosts:
            self.app.host_execution.register(host, 'synthetic-dsh' if host == 'dsh' else 'codex',
                                             'synthetic-' + host)

    def open(self, key='thread', context=None):
        return self.app.invoke('commerce_copilot_open', {
            'context': context or {'module': 'overview', 'demo': False}, 'idempotency_key': key})

    def send(self, thread, message='你好', key='send'):
        return self.app.invoke('commerce_copilot_send', {
            'thread_id': thread['id'], 'message': message, 'context_sha256': thread['context_sha256'],
            'idempotency_key': key})

    def automatic(self):
        items = self.app.invoke('commerce_model_list', {})['models']
        item = next((value for value in items if value['id'] == 'project-auto'), None)
        self.assertIsNotNone(item, 'Opt-in automatic host choice is absent from the real catalog')
        return item

    def selected_host(self, sent):
        choice = sent['latest_run']['model_choice']
        self.assertIn('host_id', choice, 'Public run must expose its frozen actual host')
        self.assertTrue(choice.get('routing_reason'), 'Automatic choice needs an inspectable reason')
        return choice['host_id']

    def count(self, table):
        with self.app.core.db() as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def payload(self, run_id):
        with self.app.core.db() as db:
            return json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?', (run_id,)).fetchone()[0])

    def native(self, lease, cancelled):
        self.calls.append(deepcopy(lease))
        if self.native_error:
            raise ValueError(self.native_error)
        route = lease['request']['route']
        return {'data': deepcopy(self.native_response), 'receipt': {
            'session_id': 'synthetic-native-' + lease['attempt_id'], 'provider': route['provider'],
            'model': route['model'], 'finish_reason': 'completed', 'tools_used': []}}

    def execute(self, result=None):
        if result is not None:
            self.native_response = result
        # DSH is an external broker worker. The real parent driver and real
        # claim/finish journal still execute; only native inference is synthetic.
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.app.agent_runtime.run_once)
            deadline = time.monotonic() + 4
            try:
                while not future.done() and time.monotonic() < deadline:
                    lease = self.app.host_execution.claim('dsh', 'synthetic-auto-worker')
                    if lease:
                        value = self.native(lease, lambda: False)
                        self.app.host_execution.finish(lease['attempt_id'], lease['generation'],
                            lease['worker_id'], lease['lease_token'], 'completed', value['data'],
                            {**value['receipt'], 'request_id': lease['request_id']})
                    time.sleep(.01)
                self.assertTrue(future.done(), 'Parent driver did not settle within the synthetic I/O budget')
                self.assertTrue(future.result())
            finally:
                if not future.done():
                    self.app.agent_runtime.stop_event.set()
                    future.result(timeout=2)

    def test_opt_in_selects_only_one_highest_priority_available_host(self):
        for available, expected in [(('dsh', 'hermes', 'codex'), 'dsh'),
                                    (('hermes', 'codex'), 'hermes'), (('codex',), 'codex')]:
            with self.subTest(available=available):
                with self.app.core.db() as db:
                    db.execute('DELETE FROM execution_hosts')
                self.enable()
                self.register(*available)
                self.assertTrue(self.automatic()['selectable'])
                sent = self.send(self.open('priority-' + expected), key='priority-' + expected)
                self.assertEqual(self.selected_host(sent), expected)
                self.assertEqual(len(sent['latest_run'].get('execution_hosts', [])), 1)
                self.app.copilot.cancel(sent['id'], sent['latest_run']['id'])
        self.assertEqual(self.count('tasks'), 0)
        self.assertEqual(self.calls, [])

    def test_missing_or_disabled_policy_preserves_the_existing_default(self):
        for policy in [None, {**POLICY, 'enabled': False}]:
            with self.subTest(policy=policy):
                if policy is not None:
                    (self.state / 'conversation-routing.json').write_text(json.dumps(policy))
                sent = self.send(self.open('legacy-' + str(bool(policy))), key='legacy')
                self.assertEqual(sent['model_selection']['model_id'], 'project-default')
                self.assertEqual(sent['latest_run']['model_choice']['model'], 'synthetic-fixed-model')
                self.assertFalse(sent['latest_run'].get('execution_hosts'))
                self.app.copilot.cancel(sent['id'], sent['latest_run']['id'])

    def test_invalid_policy_and_no_eligible_host_fail_closed(self):
        for policy in [{**POLICY, 'priority': ['injected-host']}, {**POLICY, 'enabled': 'true'}, POLICY]:
            with self.subTest(policy=policy):
                (self.state / 'conversation-routing.json').write_text(json.dumps(policy))
                item = self.automatic()
                self.assertFalse(item['selectable'])
                self.assertEqual(self.count('tasks'), 0)
                self.assertEqual(self.calls, [])

    def test_explicit_fixed_and_custom_models_are_not_replaced_by_auto(self):
        self.enable()
        self.register('dsh', 'hermes', 'codex')
        self.automatic()
        profile = self.app.models.configure({'label': 'Synthetic custom', 'engine': 'custom',
            'base_url': 'http://127.0.0.1:1/v1', 'model': 'synthetic-custom'})
        with patch('model_providers.inference.invoke_json', return_value={'decision': {'ok': True}}):
            self.app.models.test(profile['id'], profile['revision'])
        self.app.models.set_enabled(profile['id'], True, profile['revision'])
        for model_id, model in [('project-default', 'synthetic-fixed-model'),
                                (profile['id'], 'synthetic-custom')]:
            thread = self.open('fixed-' + model_id)
            selected = self.app.invoke('commerce_copilot_model', {'thread_id': thread['id'],
                'model_id': model_id, 'expected_revision': thread['model_selection']['revision']})
            sent = self.send(selected)
            self.assertEqual(sent['latest_run']['model_choice']['model'], model)
            self.assertFalse(sent['latest_run'].get('execution_hosts'))
            self.app.copilot.cancel(sent['id'], sent['latest_run']['id'])

    def test_greeting_and_pure_arithmetic_finish_without_business_reads_or_tasks(self):
        self.enable()
        self.register('hermes')
        self.automatic()
        for index, question in enumerate(['你好', '1+1等于几？']):
            thread = self.open('general-' + str(index))
            sent = self.send(thread, question)
            self.assertEqual(self.selected_host(sent), 'hermes')
            self.execute(answer('你好' if index == 0 else '2'))
            run = self.app.copilot.get(thread['id'])['latest_run']
            self.assertEqual(run['status'], 'completed')
            native_input = self.calls[-1]['request']['payload']
            self.assertIs(native_input.get('evidence_required'), False)
            self.assertEqual(native_input['tools'], [])
            self.assertEqual(run['result']['observations'], [])
            self.assertIn('host_attempts', run)
            self.assertEqual(run['host_attempts'][-1]['phase'], 'dialogue_1')
            self.assertIsNone(run['host_attempts'][-1]['task_id'])
        self.assertEqual(self.count('tasks'), 0)

    def test_business_question_keeps_current_evidence_gate(self):
        self.enable()
        self.register('hermes')
        self.automatic()
        thread = self.open(context={'module': 'orders', 'demo': False})
        self.send(thread, '当前店铺订单和利润是多少？')
        self.execute(answer('本月利润为1000元'))
        run = self.app.copilot.get(thread['id'])['latest_run']
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['result']['error'], 'agent_current_evidence_required')
        self.assertIsNot(self.calls[-1]['request']['payload'].get('evidence_required'), False)
        self.assertEqual(self.count('tasks'), 0)

    def test_queued_auto_request_and_idempotent_retry_keep_the_frozen_route(self):
        self.enable()
        self.register('hermes')
        self.automatic()
        thread = self.open()
        sent = self.send(thread)
        self.assertEqual(self.selected_host(sent), 'hermes')
        frozen = self.payload(sent['latest_run']['id'])
        self.register('dsh', 'codex')
        with self.app.core.db() as db:
            db.execute("UPDATE execution_hosts SET seen=0 WHERE id='hermes'")
        retried = self.send(thread)
        self.assertEqual(retried['latest_run']['id'], sent['latest_run']['id'])
        self.assertEqual(self.payload(sent['latest_run']['id']), frozen)
        self.assertEqual(self.selected_host(retried), 'hermes')
        self.assertEqual(self.calls, [])

    def test_auto_clarification_keeps_original_host_when_a_higher_priority_host_appears(self):
        self.enable()
        self.register('hermes')
        self.automatic()
        thread = self.open()
        first = self.send(thread)
        self.execute(answer('请补充', questions=['请补充说明']))
        self.assertEqual(self.app.copilot.get(thread['id'])['latest_run']['status'], 'awaiting_input')
        self.register('dsh', 'codex')
        following = self.send(thread, '补充说明：你好', 'followup')
        self.assertEqual(following['latest_run']['parent_id'], first['latest_run']['id'])
        self.assertEqual(self.selected_host(following), 'hermes')
        self.assertEqual(following['context_sha256'], thread['context_sha256'])

    def test_legacy_clarification_does_not_switch_host_when_auto_becomes_default(self):
        thread = self.open()
        first = self.send(thread)
        with patch('agent_runtime.model.invoke', return_value={**answer('请补充', ['请补充说明']),
                                                            'provider': 'codex', 'model': 'synthetic-fixed-model'}):
            self.assertTrue(self.app.agent_runtime.run_once())
        self.enable()
        self.register('dsh', 'hermes', 'codex')
        self.automatic()
        following = self.send(thread, '补充说明', 'followup')
        self.assertEqual(following['latest_run']['parent_id'], first['latest_run']['id'])
        self.assertEqual(following['latest_run']['model_choice']['model'], 'synthetic-fixed-model')
        self.assertFalse(following['latest_run'].get('execution_hosts'))

    def test_unknown_generic_attempt_is_not_replayed_or_automatically_given_to_another_host(self):
        self.enable()
        self.register('hermes')
        self.automatic()
        thread = self.open()
        sent = self.send(thread)
        self.native_error = 'agent_provider_outcome_unknown'
        self.execute()
        unknown = self.app.copilot.get(thread['id'])['latest_run']
        self.assertEqual(unknown['status'], 'unknown')
        self.register('dsh', 'codex')
        for _ in range(3):
            self.app.copilot.get(thread['id'])
            self.assertFalse(self.app.agent_runtime.run_once())
        self.assertEqual(self.send(thread)['latest_run']['id'], sent['latest_run']['id'])
        with self.assertRaisesRegex(ValueError, 'unknown|unconfirmed'):
            self.send(thread, '继续', 'new-send-after-unknown')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.count('agent_host_attempts'), 1)
        self.assertEqual(self.count('tasks'), 0)

    def test_completed_generic_receipt_is_not_reused_across_threads(self):
        self.enable()
        self.register('hermes')
        self.automatic()
        runs = []
        for key in ['first-thread', 'second-thread']:
            thread = self.open(key)
            sent = self.send(thread)
            self.execute(answer())
            current = self.app.copilot.get(thread['id'])['latest_run']
            self.assertEqual(current['status'], 'completed')
            runs.append(sent['latest_run']['id'])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual({call['run_id'] for call in self.calls}, set(runs))
        self.assertEqual(len({call['attempt_id'] for call in self.calls}), 2)
        self.assertEqual(self.count('agent_host_attempts'), 2)
        self.assertEqual(self.count('tasks'), 0)


if __name__ == '__main__':
    unittest.main()
