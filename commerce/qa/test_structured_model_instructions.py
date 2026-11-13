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
from jsonschema import validate


ANSWER = {'phase': 'answer', 'answer': '合成回答', 'questions': [], 'evidence_refs': [], 'proposals': []}


class StructuredModelInstructions(unittest.TestCase):
    def assert_examples_match_schema(self, instructions):
        block = re.search(r'Return ONLY JSON[^:\n]*:\n(.*?)\nFor report', instructions, re.S)
        self.assertIsNotNone(block, 'The requested output examples must be explicit')
        examples = block.group(1).strip().removesuffix('.').split('\nor ')
        self.assertEqual(len(examples), 2)
        for text in examples:
            example, _ = json.JSONDecoder().raw_decode(text)
            validate(example, codex_provider.schema())
            codex_provider.decode(example)

    def test_native_host_prompt_examples_match_the_committed_result_schema(self):
        host = object.__new__(HostExecution)
        with patch.object(host, 'generate', return_value={
                'data': {'decision': ANSWER}, 'host_id': 'dsh', 'model': 'synthetic'}) as generate:
            host.invoke_run('synthetic-run', 1, {'observations': []}, lambda: False)
        self.assert_examples_match_schema(generate.call_args.args[4])

    def test_codex_prompt_examples_match_the_cli_schema(self):
        with patch.object(codex_provider, 'invoke_json', return_value={'decision': ANSWER}) as invoke:
            codex_provider.invoke({'observations': []}, lambda: False, {'model': 'synthetic'})
        self.assert_examples_match_schema(invoke.call_args.args[4])

    def test_local_structured_prompt_examples_match_the_http_schema(self):
        for engine in ('llama_cpp', 'vllm'):
            with self.subTest(engine=engine), patch.object(inference, 'invoke_json', return_value={
                    'decision': {'decision': ANSWER}}) as invoke:
                inference.invoke({'observations': []}, lambda: False, {'engine': engine})
                self.assert_examples_match_schema(invoke.call_args.args[3])

    def test_legacy_http_keeps_the_original_unwrapped_protocol(self):
        with patch.object(inference, 'invoke_json', return_value={'decision': ANSWER}) as invoke:
            inference.invoke({}, lambda: False, {'engine': 'compatible'})
        self.assertEqual(invoke.call_args.args[3], SYSTEM)
        self.assertNotIn('output_schema', invoke.call_args.kwargs)


if __name__ == '__main__':
    unittest.main()
