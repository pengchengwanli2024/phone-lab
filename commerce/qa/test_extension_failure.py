"""Extension failure classification alone: no runtime, database or clock."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extension_runtime.failure import budget_expired, charge_inflight, classify


def flight(**extra):
    return {'step_id': 'root.read', 'started_at': 100.0, 'accounted_at': 100.0, **extra}


class FailureTests(unittest.TestCase):
    def test_a_coded_failure_keeps_its_own_code_and_cause_is_not_recorded(self):
        status, code, cause = classify(error_code='extension_scope_mismatch', error_type='ValueError',
                                       flight=flight(), expired=False)
        self.assertEqual((status, code, cause), ('failed', 'extension_scope_mismatch', None))

    def test_only_a_deliberately_coded_value_error_keeps_its_code(self):
        self.assertEqual(classify(error_code='extension_scope_mismatch', error_type='RuntimeError',
                                  flight=flight(), expired=False)[1], 'extension_execution_failed')
        self.assertEqual(classify(error_code='agent_provider_outcome_unknown', error_type='OSError',
                                  flight=flight(), expired=False)[:2], ('unknown', 'extension_execution_failed'))

    def test_an_unexpected_failure_gets_the_generic_code_plus_type_and_step(self):
        status, code, cause = classify(error_code='SECRET /Users/x token=abc', error_type='KeyError',
                                       flight=flight(), expired=False)
        self.assertEqual((status, code), ('failed', 'extension_execution_failed'))
        self.assertEqual(cause, {'type': 'KeyError', 'step': 'root.read'})
        self.assertNotIn('SECRET', str(cause))

    def test_a_strange_type_or_step_is_reduced_instead_of_stored_verbatim(self):
        _, code, cause = classify(error_code='boom', error_type='A' * 200, flight={'step_id': 'bad step!'}, expired=False)
        self.assertEqual(code, 'extension_execution_failed')
        self.assertEqual(cause, {'type': 'Error', 'step': None})

    def test_an_external_write_is_always_unknown_but_a_model_step_only_once_out_of_budget(self):
        self.assertEqual(classify(error_code='boom', error_type='OSError', flight=flight(effect='external_write'), expired=False)[:2],
                         ('unknown', 'extension_execution_failed'))
        # Unchanged from the runtime's behaviour before this was extracted: a model step
        # inside its budget is 'failed' here. See the note in the module docstring.
        self.assertEqual(classify(error_code='boom', error_type='OSError', flight=flight(kind='model'), expired=False)[:2],
                         ('failed', 'extension_execution_failed'))
        self.assertEqual(classify(error_code='boom', error_type='OSError', flight=flight(kind='model'), expired=True)[:2],
                         ('unknown', 'extension_budget_exhausted'))
        self.assertEqual(classify(error_code='boom', error_type='OSError', flight=flight(), expired=False, outcome_unknown=True)[0], 'unknown')
        self.assertEqual(classify(error_code='agent_provider_outcome_unknown', error_type='ValueError', flight=flight(), expired=False)[0], 'unknown')

    def test_a_read_step_that_only_read_fails_is_safe_to_ask_again(self):
        self.assertEqual(classify(error_code='boom', error_type='OSError', flight=flight(effect='read'), expired=False)[0], 'failed')

    def test_running_out_of_budget_dominates_and_a_model_step_is_then_unknown(self):
        self.assertEqual(classify(error_code='boom', error_type='OSError', flight=flight(kind='model'), expired=True)[:2],
                         ('unknown', 'extension_budget_exhausted'))
        self.assertEqual(classify(error_code='boom', error_type='OSError', flight=flight(effect='read'), expired=True)[:2],
                         ('failed', 'extension_budget_exhausted'))
        self.assertIsNone(classify(error_code='boom', error_type='OSError', flight=flight(), expired=True)[2])

    def test_budget_counts_the_current_step_and_charging_stamps_it(self):
        self.assertFalse(budget_expired(0, 60, flight(), now=159.0))
        self.assertTrue(budget_expired(0, 60, flight(), now=160.0))
        self.assertEqual(budget_expired(0, 60, {}, now=999.0), False)
        live = flight()
        self.assertEqual(charge_inflight(live, 130.5), 30.5)
        self.assertEqual(live['accounted_at'], 130.5)
        self.assertEqual(charge_inflight(live, 140.0), 9.5)
        self.assertEqual(charge_inflight({}, 140.0), 0)
        # A step that started but was never accounted still charges from its start.
        self.assertEqual(charge_inflight({'started_at': 10.0}, 15.0), 5.0)


if __name__ == '__main__':
    unittest.main()
