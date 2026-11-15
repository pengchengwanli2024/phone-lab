"""Declared Agent results constrain inference and remain host-validated."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_extension_runtime import RuntimeCase
from test_extension_runtime_agents import Models
from extension_runtime import ExtensionRuntime


class AgentOutputContract(RuntimeCase):
    def test_saved_output_schema_reaches_compatible_model(self):
        self.service.models = Models()
        contract = {'type': 'object', 'properties': {'advice': {'type': 'array', 'items': {'type': 'string'}}},
                    'required': ['advice'], 'additionalProperties': False}
        ext = self.ready(kind='agent', output_schema=contract,
                         spec={'instructions': 'Synthetic advice.', 'tools': [], 'max_turns': 1})
        run = self.call('run', extension_id=ext['id'], idempotency_key='declared-result',
                        budget={'allow_model_calls': True})
        with patch('model_providers.inference.invoke_json', return_value={
                'decision': {'action': 'finish', 'output': {'advice': ['Synthetic']}}}) as inference:
            result = self.drain(run)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(inference.call_args.kwargs['output_schema']['properties']['output'], contract)

    def test_codex_route_receives_same_output_contract(self):
        contract = {'type': 'string', 'minLength': 1}
        with patch('agent_runtime.codex_provider.invoke_json', return_value={
                'action': 'finish', 'output': 'Synthetic'}) as inference:
            result = ExtensionRuntime._model({}, lambda: False, {'provider': 'codex'},
                                             'Synthetic advice.', contract)
        self.assertEqual(result['output'], 'Synthetic')
        self.assertEqual(inference.call_args.args[3]['properties']['output'], contract)

    def test_invalid_actual_result_is_still_rejected_without_retry(self):
        self.service.models = Models()
        ext = self.ready(kind='agent', output_schema={'type': 'object'},
                         spec={'instructions': 'Synthetic only.', 'tools': [], 'max_turns': 1})
        run = self.call('run', extension_id=ext['id'], idempotency_key='bad-result',
                        budget={'allow_model_calls': True})
        with patch('model_providers.inference.invoke_json', return_value={
                'decision': {'action': 'finish', 'output': ['invalid']}}) as inference:
            result = self.drain(run)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'extension_schema_type')
        self.assertIsNone(result['output'])
        self.assertEqual(inference.call_count, 1)


if __name__ == '__main__':
    unittest.main()
