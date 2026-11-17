"""Validate the actual JSON examples sent by each structured transport, without IO."""
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_runtime import codex_provider
from agent_runtime.model_worker import SYSTEM
from host_execution import HostExecution
from model_providers import inference
from model_providers.decision_contract import decode as decode_local
from jsonschema import validate


ANSWER = {'phase': 'answer', 'answer': '合成回答', 'questions': [], 'evidence_refs': [], 'proposals': []}


class StructuredModelInstructions(unittest.TestCase):
    def assert_examples_match_schema(self, instructions, output_schema, decoder, arguments_key):
        # Decode the envelope itself; surrounding prose and language are not
        # delimiters, and may contain ordinary phrases such as "or saved task".
        starts = list(re.finditer(r'\{\s*"decision"\s*:', instructions))
        self.assertEqual(len(starts), 2, 'Exactly one example for each phase is required')
        examples = [json.JSONDecoder().raw_decode(instructions[start.start():])[0]
                    for start in starts]
        self.assertCountEqual([example['decision']['phase'] for example in examples],
                              ['inspect', 'answer'])
        for example in examples:
            validate(example, output_schema)
            decoded = decoder(example)
            if example['decision']['phase'] == 'answer':
                self.assertEqual(decoded, example['decision'])
                continue
            expected_calls = []
            for call in example['decision']['calls']:
                self.assertEqual(set(call), {'tool', arguments_key})
                arguments = call[arguments_key]
                if arguments_key == 'arguments_json':
                    self.assertIsInstance(arguments, str)
                    arguments = json.loads(arguments)
                self.assertIsInstance(arguments, dict)
                expected_calls.append({'tool': call['tool'], 'arguments': arguments})
            self.assertEqual(decoded, {'phase': 'inspect', 'calls': expected_calls})

    def test_native_host_prompt_examples_match_the_committed_result_schema(self):
        host = object.__new__(HostExecution)
        payload = {'observations': [],
                   'tools': [{'tool': 'commerce_runtime_status', 'arguments': {}}]}
        with patch.object(host, 'generate', return_value={
                'data': {'decision': ANSWER}, 'host_id': 'dsh', 'model': 'synthetic'}) as generate:
            host.invoke_run('synthetic-run', 1, payload, lambda: False)
        self.assert_examples_match_schema(generate.call_args.args[4], generate.call_args.args[3],
                                          codex_provider.decode, 'arguments_json')

    def test_codex_prompt_examples_match_the_cli_schema(self):
        payload = {'observations': [],
                   'tools': [{'tool': 'commerce_runtime_status', 'arguments': {}}]}
        with patch.object(codex_provider, 'invoke_json', return_value={'decision': ANSWER}) as invoke:
            codex_provider.invoke(payload, lambda: False, {'model': 'synthetic'})
        self.assert_examples_match_schema(invoke.call_args.args[4], invoke.call_args.args[3],
                                          codex_provider.decode, 'arguments_json')

    def test_local_structured_prompt_examples_match_the_http_schema(self):
        # The generic local prompt documents a tool-name placeholder and R1.
        # Declare those exact synthetic inputs so both offered phases remain
        # available, without changing the emitted examples or relaxing schema.
        payload = {'observations': [{'id': 'R1', 'tool': 'commerce_runtime_status', 'data': {}}],
                   'tools': [{'tool': '允许工具名', 'arguments': {}}]}
        answer = {**ANSWER, 'evidence_refs': ['R1']}
        for engine in ('llama_cpp', 'vllm'):
            with self.subTest(engine=engine), patch.object(inference, 'invoke_json', return_value={
                    'decision': {'decision': answer}}) as invoke:
                inference.invoke(payload, lambda: False, {'engine': engine})
                self.assert_examples_match_schema(invoke.call_args.args[3],
                                                  invoke.call_args.kwargs['output_schema'],
                                                  decode_local, 'arguments')

    def test_legacy_http_keeps_the_original_unwrapped_protocol(self):
        with patch.object(inference, 'invoke_json', return_value={'decision': ANSWER}) as invoke:
            inference.invoke({}, lambda: False, {'engine': 'compatible'})
        self.assertEqual(invoke.call_args.args[3], SYSTEM)
        self.assertNotIn('output_schema', invoke.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
