"""Isolated synthetic order-to-support continuity; no network or buyer messages."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from order_support import OrderSupport, definitions
from business_workflows.store import digest, encoded


class OrderSupportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        self.support = OrderSupport(self.app)
        self.scope = {'demo': True, 'platform': 'ozon', 'store_id': 'synthetic-store', 'market': 'RU'}
        body = {'filename': 'synthetic.csv', 'content': 'order_id,line_id,sku,order_date,quantity,unit_price,currency\nSYN-1,1,SYN-A,2026-11-01,2,12.50,CNY\nSYN-1,2,SYN-B,2026-11-01,1,3.20,CNY\n',
                'scope': {'platform': 'ozon', 'store_ref': 'synthetic-store', 'market': 'RU'}, 'synthetic': True,
                'field_mapping': {k: k for k in ['order_id', 'line_id', 'sku', 'order_date', 'quantity', 'unit_price', 'currency']},
                'idempotency_key': 'preview'}
        self.batch = self.app.order_imports.preview(**body)
        self.args = {**self.scope, 'order_id': 'SYN-1:1', 'import_batch_id': self.batch['id']}

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self):
        self.app.order_imports.confirm(self.batch['id'], self.batch['sha256'], True, 'confirm')
        return self.support.prepare(**self.args)

    def source(self, kind, key, scope=None, synthetic=True, market='RU', order='SYN-1'):
        doc = self.app.business.template(kind)['document']
        doc.update(scope=scope or {'platform': 'ozon', 'store_ref': 'synthetic-store', 'subject_ref': order}, synthetic=synthetic)
        if kind != 'conversation':
            doc['records'] = [{'key': 'order_ref', 'value': order}, {'key': 'market', 'value': market}, {'key': 'policy_ref', 'value': 'synthetic-policy'}]
        ref = self.app.business.import_source(doc, key)
        return {'id': ref['source_id'], 'version': ref['version'], 'sha256': ref['sha256']}, doc

    def payload(self):
        prepared = self.prepare()
        conv, _ = self.source('conversation', 'conversation')
        facts, _ = self.source('support', 'facts')
        return {'context': prepared['context'], 'source_refs': [conv, facts],
                'content': {'fields': {'conversation_ref': 'SYN-1', 'reply': '合成回复，待人工逐句核对。', 'policy_ref': 'synthetic-policy'},
                            'citations': {'policy_ref': {'source_id': facts['id'], 'key': 'policy_ref'}}},
                'idempotency_key': 'draft'}

    def test_import_requires_confirmed_exact_line_and_keeps_order_identity(self):
        with self.assertRaisesRegex(ValueError, 'order_support_source_unavailable'):
            self.support.prepare(**self.args)
        prepared = self.prepare()
        context = prepared['context']
        self.assertEqual(context['scope'], self.scope)
        self.assertEqual(context['order']['id'], 'SYN-1:1')
        self.assertEqual(context['order']['order_id'], 'SYN-1')
        self.assertEqual(context['order']['line_id'], '1')
        self.assertEqual(context['order']['import_batch_id'], self.batch['id'])
        self.assertEqual(context['order']['batch_sha256'], self.batch['sha256'])
        self.assertFalse(prepared['external_execution_allowed'])
        self.assertEqual(self.app.business.listing(True)['sources'], [])
        with self.assertRaisesRegex(ValueError, 'order_support_scope'):
            self.support.prepare(**{**self.args, 'market': 'US'})
        with self.assertRaisesRegex(ValueError, 'order_support_source_changed'):
            self.support.prepare(**self.args, expected_source_sha256='0' * 64)

    def test_local_draft_binds_source_snapshot_deduplicates_and_revises(self):
        payload = self.payload()
        first = self.support.draft(**payload)
        again = self.support.draft(**payload)
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(first['order_context']['status'], 'current')
        self.assertEqual(first['order_context']['context'], payload['context'])
        self.assertEqual(first['draft']['kind'], 'support')
        self.assertFalse(first['external_execution_allowed'])
        self.assertTrue(first['preflight']['ready_for_local_review'])
        changed = deepcopy(payload); changed['content']['fields']['reply'] = '新版合成回复'
        with self.assertRaisesRegex(ValueError, 'business_idempotency_conflict'):
            self.support.draft(**changed)
        changed.update(idempotency_key='revision', parent_id=first['id'], expected_parent_sha256=first['draft']['draft_sha256'])
        second = self.support.draft(**changed)
        self.assertEqual(second['parent_id'], first['id'])
        self.assertEqual(second['order_context']['context'], payload['context'])
        changed.update(idempotency_key='bad-revision', expected_parent_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'order_support_parent_changed'):
            self.support.draft(**changed)
        exported = self.support.export(first['id'])
        body = json.loads(exported['content'])
        self.assertEqual(body['draft']['order_context']['context'], payload['context'])
        self.assertEqual(exported['sha256'], digest(body))

    def test_scope_market_mode_versions_and_expiry_are_rejected_before_save(self):
        payload = self.payload()
        for mutation in ['scope', 'market', 'mode', 'order']:
            p = deepcopy(payload)
            args = {'scope': {'platform': 'ozon', 'store_ref': 'other-synthetic', 'subject_ref': 'SYN-1'}} if mutation == 'scope' else {'market': 'US'} if mutation == 'market' else {'synthetic': False} if mutation == 'mode' else {'order': 'OTHER'}
            ref, _ = self.source('support', mutation, **args)
            p.update(source_refs=[payload['source_refs'][0], ref], idempotency_key=mutation)
            with self.assertRaisesRegex(ValueError, 'order_support_(scope|market|order)'):
                self.support.draft(**p)
        ref = payload['source_refs'][1]
        old = self.app.business.source(ref['id'])
        updated = deepcopy(old['document']); updated['label'] = 'Revised synthetic facts'
        self.app.business.import_source(updated, 'update', ref['id'], ref['version'])
        with self.assertRaisesRegex(ValueError, 'order_support_source_changed'):
            self.support.draft(**payload)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM business_drafts').fetchone()[0], 0)

    def test_changed_order_is_stale_and_cannot_be_reviewed_or_rebound(self):
        payload = self.payload(); saved = self.support.draft(**payload)
        with self.app.core.db() as db:
            row = db.execute('SELECT scope_key,line_key,document FROM order_import_lines WHERE batch_id=? ORDER BY rowid LIMIT 1', (self.batch['id'],)).fetchone()
            value = json.loads(row[2]); value['quantity'] = 7
            db.execute('UPDATE order_import_lines SET document=? WHERE scope_key=? AND line_key=?', (encoded(value), row[0], row[1]))
        shown = self.support.decorate(self.app.business.get(saved['id']))
        self.assertEqual(shown['status'], 'stale')
        self.assertFalse(shown['preflight']['ready_for_local_review'])
        self.assertEqual(shown['order_context']['context'], payload['context'])
        with self.assertRaisesRegex(ValueError, 'order_support_source_changed'):
            self.support.review(draft_id=saved['id'], expected_sha256=saved['draft']['draft_sha256'], decision='reviewed', confirmed=True, idempotency_key='review')
        with self.assertRaisesRegex(ValueError, 'order_support_source_changed'):
            self.support.draft(**{**payload, 'idempotency_key': 'new'})
        self.assertEqual(self.support.draft(**payload)['id'], saved['id'])

    def test_expired_market_facts_and_tampered_order_context_cannot_save(self):
        from datetime import datetime, timezone, timedelta
        payload = self.payload()
        altered = deepcopy(payload)
        altered['context']['scope']['market'] = 'US'
        with self.assertRaisesRegex(ValueError, 'order_support_invalid_context'):
            self.support.draft(**altered)
        altered['context']['context_sha256'] = digest({k: v for k, v in altered['context'].items() if k != 'context_sha256'})
        with self.assertRaisesRegex(ValueError, 'order_support_scope_mismatch'):
            self.support.draft(**altered)
        current = self.app.business.source(payload['source_refs'][1]['id'])
        doc = deepcopy(current['document'])
        doc['observed_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        doc['valid_until'] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        ref = self.app.business.import_source(doc, 'expire', current['id'], current['version'])
        payload['source_refs'][1] = {'id': ref['source_id'], 'version': ref['version'], 'sha256': ref['sha256']}
        with self.assertRaisesRegex(ValueError, 'order_support_source_stale'):
            self.support.draft(**payload)

    def test_bound_revision_cannot_bypass_snapshot_guard_via_legacy_draft(self):
        payload = self.payload();saved = self.support.draft(**payload)
        with self.assertRaisesRegex(ValueError, 'order_support_bound_draft_required'):
            self.support.legacy_draft(kind='support', source_ids=[r['id'] for r in payload['source_refs']],
                                      content=payload['content'], idempotency_key='legacy', parent_id=saved['id'])
        payload['content']['fields']['conversation_ref'] = 'OTHER'
        with self.assertRaisesRegex(ValueError, 'order_support_order_mismatch'):
            self.support.draft(**{**payload, 'idempotency_key': 'wrong-conversation'})

    def test_parallel_idempotency_creates_one_link_and_original_draft(self):
        from concurrent.futures import ThreadPoolExecutor
        payload = self.payload()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: self.support.draft(**payload), range(2)))
        self.assertEqual(result[0]['id'], result[1]['id'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM business_drafts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM order_support_drafts').fetchone()[0], 1)

    def test_history_summary_rechecks_bound_order_without_changing_original_review(self):
        payload = self.payload();saved = self.support.draft(**payload)
        self.support.review(draft_id=saved['id'], expected_sha256=saved['draft']['draft_sha256'],
                            decision='reviewed', confirmed=True, idempotency_key='history-review')
        board = self.app.business.listing(True)
        self.assertEqual(board['drafts'][0]['status'], 'local_review_recorded')
        shown = self.support.decorate_listing(board)
        self.assertEqual(shown['drafts'][0]['order_context_status'], 'current')
        with self.app.core.db() as db:
            row = db.execute('SELECT scope_key,line_key,document FROM order_import_lines WHERE batch_id=? ORDER BY rowid LIMIT 1', (self.batch['id'],)).fetchone()
            record = json.loads(row[2]);record['quantity'] = 9
            db.execute('UPDATE order_import_lines SET document=? WHERE scope_key=? AND line_key=?', (encoded(record), row[0], row[1]))
        shown = self.support.decorate_listing(board)
        self.assertEqual(shown['drafts'][0]['status'], 'stale')
        self.assertEqual(shown['drafts'][0]['order_context_status'], 'stale')
        self.assertEqual(shown['drafts'][0]['order_context_reason'], 'order_support_source_changed')
        self.assertNotIn('order_context', shown['drafts'][0])
        self.assertEqual(board['drafts'][0]['status'], 'local_review_recorded')
        self.assertEqual(self.app.business.listing(True)['drafts'][0]['status'], 'local_review_recorded')
        self.assertEqual(len(self.app.business.get(saved['id'])['receipts']), 1)
        self.assertEqual(self.support.decorate_listing({'sources': [], 'drafts': []}), {'sources': [], 'drafts': []})

    def test_decorate_keeps_unlinked_existing_business_draft_unchanged(self):
        ref, _ = self.source('support', 'unlinked')
        draft = self.app.business.draft('support', [ref['id']], {'fields': {}, 'citations': {}}, 'unlinked-draft')
        self.assertEqual(self.support.decorate(draft), draft)

    def test_freshness_and_explicit_confirmed_scope_are_not_inferred(self):
        original = self.app.invoke
        row = {'id': 'synthetic-live', 'platform': 'ozon', 'store_id': 'synthetic-store', 'market': 'RU', 'source_sha256': 'a' * 64, 'stale': True}
        self.app.invoke = lambda name, args: {'orders': [row], 'scope_confirmed': True} if name == 'commerce_orders_list' else original(name, args)
        with self.assertRaisesRegex(ValueError, 'order_support_source_stale'):
            self.support.prepare(**{**self.scope, 'order_id': row['id']})
        row['stale'] = False
        self.app.invoke = lambda name, args: {'orders': [row], 'scope_confirmed': False}
        with self.assertRaisesRegex(ValueError, 'order_support_scope_unconfirmed'):
            self.support.prepare(**{**self.scope, 'order_id': row['id']})


if __name__ == '__main__':
    unittest.main()
