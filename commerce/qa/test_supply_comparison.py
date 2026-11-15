"""Quotation comparison is a scoped, exact, read-only procurement draft."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from copilot import reads
from copilot.memory_scope import history_refs
from test_agent_runtime import inspect, answer


class SupplyComparison(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OrganizationTests();self.fixture.setUp()
        self.app,self.cid=self.fixture.app,self.fixture.cid
        self.app.organization.set_currency(self.cid,'CNY')
        self.index=0

    def tearDown(self):
        self.app.agent_runtime.stop();self.fixture.tearDown()

    def save(self, ident, **changes):
        fields=dict(supplier='Synthetic '+ident,currency='CNY',purchase_cost=1,
                    lead_time_days=14,moq=1,source_ref='synthetic:'+ident,
                    valid_until=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),
                    packaging=dict(length_cm=20,width_cm=10,height_cm=5,weight_kg=.4,units_per_pack=1))
        revision=changes.pop('revision',0);fields.update(changes);self.index+=1
        return self.app.invoke('commerce_workspace_quote_save',dict(case_id=self.cid,quote_id=ident,
            payload=fields,expected_revision=revision,
            expected_source_sha256=self.app.product_workspace.get(self.cid)['source_sha256'],
            idempotency_key='comparison-quote-'+str(self.index)),'test')

    def compare(self, quantity=13):
        return self.app.invoke('commerce_workspace_quote_compare',dict(case_id=self.cid,quantity=quantity),'test')

    def test_moq_and_whole_packages_use_exact_money_without_selecting_a_supplier(self):
        self.save('whole-pack',purchase_cost=1.005,moq=15,
                  packaging=dict(length_cm=20,width_cm=10,height_cm=5,weight_kg=.4,units_per_pack=6))
        before=self.app.product_workspace.get(self.cid)
        with self.app.core.db() as db:artifacts=list(db.execute('SELECT * FROM org_artifacts ORDER BY id'))
        value=self.compare();row=value['items'][0]
        self.assertEqual((row['order_units'],row['extra_units'],row['packages']),(18,5,3))
        self.assertEqual(row['unit_price'],'1.005');self.assertEqual(row['goods_subtotal'],'18.09')
        self.assertEqual(row['source_ref'],'synthetic:whole-pack')
        self.assertFalse(value['external_execution_allowed']);self.assertFalse(value['independently_verified'])
        self.assertEqual(before,self.app.product_workspace.get(self.cid))
        with self.app.core.db() as db:self.assertEqual(artifacts,list(db.execute('SELECT * FROM org_artifacts ORDER BY id')))
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_lower_unit_price_does_not_imply_lower_cash_required(self):
        self.save('low-unit',purchase_cost=1,moq=100)
        self.save('small-order',purchase_cost=1.1)
        rows={r['quote_id']:r for r in self.compare()['items']}
        self.assertEqual(rows['low-unit']['goods_subtotal'],'100.00')
        self.assertEqual(rows['small-order']['goods_subtotal'],'14.30')
        self.assertEqual(rows['low-unit']['extra_units'],87)
        self.assertNotIn('recommended_quote_id',self.compare())

    def test_incomplete_expired_and_other_currency_quotes_have_no_invented_total(self):
        self.save('expired',valid_until='2020-01-01T00:00:00+00:00')
        self.save('usd',currency='USD')
        self.save('missing',packaging={})
        rows={r['quote_id']:r for r in self.compare()['items']}
        for ident,status in [('expired','EXPIRED'),('usd','CURRENCY_MISMATCH'),('missing','HOLD')]:
            self.assertEqual(rows[ident]['status'],status)
            self.assertIsNone(rows[ident]['goods_subtotal']);self.assertIsNone(rows[ident]['order_units'])
        self.assertEqual(self.compare()['comparable_count'],0)

    def test_invalid_quantities_fail_in_the_backend(self):
        for quantity in (True,False,0,-1,1.5,'13',None,10**9+1):
            with self.subTest(quantity=quantity),self.assertRaisesRegex(ValueError,'invalid_quantity'):
                self.compare(quantity)

    def test_large_goods_amounts_remain_exact_decimal_strings(self):
        self.save('large',purchase_cost=10**12)
        row=self.compare(10**9)['items'][0]
        self.assertEqual(row['goods_subtotal'],'1000000000000000000000.00')
        self.assertEqual(row['order_units'],10**9)

    def test_expiration_removes_the_old_total_and_invalidates_assistant_evidence(self):
        self.save('expiring',valid_until=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat())
        original=self.compare()
        context=dict(module='organization',demo=False,entity={'kind':'case','id':self.cid})
        later=(datetime.now(timezone.utc)+timedelta(minutes=2)).timestamp()
        with patch('supply_quotes.time.time',return_value=later):
            expired=self.compare()
            self.assertEqual(expired['items'][0]['status'],'EXPIRED')
            self.assertIsNone(expired['items'][0]['goods_subtotal'])
            with self.assertRaisesRegex(ValueError,'workspace_evidence_changed'):
                reads.revalidate_workspace(self.app,context,original)

    def test_versions_and_expiry_invalidate_the_original_comparison_evidence(self):
        self.save('versioned')
        first=self.compare();self.assertEqual(first['comparison_sha256'],self.compare()['comparison_sha256'])
        context=dict(module='organization',demo=False,entity={'kind':'case','id':self.cid})
        reads.revalidate_workspace(self.app,context,first)
        self.save('versioned',purchase_cost=2,revision=1)
        newer=self.compare()
        self.assertNotEqual(first['comparison_sha256'],newer['comparison_sha256'])
        self.assertEqual(newer['items'][0]['revision'],2)
        with self.assertRaisesRegex(ValueError,'workspace_evidence_changed'):
            reads.revalidate_workspace(self.app,context,first)
        with self.assertRaisesRegex(ValueError,'workspace_source_changed'):
            self.app.product_workspace.supply.select(self.cid,'versioned',first['items'][0]['sha256'],
                first['source_sha256'],'must-not-select-a-stale-comparison')

    def test_assistant_comparison_is_limited_to_the_selected_case_and_declared_quantity(self):
        context=dict(module='organization',demo=False,entity={'kind':'case','id':self.cid})
        self.assertIn('commerce_workspace_quote_compare',{r['tool'] for r in reads.menu(context)})
        args=dict(case_id=self.cid,quantity=13)
        self.assertEqual(reads.check(context,'commerce_workspace_quote_compare',args,set()),('commerce_workspace_quote_compare',args))
        for wrong in ({**args,'case_id':'another-case'},{**args,'quantity':False},{**args,'new_permission':True}):
            with self.assertRaises(ValueError):reads.check(context,'commerce_workspace_quote_compare',wrong,set())
        with self.assertRaises(ValueError):reads.check(dict(module='overview',demo=False),'commerce_workspace_quote_compare',args,set())

    def test_real_assistant_reads_exact_comparison_and_old_history_is_invalidated(self):
        self.save('assistant')
        context=dict(module='organization',demo=False,platform='ozon',market='RU',entity={'kind':'case','id':self.cid})
        chat=self.app.copilot.open(context,'comparison-chat')
        self.app.copilot.send(chat['id'],'请按13件需求比较当前报价。',chat['context_sha256'],'compare-thirteen')
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_workspace_quote_compare',dict(case_id=self.cid,quantity=13)),answer()]) as provider:
            self.app.agent_runtime.run_once()
        run=self.app.copilot.get(chat['id'])['latest_run']
        self.assertEqual(run['status'],'completed')
        consumed=provider.call_args_list[1].args[0]['observations'][0]['data']
        self.assertEqual(consumed['items'][0]['goods_subtotal'],'13.00')
        self.assertEqual(run['result']['observations'][0]['data'],consumed)
        self.assertTrue(history_refs(self.app,context,run['id']))
        self.save('assistant',purchase_cost=2,revision=1)
        self.assertIsNone(history_refs(self.app,context,run['id']))

    def test_quote_changes_while_model_is_answering_reject_the_stale_result(self):
        self.save('changed')
        context=dict(module='organization',demo=False,platform='ozon',market='RU',entity={'kind':'case','id':self.cid})
        chat=self.app.copilot.open(context,'changed-comparison-chat')
        self.app.copilot.send(chat['id'],'请按13件比较报价。',chat['context_sha256'],'compare-changing')
        def model(payload,cancelled):
            if not payload['observations']:return inspect('commerce_workspace_quote_compare',dict(case_id=self.cid,quantity=13))
            self.save('changed',purchase_cost=2,revision=1)
            return answer()
        with patch('agent_runtime.model.invoke',side_effect=model):self.app.agent_runtime.run_once()
        run=self.app.copilot.get(chat['id'])['latest_run']
        self.assertEqual(run['status'],'failed')
        self.assertEqual(run['result']['error'],'agent_workspace_evidence_changed')


if __name__=='__main__':unittest.main()
