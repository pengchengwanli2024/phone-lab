"""A plain team question must produce a valid local-model JSON grammar."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
import jsonschema
from model_providers import inference


class TeamLocalContract(unittest.TestCase):
    def test_plain_team_question_has_valid_schema_and_no_unbacked_proposals(self):
        payload = {'question': '用一句话说明运输单证海运提单。', 'evidence_required': True,
                   'parameters': {'context': {'module': 'overview', 'demo': True}},
                   'assistant_team': {'profile': {'instructions': '只解释概念。'}},
                   'observations': [], 'tools': []}
        response = {'decision': {'decision': {'phase': 'answer', 'answer': '需要更多证据。',
                    'questions': ['需要核对哪个范围？'], 'proposals': [], 'evidence_refs': []}}}
        with patch.object(inference, 'invoke_json', return_value=response) as invoked:
            inference.invoke(payload, lambda: False, {'engine': 'llama_cpp', 'json_mode': True})
        schema = invoked.call_args.kwargs['output_schema']
        jsonschema.Draft202012Validator.check_schema(schema)
        def check_grammar(node):
            if isinstance(node, dict):
                if 'enum' in node:
                    self.assertTrue(node['enum'], 'Local grammar rejects an empty enum')
                for value in node.values(): check_grammar(value)
            elif isinstance(node, list):
                for value in node: check_grammar(value)
        check_grammar(schema)
        answer = next(x for x in schema['properties']['decision']['anyOf']
                      if x['properties']['phase']['enum'] == ['answer'])
        self.assertEqual(answer['properties']['proposals']['maxItems'], 0)
        jsonschema.validate(response['decision'], schema)
        for question in ('', '问' * 401):
            invalid = {'decision': {**response['decision']['decision'], 'questions': [question]}}
            with self.subTest(question_length=len(question)), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(invalid, schema)
