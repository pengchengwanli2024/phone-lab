"""CLI automation contract at the request boundary; no server, worker or model."""
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
import importlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import runtime


class AssistantCLIAutomation(unittest.TestCase):
    def setUp(self):
        self.cli = importlib.import_module('assistant_cli')
        self.temp = tempfile.TemporaryDirectory(prefix='assistant-cli-automation-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requests = []
        self.response = {}
        self.request_error = None
        self.original_request = self.cli._request
        guard = patch.object(self.cli, '_request', side_effect=self.request)
        guard.start(); self.addCleanup(guard.stop)
        guard = patch.object(runtime, 'ensure', side_effect=AssertionError('CLI must not start services'))
        guard.start(); self.addCleanup(guard.stop)

    def request(self, suffix, arguments, **kwargs):
        self.requests.append((suffix, arguments, kwargs))
        if self.request_error:
            raise self.request_error
        return self.response

    def call(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.cli.main(list(arguments))
        self.assertEqual(err.getvalue(), '')
        self.assertNotIn('PRIVATE_AUTOMATION_SENTINEL', out.getvalue())
        return code, json.loads(out.getvalue())

    def source(self, text, name='input.json'):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return str(path)

    @staticmethod
    def discussion(status='queued'):
        return {'id': 'discussion_synthetic', 'channel_id': 'channel_synthetic', 'status': status,
                'mode': 'collaborate', 'max_rounds': 2, 'created': 12.0, 'updated': 12.5,
                'plan': [{'index': 0, 'round': 1, 'profile_id': 'profile_synthetic', 'name': 'Public member',
                          'kind': 'contribution', 'status': status, 'run_id': 'run_original',
                          'private_config': 'PRIVATE_AUTOMATION_SENTINEL'}],
                'routing_decision': {'selected_member_ids': ['profile_synthetic'],
                    'selected_member_names': ['Public member'], 'lead_id': 'profile_synthetic',
                    'reason': 'lead_fallback', 'matched_keywords': [], 'token': 'PRIVATE_AUTOMATION_SENTINEL'},
                'budget': {'max_member_requests': 3, 'used_member_requests': 1,
                           'private_config': 'PRIVATE_AUTOMATION_SENTINEL'},
                'final_answer': 'Public synthesis' if status == 'completed' else '',
                'members': [{'profile_id': 'profile_synthetic', 'name': 'Public member',
                             'run_id': 'run_original', 'original_run_id': 'run_original', 'status': status,
                             'index': 0, 'round': 1, 'kind': 'contribution', 'answer': 'Public answer'}],
                'private_config': 'PRIVATE_AUTOMATION_SENTINEL'}

    @staticmethod
    def trigger():
        return {'id': 'trigger_synthetic', 'name': 'Public trigger', 'kind': 'manual',
                'channel_id': 'channel_synthetic', 'channel_revision': 2, 'revision': 1,
                'question': 'Public question', 'dispatch_mode': 'auto', 'max_rounds': 1,
                'schedule': {}, 'enabled': False, 'created': 12.0, 'next_at': None,
                'pins': {'token': 'PRIVATE_AUTOMATION_SENTINEL'}, 'history': [],
                'private_config': 'PRIVATE_AUTOMATION_SENTINEL'}

    def test_ask_forwards_only_explicit_automation_options(self):
        self.response = self.discussion()
        original = ('ask', '--channel', 'channel_synthetic', '--revision', '2',
                    '--question', 'Public question', '--key', 'ask-key')
        self.assertEqual(self.call(*original)[0], 0)
        self.assertEqual(self.requests[-1][:2], ('discussion_start', {
            'channel_id': 'channel_synthetic', 'expected_revision': 2,
            'question': 'Public question', 'idempotency_key': 'ask-key'}))
        for mode in ('all', 'auto', 'collaborate'):
            code, result = self.call(*original, '--mode', mode, '--rounds', '2', '--playbook', 'review')
            self.assertEqual((code, result.get('mode')), (0, 'collaborate'))
            self.assertEqual(self.requests[-1][1], {'channel_id': 'channel_synthetic', 'expected_revision': 2,
                'question': 'Public question', 'idempotency_key': 'ask-key',
                'mode': mode, 'max_rounds': 2, 'playbook_key': 'review'})

    def test_get_and_wait_keep_collaboration_evidence_without_runtime_configuration(self):
        self.response = self.discussion('completed')
        for command in ('get', 'wait'):
            with self.subTest(command=command):
                code, value = self.call(command, '--discussion', 'discussion_synthetic')
                result = value['discussion'] if command == 'wait' else value
                self.assertEqual(code, 0)
                self.assertEqual(result.get('updated'), 12.5)
                self.assertEqual(result.get('final_answer'), 'Public synthesis')
                self.assertEqual(result.get('budget'), {'max_member_requests': 3, 'used_member_requests': 1})
                self.assertEqual(result.get('plan', [{}])[0].get('run_id'), 'run_original')
                self.assertEqual(result.get('routing_decision', {}).get('reason'), 'lead_fallback')
                self.assertEqual(result['members'][0].get('round'), 1)
                self.assertEqual(self.requests[-1][0], 'discussion_get')
        self.assertEqual(len(self.requests), 2)

    def test_wait_on_paused_collaboration_never_advances_or_resends(self):
        self.response = self.discussion('awaiting_input')
        code, result = self.call('wait', '--discussion', 'discussion_synthetic', '--timeout', '1')
        self.assertEqual((code, result['outcome']), (2, 'awaiting_input'))
        self.assertEqual([item[0] for item in self.requests], ['discussion_get'])

    def test_advance_uses_the_supplied_version_once_and_keeps_conflicts_safe(self):
        self.response = self.discussion('running')
        command = ('advance', '--discussion', 'discussion_synthetic', '--expected-updated', '12.5')
        self.assertEqual(self.call(*command)[0], 0)
        self.assertEqual(self.requests, [('discussion_advance', {
            'discussion_id': 'discussion_synthetic', 'expected_updated': 12.5}, {})])
        self.request_error = ValueError('team_discussion_changed')
        code, result = self.call(*command)
        self.assertEqual((code, result), (3, {'error': 'team_discussion_changed'}))
        self.assertEqual(len(self.requests), 2)

    def test_new_numeric_options_reject_nonfinite_and_out_of_range_before_request(self):
        commands = [
            ('advance', '--discussion', 'discussion_synthetic', '--expected-updated', value)
            for value in ('nan', 'inf', '-inf', '1e999', 'private-invalid')]
        commands += [('ask', '--channel', 'channel_synthetic', '--revision', '1', '--question', 'Public',
                      '--key', 'ask-key', '--rounds', value) for value in ('0', '4', '1.5', 'nan')]
        commands += [('trigger-enable', '--trigger', 'trigger_synthetic', '--revision', value)
                     for value in ('0', '-1', 'nan', '1.5')]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.call(*command), (2, {'error': 'assistant_cli_invalid_arguments'}))
        self.assertEqual(self.requests, [])

    def test_catalog_returns_compact_installed_presets(self):
        self.response = {'presets': [{'id': 'preset_synthetic', 'name': 'Public team', 'created': 12.0,
            'source_format': 'json', 'package': {'profiles': [{}], 'channels': [{}], 'playbooks': [{}],
                'instructions': 'PRIVATE_AUTOMATION_SENTINEL'}, 'private_config': 'PRIVATE_AUTOMATION_SENTINEL'}]}
        code, result = self.call('catalog')
        self.assertEqual(code, 0)
        self.assertEqual(result.get('presets'), [{'id': 'preset_synthetic', 'name': 'Public team',
            'created': 12.0, 'source_format': 'json',
            'counts': {'profiles': 1, 'channels': 1, 'playbooks': 1, 'starter_notes': 0,
                       'skills': 0, 'connector_requirements': 0, 'triggers': 0}}])

    def test_export_supports_presets_and_keeps_legacy_payload_and_private_exclusive_writes(self):
        self.response = {'content': '# Public team\nPublic package\n', 'sha256': 'a' * 64}
        variants = [(['--channel', 'channel_synthetic'], {'channel_id': 'channel_synthetic', 'name': 'Public team'}),
                    (['--preset', 'preset_synthetic', '--version', '2'],
                     {'preset_id': 'preset_synthetic', 'name': 'Public team', 'version': 2}),
                    (['--channel', 'channel_synthetic', '--version', '2'],
                     {'channel_id': 'channel_synthetic', 'name': 'Public team', 'version': 2})]
        for i, (flags, payload) in enumerate(variants):
            destination = self.root / ('team-' + str(i) + '.md')
            command = ('export', *flags, '--name', 'Public team', '--output', str(destination))
            code, result = self.call(*command)
            self.assertEqual((code, result.get('status')), (0, 'exported'))
            self.assertEqual(self.requests[-1][:2], ('package_export', payload))
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            self.assertEqual(self.call(*command), (3, {'error': 'assistant_cli_output_exists'}))
            self.assertEqual(destination.read_text(), '# Public team\nPublic package\n')

    def test_export_requires_one_source(self):
        for flags in ([], ['--channel', 'channel_synthetic', '--preset', 'preset_synthetic']):
            code, _ = self.call('export', *flags, '--name', 'Public', '--output', str(self.root / 'absent.md'))
            self.assertEqual(code, 2)
        self.assertEqual(self.requests, [])

    def test_import_returns_paused_triggers_and_preset_without_activating_anything(self):
        source = self.source('# Public team\nPackage\n', 'team.md')
        preset = {'id': 'preset_synthetic', 'name': 'Public team', 'created': 12.0,
                  'package': {'profiles': [{}], 'channels': [{}]}, 'private_config': 'PRIVATE_AUTOMATION_SENTINEL'}
        preview = {'sha256': 'a' * 64, 'package': {}, 'source_format': 'json', 'execution_started': False}
        imported = {'status': 'imported', 'package_sha256': 'a' * 64, 'execution_started': False,
                    'profiles': [], 'channels': [], 'triggers': [self.trigger()], 'preset': preset}
        with patch.object(self.cli, '_request', side_effect=[preview, imported]) as boundary:
            code, result = self.call('import', '--file', source, '--expected-sha', 'a' * 64, '--key', 'import-key')
        self.assertEqual((code, result.get('execution_started')), (0, False))
        self.assertEqual(result.get('preset', {}).get('id'), 'preset_synthetic')
        self.assertFalse(result.get('triggers', [{}])[0].get('enabled', True))
        self.assertEqual([item.args[0] for item in boundary.call_args_list], ['package_preview', 'package_import'])

    def test_trigger_list_and_get_use_only_read_tools_and_hide_pins(self):
        self.response = {'triggers': [self.trigger()]}
        code, result = self.call('trigger-list', '--channel', 'channel_synthetic')
        self.assertEqual((code, result.get('triggers', [{}])[0].get('revision')), (0, 1))
        self.assertEqual(self.requests[-1][:2], ('trigger_list', {'channel_id': 'channel_synthetic'}))
        self.response = self.trigger()
        code, result = self.call('trigger-get', '--trigger', 'trigger_synthetic')
        self.assertEqual((code, result.get('enabled')), (0, False))
        self.assertNotIn('pins', result)
        self.assertEqual(self.requests[-1][:2], ('trigger_get', {'trigger_id': 'trigger_synthetic'}))

    def test_trigger_save_sends_json_object_and_optional_revision_without_enabling(self):
        definition = {'name': 'Public trigger', 'kind': 'manual', 'channel_id': 'channel_synthetic',
                      'channel_revision': 2, 'question': 'Public question', 'dispatch_mode': 'auto',
                      'max_rounds': 1, 'schedule': {}}
        source = self.source(json.dumps(definition))
        self.response = self.trigger()
        self.assertEqual(self.call('trigger-save', '--file', source)[0], 0)
        self.assertEqual(self.requests[-1][:2], ('trigger_save', {'trigger': definition}))
        self.assertEqual(self.call('trigger-save', '--file', source, '--revision', '3')[0], 0)
        self.assertEqual(self.requests[-1][:2], ('trigger_save', {'trigger': definition, 'expected_revision': 3}))
        self.assertEqual([item[0] for item in self.requests], ['trigger_save', 'trigger_save'])

    def test_trigger_pause_is_explicit_disable_and_never_runs(self):
        self.response = self.trigger()
        for command, enabled in (('trigger-enable', True), ('trigger-pause', False)):
            self.assertEqual(self.call(command, '--trigger', 'trigger_synthetic', '--revision', '3')[0], 0)
            self.assertEqual(self.requests[-1][:2], ('trigger_enable', {
                'trigger_id': 'trigger_synthetic', 'expected_revision': 3, 'enabled': enabled}))

    def test_trigger_run_and_event_preserve_dispatch_receipt_without_waiting(self):
        self.response = {'id': 'event_synthetic', 'status': 'dispatched', 'trigger_id': 'trigger_synthetic',
            'discussion_id': 'discussion_synthetic', 'discussion': self.discussion(),
            'payload_sha256': 'a' * 64, 'private_config': 'PRIVATE_AUTOMATION_SENTINEL'}
        code, result = self.call('trigger-run', '--trigger', 'trigger_synthetic', '--revision', '3', '--key', 'run-key')
        self.assertEqual((code, result.get('status')), (0, 'dispatched'))
        self.assertEqual(result.get('discussion', {}).get('status'), 'queued')
        self.assertEqual(self.requests[-1][:2], ('trigger_run', {
            'trigger_id': 'trigger_synthetic', 'expected_revision': 3, 'idempotency_key': 'run-key'}))
        payload = {'type': 'public_event', 'count': 1, 'items': ['public']}
        source = self.source(json.dumps(payload))
        code, result = self.call('trigger-event', '--trigger', 'trigger_synthetic', '--revision', '3',
                                 '--event-id', 'source-event-1', '--file', source)
        self.assertEqual((code, result.get('status')), (0, 'dispatched'))
        self.assertEqual(self.requests[-1][:2], ('trigger_event', {'trigger_id': 'trigger_synthetic',
            'expected_revision': 3, 'event_id': 'source-event-1', 'payload': payload}))
        self.assertEqual([item[0] for item in self.requests], ['trigger_run', 'trigger_event'])

    def test_trigger_history_keeps_event_status_and_safe_discussion_evidence(self):
        self.response = self.trigger()
        self.response['history'] = [{'id': 'event_synthetic', 'status': 'blocked',
            'error': 'team_trigger_source_changed', 'payload_sha256': 'a' * 64,
            'discussion': self.discussion('awaiting_review'), 'private_config': 'PRIVATE_AUTOMATION_SENTINEL'}]
        code, result = self.call('trigger-get', '--trigger', 'trigger_synthetic')
        self.assertEqual((code, result.get('history', [{}])[0].get('status')), (0, 'blocked'))
        self.assertEqual(result['history'][0]['error'], 'team_trigger_source_changed')
        self.assertEqual(result['history'][0]['discussion']['updated'], 12.5)

    def test_invalid_json_files_are_rejected_before_any_request(self):
        values = ('[]', '"text"', 'null', '{broken', '{"a":1,"a":2}', '{"n":NaN}',
                  '{"n":Infinity}', '{"n":1e999}', '{"text":"\\ud800"}',
                  '{"deep":' + '[' * 1100 + '0' + ']' * 1100 + '}')
        for i, value in enumerate(values):
            with self.subTest(case=i):
                source = self.source(value)
                code, result = self.call('trigger-save', '--file', source)
                self.assertEqual((code, result.get('error')), (3, 'assistant_cli_invalid_json'))
        self.assertEqual(len(self.requests), 0)

    def test_json_files_are_bounded_and_unsafe_paths_never_reach_the_service(self):
        regular = self.root / 'regular.json'; regular.write_text('{}')
        link = self.root / 'link.json'; link.symlink_to(regular)
        fifo = self.root / 'pipe'; os.mkfifo(fifo)
        bad_utf8 = self.root / 'bad.json'; bad_utf8.write_bytes(b'\xff')
        too_large = self.source('{"text":"' + 'x' * 65536 + '"}', 'large.json')
        for path in (link, fifo, self.root, bad_utf8, too_large):
            with self.subTest(path=Path(path).name):
                self.assertEqual(self.call('trigger-save', '--file', str(path))[0], 3)
        event = self.source('{"text":"' + 'x' * 8192 + '"}', 'event.json')
        code, result = self.call('trigger-event', '--trigger', 'trigger_synthetic', '--revision', '1',
                                 '--event-id', 'event-key', '--file', event)
        self.assertEqual((code, result.get('error')), (3, 'assistant_cli_json_too_large'))
        self.assertEqual(self.requests, [])
        self.assertEqual(regular.read_text(), '{}')

    def test_trigger_conflict_is_not_retried_and_private_backend_errors_are_sanitized(self):
        for error, expected in (('team_trigger_revision_changed', 'team_trigger_revision_changed'),
                                ('token=PRIVATE_AUTOMATION_SENTINEL', 'assistant_cli_request_failed')):
            self.request_error = ValueError(error)
            code, result = self.call('trigger-run', '--trigger', 'trigger_synthetic', '--revision', '2', '--key', 'run-key')
            self.assertEqual((code, result), (3, {'error': expected}))
        self.assertEqual([item[0] for item in self.requests], ['trigger_run', 'trigger_run'])

    def test_trigger_commands_keep_original_authentication_without_autostart(self):
        state = self.root / 'state'; state.mkdir(mode=0o700)
        (state / 'auth.token').write_text('synthetic-local-auth')
        original_request = self.original_request
        with patch.object(self.cli, '_request', original_request), patch.object(runtime, 'STATE', state), \
                patch.object(runtime, 'request', return_value={'triggers': []}) as boundary:
            self.assertEqual(self.call('trigger-list'), (0, {'triggers': []}))
            boundary.assert_called_once_with('commerce_assistant_team_trigger_list', {}, client='local', timeout=None)
        (state / 'auth.token').unlink()
        with patch.object(self.cli, '_request', original_request), patch.object(runtime, 'STATE', state), \
                patch.object(runtime, 'request', side_effect=AssertionError('missing auth must not connect')):
            self.assertEqual(self.call('trigger-list'), (3, {'error': 'assistant_cli_auth_required'}))
        self.assertFalse((state / 'auth.token').exists())


if __name__ == '__main__':
    unittest.main()
