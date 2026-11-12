"""Synthetic inventory-to-plan invariants; no external access or real business data."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from live_connections import LiveConnections, now
from live_planning import LivePlanning
from research import canonical, digest
from test_live_connections import batch, SECRET, HOOK


class Planning(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.live=LiveConnections(Core(Path(self.temp.name)/'db.sqlite'),self.temp.name);self.plans=LivePlanning(self.live)
        self.live.configure({'ozon_client_id':'123456','ozon_api_key':SECRET,'fulfillment_modes':['OGL']})
        self.publish('orders');self.publish('stock')

    def tearDown(self):self.temp.cleanup()
    def publish(self,kind,**kwargs):
        config=self.live.config();self.live._publish(config['connection_id'],kind,batch(kind,**kwargs),config,self.live.snapshot(config['connection_id'],kind) is not None)
    def review(self):self.live.configure({'stock_basis':'present_minus_reserved','basis_confirmed':True,'orders_scope_confirmed':True})
    def inputs(self,**kwargs):return dict(sold_units=60,window_days=30,lead_time_days=14,safety_days=7,pack_size=6,inbound_units=0,source_ref='synthetic:sales.csv row 2; units, same scope',demand_observed_at=now(),**kwargs)
    def save(self,data=None,key='draft-1',row='10:fbs',sha=None):return self.plans.save(row,sha or self.plans.candidates()[0]['source_sha256'],data if data is not None else self.inputs(),key)

    def test_review_and_unknown_fields_hold_without_inventing_quantity(self):
        result=self.save({})
        self.assertEqual(result['current_result']['status'],'HOLD');self.assertIsNone(result['current_result']['suggested_qty'])
        self.assertIn('stock_basis_unconfirmed',result['current_reasons']);self.assertIn('demand_evidence_missing',result['current_reasons'])
        self.assertIsNone(self.plans.candidates()[0]['available'])

    def test_known_inventory_calculation_rounding_and_inbound(self):
        self.review();result=self.save()
        self.assertEqual(result['current_result']['suggested_qty'],36);self.assertEqual(result['stock']['available'],9)
        data=self.inputs();data.update(inbound_units=12,inbound_due_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
        result=self.save(data,key='with-inbound');self.assertEqual(result['current_result']['suggested_qty'],24)
        self.assertFalse(result['marketplace_writes']);self.assertEqual(self.live.status()['outbox'],[])

    def test_unknown_and_late_inbound_do_not_reduce_purchase(self):
        self.review();data=self.inputs();data.pop('inbound_units');self.assertEqual(self.save(data)['current_result']['status'],'HOLD')
        data.update(inbound_units=12,inbound_due_at=(datetime.now(timezone.utc)+timedelta(days=20)).isoformat())
        result=self.save(data,key='late');self.assertEqual(result['current_result']['suggested_qty'],36);self.assertEqual(result['current_result']['eligible_inbound'],0)

    def test_exact_product_and_fulfillment_key_prevents_same_sku_merge(self):
        config=self.live.config();data=batch('stock');data['records'][0]['stocks'].append({'type':'rfbs','present':5,'reserved':1,'sku':'123'})
        data['records'].append({'product_id':'11','offer_id':'SYN-SKU','stocks':[{'type':'fbs','present':100,'reserved':0,'sku':'456'}]})
        self.live._publish(config['connection_id'],'stock',data,config,True);self.review()
        self.assertEqual(self.save(row='10:rfbs')['stock']['available'],4)
        self.assertEqual(self.save(key='second-product',row='11:fbs')['stock']['available'],100)
        with self.assertRaisesRegex(ValueError,'stock_row_not_found'):self.save(key='missing-row',row='SYN-SKU')

    def test_idempotency_and_account_isolation(self):
        self.review();data=self.inputs();a=self.save(data);b=self.save(data);self.assertEqual(a['id'],b['id'])
        changed={**data,'sold_units':61}
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.save(changed)
        self.live.configure({'ozon_client_id':'654321'})
        self.assertEqual(self.plans.list()['plans'],[])
        with self.assertRaisesRegex(ValueError,'restock_plan_not_found'):self.plans.export(a['id'])

    def test_new_snapshot_withdraws_current_quantity_and_rejects_stale_save(self):
        self.review();a=self.save();self.publish('stock',value=20)
        b=self.plans.list()['plans'][0];self.assertEqual(b['result']['suggested_qty'],36);self.assertIsNone(b['current_result']['suggested_qty']);self.assertIn('source_changed',b['current_reasons'])
        with self.assertRaisesRegex(ValueError,'stock_source_changed'):self.save(key='new',sha=a['snapshot_sha256'])

    def test_stale_inventory_or_expired_manual_evidence_holds(self):
        self.review();a=self.save();snapshot=self.live.snapshot(self.live.config()['connection_id'],'stock')
        with self.live.core.db()as db:db.execute('UPDATE live_snapshots SET observed=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),snapshot['id']))
        self.assertIsNone(self.plans.candidates()[0]['available']);self.assertIn('stock_stale',self.plans.list()['plans'][0]['current_reasons'])
        self.publish('stock');data=self.inputs();data['demand_observed_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        self.assertIn('demand_evidence_stale',self.save(data,key='old-demand')['current_reasons'])

    def test_changed_basis_and_passed_inbound_withdraw_plan(self):
        self.review();a=self.save();self.live.configure({'stock_basis':'present_is_available','basis_confirmed':True})
        self.assertIn('basis_changed',self.plans.list()['plans'][0]['current_reasons'])
        data=self.inputs();data.update(inbound_units=12,inbound_due_at=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat());self.save(data,key='inbound')
        with patch.object(self.plans,'clock',return_value=datetime.now(timezone.utc)+timedelta(minutes=2)):
            self.assertIn('inbound_delivery_needs_review',self.plans.list()['plans'][0]['current_reasons'])

    def test_invalid_values_do_not_become_zero_even_if_other_fields_missing(self):
        for value in (-1,True,float('nan'),float('inf'),'12',1.5):
            with self.subTest(value=value),self.assertRaises(ValueError):self.save({'sold_units':value})
        with self.assertRaisesRegex(ValueError,'future_demand_observation'):self.save({'demand_observed_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        with self.assertRaises(ValueError):self.save({'available':999})

    def test_export_hash_evidence_chinese_fields_and_secret_exclusion(self):
        self.review();a=self.save();result=self.plans.export(a['id']);document=json.loads(result['content']);sha=document.pop('sha256')
        self.assertEqual(digest(canonical(document)),sha);self.assertEqual(document['plan']['snapshot_sha256'],a['snapshot_sha256']);self.assertIn('response_sha256',result['content'])
        self.assertIn('销量来源',result['content']);self.assertNotIn(SECRET,result['content']);self.assertNotIn('SYNTHETIC-CANARY',result['content'])

    def test_diagnostics_explain_staleness_and_unknown_delivery_without_secrets(self):
        result=self.plans.readiness();self.assertIn('stock_basis',[c['key']for c in result['checks']if c['status']=='needs_action'])
        config=self.live.config()
        with self.live.core.db()as db:db.execute('INSERT INTO live_outbox VALUES (?,?,?,?,?,?,?,?,?)',('synthetic-receipt','event',config['connection_id'],'private-channel','unknown','PRIVATE-MESSAGE',now(),now(),canonical({'code':'feishu_delivery_unknown'})))
        result=self.plans.readiness();self.assertEqual(result['deliveries'][0]['status'],'unknown');self.assertNotIn('PRIVATE-MESSAGE',canonical(result));self.assertNotIn(SECRET,canonical(result))


if __name__=='__main__':unittest.main()
