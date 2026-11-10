"""Synthetic acceptance of adapted calculations and scoped retrieval."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from operations_analysis import unit_economics, restock_plan
from knowledge_ranking import ranked_notes
from service import Commerce, TOOLS


UNIT = dict(currency='CNY', price=100, purchase_cost=30, domestic_shipping=2,
            packaging=1, fulfillment_cost=10, electronic_fee=1,
            commission_rate=.1, payment_rate=.01, return_rate=.02, ad_rate=.05)
STOCK = dict(available=10, sold_units=60, window_days=30,
             lead_time_days=14, safety_days=7, pack_size=6)


class Calculations(unittest.TestCase):
    def test_complete_cost_decomposition(self):
        result = unit_economics(UNIT)
        self.assertEqual(result['total_cost'], 62)
        self.assertEqual(result['contribution'], 38)
        self.assertEqual(result['contribution_rate'], .38)
        self.assertTrue(result['review_required'])
        self.assertFalse(result['marketplace_writes'])

    def test_missing_cost_is_unknown_and_explicit_zero_is_valid(self):
        missing = {k: v for k, v in UNIT.items() if k != 'purchase_cost'}
        result = unit_economics(missing)
        self.assertEqual(result['status'], 'HOLD')
        self.assertIsNone(result['contribution'])
        self.assertIn('purchase_cost', result['missing'])
        self.assertEqual(unit_economics({**UNIT, 'purchase_cost': 0})['status'], 'CALCULATED')

    def test_invalid_amounts_rates_and_currency_are_rejected(self):
        for key, value in [('price', 0), ('purchase_cost', -1), ('ad_rate', 1.01),
                           ('price', True), ('price', float('nan')), ('price', float('inf')),
                           ('currency', 'CNY/RUB')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                unit_economics({**UNIT, key: value})
        with self.assertRaises(ValueError):
            unit_economics({**UNIT, 'assumed_fx': 12})

    def test_monetary_rounding_and_negative_contribution(self):
        result = unit_economics({**UNIT, 'packaging': 1.005})
        self.assertEqual(result['cost_breakdown']['packaging'], 1.01)
        self.assertLess(unit_economics({**UNIT, 'purchase_cost': 200})['contribution'], 0)
        json.dumps(result, allow_nan=False)

    def test_window_and_pack_rounding(self):
        result = restock_plan(STOCK)
        self.assertEqual(result['days_of_cover'], 5)
        self.assertEqual(result['target_units'], 42)
        self.assertEqual(result['suggested_qty'], 36)
        self.assertEqual(result['urgency'], 'P0')

    def test_non_30_day_window_and_unrounded_velocity(self):
        result = restock_plan(dict(available=0, sold_units=1, window_days=365,
                                   lead_time_days=1, safety_days=0, pack_size=1))
        self.assertGreater(result['velocity'], 0)
        self.assertEqual(result['suggested_qty'], 1)

    def test_unknown_demand_and_missing_window_are_not_zero_restock(self):
        result = restock_plan({**STOCK, 'sold_units': 0})
        self.assertEqual(result['status'], 'HOLD')
        self.assertIsNone(result['suggested_qty'])
        missing = {k: v for k, v in STOCK.items() if k != 'window_days'}
        self.assertEqual(restock_plan(missing)['missing'], ['window_days'])
        for key, value in [('available', -1), ('sold_units', .5), ('window_days', 0),
                           ('pack_size', 0), ('lead_time_days', True)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                restock_plan({**STOCK, key: value})


class Ranking(unittest.TestCase):
    def test_chinese_query_retrieves_english_note(self):
        docs = [{'path': 'inventory.md', 'content': '# Inventory\nRestock when stock is low.'},
                {'path': 'ads.md', 'content': '# Ads\nAdvertising campaign.'}]
        self.assertEqual(ranked_notes(docs, '如何补货')[0]['path'], 'inventory.md')
        self.assertEqual(ranked_notes(docs, '库存')[0]['path'], 'inventory.md')

    def test_english_boundaries_and_empty_query(self):
        self.assertEqual(ranked_notes([{'path': 'upload.md', 'content': 'uploads only'}], 'ads'), [])
        self.assertEqual(ranked_notes([], 'inventory'), [])
        self.assertEqual(ranked_notes([{'path': 'a.md', 'content': 'inventory'}], '如何'), [])

    def test_concept_coverage_beats_repetition(self):
        docs = [{'path': 'spam.md', 'content': '# Ads\n' + 'ads ' * 100},
                {'path': 'specific.md', 'content': '# Inventory ads\nstock advertising'}]
        hits = ranked_notes(docs, '库存 广告')
        self.assertEqual(hits[0]['path'], 'specific.md')
        self.assertLessEqual(len(hits[0]['excerpt']), 280)


class ServiceAdaptation(unittest.TestCase):
    def test_tools_and_scoped_bilingual_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); notes = root / 'notes'; notes.mkdir()
            (notes / 'Inventory.md').write_text('# Inventory\nReplenishment planning.')
            outside = root / 'outside.md'; outside.write_text('synthetic private canary')
            (notes / 'escape.md').symlink_to(outside)
            app = Commerce(root / 'state')
            (root / 'state/config.json').write_text(json.dumps({'knowledge_root': str(notes)}))
            names = [item[0] for item in TOOLS]
            self.assertIn('commerce_unit_economics', names)
            self.assertIn('commerce_restock_plan', names)
            self.assertEqual(app.invoke('commerce_unit_economics', {'input': UNIT})['contribution'], 38)
            self.assertEqual(app.invoke('commerce_restock_plan', {'input': STOCK})['suggested_qty'], 36)
            hits = app.invoke('commerce_knowledge_search', {'query': '补货'})['hits']
            self.assertEqual([row['path'] for row in hits], ['Inventory.md'])
            self.assertEqual(app.invoke('commerce_knowledge_search', {'query': 'canary'})['hits'], [])
            with self.assertRaises(ValueError):
                app.invoke('commerce_unit_economics', {'input': [], 'unexpected': True})


if __name__ == '__main__':
    unittest.main(verbosity=2)
