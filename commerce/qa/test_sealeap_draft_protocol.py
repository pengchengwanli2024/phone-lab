"""Schema drift must stop before resolving a provider or submitting a paid call."""
import contextlib
import io
import json
from pathlib import Path
import sys
import subprocess
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sealeap_draft_worker as worker
from sealeap_drafts import invoke_model, validate_response


class ProtocolTests(unittest.TestCase):
    def worker_call(self, payload):
        raw = dict(status='needs_inputs', sections=[], questions=['Missing evidence'], limitations=[], requirement_checks=[])
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=json.dumps(raw)))], model='synthetic-model')
        create = Mock(return_value=response)
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        provider = types.ModuleType('hermes_cli.runtime_provider')
        config = Mock(return_value={'default': 'synthetic-model'})
        provider._get_model_config = config
        provider.resolve_runtime_provider = lambda **kw: {'provider': 'synthetic'}
        auxiliary = types.ModuleType('agent.auxiliary_client')
        auxiliary.resolve_provider_client = lambda *a, **kw: (client, 'synthetic-model')
        modules = {'hermes_cli': types.ModuleType('hermes_cli'), 'hermes_cli.runtime_provider': provider,
                   'agent': types.ModuleType('agent'), 'agent.auxiliary_client': auxiliary}
        out = io.StringIO();code = 0
        with patch.dict(sys.modules, modules), patch('sys.stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(out):
            try:
                worker.main()
            except SystemExit as error:
                code = error.code
        return code, json.loads(out.getvalue()), create, config

    def test_legacy_contract_stops_before_provider_resolution(self):
        code, result, create, config = self.worker_call({'contract': {'version': 'source-bound-draft-v1', 'sections': ['evidence_scope']}})
        self.assertEqual(code, 1)
        self.assertEqual(result['error'], 'sealeap_draft_contract_version_mismatch_refresh_required')
        self.assertFalse(result['outcome_unknown'])
        create.assert_not_called();config.assert_not_called()

    def test_current_version_preserves_response_shape_and_single_call(self):
        code, result, create, config = self.worker_call({'contract': {'version': 'source-bound-draft-v2', 'sections': ['evidence_scope'], 'source_requirements': []}})
        self.assertEqual(code, 0)
        self.assertEqual(set(result['draft']), {'status', 'sections', 'questions', 'limitations', 'requirement_checks'})
        create.assert_called_once();config.assert_called_once()
        self.assertEqual(create.call_args.kwargs['tools'], [])

    def test_unknown_version_and_incomplete_current_contract_stop_without_call(self):
        for contract in [{'version': 'future-version'}, {'version': 'source-bound-draft-v2', 'sections': ['evidence_scope']}]:
            with self.subTest(contract=contract):
                code, result, create, config = self.worker_call({'contract': contract})
                self.assertEqual(code, 1)
                self.assertFalse(result['outcome_unknown'])
                create.assert_not_called();config.assert_not_called()

    def test_host_preflight_stops_before_launching_child(self):
        with patch('sealeap_drafts.model_command') as command:
            with self.assertRaisesRegex(ValueError, 'contract_version_mismatch'):
                invoke_model({'contract': {'version': 'source-bound-draft-v1'}}, lambda: False)
            command.assert_not_called()

    def test_current_validator_does_not_accept_legacy_output(self):
        payload={'contract': {'version': 'source-bound-draft-v2', 'sections': ['evidence_scope'], 'source_requirements': []}}
        with self.assertRaisesRegex(ValueError, 'sealeap_draft_invalid_response'):
            validate_response(payload, {'draft': {'status': 'needs_inputs', 'sections': [], 'questions': ['missing'], 'limitations': []}})

    def test_isolated_runpy_rejects_legacy_without_loading_provider(self):
        result = subprocess.run([sys.executable, '-I', '-c', 'import runpy,sys;runpy.run_path(sys.argv[1],run_name="__main__")', str(Path(worker.__file__).resolve())],
                                input=json.dumps({'contract': {'version': 'source-bound-draft-v1'}}), text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error'], 'sealeap_draft_contract_version_mismatch_refresh_required')
        self.assertEqual(result.stderr, '')
