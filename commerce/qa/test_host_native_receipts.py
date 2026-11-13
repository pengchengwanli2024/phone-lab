"""Native process output must prove completion without executing extra tools."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_runtime import codex_provider


class NativeReceiptContract(unittest.TestCase):
    def receipt(self, events):
        self.assertTrue(hasattr(codex_provider, 'native_receipt'), 'Native completion receipt is missing')
        return codex_provider.native_receipt('\n'.join(json.dumps(e) for e in events), 'synthetic-model')

    def test_completed_native_thread_retains_actual_session_identity(self):
        result = self.receipt([{'type': 'thread.started', 'thread_id': 'actual-native-thread'},
                               {'type': 'turn.started'}, {'type': 'turn.completed'}])
        self.assertEqual(result['session_id'], 'actual-native-thread')
        self.assertEqual(result['model'], 'synthetic-model')
        self.assertEqual(result['tools_used'], [])

    def test_admission_without_completed_turn_is_unknown(self):
        with self.assertRaisesRegex(ValueError, 'outcome_unknown'):
            self.receipt([{'type': 'thread.started', 'thread_id': 'native-thread'}, {'type': 'turn.started'}])

    def test_completed_output_without_native_identity_is_not_a_receipt(self):
        with self.assertRaisesRegex(ValueError, 'invalid_response'):
            self.receipt([{'type': 'turn.completed'}])

    def test_unexpected_tool_execution_is_never_accepted_as_bounded_completion(self):
        with self.assertRaisesRegex(ValueError, 'unexpected_tool'):
            self.receipt([{'type': 'thread.started', 'thread_id': 'native-thread'},
                          {'type': 'item.completed', 'item': {'type': 'command_execution'}},
                          {'type': 'turn.completed'}])


if __name__ == '__main__':
    unittest.main()
