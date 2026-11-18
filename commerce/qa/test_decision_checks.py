"""Synthetic checks for the stateless decision checks (third PAOS-inspired batch)."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import decision_checks as dc
from service import Commerce, TOOLS


def trend(source, kind, group, values, start=(2025, 1), country='RU', **extra):
    rows = []
    for offset, value in enumerate(values):
        index = start[0] * 12 + start[1] - 1 + offset
        rows.append({'id': f'{source}-{offset}', 'source_id': source, 'source_type': kind,
                     'independent_group': group, 'country_code': country, 'metric': 'search_interest',
                     'unit': 'index', 'series_version': 'v1', 'period': f'{index // 12:04}-{index % 12 + 1:02}',
                     'value': value, 'source_kind': 'THIRD_PARTY_ESTIMATE', **extra})
    return rows


def snapshot(identifier, day, **values):
    return {'id': identifier, 'platform': 'ozon', 'country_code': 'RU', 'external_id': 'SYNTHETIC-1',
            'observed_at': day, 'source_id': 'synthetic-export', 'series_version': 'v1', **values}


class DecisionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, data):
        return self.app.invoke(name, {'input': data})

    def assertRejected(self, name, data, code=None):
        with self.assertRaises(ValueError) as caught:
            self.call(name, data)
        if code:
            self.assertEqual(str(caught.exception), code)

    def test_every_tool_is_registered_once_and_never_claims_execution(self):
        names = [tool[0] for tool in TOOLS]
        for name in dc.READ_ONLY:
            self.assertEqual(names.count(name), 1)
        result = self.call('commerce_selection_scorecard', {'candidates': [
            {'sku': 'A', 'source': 'synthetic', 'source_kind': 'MANUAL_QUOTE'}]})
        self.assertFalse(result['marketplace_writes'])
        self.assertFalse(result['external_execution_allowed'])
        self.assertTrue(result['review_required'])
        self.assertEqual(self.app.invoke('commerce_task_list', {})['tasks'], [])

    # selection
    def candidate(self, sku, **values):
        base = {'sku': sku, 'source': 'synthetic sheet', 'source_kind': 'FIRST_PARTY_ACTUAL',
                'review_dependency': 'low', 'net_margin_pct': 30, 'promo_intensity': 'medium',
                'estimated_acos_pct': 10, 'differentiation': 'buyer_visible'}
        base.update(values)
        return base

    def test_scorecard_statuses_and_estimate_marking(self):
        rows = [self.candidate('READY'),
                self.candidate('MISSING', net_margin_pct=None),
                self.candidate('SAME', differentiation='none'),
                self.candidate('NEGATIVE', net_margin_pct=10, estimated_acos_pct=12),
                self.candidate('THIN', net_margin_pct=20, estimated_acos_pct=16),
                self.candidate('UNDIFF', differentiation='unknown', source_kind='THIRD_PARTY_ESTIMATE'),
                self.candidate('SIM', source_kind='SIMULATION')]
        result = self.call('commerce_selection_scorecard', {'candidates': rows})
        got = {row['sku']: row for row in result['matrix']}
        self.assertEqual([row['sku'] for row in result['matrix']], [row['sku'] for row in rows])
        self.assertEqual({k: v['status'] for k, v in got.items()},
                         {'READY': 'READY', 'MISSING': 'HOLD', 'SAME': 'REJECT', 'NEGATIVE': 'REJECT',
                          'THIN': 'HOLD', 'UNDIFF': 'HOLD', 'SIM': 'HOLD'})
        self.assertEqual(got['MISSING']['needs_evidence'], ['net_margin_pct'])
        self.assertIsNone(got['MISSING']['scores'])
        self.assertEqual(got['READY']['scores'], {'review_dependency': 5, 'net_margin_pct': 5,
                                                  'promo_intensity': 3, 'estimated_acos_pct': 5})
        self.assertEqual(got['READY']['profit_after_ads_pct'], '20.00')
        self.assertFalse(got['READY']['estimated'])
        self.assertTrue(got['UNDIFF']['estimated'])
        self.assertEqual(got['UNDIFF']['needs_evidence'], ['differentiation'])
        self.assertEqual(result['status_counts'], {'READY': 1, 'HOLD': 4, 'REJECT': 2})

    def test_scorecard_bounds_and_strict_input(self):
        self.assertEqual(self.call('commerce_selection_scorecard', {
            'candidates': [self.candidate(f'S{i}') for i in range(100)]})['candidate_count'], 100)
        self.assertRejected('commerce_selection_scorecard', {'candidates': [self.candidate(f'S{i}') for i in range(101)]})
        self.assertRejected('commerce_selection_scorecard', {'candidates': []})
        self.assertRejected('commerce_selection_scorecard', {'candidates': [self.candidate('A'), self.candidate('A')]},
                            'decision_duplicate_sku')
        for bad in ({'net_margin_pct': '30'}, {'net_margin_pct': True}, {'net_margin_pct': float('nan')},
                    {'estimated_acos_pct': -1}, {'review_dependency': 'none'}, {'extra': 1}, {'source': 'a\nb'}):
            with self.subTest(bad=bad):
                self.assertRejected('commerce_selection_scorecard', {'candidates': [self.candidate('A', **bad)]})

    # demand
    def demand(self, records, **extra):
        return self.call('commerce_demand_trend_assess', {'country_code': 'RU', 'query': 'synthetic shelf',
                                                         'as_of_month': '2025-12', 'records': records, **extra})

    def test_demand_needs_two_independent_sources(self):
        rising = [10, 10, 10, 10, 12, 13, 14, 15, 18, 20, 20, 20]
        single = self.demand(trend('a', 'search', 'g1', rising))
        self.assertEqual(single['classification'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(single['cards'][0]['direction'], 'UP')
        self.assertEqual(single['cards'][0]['change_pct'], '95.00')  # first third mean 10 -> last third mean 19.5
        same_group = self.demand(trend('a', 'search', 'g1', rising) + trend('b', 'marketplace', 'g1', rising))
        self.assertEqual(same_group['classification'], 'INSUFFICIENT_EVIDENCE')
        both = self.demand(trend('a', 'search', 'g1', rising) + trend('b', 'marketplace', 'g2', rising))
        self.assertEqual((both['classification'], both['consistency']), ('EMERGING', 'CORROBORATED'))
        falling = list(reversed(rising))
        split = self.demand(trend('a', 'search', 'g1', rising) + trend('b', 'marketplace', 'g2', falling))
        self.assertEqual((split['classification'], split['consistency']), ('INSUFFICIENT_EVIDENCE', 'DIVERGENT'))
        down = self.demand(trend('a', 'search', 'g1', falling) + trend('b', 'marketplace', 'g2', falling))
        self.assertEqual(down['classification'], 'DECLINING')
        flat = self.demand(trend('a', 'search', 'g1', [10] * 12) + trend('b', 'marketplace', 'g2', rising))
        self.assertEqual(flat['classification'], 'SUSTAINED')

    def test_demand_gaps_are_reported_not_guessed(self):
        rising = [10, 10, 10, 10, 12, 13, 14, 15, 18, 20, 20, 20]
        sparse = self.demand(trend('a', 'search', 'g1', rising[:6]))['cards'][0]
        self.assertEqual(sparse['direction'], 'UNKNOWN')
        self.assertIn('COVERAGE_BELOW_70_PERCENT', sparse['reasons'])
        self.assertIn('WINDOW_EDGE_MISSING', sparse['reasons'])
        conflict = trend('a', 'search', 'g1', rising)
        conflict.append({**conflict[3], 'id': 'a-dup', 'value': 99})
        card = self.demand(conflict)['cards'][0]
        self.assertEqual(card['conflicting_months'], ['2025-04'])
        self.assertIn('CONFLICTING_MONTHS', card['reasons'])
        self.assertIsNone(card['points'][3]['value'])
        repeated = trend('a', 'search', 'g1', rising)
        repeated.append({**repeated[3], 'id': 'a-same'})
        self.assertEqual(self.demand(repeated)['cards'][0]['direction'], 'UP')
        for extra, reason in (({'country': 'US'}, 'REGION_MISMATCH'), ({'source_revoked': True}, 'SOURCE_UNAVAILABLE'),
                              ({'source_kind': 'SIMULATION'}, 'SIMULATION_EXCLUDED')):
            with self.subTest(reason=reason):
                self.assertIn(reason, self.demand(trend('a', 'search', 'g1', rising, **extra))['cards'][0]['reasons'])
        self.assertIn('ZERO_BASELINE', self.demand(trend('a', 'search', 'g1', [0] * 12))['cards'][0]['reasons'])
        mixed = trend('a', 'search', 'g1', rising)
        mixed[0]['unit'] = 'orders'
        self.assertEqual(len(self.demand(mixed)['cards']), 2)

    def test_demand_seasonality_requires_two_full_years_with_the_same_peak(self):
        year = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 40]
        records = trend('a', 'search', 'g1', year * 2, start=(2024, 1)) + trend('b', 'marketplace', 'g2', year * 2, start=(2024, 1))
        seasonal = self.demand(records, months=24)
        self.assertEqual(seasonal['classification'], 'SEASONAL')
        shifted = year[1:] + year[:1]
        other = trend('a', 'search', 'g1', year + shifted, start=(2024, 1)) + trend('b', 'marketplace', 'g2', year + shifted, start=(2024, 1))
        self.assertNotEqual(self.demand(other, months=24)['classification'], 'SEASONAL')
        self.assertFalse(self.demand(trend('a', 'search', 'g1', year) + trend('b', 'marketplace', 'g2', year))['cards'][0]['seasonal'])
        self.assertRejected('commerce_demand_trend_assess', {'country_code': 'RU', 'query': 'q', 'as_of_month': '2025-13', 'records': records})
        self.assertRejected('commerce_demand_trend_assess', {'country_code': 'RU', 'query': 'q', 'as_of_month': '2025-12', 'records': records, 'months': 18})

    # competitors
    def test_competitor_changes_only_for_comparable_fields(self):
        result = self.call('commerce_competitor_changes', {'snapshots': [
            snapshot('s1', '2025-01-01', price=100, currency='RUB', rating=4.5, review_count=10),
            snapshot('s2', '2025-01-08', price=120, currency='RUB', rating=4.5, review_count=0, rank=3),
            snapshot('s0', '2024-12-01', price=1, currency='RUB')]})
        product = result['products'][0]
        self.assertEqual((product['current_evidence_id'], product['previous_evidence_id']), ('s2', 's1'))
        self.assertEqual(product['changes']['price'], {'previous': '100.00', 'current': '120.00', 'absolute': '20.00',
                                                       'percent': '20.00', 'reason': None})
        self.assertEqual(product['changes']['rating']['absolute'], '0.00')
        self.assertEqual(product['changes']['review_count']['percent'], '-100.00')
        self.assertEqual(product['changes']['rank']['reason'], 'VALUE_MISSING')
        self.assertEqual(product['gaps'], ['VALUE_MISSING'])
        self.assertEqual(product['evidence_ids'], ['s0', 's1', 's2'])

    def test_competitor_breaks_and_invalid_snapshots(self):
        def reason(first, second):
            return self.call('commerce_competitor_changes', {'snapshots': [first, second]})['products'][0]['changes']['price']['reason']
        base = snapshot('s1', '2025-01-01', price=100, currency='RUB')
        self.assertEqual(reason(base, snapshot('s2', '2025-01-08', price=2, currency='USD')), 'CURRENCY_MISMATCH')
        self.assertEqual(reason(base, {**snapshot('s2', '2025-01-08', price=2, currency='RUB'), 'series_version': 'v2'}), 'COMPARABILITY_BREAK')
        self.assertEqual(reason(base, {**snapshot('s2', '2025-01-08', price=2, currency='RUB'), 'source_revoked': True}), 'SOURCE_UNAVAILABLE')
        self.assertEqual(reason({**base, 'source_revoked': True}, snapshot('s2', '2025-01-08', price=2, currency='RUB')), 'SOURCE_UNAVAILABLE')
        self.assertEqual(reason(base, snapshot('s2', '2025-01-01', price=2, currency='RUB')), 'AMBIGUOUS_ORDER')
        only = self.call('commerce_competitor_changes', {'snapshots': [base]})['products'][0]
        self.assertEqual(only['changes']['price']['reason'], 'NO_BASELINE')
        zero = self.call('commerce_competitor_changes', {'snapshots': [
            snapshot('s1', '2025-01-01', review_count=0), snapshot('s2', '2025-01-02', review_count=5)]})['products'][0]
        self.assertEqual((zero['changes']['review_count']['absolute'], zero['changes']['review_count']['percent']), ('5.00', None))
        self.assertRejected('commerce_competitor_changes', {'snapshots': [snapshot('s1', '2025-01-01', price=1)]},
                            'decision_price_requires_currency')
        self.assertRejected('commerce_competitor_changes', {'snapshots': [base, base]})
        self.assertRejected('commerce_competitor_changes', {'snapshots': [snapshot('s1', '2025-02-30')]})

    # shipments
    def shipment(self, events, as_of='2025-03-01', **extra):
        return self.call('commerce_shipment_reconcile', {'as_of': as_of, 'events': events, **extra, 'shipment': {
            'shipment_ref': 'SYNTHETIC-SHIP', 'sku': 'SYNTHETIC-A', 'expected_quantity': 100, 'shipped_date': '2025-01-01'}})

    @staticmethod
    def event(kind, quantity, day='2025-01-10', source='synthetic receipt'):
        return {'event_type': kind, 'quantity': quantity, 'event_date': day, 'source': source}

    def test_shipment_states(self):
        self.assertEqual(self.shipment([self.event('RECEIVED', 100)])['state'], 'BALANCED')
        early = self.shipment([self.event('RECEIVED', 90)], as_of='2025-01-15')
        self.assertEqual((early['state'], early['pending_variance'], early['age_days']), ('IN_TRANSIT', 10, 14))
        self.assertEqual(self.shipment([self.event('RECEIVED', 90)], as_of='2025-01-16')['state'], 'CONFIRMED_VARIANCE')
        excluded = self.shipment([self.event('RECEIVED', 80), self.event('TRANSFER', 5), self.event('ADJUSTMENT', 5),
                                  self.event('LOST_FOUND', 4)],
                                 claims=[{'claim_ref': 'c1', 'claimed_quantity': 3, 'state': 'OPEN'},
                                         {'claim_ref': 'c2', 'claimed_quantity': 50, 'state': 'REJECTED'}])
        self.assertEqual((excluded['state'], excluded['pending_variance'], excluded['already_claimed'],
                          excluded['received_quantity']), ('CONFIRMED_VARIANCE', 3, 3, 84))
        over = self.shipment([self.event('RECEIVED', 104)])
        self.assertEqual((over['state'], over['over_received'], over['pending_variance']), ('OVER_RECEIVED', 4, 0))
        doubled = self.shipment([self.event('RECEIVED', 50), self.event('RECEIVED', 50)])
        self.assertEqual((doubled['state'], doubled['warnings']), ('BALANCED', ['IDENTICAL_EVENT_ROWS']))
        overclaimed = self.shipment([self.event('RECEIVED', 95)], claims=[{'claim_ref': 'c1', 'claimed_quantity': 9, 'state': 'RESOLVED'}])
        self.assertEqual((overclaimed['state'], overclaimed['warnings']), ('BALANCED', ['CLAIMS_EXCEED_VARIANCE']))
        self.assertEqual(self.shipment([], as_of='2025-01-02')['state'], 'IN_TRANSIT')

    def test_shipment_proposed_claim_verdicts_and_input_dates(self):
        def verdict(quantity, events, **extra):
            return self.shipment(events, proposed_claim_quantity=quantity, **extra)['proposed_claim']['verdict']
        short = [self.event('RECEIVED', 90)]
        self.assertEqual(verdict(10, short), 'WITHIN_VARIANCE')
        self.assertEqual(verdict(11, short), 'BLOCKED_EXCESS')
        self.assertEqual(verdict(1, short, as_of='2025-01-10'), 'BLOCKED_IN_TRANSIT')
        self.assertEqual(verdict(1, [self.event('RECEIVED', 100)]), 'BLOCKED_NO_VARIANCE')
        self.assertEqual(verdict(1, short, claims=[{'claim_ref': 'c1', 'claimed_quantity': 10, 'state': 'OPEN'}]), 'BLOCKED_NO_VARIANCE')
        self.assertEqual(verdict(1, short, as_of='2025-06-01'), 'BLOCKED_WINDOW_ELAPSED')
        self.assertEqual(verdict(1, short, as_of='2025-06-01', claim_window_days=365), 'WITHIN_VARIANCE')
        self.assertNotIn('proposed_claim', self.shipment(short))
        self.assertRejected('commerce_shipment_reconcile', {'as_of': '2024-12-31', 'events': [], 'shipment': {
            'shipment_ref': 'S', 'sku': 'A', 'expected_quantity': 1, 'shipped_date': '2025-01-01'}}, 'decision_invalid_shipped_date')
        self.assertRejected('commerce_shipment_reconcile', {'as_of': '2025-03-01', 'events': [self.event('RECEIVED', 1, '2025-04-01')], 'shipment': {
            'shipment_ref': 'S', 'sku': 'A', 'expected_quantity': 1, 'shipped_date': '2025-01-01'}}, 'decision_invalid_event_date')
        with self.assertRaises(ValueError):
            self.shipment([self.event('STOLEN', 1)])
        with self.assertRaises(ValueError):
            self.shipment([self.event('RECEIVED', 1.5)])
        with self.assertRaises(ValueError):
            self.shipment([], claims=[{'claim_ref': 'c', 'claimed_quantity': 1, 'state': 'OPEN'}] * 2)

    # experiments
    def experiment(self, baseline, variant, **extra):
        data = {'primary_metric': 'conversion', 'changed_variables': ['main image'], 'higher_is_better': True,
                'baseline': {'trials': baseline[0], 'successes': baseline[1]},
                'variant': {'trials': variant[0], 'successes': variant[1]}}
        data.update(extra)
        return self.call('commerce_experiment_evaluate', data)

    def test_experiment_outcomes(self):
        win = self.experiment((1000, 100), (1000, 150))
        self.assertEqual((win['outcome'], win['decision_ready']), ('VARIANT_FAVORED', True))
        self.assertEqual(win['z_score'], '3.3806')
        self.assertEqual(win['variant']['rate'], '0.150000')
        self.assertEqual(self.experiment((1000, 150), (1000, 100))['outcome'], 'BASELINE_FAVORED')
        self.assertEqual(self.experiment((1000, 100), (1000, 150), higher_is_better=False)['outcome'], 'BASELINE_FAVORED')
        near = self.experiment((1000, 100), (1000, 110))
        self.assertEqual((near['outcome'], near['decision_ready']), ('NO_DETECTED_DIFFERENCE', False))
        small = self.experiment((99, 1), (5000, 2500))
        self.assertEqual((small['outcome'], small['z_score']), ('INCONCLUSIVE', None))
        self.assertEqual(self.experiment((100, 1), (100, 30))['outcome'], 'VARIANT_FAVORED')
        self.assertEqual(self.experiment((200, 0), (200, 0))['outcome'], 'INCONCLUSIVE')
        self.assertEqual(self.experiment((0, 0), (0, 0))['baseline']['rate'], None)
        multi = self.experiment((1000, 100), (1000, 150), changed_variables=['main image', 'price'])
        self.assertEqual((multi['outcome'], multi['decision_ready'], multi['z_score']), ('CONFOUNDED', False, None))

    def test_experiment_flags_block_decision_and_inputs_are_strict(self):
        noisy = self.experiment((1000, 100), (1000, 150), external_interference=['platform sale'])
        self.assertEqual((noisy['outcome'], noisy['flags'], noisy['decision_ready']),
                         ('VARIANT_FAVORED', ['EXTERNAL_INTERFERENCE'], False))
        spent = self.experiment((1000, 100), (1000, 150), budget_cap=100, budget_spent=100.01)
        self.assertEqual((spent['flags'], spent['decision_ready']), (['BUDGET_CAP_EXCEEDED'], False))
        self.assertTrue(self.experiment((1000, 100), (1000, 150), budget_cap=100, budget_spent=100)['decision_ready'])
        for bad in ({'budget_cap': 1}, {'min_sample_per_arm': 5}, {'changed_variables': []},
                    {'changed_variables': ['a', 'a']}, {'higher_is_better': 1}, {'unknown': 1}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.experiment((1000, 100), (1000, 150), **bad)
        with self.assertRaises(ValueError):
            self.experiment((10, 11), (10, 1))
        with self.assertRaises(ValueError):
            self.experiment((10.5, 1), (10, 1))


if __name__ == '__main__':
    unittest.main()
