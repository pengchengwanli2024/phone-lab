"""Versioned local quotations reuse organization artifacts; never buy or execute."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from service import TOOLS


class SupplyQuotes(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests(); self.fixture.setUp()
        self.app, self.cid = self.fixture.app, self.fixture.cid
        self.app.organization.set_currency(self.cid, 'CNY')
        self.index = 0

    def tearDown(self):
        self.app.agent_runtime.stop(); self.fixture.tearDown()

    def snapshot(self):
        return self.app.product_workspace.get(self.cid)

    def fields(self):
        return dict(supplier='Synthetic supplier', currency='CNY', purchase_cost=30,
                    lead_time_days=14, moq=20, source_ref='synthetic:quotation',
                    valid_until=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),
                    packaging=dict(length_cm=20, width_cm=10, height_cm=5, weight_kg=.4, units_per_pack=1))

    def save(self, fields=None, revision=0, key=None):
        self.index += 1
        return self.app.invoke('commerce_workspace_quote_save', dict(case_id=self.cid,
            quote_id='supplier-one', payload=fields if fields is not None else self.fields(),
            expected_revision=revision, expected_source_sha256=self.snapshot()['source_sha256'],
            idempotency_key=key or 'quote-'+str(self.index)), 'test')

    def select(self, row):
        return self.app.invoke('commerce_workspace_quote_select', dict(case_id=self.cid,
            quote_id=row['quote_id'], expected_quote_sha256=row['sha256'],
            expected_source_sha256=self.snapshot()['source_sha256'],
            idempotency_key='select-'+row['sha256']), 'test')

    def test_partial_quote_is_visible_as_hold_without_becoming_selected_supply(self):
        self.assertIn('commerce_workspace_quote_save', {t[0] for t in TOOLS})
        row=self.save({'supplier':'Synthetic supplier'})
        self.assertEqual(row['status'], 'HOLD')
        self.assertIn('moq', row['missing'])
        self.assertIsNone(self.snapshot()['artifacts']['supply'])
        self.assertEqual(self.app.core.invoke('commerce_task_list', {})['tasks'], [])

    def test_versions_are_preserved_and_stale_revision_cannot_overwrite(self):
        first=self.save(); fields=self.fields(); fields['purchase_cost']=29
        second=self.save(fields, 1)
        self.assertEqual(second['revision'], 2)
        with self.assertRaisesRegex(ValueError, 'quote_conflict'):
            self.save(fields, 1)
        result=self.app.invoke('commerce_workspace_quotes', {'case_id':self.cid}, 'test')
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(len(result['items'][0]['history']), 2)
        self.assertEqual(result['items'][0]['history'][1]['sha256'], first['sha256'])

    def test_selected_quote_revision_change_invalidates_saved_cost_and_gate(self):
        self.fixture.prepare_research()
        row=self.save(); self.select(row)
        before=self.snapshot()
        self.assertEqual(before['artifacts']['supply']['payload']['purchase_cost'], 30)
        self.app.product_workspace.save(self.cid, 'cost', {'input':{'currency':'CNY','purchase_cost':30}}, 0, before['source_sha256'])
        self.save(self.fields(), 1)
        after=self.snapshot()
        self.assertTrue(after['forms']['cost']['stale'])
        stage=next(s for s in after['stages'] if s['id']=='S3')
        self.assertNotEqual(stage['status'], 'PASS')
        self.assertTrue(any(g['id']=='quote' for g in stage['gaps']))

    def test_expiry_and_currency_mismatch_reject_selection(self):
        fields=self.fields(); fields['valid_until']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        expired=self.save(fields)
        with self.assertRaisesRegex(ValueError, 'quote_not_ready'):self.select(expired)
        fields=self.fields();fields['currency']='USD'; foreign=self.save(fields,1)
        with self.assertRaisesRegex(ValueError, 'quote_currency_mismatch'):self.select(foreign)

    def test_invalid_numbers_and_units_are_rejected_without_persistence(self):
        for field,value in [('moq',0),('purchase_cost',float('nan')),('packaging',{'weight_kg':-1}),('valid_until','2026-11-14')]:
            data=self.fields();data[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.save(data)
        self.assertEqual(self.app.invoke('commerce_workspace_quotes',{'case_id':self.cid},'test')['items'],[])

    def test_forged_selection_cannot_borrow_another_quotes_evidence(self):
        self.fixture.prepare_research();row=self.save();self.select(row)
        supply=self.snapshot()['artifacts']['supply']['payload']
        self.app.organization.record(self.cid,'supply',{**supply,'purchase_cost':999},'forged-cost')
        stage=next(s for s in self.snapshot()['stages'] if s['id']=='S3')
        self.assertNotEqual(stage['status'],'PASS')

    def test_expired_selected_quote_holds_calculation_and_preserves_original_receipt(self):
        row=self.save();first=self.select(row);second=self.select(row)
        self.assertEqual(first.get('id'),second.get('id'))
        with patch('supply_quotes.time.time',return_value=datetime.now(timezone.utc).timestamp()+4*86400):
            value=self.snapshot()
            self.assertEqual(value['calculation']['status'],'HOLD')
            self.assertTrue(value['calculation']['stale'])

    def test_model_sees_quote_conditions_without_supplier_notes_and_stale_approval_is_rejected(self):
        from agent_runtime.policy import project
        from test_agent_runtime import inspect,answer
        fields=self.fields();fields.update(supplier='PRIVATE_SUPPLIER_SENTINEL',source_ref='PRIVATE_QUOTE_NOTE_SENTINEL')
        self.save(fields)
        value=project('commerce_workspace_get',self.snapshot())
        self.assertTrue(value.get('quotes',{}).get('items'),'quote conditions must reach the scoped model read')
        self.assertNotIn('PRIVATE_',str(value))
        self.assertEqual(value['quotes']['items'][0]['fields']['moq'],20)
        context=dict(module='organization',demo=False,platform='ozon',market='RU',entity={'kind':'case','id':self.cid},calculator='unit_economics',input={'currency':'CNY','price':100})
        chat=self.app.copilot.open(context,'quote-chat')
        self.app.copilot.send(chat['id'],'核对报价',chat['context_sha256'],'quote-chat-turn')
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_workspace_get',{'case_id':self.cid}),answer(proposals=[{'operation':'unit_economics','reason':'核对当前报价摘要'}])]):
            self.app.agent_runtime.run_once()
        run=self.app.copilot.get(chat['id'])['latest_run']
        self.assertEqual(run['status'],'awaiting_review')
        self.save(fields,1)
        with self.assertRaisesRegex(ValueError,'workspace_evidence_changed'):
            self.app.copilot.apply(chat['id'],run['id'],'P1',run['result_sha256'],chat['context_sha256'])
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        self.app.copilot.send(chat['id'],'重新核对新版本',chat['context_sha256'],'quote-chat-next')
        with self.app.core.db() as db:
            import json
            payload=json.loads(db.execute('SELECT payload FROM agent_runs ORDER BY created DESC LIMIT 1').fetchone()[0])
        self.assertEqual(payload['conversation'],[])


if __name__=='__main__':unittest.main()
