"""Product workspace uses existing identities, artifacts and guarded local writes."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from service import Commerce
from research import canonical


class ProductWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.case_id = self.fixture.cid

    def tearDown(self):
        self.fixture.tearDown()

    def call(self, suffix, **args):
        return self.app.invoke('commerce_workspace_' + suffix, args, 'test')

    def snapshot(self):
        return self.call('get', case_id=self.case_id)

    def save(self, form, payload, revision=0, source=None):
        return self.call('save', case_id=self.case_id, form=form, payload=payload,
                         expected_revision=revision,
                         expected_source_sha256=source or self.snapshot()['source_sha256'])

    def test_snapshot_preserves_case_and_missing_facts_without_writes(self):
        listed = self.call('list')
        self.assertEqual(listed['items'][0]['id'], self.case_id)
        value = self.snapshot()
        self.assertEqual(value['case']['id'], self.case_id)
        self.assertIsNone(value['artifacts']['research'])
        self.assertEqual(value['calculation']['status'], 'HOLD')
        self.assertIsNone(value['calculation']['contribution'])
        self.assertEqual(value['tasks'], [])
        self.assertEqual(value['read_scope'], 'selected_case_only')
        self.assertFalse(value['external_execution_allowed'])

    def test_explicit_goal_and_form_recover_without_creating_tasks(self):
        saved = self.save('plan', {'goal': '核对同一商品的成本与来源', 'steps': []})
        self.assertEqual(saved['revision'], 1)
        restored = Commerce(self.fixture.tmp.name).invoke('commerce_workspace_get', {'case_id': self.case_id})
        self.assertEqual(restored['forms']['plan']['payload']['goal'], '核对同一商品的成本与来源')
        self.assertEqual(restored['tasks'], [])
        with self.assertRaisesRegex(ValueError, 'form_draft_conflict'):
            self.save('plan', {'goal': '迟到的修改', 'steps': []})
        self.assertEqual(self.snapshot()['forms']['plan']['revision'], 1)

    def test_changed_source_rejects_old_save_and_preserves_checkpoint(self):
        old = self.snapshot()['source_sha256']
        self.save('cost', {'input': {'currency': 'CNY', 'purchase_cost': 12}}, source=old)
        self.fixture.prepare_research()
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.save('cost', {'input': {'purchase_cost': 99}}, 1, old)
        current = self.snapshot()
        self.assertTrue(current['forms']['cost']['stale'])
        self.assertEqual(current['forms']['cost']['payload']['input']['purchase_cost'], 12)

    def test_cost_commit_is_version_bound_and_uses_existing_artifact(self):
        values = self.fixture.prepare_cost()
        saved = self.save('cost', {'input': values})
        source = self.snapshot()['source_sha256']
        result = self.call('calculate', case_id=self.case_id,
                           expected_source_sha256=source, expected_revision=saved['revision'])
        self.assertEqual(result['status'], 'CALCULATED')
        self.assertEqual(result['contribution'], 38)
        self.assertEqual(result['artifact_handoff']['status'], 'saved')
        self.assertEqual(self.app.organization.artifact(self.case_id, 'economics')['payload'], values)
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.call('calculate', case_id=self.case_id, expected_source_sha256=source,
                      expected_revision=saved['revision'])

    def test_case_from_inactive_connection_is_not_read_or_written(self):
        old = self.snapshot()['source_sha256']
        self.app.live.configure({'ozon_client_id': '654321'})
        self.assertEqual(self.call('list')['items'], [])
        with self.assertRaisesRegex(ValueError, 'case_not_found'):
            self.snapshot()
        with self.assertRaisesRegex(ValueError, 'case_not_found'):
            self.save('plan', {'goal': '禁止跨店铺', 'steps': []}, source=old)

    def test_only_tasks_bound_to_this_case_are_visible(self):
        own = self.app.core.invoke('commerce_task_create', {'idempotency_key': 'own', 'kind': 'analysis', 'input': {'organization_case': self.case_id, 'title': '原任务'}})
        self.app.core.invoke('commerce_task_create', {'idempotency_key': 'other', 'kind': 'analysis', 'input': {'organization_case': 'another-case', 'title': '不能串入'}})
        self.assertEqual([t['id'] for t in self.snapshot()['tasks']], [own['id']])

    def test_cost_fields_do_not_default_missing_values_to_zero(self):
        self.save('cost', {'input': {'currency': 'CNY', 'price': 0.01}})
        result = self.snapshot()['calculation']
        self.assertEqual(result['status'], 'HOLD')
        self.assertIn('purchase_cost', result['missing'])
        for bad in [{'input': {'commission_rate': 2}}, {'input': {'price': float('nan')}}, {'input': {'currency': '人民币'}}]:
            with self.assertRaises(ValueError):
                self.save('cost', bad, 1)

    def test_model_case_read_is_exact_and_privacy_minimal(self):
        from agent_runtime.policy import check_call, project, tool_menu
        context = {'module': 'organization', 'entity': {'kind': 'case', 'id': self.case_id}}
        params = {'context': context}
        self.assertIn('commerce_workspace_get', [t['tool'] for t in tool_menu('workspace', params)])
        with self.assertRaisesRegex(ValueError, 'outside_scope'):
            check_call('workspace', params, {'tool': 'commerce_workspace_get', 'arguments': {'case_id': 'other'}}, set())
        value = self.snapshot()
        value['case']['scope']['source_ref'] = 'PRIVATE_PATH_SENTINEL'
        value['forms']['plan']['payload'] = {'goal': 'PRIVATE_FORM_SENTINEL'}
        projection = project('commerce_workspace_get', value)
        self.assertTrue(projection['entity_details_available'])
        self.assertNotIn('PRIVATE_PATH_SENTINEL', canonical(projection))
        self.assertNotIn('PRIVATE_FORM_SENTINEL', canonical(projection))

    def test_currency_choice_is_explicit_and_source_guarded(self):
        source = self.snapshot()['source_sha256']
        changed = self.call('currency', case_id=self.case_id, currency='CNY', expected_source_sha256=source)
        self.assertEqual(changed['currency'], 'CNY')
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.call('currency', case_id=self.case_id, currency='RUB', expected_source_sha256=source)
        self.assertEqual(self.app.organization.case(self.case_id)['currency'], 'CNY')

    def test_generic_form_tools_cannot_bypass_product_scope(self):
        self.save('plan', {'goal': '仅限当前连接', 'steps': []})
        scope = {'module': 'product_workspace', 'form': 'plan', 'case_id': self.case_id}
        with self.assertRaisesRegex(ValueError, 'workspace_scope_requires_guard'):
            self.app.invoke('commerce_form_draft_get', {'scope': scope}, 'test')
        with self.assertRaisesRegex(ValueError, 'workspace_scope_requires_guard'):
            self.app.invoke('commerce_form_draft_save', {'scope': scope, 'payload': {}, 'expected_revision': 1}, 'test')

    def test_content_submission_uses_saved_revision_and_frozen_sources(self):
        document = self.app.business.template('listing')['document']
        document.update(synthetic=False, scope={'platform': 'ozon', 'store_ref': 'synthetic-store', 'subject_ref': self.case_id})
        source = self.app.business.import_source(document, 'content-source')
        fields = {r['key']: r['value'] for r in document['records']}
        saved = self.save('content', {'source_id': source['source_id'], 'fields': fields})
        sha = self.snapshot()['source_sha256']
        args = {'case_id': self.case_id, 'expected_revision': saved['revision'], 'expected_source_sha256': sha}
        created = self.call('submit_content', **args)
        self.assertEqual(self.call('submit_content', **args)['id'], created['id'])
        self.assertEqual(created['draft']['scope']['subject_ref'], self.case_id)
        self.assertFalse(created['external_execution_allowed'])
        changed = deepcopy(document);changed['label'] += ' 新来源版本'
        self.app.business.import_source(changed, 'content-source-new', source['source_id'], 1)
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.call('submit_content', **args)
        with self.assertRaisesRegex(ValueError, 'form_draft_conflict'):
            self.call('submit_content', **{**args, 'expected_revision': 99, 'expected_source_sha256': self.snapshot()['source_sha256']})

    def test_view_checkpoint_resumes_without_new_tasks(self):
        self.save('view', {'tab': 'cost'})
        self.assertEqual(self.snapshot()['forms']['view']['payload']['tab'], 'cost')
        with self.assertRaises(ValueError):
            self.save('view', {'tab': 'invented'}, 1)


if __name__ == '__main__':
    unittest.main()
