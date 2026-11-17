import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from host_diagnostics import latest


class HostDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.attempt = dict(attempt_id='a' * 32, request_id='b' * 32,
                            phase='dialogue_3', status='unknown',
                            route=dict(provider='test-provider', model='test-model'))
        self.path = self.state / 'host-work' / self.attempt['attempt_id'] / 'outcome.json'
        self.path.parent.mkdir(parents=True)
        self.diagnostic = dict(schema='commerce-native-outcome-v1',
                               attempt_id=self.attempt['attempt_id'],
                               request_id=self.attempt['request_id'], phase='dialogue_3',
                               provider='test-provider', model='test-model',
                               code='native_output_limit', submitted=True,
                               max_tokens=8192, recorded_at=1000)

    def write(self, **changes):
        self.path.write_text(json.dumps({**self.diagnostic, **changes}))

    def test_exact_terminal_diagnostic_is_read_without_changing_original(self):
        self.write(prompt='must not leak', error='private response')
        before = json.dumps(self.attempt)
        result = latest(self.state, [self.attempt])
        self.assertEqual(result, dict(code='native_output_limit', attempt_id='a' * 32,
                                     phase='dialogue_3', recorded_at=1000))
        self.assertEqual(before, json.dumps(self.attempt))
        self.assertEqual(json.loads(self.path.read_text())['prompt'], 'must not leak')

    def test_mismatched_identity_or_nonterminal_attempt_cannot_explain_a_run(self):
        for key, value in [('request_id', 'c' * 32), ('attempt_id', 'c' * 32),
                           ('provider', 'other'), ('model', 'other'),
                           ('phase', 'dialogue_1'), ('schema', 'other'),
                           ('code', 'arbitrary error'), ('submitted', False),
                           ('recorded_at', '1000')]:
            with self.subTest(key=key):
                self.write(**{key: value})
                self.assertIsNone(latest(self.state, [self.attempt]))
        self.write()
        for status in ('completed', 'pending', 'claimed'):
            self.assertIsNone(latest(self.state, [{**self.attempt, 'status': status}]))

    def test_missing_invalid_oversize_and_symlink_are_ignored(self):
        self.assertIsNone(latest(self.state, [self.attempt]))
        self.path.write_text('{')
        self.assertIsNone(latest(self.state, [self.attempt]))
        self.path.write_text(' ' * 4097)
        self.assertIsNone(latest(self.state, [self.attempt]))
        self.path.unlink()
        target = self.state / 'unrelated.json'
        target.write_text(json.dumps(self.diagnostic))
        self.path.symlink_to(target)
        self.assertIsNone(latest(self.state, [self.attempt]))
        self.assertIsNone(latest(self.state, [{**self.attempt, 'attempt_id': '../unrelated'}]))

    def test_only_the_last_attempt_may_explain_the_unconfirmed_result(self):
        self.write()
        later = {**self.attempt, 'attempt_id': 'c' * 32}
        self.assertIsNone(latest(self.state, [self.attempt, later]))

    def test_real_run_read_attaches_diagnostic_without_rewriting_result_or_history(self):
        from service import Commerce
        (self.state / 'agent-model.json').write_text(json.dumps(
            {'provider': 'codex', 'model': 'synthetic'}))
        (self.state / 'conversation-routing.json').write_text(json.dumps(
            {'mode': 'auto', 'enabled': True, 'priority': ['dsh', 'hermes', 'codex']}))
        app = Commerce(self.state)
        self.addCleanup(app.agent_runtime.stop)
        app.host_execution.register('dsh', 'test-provider', 'test-model')
        thread = app.copilot.open({'module': 'intelligence', 'demo': False}, 'diagnostic-test')
        sent = app.copilot.send(thread['id'], '检索今日公开新闻', thread['context_sha256'], 'send')
        ident = sent['latest_run']['id']
        with patch.object(app.host_execution, 'invoke_run', side_effect=ValueError('agent_provider_outcome_unknown')):
            app.agent_runtime.run_once()
        self.write()
        with app.core.db() as db:
            before = db.execute('SELECT status,result,trace FROM agent_runs WHERE id=?', (ident,)).fetchone()
        with patch.object(app.host_execution, 'for_run', return_value=[self.attempt]):
            result = app.copilot.get(thread['id'])
        run = result['latest_run']
        self.assertEqual(run.get('host_diagnostic', {}).get('code'), 'native_output_limit')
        self.assertEqual(run['status'], 'unknown')
        self.assertEqual(run['actions'], [])
        self.assertEqual(result['total_turns'], 1)
        with app.core.db() as db:
            after = db.execute('SELECT status,result,trace FROM agent_runs WHERE id=?', (ident,)).fetchone()
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
