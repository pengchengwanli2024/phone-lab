"""Independent supplement contracts using temporary state and synthetic I/O.

These checks do not prove that local Ozon collection or native rendering works.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import TOOLS
import test_market_research_supplement as base_fixture


class SupplementPublicContract(unittest.TestCase):
    def setUp(self):
        for guard in (
            patch('host_native.invoke', side_effect=AssertionError('Native I/O forbidden')),
            patch('agent_runtime.model.invoke', side_effect=AssertionError('Model I/O forbidden')),
        ):
            guard.start()
            self.addCleanup(guard.stop)
        self.flow = base_fixture.SupplementFlow()
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)
        self.app = self.flow.app
        self.original = deepcopy(self.flow.before)
        self.task = self.flow.task_id
        self.ref, self.document = self.flow.source()
        self.serial = 0
        self.assertEqual(self.original['status'], 'partial', 'fixture must have a real synthetic published study')

    def source(self, change=None):
        doc = deepcopy(self.document)
        if change:
            change(doc)
        self.serial += 1
        receipt = self.app.business.import_source(doc, 'independent-source-' + str(self.serial))
        return {key: receipt['source_id'] if key == 'id' else receipt[key]
                for key in ('id', 'version', 'sha256')}, doc

    @staticmethod
    def notes(doc):
        return next(row['value'] for row in doc['records'] if row['key'] == 'source_notes')

    def supplement(self, refs=None, **changes):
        args = dict(task_id=self.task, expected_revision=self.original['revision'],
                    source_refs=[self.ref] if refs is None else refs,
                    idempotency_key='independent-supplement')
        args.update(changes)
        return self.app.invoke('commerce_market_research_supplement', args, 'test')

    def state(self):
        with self.app.core.db() as db:
            return {table: db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
                    for table in ('tasks', 'agent_runs', 'market_research_jobs',
                                  'market_research_runs', 'copilot_turns', 'org_cases', 'org_artifacts')}

    def reject_unchanged(self, refs=None, **changes):
        before = self.state()
        with self.assertRaises(ValueError) as failure:
            self.supplement(refs, **changes)
        self.assertNotEqual(str(failure.exception), 'unknown_tool', 'missing registration is not a valid rejection')
        self.assertEqual(self.state(), before)

    def execute(self, generate=None):
        with patch('market_research.collector.capture', side_effect=AssertionError('Supplement cannot refetch')):
            with patch('market_research.model.generate', side_effect=generate or self.flow.generate):
                self.assertTrue(self.app.agent_runtime.run_once())

    def test_registered_bounded_public_action_uses_existing_task(self):
        self.assertIn('commerce_market_research_supplement', [item[0] for item in TOOLS])
        before = self.state()
        queued = self.supplement()
        after = self.state()
        self.assertEqual(queued['task_id'], self.task)
        self.assertNotEqual(queued['run_id'], self.original['run_id'])
        self.assertEqual(after['tasks'][0][0], before['tasks'][0][0])
        self.assertEqual(len(after['tasks']), len(before['tasks']))
        self.assertEqual(after['copilot_turns'], before['copilot_turns'])
        self.assertEqual(len(after['agent_runs']), len(before['agent_runs']) + 1)
        old_payload = json.loads(next(row[3] for row in before['agent_runs'] if row[0] == self.original['run_id']))
        new_payload = json.loads(next(row[3] for row in after['agent_runs'] if row[0] == queued['run_id']))
        self.assertEqual(new_payload['model_route'], old_payload['model_route'])

    def test_wrong_scope_platform_store_and_synthetic_are_rejected_without_queue(self):
        mutations = [
            lambda d: d['scope'].update(subject_ref='different-task'),
            lambda d: d['scope'].update(platform='tiktok'),
            lambda d: d['scope'].update(store_ref='another-store'),
            lambda d: d.update(synthetic=True),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                ref, _ = self.source(mutate)
                self.reject_unchanged([ref])

    def test_expired_facts_hash_mismatch_and_stale_task_revision_are_rejected(self):
        def expired(doc):
            now = datetime.now(timezone.utc)
            doc.update(observed_at=(now - timedelta(days=2)).isoformat(),
                       valid_until=(now - timedelta(days=1)).isoformat())
        ref, _ = self.source(expired)
        self.reject_unchanged([ref])
        self.reject_unchanged([dict(self.ref, sha256='0' * 64)])
        self.reject_unchanged(expected_revision=self.original['revision'] - 1)

    def test_superseded_source_version_is_not_accepted_as_current(self):
        changed = deepcopy(self.document)
        changed['label'] = 'A new immutable source version'
        self.app.business.import_source(changed, 'advance-source', source_id=self.ref['id'], expected_version=self.ref['version'])
        self.reject_unchanged()

    def test_source_ref_shape_and_batch_limits_are_enforced(self):
        for refs in ([], [self.ref] * 13, [self.ref, self.ref],
                     [dict(self.ref, version=True)], [dict(self.ref, unexpected='not allowed')]):
            with self.subTest(refs=refs):
                self.reject_unchanged(refs)

    def test_idempotent_replay_returns_original_run_and_conflicting_request_is_rejected(self):
        first = self.supplement()
        state = self.state()
        second = self.supplement()
        self.assertEqual(first['run_id'], second['run_id'])
        self.assertEqual(self.state(), state)
        self.reject_unchanged([dict(self.ref, sha256='1' * 64)])

    def test_an_active_supplement_prevents_another_analysis_request(self):
        self.supplement()
        revision = self.app.market_research.get(self.task)['revision']
        self.reject_unchanged(expected_revision=revision, idempotency_key='second-active-request')

    def test_remote_snapshot_cannot_claim_local_capture_or_verified_provenance(self):
        for key, value in (('acquisition', 'local_html'), ('local_live_capture', True),
                           ('review_status', 'independently_verified')):
            with self.subTest(key=key):
                def mutate(doc):
                    next(row for row in doc['records'] if row['key'] == key)['value'] = value
                ref, _ = self.source(mutate)
                self.reject_unchanged([ref])

    def test_source_notes_url_kind_and_crawl_metadata_are_validated(self):
        changes = [
            lambda d: self.notes(d).update(url='https://www.maxidom.ru/catalog/123/'),
            lambda d: self.notes(d).update(url='https://www.ozon.ru.evil.test/product/123456789/'),
            lambda d: self.notes(d).update(url='https://user:pass@www.ozon.ru/product/123456789/'),
            lambda d: self.notes(d).update(url=self.notes(d)['url'] + '?token=synthetic'),
            lambda d: self.notes(d).update(kind='arbitrary_html'),
            lambda d: self.notes(d).pop('crawl_age_reported'),
        ]
        for index, mutate in enumerate(changes):
            with self.subTest(index=index):
                ref, _ = self.source(mutate)
                self.reject_unchanged([ref])

    def test_matching_origin_and_notes_still_require_authorized_ozon_product_url(self):
        for url in ('https://www.ozon.ru.evil.test/product/synthetic-123456789/',
                    'https://www.ozon.ru:443/product/synthetic-123456789/',
                    'https://www.ozon.ru/cart/123456789/',
                    'https://seller.ozon.ru/media/not-a-product/'):
            with self.subTest(url=url):
                def mutate(doc):
                    doc['origin_ref'] = url
                    self.notes(doc)['url'] = url
                ref, _ = self.source(mutate)
                self.reject_unchanged([ref])

    def test_product_title_and_price_cannot_be_invented_or_invalid(self):
        changes = [lambda d: self.notes(d)['facts'].pop('product')]
        changes += [lambda d, v=v: self.notes(d)['facts'].update(snapshot_price_rub_other_banks=v)
                    for v in (0, -1, True, 'not-a-price')]
        for index, mutate in enumerate(changes):
            with self.subTest(index=index):
                ref, _ = self.source(mutate)
                self.reject_unchanged([ref])

    def test_review_or_seller_guidance_alone_cannot_create_a_product_candidate(self):
        rows = [('review_snapshot', self.document['origin_ref'] + 'reviews/'),
                ('official_seller_guidance', 'https://seller.ozon.ru/media/synthetic-guidance/')]
        for kind, url in rows:
            with self.subTest(kind=kind):
                def mutate(doc):
                    doc['origin_ref'] = url
                    self.notes(doc).update(kind=kind, url=url)
                ref, _ = self.source(mutate)
                self.reject_unchanged([ref])

    def test_missing_general_price_does_not_substitute_a_bank_price_or_cost(self):
        def mutate(doc):
            facts = self.notes(doc)['facts']
            facts.pop('snapshot_price_rub_other_banks')
            facts['snapshot_price_rub_ozon_bank'] = 1
        ref, _ = self.source(mutate)
        self.supplement([ref])
        seen = []
        def generate(phase, payload, cancelled, route):
            seen.extend(deepcopy(list(payload['products'].values())))
            return self.flow.generate(phase, payload, cancelled, route)
        self.execute(generate)
        self.assertEqual(len(seen), 1)
        self.assertIsNone(seen[0]['price'])
        self.assertIsNone(seen[0]['currency'])
        candidate = self.app.market_research.get(self.task)['candidates'][-1]
        view = self.app.invoke('commerce_workspace_get', {'case_id': candidate['case_id']}, 'test')
        self.assertEqual(view['calculation']['status'], 'HOLD')
        self.assertIsNone(view['calculation']['contribution'])

    def test_model_sees_only_current_batch_and_imported_evidence_stays_distinct(self):
        self.supplement()
        seen = []
        def generate(phase, payload, cancelled, route):
            seen.append(deepcopy(payload))
            return self.flow.generate(phase, payload, cancelled, route)
        self.execute(generate)
        after = self.app.market_research.get(self.task)
        self.assertEqual(len(seen), 1)
        self.assertNotIn('S1', seen[0]['source_ids'])
        self.assertTrue(all('www.ozon.ru/product/' in product['url'] for product in seen[0]['products'].values()))
        self.assertEqual(after['source_count'], self.original['source_count'])
        self.assertEqual(after['supplemental_source_count'], 1)
        self.assertEqual([s for s in after['sources'] if s['status'] != 'imported'], self.original['sources'])
        imported = [s for s in after['sources'] if s['status'] == 'imported']
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]['evidence_kind'], 'imported_public_notes')
        self.assertEqual(imported[0]['sha256'], self.ref['sha256'])

    def test_old_report_candidates_artifacts_and_workspace_run_survive_enrichment(self):
        old_state = self.state()
        old_candidate = self.original['candidates'][0]
        self.supplement()
        self.execute()
        after = self.app.market_research.get(self.task)
        now = self.state()
        self.assertEqual(after['report_history'][0]['report'], self.original['report'])
        self.assertEqual(after['candidate_count'], self.original['candidate_count'] + 1)
        for row in old_state['org_artifacts']:
            self.assertIn(row, now['org_artifacts'])
        for row in old_state['org_cases']:
            self.assertIn(row, now['org_cases'])
        self.assertEqual(after['candidates'][0]['artifact_id'], old_candidate['artifact_id'])
        self.assertEqual(after['candidates'][0]['research_run_id'], self.original['run_id'])
        view = self.app.invoke('commerce_workspace_get', dict(case_id=old_candidate['case_id'], research_task_id=self.task), 'test')
        self.assertEqual(view['research_context']['run_id'], self.original['run_id'])
        self.assertEqual(view['research_context']['artifact_id'], old_candidate['artifact_id'])
        self.assertTrue(view['research_context']['artifact']['intact'])
        new_candidate = after['candidates'][-1]
        new_view = self.app.invoke('commerce_workspace_get', dict(case_id=new_candidate['case_id'], research_task_id=self.task), 'test')
        self.assertEqual(new_view['research_context']['run_id'], after['run_id'])
        self.assertEqual(new_view['calculation']['status'], 'HOLD')
        self.assertIsNone(new_view['calculation']['contribution'])

    def test_changing_source_head_after_queue_does_not_change_frozen_analysis_input(self):
        self.supplement()
        changed = deepcopy(self.document)
        self.notes(changed)['facts']['product'] = 'UNREQUESTED_NEW_HEAD_PRODUCT'
        self.app.business.import_source(changed, 'change-after-queue', source_id=self.ref['id'], expected_version=self.ref['version'])
        seen = []
        def generate(phase, payload, cancelled, route):
            seen.append(deepcopy(payload))
            return self.flow.generate(phase, payload, cancelled, route)
        self.execute(generate)
        self.assertNotIn('UNREQUESTED_NEW_HEAD_PRODUCT', json.dumps(seen))
        self.assertIn(self.app.market_research.get(self.task)['status'], ('partial', 'failed'))

    def test_duplicate_product_from_previous_supplement_is_rejected(self):
        self.supplement()
        self.execute()
        ref, _ = self.source(lambda doc: doc.update(label='Repeated URL under another source ID'))
        after = self.app.market_research.get(self.task)
        self.reject_unchanged([ref], expected_revision=after['revision'], idempotency_key='duplicate-product')

    def test_unknown_outcome_cannot_be_replayed_by_another_supplement(self):
        self.supplement()
        def unknown(phase, payload, cancelled, route):
            raise ValueError('agent_provider_outcome_unknown')
        self.execute(unknown)
        after = self.app.market_research.get(self.task)
        self.assertEqual(after['status'], 'unknown')
        self.reject_unchanged(expected_revision=after['revision'], idempotency_key='cannot-bypass-unknown')

    def test_explicit_fresh_refs_can_recover_a_failed_stale_batch_on_the_same_task(self):
        first = self.supplement()
        changed = deepcopy(self.document)
        self.notes(changed)['facts']['product'] = 'Explicitly authorized corrected source'
        receipt = self.app.business.import_source(changed, 'correct-source-version',
                                                 source_id=self.ref['id'], expected_version=self.ref['version'])
        fresh = {'id': receipt['source_id'], 'version': receipt['version'], 'sha256': receipt['sha256']}
        self.execute()
        failed = self.app.market_research.get(self.task)
        self.assertEqual(failed['status'], 'failed')
        self.reject_unchanged([dict(fresh, sha256='0' * 64)], expected_revision=failed['revision'],
                              idempotency_key='invalid-replacement-must-not-write')
        preserved = self.state()
        recovery = self.supplement([fresh], expected_revision=failed['revision'],
                                   idempotency_key='explicit-fresh-source-recovery')
        self.assertEqual(recovery['task_id'], self.task)
        self.assertNotEqual(recovery['run_id'], first['run_id'])
        self.assertEqual(len(recovery['report_history']), len(failed['report_history']))
        superseded = [source for source in recovery['sources'] if source['status'] == 'superseded']
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0]['source_ref'], self.ref)
        history = recovery['supplement_history'][-1]
        self.assertEqual(history['run_id'], first['run_id'])
        self.assertEqual(history['status'], 'failed')
        self.assertEqual(history['error'], failed['error'])
        self.assertEqual(history['source_refs'], [self.ref])
        self.assertEqual(history['source_ids'], [superseded[0]['id']])
        self.execute()
        after = self.app.market_research.get(self.task)
        state = self.state()
        self.assertEqual(after['status'], 'partial')
        self.assertEqual(len(state['tasks']), len(preserved['tasks']))
        self.assertEqual(state['copilot_turns'], preserved['copilot_turns'])
        for old in preserved['org_artifacts']:
            self.assertIn(old, state['org_artifacts'])
        self.assertIn(next(row for row in preserved['agent_runs'] if row[0] == first['run_id']), state['agent_runs'])


if __name__ == '__main__':
    unittest.main()
