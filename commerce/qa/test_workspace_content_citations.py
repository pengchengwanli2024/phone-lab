"""Exact physical Ozon description citations; editorial text remains unverified."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from research import canonical, digest


class WorkspaceContentCitations(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests();self.fixture.setUp()
        self.app = self.fixture.app;self.case = self.fixture.cid;self.counter = 0

    def tearDown(self):self.fixture.tearDown()

    def source(self, attributes=True, mutate=None):
        self.counter += 1
        doc = self.app.business.template('listing')['document']
        doc.update(synthetic=False, scope={'platform': 'ozon', 'store_ref': 'synthetic-store', 'subject_ref': self.case})
        values = {r['key']: r['value'] for r in doc['records']}
        if attributes:
            doc['records'] = [r for r in doc['records'] if r['key'] != 'description']
            doc['records'].append({'key': 'attributes', 'value': [{'id': '4191', 'complex_id': '0',
                'values': [{'dictionary_value_id': '0', 'value': values['description']}]}]})
        if mutate:mutate(doc)
        source = self.app.business.import_source(doc, 'synthetic-citation-source-' + str(self.counter))
        return source, values, doc

    def save(self, source, values):
        view = self.app.product_workspace.get(self.case)
        result = self.app.product_workspace.save(self.case, 'content', {'source_id': source['source_id'], 'fields': values},
            view['forms']['content']['revision'], view['source_sha256'])
        return {'case_id': self.case, 'expected_revision': result['revision'], 'expected_source_sha256': view['source_sha256']}

    def test_unique_physical_description_attribute_cites_exact_source_version(self):
        source, fields, doc = self.source();args = self.save(source, fields)
        result = self.app.product_workspace.submit_content(**args)
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual(result['draft']['content']['citations']['description'], {'source_id': source['source_id'], 'key': 'attributes.4191'})
        self.assertEqual(result['draft']['sources'], [{'id': source['source_id'], 'version': 1, 'sha256': source['sha256']}])
        self.assertFalse(result['preflight']['semantic_accuracy_verified']);self.assertFalse(result['external_execution_allowed'])
        self.assertEqual(self.app.product_workspace.submit_content(**args)['id'], result['id'])

    def test_editorial_rewrite_stays_uncited_and_is_never_imported_as_a_fact(self):
        source, fields, doc = self.source();fields['description'] += ' Editorial proposal, not a source fact.'
        args = self.save(source, fields);result = self.app.product_workspace.submit_content(**args)
        self.assertEqual(result['status'], 'needs_input');self.assertIn('description', result['preflight']['uncited_fields'])
        self.assertFalse(result['preflight']['ready_for_local_review'])
        self.assertEqual(self.app.business.source(source['source_id'])['document'], doc)

    def test_missing_duplicate_complex_dictionary_or_multiple_values_do_not_substitute_other_text(self):
        def attr(doc):return next(r['value'] for r in doc['records'] if r['key'] == 'attributes')
        cases = [lambda d: attr(d)[0].update(id='4192'),
                 lambda d: attr(d).append(deepcopy(attr(d)[0])),
                 lambda d: attr(d)[0].update(complex_id='1'),
                 lambda d: attr(d)[0]['values'][0].update(dictionary_value_id='4'),
                 lambda d: attr(d)[0]['values'].append(deepcopy(attr(d)[0]['values'][0]))]
        for change in cases:
            with self.subTest(change=cases.index(change)):
                source, fields, doc = self.source(mutate=change)
                doc_before = self.app.business.source(source['source_id'])
                result = self.app.product_workspace.submit_content(**self.save(source, fields))
                self.assertEqual(result['status'], 'needs_input');self.assertIn('description', result['preflight']['uncited_fields'])
                self.assertEqual(self.app.business.source(source['source_id']), doc_before)

    def test_top_level_description_and_existing_legacy_draft_keep_their_contract(self):
        source, fields, doc = self.source(attributes=False);args = self.save(source, fields)
        result = self.app.product_workspace.submit_content(**args)
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual(result['draft']['content']['citations']['description']['key'], 'description')
        self.assertEqual(self.app.product_workspace.submit_content(**args)['id'], result['id'])

    def test_fixed_physical_path_does_not_mutate_or_conflict_with_old_incomplete_draft(self):
        source, fields, doc = self.source();args = self.save(source, fields)
        old_key = 'workspace-content:' + digest(canonical([self.case, args['expected_source_sha256'], args['expected_revision']]))
        legacy = self.app.business.draft('listing', [source['source_id']], {'fields': fields,
            'citations': {key: {'source_id': source['source_id'], 'key': key} for key in fields}}, old_key)
        self.assertEqual(legacy['status'], 'needs_input')
        result = self.app.product_workspace.submit_content(**args)
        self.assertNotEqual(result['id'], legacy['id']);self.assertEqual(result['status'], 'ready_for_review')
        self.assertEqual(self.app.product_workspace.submit_content(**args)['id'], result['id'])
        self.assertEqual(self.app.business.get(legacy['id'])['draft'], legacy['draft'])
        self.assertEqual(self.app.business.get(legacy['id'])['status'], 'needs_input')

    def test_source_revision_change_rejects_old_checkpoint_and_stales_old_draft(self):
        source, fields, doc = self.source();args = self.save(source, fields)
        result = self.app.product_workspace.submit_content(**args)
        changed = deepcopy(doc);changed['label'] += ' revised'
        self.app.business.import_source(changed, 'synthetic-source-revision', source['source_id'], 1)
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):self.app.product_workspace.submit_content(**args)
        self.assertEqual(self.app.business.get(result['id'])['status'], 'stale')

    def test_other_case_citation_is_rejected_and_expired_physical_facts_remain_stale(self):
        source, fields, doc = self.source(mutate=lambda d: d['scope'].update(subject_ref='synthetic-other-case'))
        with self.assertRaisesRegex(ValueError, 'workspace_source_outside_scope'):self.save(source, fields)
        def expired(doc):
            at = datetime.now(timezone.utc);doc.update(observed_at=(at - timedelta(hours=1)).isoformat(), valid_until=(at - timedelta(seconds=5)).isoformat())
        source, fields, doc = self.source(mutate=expired)
        result = self.app.product_workspace.submit_content(**self.save(source, fields))
        self.assertEqual(result['status'], 'stale');self.assertFalse(result['preflight']['ready_for_local_review'])


if __name__ == '__main__':unittest.main()
