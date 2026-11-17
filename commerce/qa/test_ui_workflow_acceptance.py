"""Cross-module acceptance on private synthetic state; no external execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from service import Commerce
import test_organization as fixtures
import test_paos_round2 as import_fixtures
import test_paos_mcp as mcp_fixtures


class ProductDeliveryAcceptance(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests()
        self.fixture.setUp()
        self.app, self.cid = self.fixture.app, self.fixture.cid

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.app.listing_releases.stop()
        self.fixture.tearDown()

    def call(self, name, **args):
        return self.app.invoke('commerce_' + name, args, 'test')

    def prepare_product_delivery(self):
        values = self.fixture.prepare_cost()
        source = self.call('workspace_get', case_id=self.cid)
        saved = self.call('workspace_save', case_id=self.cid, form='cost', payload={'input': values},
                          expected_revision=0, expected_source_sha256=source['source_sha256'])
        result = self.call('workspace_calculate', case_id=self.cid, expected_revision=saved['revision'],
                           expected_source_sha256=source['source_sha256'])
        self.assertEqual(result['contribution'], 38)
        self.assertEqual(self.call('workspace_get', case_id=self.cid)['forms']['cost']['payload']['input']['commission_rate'], .1)
        document = self.app.business.template('listing')['document']
        document.update(synthetic=False, scope={'platform': 'ozon', 'store_ref': self.app.live.config()['connection_id'], 'subject_ref': self.cid})
        for row in document['records']:
            if row['key'] == 'price':
                row['value'] = '100.00'
            elif row['key'] == 'currency':
                row['value'] = 'CNY'
        imported = self.call('business_import', document=document, idempotency_key='acceptance-facts')
        fields = {row['key']: row['value'] for row in document['records']}
        source = self.call('workspace_get', case_id=self.cid)
        saved = self.call('workspace_save', case_id=self.cid, form='content', payload={'source_id': imported['source_id'], 'fields': fields},
                          expected_revision=0, expected_source_sha256=source['source_sha256'])
        draft = self.call('workspace_submit_content', case_id=self.cid, expected_revision=saved['revision'],
                          expected_source_sha256=source['source_sha256'])
        project, asset = self.fixture.creative()  # Copies synthetic fixture bytes; no media generation.
        delivered = self.app.organization.deliver(self.cid, project['id'], [asset['id']], 'acceptance-delivery')
        self.assertEqual(delivered['file_count'], 1)
        package = self.call('workspace_delivery_get', case_id=self.cid)
        checks = {key: {'status': 'confirmed', 'source_ref': 'synthetic:acceptance-' + key, 'note': 'Synthetic local review'}
                  for key in ('facts', 'translation', 'media_rights', 'platform_rules')}
        # New sources invalidate the full product checkpoint. Recovery must be explicit
        # and must retain the original rate/input rather than silently accepting it.
        self.assertFalse(next(row for row in package['automatic_checks'] if row['id'] == 'cost')['passed'])
        with self.assertRaisesRegex(ValueError, 'workspace_delivery_incomplete'):
            self.call('workspace_delivery_record', case_id=self.cid, expected_package_sha256=package['package_sha256'],
                      expected_source_sha256=package['source_sha256'], expected_review_sha256='', checks=checks,
                      decision='reviewed', confirmed=True, idempotency_key='acceptance-stale-review')
        current = self.call('workspace_get', case_id=self.cid)
        cost = current['forms']['cost']
        self.assertTrue(cost['stale'])
        self.assertEqual(cost['payload']['input']['commission_rate'], .1)
        self.assertEqual(self.call('business_get', draft_id=draft['id'])['receipts'], [])
        saved = self.call('workspace_save', case_id=self.cid, form='cost', payload=cost['payload'],
                          expected_revision=cost['revision'], expected_source_sha256=current['source_sha256'])
        result = self.call('workspace_calculate', case_id=self.cid, expected_revision=saved['revision'],
                           expected_source_sha256=current['source_sha256'])
        self.assertEqual(result['contribution'], 38)
        package = self.call('workspace_delivery_get', case_id=self.cid)
        self.assertTrue(all(row['passed'] for row in package['automatic_checks']))
        self.call('workspace_delivery_record', case_id=self.cid, expected_package_sha256=package['package_sha256'],
                  expected_source_sha256=package['source_sha256'], expected_review_sha256='', checks=checks,
                  decision='reviewed', confirmed=True, idempotency_key='acceptance-review')
        self.assertEqual(self.call('workspace_delivery_get', case_id=self.cid)['status'], 'local_review_recorded')
        return draft, asset

    def test_saved_cost_content_bytes_review_and_local_application_keep_one_case(self):
        before = self.call('task_list')['tasks']
        draft, asset = self.prepare_product_delivery()
        target = dict(case_id=self.cid, platform='ozon', store_ref='ozon-live', market='RU')
        preview = self.call('listing_get', **target)
        self.assertEqual(preview['payload']['fields']['price'], '100.00')
        self.assertEqual(preview['delivery_status'], 'local_review_recorded')
        saved = self.call('listing_save', **target, payload=preview['payload'], expected_revision=preview['revision'],
                          expected_source_sha256=preview['source_sha256'])
        created = self.call('listing_release_create', **target, expected_preview_sha256=saved['preview_sha256'],
                            note='Synthetic local acceptance application', confirmed=True, idempotency_key='acceptance-release')
        reopened = Commerce(self.fixture.tmp.name)
        try:
            request = reopened.invoke('commerce_listing_release_get', {**target, 'request_id': created['id']})['request']
            self.assertEqual(request['frozen']['target'], target)
            self.assertEqual(request['frozen']['delivery_status'], 'local_review_recorded')
            self.assertFalse(request['platform_submission_verified'])
            self.assertFalse(request['external_execution_allowed'])
            self.assertIn('professional_gate', request['missing'])
            exported = reopened.invoke('commerce_listing_release_export', {'request_id': created['id'], 'expected_event_sha256': request['event_sha256']})
            self.assertEqual(json.loads(exported['content'])['request']['sha256'], request['sha256'])
        finally:
            reopened.agent_runtime.stop()
            reopened.listing_releases.stop()
        manifest = self.app.organization.artifact(self.cid, 'images')['payload']
        path = self.app.organization.state / manifest['files'][0]['relative_path']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset['sha256'])
        self.assertTrue(self.call('business_get', draft_id=draft['id'])['receipts'])
        self.assertEqual(self.call('task_list')['tasks'], before)

    def test_delivery_bytes_drift_invalidates_review_and_old_listing_preview(self):
        self.prepare_product_delivery()
        target = dict(case_id=self.cid, platform='ozon', store_ref='ozon-live', market='RU')
        initial = self.call('listing_get', **target)
        saved = self.call('listing_save', **target, payload=initial['payload'], expected_revision=initial['revision'],
                          expected_source_sha256=initial['source_sha256'])
        manifest = self.app.organization.artifact(self.cid, 'images')['payload']
        path = self.app.organization.state / manifest['files'][0]['relative_path']
        path.write_bytes(b'synthetic changed delivery')
        current = self.call('workspace_delivery_get', case_id=self.cid)
        self.assertNotEqual(current['status'], 'local_review_recorded')
        with self.assertRaisesRegex(ValueError, 'listing_preview_changed'):
            self.call('listing_export', **target, expected_preview_sha256=saved['preview_sha256'])
        self.assertEqual(self.call('task_list')['tasks'], [])


class OrderSupportAcceptance(unittest.TestCase):
    def setUp(self):
        self.fixture = import_fixtures.OrderImports()
        self.fixture.setUp()
        self.app = self.fixture.app
        csv = 'Order,Line,SKU,Date,Qty,Price,Currency\nSYN-1,1,SYN-A,2026-11-01,2,12.50,CNY\n'
        self.batch = self.fixture.call('preview', **self.fixture.body(csv))
        self.fixture.confirm(self.batch)
        self.row = self.app.invoke('commerce_orders_list', {'demo': True, 'import_batch_id': self.batch['id']})['orders'][0]
        self.target = dict(demo=True, platform='ozon', store_id='synthetic-store', market='RU',
                           order_id=self.row['id'], import_batch_id=self.batch['id'], expected_source_sha256=self.row['source_sha256'])
        scope = {'platform': 'ozon', 'store_ref': 'synthetic-store', 'subject_ref': 'SYN-1'}
        self.refs = []
        for kind in ('conversation', 'support'):
            document = self.app.business.template(kind)['document']
            document['scope'] = scope
            if kind == 'support':
                document['records'] += [{'key': 'order_ref', 'value': 'SYN-1'}, {'key': 'market', 'value': 'RU'}]
                self.facts_document = deepcopy(document)
            imported = self.app.invoke('commerce_business_import', {'document': document, 'idempotency_key': 'support-' + kind})
            self.refs.append({'id': imported['source_id'], 'version': imported['version'], 'sha256': imported['sha256']})
        self.content = {'fields': {'conversation_ref': 'SYN-1', 'reply': '合成回复：正在核对这笔订单的规格。', 'policy_ref': 'synthetic-policy'},
                        'citations': {'policy_ref': {'source_id': self.refs[1]['id'], 'key': 'policy_ref'}}}

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.fixture.tearDown()

    def prepare(self, **changes):
        return self.app.invoke('commerce_order_support_prepare', {**self.target, **changes})

    def draft(self, context, key='support-draft', **changes):
        return self.app.invoke('commerce_order_support_draft', {'context': context, 'source_refs': self.refs,
                               'content': self.content, 'idempotency_key': key, **changes})

    def test_csv_order_to_local_reply_review_and_reopen_keep_exact_identity(self):
        tasks = self.app.invoke('commerce_task_list', {})['tasks']
        prepared = self.prepare()
        context = prepared['context']
        self.assertEqual(context['order']['id'], 'SYN-1:1')
        self.assertEqual(context['order']['order_id'], 'SYN-1')
        self.assertEqual(context['order']['import_batch_id'], self.batch['id'])
        self.assertEqual({row['id'] for row in prepared['sources']}, {row['id'] for row in self.refs})
        draft = self.draft(context)
        self.assertEqual(self.draft(context)['id'], draft['id'])
        self.assertEqual(draft['order_context']['status'], 'current')
        self.assertTrue(draft['preflight']['ready_for_local_review'])
        receipt = self.app.invoke('commerce_business_review', {'draft_id': draft['id'], 'expected_sha256': draft['draft']['draft_sha256'],
                                  'decision': 'reviewed', 'confirmed': True, 'idempotency_key': 'reply-local-review'})
        self.assertEqual(receipt['approval_scope'], 'local_draft_only')
        self.assertFalse(receipt['external_execution_allowed'])
        reopened = Commerce(self.fixture.tmp.name)
        try:
            restored = reopened.invoke('commerce_business_get', {'draft_id': draft['id']})
            self.assertEqual(restored['order_context']['context'], context)
            self.assertEqual(restored['status'], 'local_review_recorded')
            self.assertEqual(restored['draft']['content']['fields']['reply'], self.content['fields']['reply'])
            self.assertFalse(restored['external_execution_allowed'])
        finally:
            reopened.agent_runtime.stop()
        self.assertEqual(self.app.invoke('commerce_task_list', {})['tasks'], tasks)
        self.assertEqual(self.app.invoke('commerce_orders_list', {'demo': True, 'import_batch_id': self.batch['id']})['total'], 1)

    def test_changed_source_or_order_scope_cannot_replace_the_existing_reply(self):
        context = self.prepare()['context']
        draft = self.draft(context)
        with self.assertRaisesRegex(ValueError, 'order_support_scope_mismatch'):
            self.prepare(store_id='other-store')
        with self.assertRaisesRegex(ValueError, 'order_support_source_changed'):
            self.prepare(expected_source_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'order_support_parent_changed'):
            self.draft(context, key='late-edit', parent_id=draft['id'], expected_parent_sha256='0' * 64)
        changed = deepcopy(self.facts_document)
        next(row for row in changed['records'] if row['key'] == 'policy_ref')['value'] = 'synthetic-revised-policy'
        self.app.invoke('commerce_business_import', {'document': changed, 'source_id': self.refs[1]['id'],
                        'expected_version': self.refs[1]['version'], 'idempotency_key': 'revised-policy'})
        with self.assertRaisesRegex(ValueError, 'order_support_source_changed'):
            self.draft(context, key='late-new-reply')
        old = self.app.invoke('commerce_business_get', {'draft_id': draft['id']})
        self.assertEqual(old['draft']['content']['fields']['reply'], self.content['fields']['reply'])
        self.assertEqual(old['status'], 'stale')
        self.assertEqual(old['receipts'], [])

    def test_changed_order_marks_original_reply_and_history_stale_without_resending(self):
        draft = self.draft(self.prepare()['context'])
        self.app.invoke('commerce_business_review', {'draft_id': draft['id'], 'expected_sha256': draft['draft']['draft_sha256'],
                        'decision': 'reviewed', 'confirmed': True, 'idempotency_key': 'review-before-order-drift'})
        # Simulate a changed source snapshot in this private fixture, leaving the
        # immutable reply and its business sources untouched.
        with self.app.core.db() as db:
            row = db.execute('SELECT scope_key,line_key,document FROM order_import_lines WHERE batch_id=?', (self.batch['id'],)).fetchone()
            record = json.loads(row[2])
            record['quantity'] = 7
            db.execute('UPDATE order_import_lines SET document=? WHERE scope_key=? AND line_key=?',
                       (json.dumps(record), row[0], row[1]))
        shown = self.app.invoke('commerce_business_get', {'draft_id': draft['id']})
        self.assertEqual(shown['status'], 'stale')
        self.assertEqual(shown['order_context']['status'], 'stale')
        board = self.app.invoke('commerce_business_list', {'synthetic': True})
        summary = next(row for row in board['drafts'] if row['id'] == draft['id'])
        self.assertEqual(summary['status'], 'stale')
        self.assertEqual(summary['order_context_status'], 'stale')
        self.assertNotIn('context', summary)
        self.assertEqual(shown['draft']['content']['fields']['reply'], self.content['fields']['reply'])
        with self.assertRaisesRegex(ValueError, 'order_support_source_changed'):
            self.app.invoke('commerce_business_review', {'draft_id': draft['id'], 'expected_sha256': draft['draft']['draft_sha256'],
                            'decision': 'reviewed', 'confirmed': True, 'idempotency_key': 'must-not-re-review'})
        self.assertEqual(len(self.app.invoke('commerce_business_get', {'draft_id': draft['id']})['receipts']), 1)
        self.assertEqual(self.app.invoke('commerce_task_list', {})['tasks'], [])


class ScopeAndSupportMCPAnnotations(unittest.TestCase):
    setUpClass = classmethod(mcp_fixtures.AdoptionMCP.setUpClass.__func__)
    tearDownClass = classmethod(mcp_fixtures.AdoptionMCP.tearDownClass.__func__)
    call = classmethod(mcp_fixtures.AdoptionMCP.call.__func__)
    mcp = mcp_fixtures.AdoptionMCP.mcp
    rpc = mcp_fixtures.AdoptionMCP.rpc

    def test_three_clients_distinguish_readonly_catalogue_and_local_writes(self):
        for client in ('codex', 'hermes', 'harness'):
            with self.subTest(client=client), self.mcp(client) as process:
                tools = {tool['name']: tool for tool in self.rpc(process, 'tools/list', {})['result']['tools']}
                for name in ('commerce_store_scope_list', 'commerce_execution_history', 'commerce_order_support_prepare'):
                    self.assertTrue(tools[name]['annotations']['readOnlyHint'], name)
                    self.assertFalse(tools[name]['annotations']['openWorldHint'], name)
                for name in ('commerce_store_scope_link', 'commerce_order_support_draft'):
                    self.assertFalse(tools[name]['annotations']['readOnlyHint'], name)
                    self.assertFalse(tools[name]['annotations']['openWorldHint'], name)
                    self.assertFalse(tools[name]['annotations']['destructiveHint'], name)
                self.assertIn('confirmed', tools['commerce_store_scope_link']['inputSchema']['required'])
        self.assertEqual(self.call('commerce_task_list', {})['tasks'], [])


if __name__ == '__main__':
    unittest.main()
