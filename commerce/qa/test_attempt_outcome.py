"""Attempt classification alone: synthetic event logs, no process or model."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_runtime.attempt_outcome import diagnostic, exit_error, furthest_stage, valid


def log(*events):
    return b'\n'.join(json.dumps(e).encode() if isinstance(e, dict) else e for e in events)


class AttemptOutcomeTests(unittest.TestCase):
    def test_furthest_stage_follows_the_log_and_ignores_noise(self):
        self.assertEqual(furthest_stage(b''), 'process_started')
        self.assertEqual(furthest_stage(log({'type': 'thread.started'})), 'session_started')
        self.assertEqual(furthest_stage(log({'type': 'thread.started'}, {'type': 'turn.started'})), 'model_started')
        self.assertEqual(furthest_stage(log({'type': 'turn.started'}, b'not json', b'[1,2]', {'type': 'other'})), 'model_started')
        # A completed item that is not the agent's message is not a received answer.
        self.assertEqual(furthest_stage(log({'type': 'turn.started'}, {'type': 'item.completed', 'item': {'type': 'reasoning'}})), 'model_started')
        self.assertEqual(furthest_stage(log({'type': 'item.completed', 'item': {'type': 'agent_message'}})), 'message_received')
        # Order in the log does not lower the stage reached.
        self.assertEqual(furthest_stage(log({'type': 'turn.completed'}, {'type': 'thread.started'})), 'turn_completed')

    def test_only_a_failure_after_the_model_started_is_unknown(self):
        self.assertEqual(exit_error('process_started'), 'agent_provider_failed_no_automatic_retry')
        self.assertEqual(exit_error('session_started'), 'agent_provider_failed_no_automatic_retry')
        self.assertEqual(exit_error('model_started'), 'agent_provider_outcome_unknown')
        self.assertEqual(exit_error('message_received'), 'agent_provider_outcome_unknown')

    def test_diagnostic_carries_no_content_and_never_offers_a_retry(self):
        raw = log({'type': 'turn.started', 'secret': 'SECRET_SENTINEL'}, {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'ANSWER_SENTINEL'}})
        value = diagnostic(raw, 1.23456, 'cli_exit', 1)
        self.assertEqual(value, {'provider': 'codex_cli', 'stage': 'message_received', 'reason': 'cli_exit',
                                 'elapsed_seconds': 1.235, 'returncode': 1, 'automatic_retry': False})
        self.assertNotIn('SENTINEL', json.dumps(value))
        self.assertTrue(valid(value))

    def test_only_well_formed_diagnostics_are_accepted(self):
        good = diagnostic(b'', 0.5, 'deadline', None)
        for bad in (None, 'text', {**good, 'provider': 'other'}, {**good, 'stage': 'nowhere'}, {**good, 'reason': 'guess'},
                    {**good, 'elapsed_seconds': -1}, {**good, 'elapsed_seconds': float('inf')}, {**good, 'elapsed_seconds': '1'},
                    {**good, 'returncode': '1'}):
            with self.subTest(bad=bad): self.assertFalse(valid(bad))
        self.assertTrue(valid(good))

    def test_oversized_logs_are_read_only_up_to_the_bound(self):
        raw = log({'type': 'thread.started'}) + b'\n' + b'x' * 1000000 + b'\n' + log({'type': 'turn.completed'})
        self.assertEqual(furthest_stage(raw), 'session_started')


if __name__ == '__main__':
    unittest.main()
