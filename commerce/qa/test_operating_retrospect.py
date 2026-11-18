"""Recurring failures become read-only improvement candidates; isolated state, no network."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class OperatingRetrospectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.app = Commerce(self.tmp.name);self.now = time.time()
    def tearDown(self):
        self.app.autonomy.stop();self.tmp.cleanup()
    def run_failed(self, ident, error, age_days=1, status='failed'):
        with self.app.core.db() as db:
            db.execute('INSERT INTO agent_runs (id,idem,request,payload,status,created,updated,result) VALUES (?,?,?,?,?,?,?,?)',
                       (ident, ident, '{}', '{}', status, 1, self.now - age_days * 86400, json.dumps({'error': error})))
    def http(self, error, count):
        with self.app.core.db() as db:
            for i in range(count):
                db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at) VALUES (?,?,?,?,?,?)',
                           ('j', '/v1/x', 'a' * 64, None, error, time.strftime('%Y-%m-%dT%H:%M:%S+00:00', time.gmtime(self.now - 3600 - i))))
    def get(self, **kw):
        return self.app.invoke('commerce_operating_retrospect_get', kw, 'test')
    def counts(self):
        with self.app.core.db() as db:
            return [db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in ('tasks', 'agent_runs', 'engineering_runs')]

    def test_no_failures_means_no_candidates_and_nothing_is_created(self):
        before = self.counts();value = self.get()
        self.assertEqual((value['candidates'], value['single_incidents'], value['uncoded_failures']), ([], 0, {}))
        self.assertEqual((value['automatically_applied'], value['new_tasks_created'], value['model_calls']), (False, 0, 0))
        self.assertEqual(self.counts(), before)

    def test_repeated_code_is_a_candidate_and_a_single_failure_is_only_an_incident(self):
        for i in range(3): self.run_failed('u' + str(i), 'agent_provider_outcome_unknown', status='unknown')
        self.run_failed('once', 'agent_model_invalid_response');self.http('ozon_rate_limited', 5)
        before = self.counts();value = self.get()
        by = {c['id']: c for c in value['candidates']}
        self.assertEqual(set(by), {'store_read:ozon_rate_limited', 'model_request:agent_provider_outcome_unknown'})
        self.assertEqual([c['id'] for c in value['candidates']][0], 'store_read:ozon_rate_limited')
        self.assertEqual((by['store_read:ozon_rate_limited']['count'], by['store_read:ozon_rate_limited']['fix_first']), (5, 'connector'))
        self.assertEqual((by['model_request:agent_provider_outcome_unknown']['count'], by['model_request:agent_provider_outcome_unknown']['fix_first']), (3, 'recovery'))
        self.assertEqual(value['single_incidents'], 1);self.assertEqual(self.counts(), before)
        self.assertTrue(all(c['status'] == 'candidate' for c in value['candidates']))

    def test_window_excludes_old_failures(self):
        for i in range(2): self.run_failed('old' + str(i), 'agent_tool_result_too_large', age_days=10)
        self.assertEqual(self.get()['candidates'], [])
        wide = self.get(window_days=30)['candidates']
        self.assertEqual((wide[0]['error'], wide[0]['fix_first']), ('agent_tool_result_too_large', 'contract'))
        with self.assertRaisesRegex(ValueError, 'invalid_window_days'): self.get(window_days=365)

    def test_free_text_errors_are_counted_as_uncoded_and_never_echoed(self):
        secret = 'Bearer SYNTHETIC-CANARY at /Users/someone/private'
        for i in range(3): self.run_failed('t' + str(i), secret)
        value = self.get()
        self.assertEqual((value['candidates'], value['uncoded_failures']), ([], {'model_request': 3}))
        self.assertNotIn('CANARY', json.dumps(value));self.assertNotIn('/Users/', json.dumps(value))

    def test_loop_failures_and_unknowns_are_included(self):
        with self.app.core.db() as db:
            for i, (status, error) in enumerate([('failed', 'agent_case_unavailable'), ('failed', 'agent_case_unavailable'), ('unknown', None), ('unknown', None)]):
                db.execute('INSERT INTO operating_loop_work VALUES (?,?,?,?,?,?,?)', ('w' + str(i), 'g', 's', 'b' + str(i), status, self.now - 60, json.dumps({'error': error})))
        by = {c['id']: c for c in self.get()['candidates']}
        self.assertEqual(by['operating_loop:agent_case_unavailable']['fix_first'], 'inputs')
        self.assertEqual(by['operating_loop:operating_loop_unknown']['count'], 2)

    def test_candidates_state_whether_the_engineering_executor_can_take_them(self):
        self.http('ozon_rate_limited', 3);self.http('ozon_network_error', 2)
        for i in range(2): self.run_failed('u' + str(i), 'agent_provider_outcome_unknown', status='unknown')
        value = self.get();by = {c['id']: c for c in value['candidates']}
        # Only the exact failure a registered recipe covers is marked; the rest of the domain is not.
        self.assertEqual(by['store_read:ozon_rate_limited']['engineering_feature'], 'ozon-read-backoff')
        self.assertIsNone(by['store_read:ozon_network_error']['engineering_feature'])
        self.assertEqual(by['model_request:agent_provider_outcome_unknown']['engineering_feature'], 'model-attempt-outcome')
        self.assertEqual(value['engineering']['covered_candidates'], ['model_request:agent_provider_outcome_unknown', 'store_read:ozon_rate_limited'])
        self.assertEqual(value['engineering']['uncovered_domains'], ['store_read'])
        self.assertFalse(value['engineering']['automatic_work_orders'])

    def test_every_mapped_recipe_is_registered_and_loads_within_the_executor_limits(self):
        import operating_retrospect
        from engineering.features import FeatureMap
        catalog = FeatureMap(Path(__file__).resolve().parents[2])
        for feature in set(operating_retrospect.FEATURES.values()):
            with self.subTest(feature=feature): self.assertEqual(catalog.get(feature)['id'], feature)

    def ext_failed(self, ident, cause=None, error='extension_execution_failed'):
        doc = {'id': ident, 'error': error, **({'error_cause': cause} if cause else {})}
        with self.app.core.db() as db:
            db.execute('INSERT INTO extension_runs (id,idem,extension_id,status,document,created) VALUES (?,?,?,?,?,?)',
                       (ident, ident, 'ext_x', 'failed', json.dumps(doc), self.now - 60))

    def test_a_generic_extension_failure_is_split_by_its_recorded_cause(self):
        for i in range(2): self.ext_failed('k' + str(i), {'type': 'KeyError', 'step': 'root.read'})
        self.ext_failed('t0', {'type': 'TypeError', 'step': 'root.read'})
        for i in range(2): self.ext_failed('o' + str(i))  # recorded before causes existed
        by = {c['id']: c for c in self.get()['candidates']}
        self.assertEqual(by['extension:extension_execution_failed:KeyError']['count'], 2)
        self.assertEqual(by['extension:extension_execution_failed']['count'], 2)
        self.assertNotIn('extension:extension_execution_failed:TypeError', by)
        self.assertEqual(self.get()['single_incidents'], 1)

    def test_a_cause_that_is_not_a_plain_type_name_is_ignored(self):
        for i in range(2): self.ext_failed('b' + str(i), {'type': 'Key Error: SECRET', 'step': 'x'})
        value = self.get()
        self.assertEqual([c['id'] for c in value['candidates']], ['extension:extension_execution_failed'])
        self.assertNotIn('SECRET', json.dumps(value))

    def test_specific_codes_win_over_broad_words(self):
        from operating_retrospect import classify
        expected = {'agent_case_unavailable': 'inputs', 'host_unavailable_use_workbench': 'connector', 'ozon_rate_limited': 'connector',
                    'agent_chain_budget_exhausted': 'limits', 'extension_schema_type': 'contract', 'agent_provider_outcome_unknown': 'recovery',
                    'market_research_no_product_evidence': 'inputs', 'something_new_failed': 'check'}
        self.assertEqual({code: classify(code)[0] for code in expected}, expected)

    def test_registered_read_only(self):
        import mcp_server, service
        self.assertIn('commerce_operating_retrospect_get', {n for n, _, _ in service.TOOLS})
        self.assertIn('commerce_operating_retrospect_get', mcp_server.CONTROL_READ_ONLY)


if __name__ == '__main__':
    unittest.main()
