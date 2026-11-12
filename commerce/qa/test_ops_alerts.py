"""Synthetic local alert and scenario acceptance. No external accounts or messages."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from ops_alerts import OperationsAlerts, derive, DEFAULT_RULES, iso, stock_plan
from campaign_plans import compare
from research import digest

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
BASE = dict(currency='CNY', price=100, purchase_cost=30, domestic_shipping=2, packaging=1,
            fulfillment_cost=10, electronic_fee=1, commission_rate=.1, payment_rate=.01,
            return_rate=.02, ad_rate=.05)


def observation(kind='order', **changes):
    record = dict(event_id='synthetic-order', platform='ozon', store_id='synthetic-store', market='RU',
                  fulfillment='FBS', warehouse='synthetic-wh', observed_at=iso(NOW),
                  source_ref='synthetic:fixture', kind=kind,
                  data=dict(order_id='synthetic-order', sku='synthetic-sku', quantity=2,
                            status='awaiting_packaging', ship_by=iso(NOW + timedelta(hours=2))))
    if kind == 'stock':
        record.update(event_id='synthetic-stock', data=dict(sku='synthetic-sku', available=10,
                      sold_units=60, window_days=30, lead_time_days=14, safety_days=7,
                      pack_size=6, inbound_units=0, inbound_due_at=None))
    record.update(changes)
    return record


class Alerts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.app = OperationsAlerts(Core(Path(self.temp.name)/'state.sqlite'))

    def tearDown(self): self.temp.cleanup()
    def kinds(self, state): return {a['kind'] for a in state['alerts'] if a['status'] == 'active'}

    def test_order_creates_single_source_backed_alerts_and_duplicate_is_noop(self):
        record = observation(); first = self.app.record(record, current=NOW)
        self.assertEqual(first['status'], 'recorded')
        state = self.app.list(current=NOW)
        self.assertEqual(self.kinds(state), {'order_observed', 'prepare', 'dispatch_deadline'})
        self.assertTrue(all(x['source_sha256'] == first['sha256'] for x in state['alerts']))
        count = len(json.loads(self.app.export()['content'])['audit'])
        self.assertEqual(self.app.record(record, current=NOW)['status'], 'duplicate')
        self.assertEqual(len(json.loads(self.app.export()['content'])['audit']), count)

    def test_concurrent_duplicate_events_are_single_entity(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.app.record(observation(), current=NOW), range(4)))
        self.assertEqual(sum(x['status'] == 'recorded' for x in results), 1)
        self.assertEqual(self.app.list(current=NOW)['observation_count'], 1)

    def test_unknown_and_fbo_modes_do_not_invent_seller_packaging_responsibility(self):
        for mode, wanted in [('unknown', {'order_observed', 'fulfillment_unknown'}), ('FBO', {'order_observed'})]:
            alerts, _ = derive(observation(fulfillment=mode), DEFAULT_RULES, NOW)
            self.assertEqual({x['kind'] for x in alerts}, wanted)

    def test_cancelled_order_closes_alerts_and_old_event_cannot_reopen(self):
        self.app.record(observation(), current=NOW)
        closed = observation(event_id='closed', observed_at=iso(NOW+timedelta(minutes=1)))
        closed['data']['status'] = 'cancelled'; self.app.record(closed, current=NOW+timedelta(minutes=1))
        old = observation(event_id='older', observed_at=iso(NOW-timedelta(minutes=1)))
        self.assertEqual(self.app.record(old, current=NOW+timedelta(minutes=1))['status'], 'stored_history_only')
        self.assertEqual(self.kinds(self.app.list(current=NOW+timedelta(hours=5))), set())

    def test_no_deadline_is_unknown_not_overdue(self):
        record = observation(); record['data']['ship_by'] = None
        alerts, _ = derive(record, DEFAULT_RULES, NOW)
        self.assertIn('deadline_unknown', {a['kind'] for a in alerts})
        self.assertNotIn('dispatch_deadline', {a['kind'] for a in alerts})

    def test_time_advances_deadline_without_new_data(self):
        rules = {**DEFAULT_RULES, 'max_age_minutes': 180}
        self.app.rules(rules=rules); self.app.record(observation(), current=NOW)
        state = self.app.list(current=NOW+timedelta(hours=2))
        self.assertEqual(next(a for a in state['alerts'] if a['kind']=='dispatch_deadline')['severity'], 'P0')

    def test_stale_data_suspends_old_risk_instead_of_claiming_resolution(self):
        self.app.record(observation('stock'), current=NOW)
        state = self.app.list(current=NOW+timedelta(hours=2))
        self.assertEqual(self.kinds(state), {'data_stale'})
        self.assertEqual(next(a for a in state['alerts'] if a['kind']=='restock')['status'], 'suspended')
        self.assertEqual(state['stock_plans'], [])

    def test_acknowledgement_does_not_complete_or_send_and_is_scoped(self):
        self.app.record(observation(), current=NOW); alert = self.app.list(current=NOW)['alerts'][0]
        self.assertEqual(self.app.acknowledge(alert['id'])['status'], 'acknowledged')
        self.assertEqual(next(a for a in self.app.list(current=NOW)['alerts'] if a['id']==alert['id'])['status'], 'acknowledged')
        self.assertEqual(alert['delivery'], 'workbench_only')
        with self.assertRaises(ValueError): self.app.acknowledge(alert['id'], demo=True)

    def test_store_warehouse_and_demo_scope_are_separate(self):
        record = observation('stock'); self.app.record(record, demo=True, current=NOW)
        self.assertEqual(self.app.list(current=NOW)['observation_count'], 0)
        self.app.record(record, current=NOW)
        second = observation('stock', event_id='other-warehouse', warehouse='other-wh'); self.app.record(second, current=NOW)
        self.assertEqual(self.app.list(current=NOW)['observation_count'], 2)

    def test_conflicting_ids_or_equal_timestamp_conflicts_are_rejected(self):
        record = observation(); self.app.record(record, current=NOW)
        conflicting = copy.deepcopy(record); conflicting['data']['quantity'] = 3
        with self.assertRaises(ValueError): self.app.record(conflicting, current=NOW)
        conflicting['event_id'] = 'another-id'
        with self.assertRaises(ValueError): self.app.record(conflicting, current=NOW)

    def test_future_time_unknown_fields_and_invalid_numbers_rejected(self):
        for record in [observation(observed_at=iso(NOW+timedelta(hours=1))), {**observation(), 'verified': True}]:
            with self.assertRaises(ValueError): self.app.record(record, current=NOW)
        record = observation('stock'); record['data']['available'] = True
        with self.assertRaises(ValueError): self.app.record(record, current=NOW)

    def test_inbound_only_counts_when_timed_before_gap_and_in_planning_horizon(self):
        record = observation('stock'); data = record['data']
        data.update(inbound_units=12, inbound_due_at=iso(NOW+timedelta(days=2)))
        self.assertEqual(stock_plan(data, NOW)['suggested_qty'], 24)
        self.assertEqual(stock_plan(data, NOW)['eligible_inbound'], 12)
        data['inbound_due_at'] = iso(NOW+timedelta(days=6))
        self.assertEqual(stock_plan(data, NOW)['suggested_qty'], 36)
        data['inbound_due_at'] = None
        self.assertIsNone(stock_plan(data, NOW)['suggested_qty'])

    def test_zero_stock_and_zero_demand_keep_quantity_unknown(self):
        record = observation('stock'); record['data'].update(available=0, sold_units=0)
        alerts, plan = derive(record, DEFAULT_RULES, NOW)
        self.assertIn('out_of_stock', {a['kind'] for a in alerts}); self.assertIsNone(plan['suggested_qty'])

    def test_passed_eta_without_receipt_is_not_treated_as_confirmed_stock(self):
        record = observation('stock'); record['data'].update(inbound_units=12, inbound_due_at=iso(NOW+timedelta(minutes=15)))
        _, plan = derive(record, DEFAULT_RULES, NOW+timedelta(minutes=30))
        self.assertEqual(plan['eligible_inbound'], 0)
        self.assertEqual(plan['suggested_qty'], 36)

    def test_evidence_export_keeps_exact_record_and_hash(self):
        record = observation(); result = self.app.record(record, current=NOW); exported = self.app.export()
        payload = json.loads(exported['content'])
        self.assertEqual(exported['sha256'], digest(exported['content']))
        self.assertEqual(payload['observations'][0], {'record': record, 'sha256': result['sha256']})


class Campaigns(unittest.TestCase):
    def data(self):
        return dict(base=BASE, target_contribution=20, inventory_state='unknown', plans=[
            dict(name='Synthetic A', price=100, merchant_discount=0, ad_cost_per_unit=10, affiliate_rate=0),
            dict(name='Synthetic B', price=100, merchant_discount=10, ad_cost_per_unit=10, affiliate_rate=.05)])

    def test_combined_discount_affiliate_ads_not_double_charged(self):
        result = compare(self.data()); a,b = result['plans']
        self.assertEqual(a['contribution'], 33); self.assertEqual(a['ad_allowance_at_target'], 23)
        self.assertEqual(b['contribution'], 19.8); self.assertFalse(b['meets_target'])
        self.assertIn('尚待核实', a['recommendation']); self.assertFalse(result['marketplace_writes'])

    def test_tight_stock_prevents_growth_recommendation_even_when_profitable(self):
        result = compare({**self.data(), 'inventory_state':'tight'})
        self.assertIn('优先补货', result['plans'][0]['recommendation'])

    def test_missing_cost_and_impossible_margin_are_explicit(self):
        data = self.data(); data['base'] = {k:v for k,v in BASE.items() if k!='purchase_cost'}
        self.assertEqual(compare(data)['status'], 'HOLD')
        data = self.data(); data['target_contribution'] = 80
        self.assertFalse(compare(data)['plans'][0]['target_possible_before_ads'])
        self.assertLess(compare(data)['plans'][0]['ad_allowance_at_target'], 0)

    def test_invalid_discount_and_rate_rejected(self):
        for key,value in [('merchant_discount',100),('affiliate_rate',1.1),('ad_cost_per_unit',-1)]:
            data = self.data(); data['plans'][0][key]=value
            with self.assertRaises(ValueError): compare(data)


if __name__ == '__main__': unittest.main()
