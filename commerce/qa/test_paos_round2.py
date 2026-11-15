"""Second adoption batch: local import, existing plans and source-bound memory."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
import test_product_workspace as workspace_fixtures


class OrderImports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, csv=None):
        return {'filename': 'synthetic.csv', 'content': csv or 'Order,Line,SKU,Date,Qty,Price,Currency\nA,1,X,2026-11-01,2,12.50,CNY\nA,2,Y,2026-11-01,1,3.20,CNY\nB,1,Z,2026-11-02,1,4,USD\n',
                'scope': {'platform': 'ozon', 'store_ref': 'synthetic-store', 'market': 'RU'}, 'synthetic': True,
                'field_mapping': {'order_id': 'Order', 'line_id': 'Line', 'sku': 'SKU', 'order_date': 'Date',
                                  'quantity': 'Qty', 'unit_price': 'Price', 'currency': 'Currency'},
                'idempotency_key': 'preview'}

    def call(self, action, **args):
        return self.app.invoke('commerce_order_import_' + action, args)

    def confirm(self, batch, key='confirm'):
        return self.call('confirm', batch_id=batch['id'], expected_sha256=batch['sha256'], confirmed=True, idempotency_key=key)

    def test_preview_then_confirm_integrates_orders_and_currency_totals(self):
        batch = self.call('preview', **self.body())
        self.assertEqual(batch['status'], 'preview')
        self.assertEqual(self.app.invoke('commerce_orders_list', {'demo': True, 'import_batch_id': batch['id']})['total'], 0)
        saved = self.confirm(batch)
        self.assertEqual(saved['accepted_count'], 3)
        orders = self.app.invoke('commerce_orders_list', {'demo': True, 'import_batch_id': batch['id']})
        self.assertEqual(orders['total'], 3)
        self.assertEqual(orders['data_source'], 'operator_csv_import_unverified')
        totals = {r['currency']: r for r in saved['sales_by_currency']}
        self.assertEqual(totals['CNY']['gross_sales'], '28.20')
        self.assertEqual(totals['CNY']['order_count'], 1)
        self.assertEqual(totals['CNY']['line_count'], 2)
        self.assertEqual(self.confirm(batch), saved)
        self.assertEqual(self.call('preview', **self.body())['id'], batch['id'])
        self.assertEqual(Commerce(self.tmp.name).invoke('commerce_order_import_get', {'batch_id': batch['id']})['accepted_count'], 3)
        with self.assertRaisesRegex(ValueError, 'import_mode_mismatch'):
            self.app.invoke('commerce_orders_list', {'import_batch_id': batch['id']})

    def test_quarantine_dates_missing_currency_and_conflicting_line(self):
        csv = 'Order,Line,SKU,Date,Qty,Price,Currency\nA,1,X,2026-11-01,1,1,CNY\nA,1,X,2026-11-01,1,2,CNY\nB,1,Y,2026-02-30,1,1,CNY\nC,1,Z,2026-11-01,1,1,\nD,1,Z,2026-11-01,1,NaN,CNY\n'
        batch = self.call('preview', **self.body(csv))
        self.assertEqual(batch['quarantined_count'], 5)
        self.assertEqual(batch['valid_count'], 0)
        self.assertEqual(self.confirm(batch)['accepted_count'], 0)
        self.assertEqual(self.call('get', batch_id=batch['id'])['status'], 'rejected')

    def test_repeat_and_concurrent_confirmation_do_not_double_book(self):
        batch = self.call('preview', **self.body())
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.confirm(batch), range(4)))
        self.assertEqual(len({r['id'] for r in receipts}), 1)
        new = self.body();new['content'] += 'C,1,W,2026-11-03,1,2,CNY\n';new['idempotency_key'] = 'second'
        result = self.confirm(self.call('preview', **new), 'second-confirm')
        self.assertEqual(result['accepted_count'], 1)
        self.assertEqual(result['duplicate_count'], 3)

    def test_stale_confirmation_mapping_and_reused_request_reject(self):
        body = self.body();batch = self.call('preview', **body)
        with self.assertRaisesRegex(ValueError, 'import_source_changed'):
            self.confirm({**batch, 'sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.call('preview', **{**body, 'filename': 'other.csv'})
        body['field_mapping']['sku'] = 'Order'
        with self.assertRaises(ValueError):
            self.call('preview', **body)

    def test_existing_conflict_never_overwrites_and_store_scopes_do_not_collide(self):
        first = self.confirm(self.call('preview', **self.body()))
        changed = self.body();changed['content'] = changed['content'].replace('12.50', '99.00');changed['idempotency_key'] = 'changed'
        receipt = self.confirm(self.call('preview', **changed), 'changed-confirm')
        self.assertEqual(receipt['accepted_count'], 0)
        self.assertEqual(receipt['quarantined_count'], 1)
        self.assertEqual(receipt['quarantined'][0]['code'], 'EXISTING_LINE_CONFLICT')
        original = self.app.invoke('commerce_orders_list', {'import_batch_id': first['id'], 'demo': True})
        self.assertEqual(original['orders'][0]['unit_price'], '12.50')
        changed['scope']['store_ref'] = 'other-synthetic-store';changed['idempotency_key'] = 'other-store'
        self.assertEqual(self.confirm(self.call('preview', **changed), 'other-store-confirm')['accepted_count'], 3)


class WorkflowPlans(unittest.TestCase):
    def setUp(self):
        self.fixture = workspace_fixtures.ProductWorkspaceTests();self.fixture.setUp()
        self.app = self.fixture.app;self.case = self.fixture.case_id

    def tearDown(self):
        self.fixture.tearDown()

    def get(self):
        return self.app.invoke('commerce_workflow_plan_get', {'case_id': self.case})

    def save(self, plan, snapshot):
        return self.app.invoke('commerce_workflow_plan_save', {'case_id': self.case, 'payload': plan,
            'expected_revision': snapshot['revision'], 'expected_source_sha256': snapshot['source_sha256']})

    def test_graph_uses_same_plan_checkpoint_and_never_dispatches(self):
        self.fixture.save('plan', {'goal': 'existing', 'steps': [{'title': 'first'}, {'title': 'second'}]})
        snapshot = self.get();plan = snapshot['payload']
        self.assertEqual(len(plan['graph']['edges']), 1)
        plan['graph']['positions'][plan['steps'][0]['id']] = {'x': 60, 'y': 80}
        saved = self.save(plan, snapshot)
        workspace = self.fixture.snapshot()
        self.assertEqual(workspace['forms']['plan']['payload'], plan)
        self.assertEqual(workspace['forms']['plan']['revision'], saved['revision'])
        self.assertEqual(workspace['tasks'], [])
        with self.assertRaisesRegex(ValueError, 'form_draft_conflict'):
            self.save(plan, snapshot)

    def test_cycle_unknown_nodes_and_foreign_tasks_reject(self):
        snapshot = self.get()
        plan = {'goal': 'graph', 'steps': [{'id': 'a', 'title': 'A'}, {'id': 'b', 'title': 'B'}],
                'graph': {'edges': [{'from': 'a', 'to': 'b'}, {'from': 'b', 'to': 'a'}], 'positions': {}}}
        with self.assertRaisesRegex(ValueError, 'workflow_cycle'):
            self.save(plan, snapshot)
        plan['graph']['edges'] = [{'from': 'a', 'to': 'other'}]
        with self.assertRaises(ValueError):self.save(plan, snapshot)
        plan['graph']['edges'] = [];plan['steps'][0]['task_id'] = 'foreign'
        with self.assertRaisesRegex(ValueError, 'workspace_task_outside_scope'):
            self.save(plan, snapshot)

    def test_legacy_editor_retains_surviving_edges_and_task_status_is_live(self):
        snapshot = self.get()
        task = self.app.core.invoke('commerce_task_create', {'kind': 'analysis', 'input': {'organization_case': self.case}, 'idempotency_key': 'plan-task'})
        plan = {'goal': 'graph', 'steps': [{'id': 'a', 'title': 'A', 'task_id': task['id']}, {'id': 'b', 'title': 'B'}],
                'graph': {'edges': [{'from': 'a', 'to': 'b'}], 'positions': {'a': {'x': 80, 'y': 40}}}}
        saved = self.save(plan, snapshot)
        legacy = {'goal': 'text edit', 'steps': deepcopy(plan['steps'])}
        self.fixture.save('plan', legacy, saved['revision'], saved['source_sha256'])
        current = self.get()
        self.assertEqual(current['payload']['graph']['edges'], plan['graph']['edges'])
        self.assertEqual(current['payload']['graph']['positions']['a']['x'], 80)
        self.app.core.invoke('commerce_task_cancel', {'task_id': task['id']})
        self.assertEqual(self.get()['tasks'][0]['status'], 'cancelled')
        self.fixture.fixture.prepare_research()
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.save(current['payload'], current)


class LayeredMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.app = Commerce(self.tmp.name)
        self.doc = self.app.business.template('facts')['document']
        self.doc['records'] = [{'key': 'material', 'value': '合成材质：棉'}]
        self.source = self.app.business.import_source(self.doc, 'source')

    def tearDown(self):self.tmp.cleanup()

    def call(self, action, **args):
        return self.app.invoke('commerce_memory_' + action, args)

    def propose(self, key='fact'):
        return self.call('propose', content='合成记录注明材质为棉', bindings=[{
            'source_id': self.source['source_id'], 'version': self.source['version'], 'sha256': self.source['sha256'],
            'record_key': 'material', 'quote': '棉'}], idempotency_key=key)

    def confirm(self, fact):
        return self.call('confirm', memory_id=fact['id'], expected_revision=fact['revision'],
            expected_sha256=fact['sha256'], confirmed=True, idempotency_key='confirm-' + fact['id'])

    def test_l1_l2_l3_require_explicit_confirmation_and_keep_provenance(self):
        fact = self.propose()
        self.assertEqual(fact['layer'], 'L2')
        self.assertEqual(fact['status'], 'proposed')
        with self.assertRaisesRegex(ValueError, 'memory_fact_not_confirmed'):
            self.call('summarize', fact_ids=[fact['id']], title='合成摘要', idempotency_key='summary')
        confirmed = self.confirm(fact)
        summary = self.call('summarize', fact_ids=[fact['id']], title='合成摘要', idempotency_key='summary')
        self.assertEqual(summary['layer'], 'L3')
        self.assertIn(confirmed['content'], summary['content'])
        hits = self.call('search', query='棉', synthetic=True)['hits']
        self.assertEqual({h['layer'] for h in hits}, {'L1', 'L2', 'L3'})
        self.assertFalse(summary['external_execution_allowed'])
        self.assertEqual(self.call('search', query='棉', synthetic=False)['hits'], [])

    def test_source_revision_and_withdrawal_invalidate_derived_memory(self):
        fact = self.confirm(self.propose())
        summary = self.call('summarize', fact_ids=[fact['id']], title='合成摘要', idempotency_key='summary')
        self.call('withdraw', memory_id=fact['id'], expected_revision=fact['revision'], expected_sha256=fact['sha256'],
                  confirmed=True, idempotency_key='withdraw')
        self.assertEqual(self.call('get', memory_id=summary['id'])['effective_status'], 'stale')
        self.assertEqual({h['layer'] for h in self.call('search', query='棉', synthetic=True)['hits']}, {'L1'})
        fact2 = self.confirm(self.propose('fact2'))
        self.doc['records'][0]['value'] = '合成材质：木'
        self.app.business.import_source(self.doc, 'update', self.source['source_id'], 1)
        self.assertEqual(self.call('get', memory_id=fact2['id'])['effective_status'], 'stale')
        self.assertEqual(self.call('search', query='棉', synthetic=True)['hits'], [])

    def test_quote_fabrication_and_stale_revision_cannot_confirm(self):
        fact = self.propose()
        with self.assertRaisesRegex(ValueError, 'memory_revision_conflict'):
            self.confirm({**fact, 'revision': 20})
        bindings = fact['bindings'];bindings[0]['quote'] = '未出现的原文'
        with self.assertRaisesRegex(ValueError, 'memory_quote_not_found'):
            self.call('propose', content='fake', bindings=bindings, idempotency_key='fake')
        self.assertEqual(Commerce(self.tmp.name).invoke('commerce_memory_get', {'memory_id': fact['id']})['content'], fact['content'])

    def test_correction_confirmation_retracts_original_and_invalidates_summary(self):
        proposal = self.propose()
        fact = self.confirm(proposal)
        summary = self.call('summarize', fact_ids=[fact['id']], title='old synthetic summary', idempotency_key='summary')
        replacement = self.call('propose', content='纠正：合成材质记录是棉', bindings=fact['bindings'], supersedes=fact['id'], idempotency_key='correction')
        self.assertEqual(self.call('get', memory_id=fact['id'])['status'], 'confirmed')
        self.confirm(replacement)
        self.assertEqual(self.call('get', memory_id=fact['id'])['status'], 'withdrawn')
        self.assertEqual(self.call('get', memory_id=summary['id'])['effective_status'], 'stale')
        # A retry of the old confirmation cannot revive a withdrawn fact.
        self.assertEqual(self.confirm(proposal)['status'], 'withdrawn')

    def test_mixed_source_scope_and_changed_proposal_reject(self):
        fact = self.propose()
        other_doc = deepcopy(self.doc);other_doc['scope']['subject_ref'] = 'other-synthetic-subject'
        other = self.app.business.import_source(other_doc, 'other-source')
        bindings = fact['bindings'] + [{**fact['bindings'][0], 'source_id': other['source_id'], 'sha256': other['sha256']}]
        with self.assertRaisesRegex(ValueError, 'memory_scope_mismatch'):
            self.call('propose', content='mixed', bindings=bindings, idempotency_key='mixed')
        self.doc['records'][0]['value'] = '木'
        self.app.business.import_source(self.doc, 'updated', self.source['source_id'], 1)
        with self.assertRaisesRegex(ValueError, 'memory_fact_not_confirmable'):
            self.confirm(fact)


if __name__ == '__main__':unittest.main()
