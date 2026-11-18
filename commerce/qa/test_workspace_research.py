"""Atomic current-workspace research writes in fresh synthetic databases."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import json
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from research import canonical, digest, template
from service import Commerce, TOOLS

SAVE = 'commerce_workspace_research_save'
CAPABILITIES = 'commerce_workspace_research_capabilities'


class WorkspaceResearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.cid = self.fixture.cid

    def tearDown(self):
        self.fixture.tearDown()

    def snapshot(self):
        return self.app.invoke('commerce_workspace_get', {'case_id': self.cid}, 'test')

    def request(self, key='research-editor-1', record=None):
        current = self.snapshot()
        return dict(case_id=self.cid, record=record or self.fixture.research()['record'],
                    expected_source_sha256=current['source_sha256'],
                    expected_artifact_id=(current['artifacts']['research'] or {}).get('id', ''),
                    idempotency_key=key)

    def call(self, request, app=None):
        return (app or self.app).invoke(SAVE, request, 'test')

    def counts(self):
        with self.app.core.db() as db:
            return (db.execute("SELECT count(*) FROM org_artifacts WHERE case_id=? AND kind='research'", (self.cid,)).fetchone()[0],
                    db.execute('SELECT count(*) FROM workspace_research_receipts WHERE case_id=?', (self.cid,)).fetchone()[0])

    def test_public_schema_capabilities_and_first_record_receipt(self):
        spec = next((row[2] for row in TOOLS if row[0] == SAVE), None)
        self.assertIsNotNone(spec, 'the atomic writer must be publicly registered')
        self.assertEqual(set(spec['required']), {'case_id','record','expected_source_sha256','expected_artifact_id','idempotency_key'})
        self.assertFalse(spec['additionalProperties'])
        capability = self.app.invoke(CAPABILITIES, {}, 'test')
        self.assertTrue(capability['atomic_source_and_head'])
        request = self.request()
        receipt = self.call(request)
        current = self.snapshot()
        self.assertEqual(receipt['schema'], 'workspace-research-save-v1')
        self.assertEqual(current['artifacts']['research']['id'], receipt['artifact_id'])
        self.assertEqual(current['artifacts']['research']['sha256'], receipt['artifact_sha256'])
        self.assertEqual(current['source_sha256'], receipt['source_sha256'])
        self.assertEqual(receipt['previous_source_sha256'], request['expected_source_sha256'])
        self.assertEqual(receipt['previous_artifact_id'], '')
        self.assertFalse(receipt['publication_ready'])
        self.assertFalse(receipt['external_execution_allowed'])
        self.assertFalse(receipt['external_operations_executed'])
        self.assertEqual(self.counts(), (1, 1))

    def test_partial_record_saves_as_hold_and_provenance_survives_immutable_history(self):
        record = template('ozon')['record'];record['market'] = 'RU'
        record['fields']['title'].update(original='Synthetic 12 kg', zh='合成 12 kg', translation={
            'original_sha256':digest('Synthetic 12 kg'), 'model_output':'合成 12 kg',
            'model_output_sha256':digest('合成 12 kg'), 'provider':'caller-reported-unverified'})
        first = self.call(self.request(record=record))
        self.assertEqual(first['validation_status'], 'HOLD');self.assertTrue(first['issues'])
        changed = deepcopy(record);changed['fields']['title']['zh'] = '另一个待核译文 12 kg'
        self.call(self.request('research-editor-2', changed))
        with self.app.core.db() as db:
            original = db.execute('SELECT payload,sha FROM org_artifacts WHERE id=?', (first['artifact_id'],)).fetchone()
        self.assertEqual(json.loads(original[0])['record'], record)
        self.assertEqual(digest(canonical(json.loads(original[0]))), original[1])
        self.assertEqual(self.counts(), (2, 2))

    def test_whole_source_change_and_wrong_head_reject_without_writes(self):
        request = self.request()
        self.app.organization.record(self.cid, 'supply', {'purchase_cost': 9}, 'concurrent-supply')
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.call(request)
        request = self.request();request['expected_artifact_id'] = 'a' * 32
        with self.assertRaisesRegex(ValueError, 'workspace_research_conflict'):
            self.call(request)
        self.assertEqual(self.counts(), (0, 0))

    def test_replay_returns_exact_original_receipt_after_source_and_head_advance(self):
        request = self.request()
        first = self.call(request)
        changed = self.fixture.research();changed['record']['raw_excerpt'] = 'Later caller record.'
        self.app.organization.record(self.cid, 'research', changed, 'later-original-api')
        self.assertNotEqual(self.snapshot()['source_sha256'], first['source_sha256'])
        self.assertEqual(self.call(request), first)
        restored = Commerce(self.fixture.tmp.name)
        self.assertEqual(self.call(request, restored), first)
        self.assertEqual(self.counts(), (2, 1))
        for field, value in [('record', self.fixture.research()['record']), ('expected_source_sha256', 'b' * 64), ('expected_artifact_id', 'b' * 32)]:
            conflict = deepcopy(request);conflict[field] = value
            if field == 'record':conflict[field]['raw_excerpt'] += ' Changed.'
            with self.assertRaisesRegex(ValueError, 'workspace_research_idempotency_conflict'):
                self.call(conflict)

    def test_receipt_failure_rolls_back_nested_org_record_and_all_receipts(self):
        original = self.app.organization.record
        def write_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('synthetic-after-artifact-insert')
        with patch.object(self.app.organization, 'record', side_effect=write_then_fail):
            with self.assertRaisesRegex(RuntimeError, 'synthetic-after-artifact'):
                self.call(self.request())
        self.assertEqual(self.counts(), (0, 0))

    def test_two_independent_core_connections_cannot_both_accept_same_base(self):
        second = Commerce(self.fixture.tmp.name)
        first = self.request('parallel-one');other = deepcopy(first);other['idempotency_key'] = 'parallel-two';other['record']['raw_excerpt'] += ' Alternative.'
        barrier = threading.Barrier(2)
        def save(app, request):
            barrier.wait()
            try:return ('saved', self.call(request, app))
            except ValueError as error:return ('rejected', str(error))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(save, self.app, first),pool.submit(save, second, other)]
            results=[future.result(timeout=20) for future in futures]
        self.assertEqual(sorted(value[0] for value in results), ['rejected','saved'])
        self.assertEqual(next(value[1] for value in results if value[0]=='rejected'), 'workspace_source_changed')
        self.assertEqual(self.counts(), (1, 1))

    def test_same_key_racing_identical_requests_share_one_durable_success(self):
        second = Commerce(self.fixture.tmp.name);request = self.request();barrier = threading.Barrier(2)
        def save(app):barrier.wait();return self.call(deepcopy(request), app)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(save, app) for app in (self.app, second)]
            results=[future.result(timeout=20) for future in futures]
        self.assertEqual(results[0], results[1]);self.assertEqual(self.counts(), (1, 1))

    def test_scope_schema_and_unknown_fields_do_not_create_artifacts(self):
        for field,value in [('platform','amazon'),('market','US')]:
            request = self.request();request['record'][field] = value
            with self.assertRaisesRegex(ValueError, 'workspace_research_scope_mismatch'):
                self.call(request)
        request = self.request();request['record']['unexpected'] = 'cannot be silently removed'
        with self.assertRaisesRegex(ValueError, 'invalid_research_version_or_fields'):
            self.call(request)
        request = self.request();request['extra'] = True
        with self.assertRaisesRegex(ValueError, 'invalid_arguments'):
            self.call(request)
        self.assertEqual(self.counts(), (0, 0))

    def test_generic_research_only_matches_the_existing_precise_candidate_exception(self):
        scope = {**self.fixture.case['scope'], 'origin':'research_candidate_not_inventory',
                 'research_task_id':'synthetic-research-task','inventory_type':'candidate','product_id':None}
        with self.app.core.db() as db:db.execute('UPDATE org_cases SET scope=? WHERE id=?', (canonical(scope), self.cid))
        record = template('research')['record'];record['market']='RU'
        self.call(self.request(record=record))
        for key,value in [('origin','inventory_scope_not_independently_verified'),('research_task_id',''),('inventory_type','fbs'),('product_id',123)]:
            wrong={**scope,key:value}
            with self.app.core.db() as db:db.execute('UPDATE org_cases SET scope=? WHERE id=?', (canonical(wrong), self.cid))
            with self.assertRaisesRegex(ValueError, 'workspace_research_scope_mismatch'):
                self.call(self.request(key='wrong-'+key,record=record))
        self.assertEqual(self.counts(), (1, 1))

    def test_tampered_history_cannot_be_reported_as_a_successful_replay(self):
        request = self.request();first = self.call(request)
        with self.app.core.db() as db:db.execute("UPDATE org_artifacts SET payload='{}' WHERE id=?", (first['artifact_id'],))
        with self.assertRaisesRegex(ValueError, 'workspace_artifact_changed'):
            self.call(request)

    def test_case_binding_change_is_part_of_the_guard_even_without_a_research_head(self):
        request = self.request();self.app.organization.set_currency(self.cid, 'CNY')
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.call(request)
        self.assertEqual(self.counts(), (0, 0))

    def test_replay_does_not_reveal_a_case_after_its_connection_is_revoked(self):
        request = self.request();self.call(request)
        self.app.live.configure({'ozon_client_id':'654321'})
        with self.assertRaisesRegex(ValueError, 'organization_case_not_found'):
            self.call(request)

    def test_malformed_guards_keys_and_oversized_record_leave_no_rows(self):
        for field,value in [('expected_source_sha256','A'*64),('expected_artifact_id','Z'*32),('idempotency_key',' ')]:
            request=self.request();request[field]=value
            with self.assertRaisesRegex(ValueError, 'invalid_'):
                self.call(request)
        request=self.request();request['record']['raw_excerpt']='x'*100001
        with self.assertRaisesRegex(ValueError, 'invalid_research_record'):
            self.call(request)
        self.assertEqual(self.counts(), (0, 0))

    def test_corrupted_durable_receipt_is_not_replayed_as_success(self):
        request=self.request();self.call(request)
        with self.app.core.db() as db:db.execute("UPDATE workspace_research_receipts SET receipt='{}' WHERE case_id=?",(self.cid,))
        with self.assertRaisesRegex(ValueError, 'workspace_artifact_changed'):
            self.call(request)


if __name__ == '__main__':unittest.main()
