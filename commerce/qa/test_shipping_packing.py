"""Geometry and admission regressions for the offline shipping planner."""
import copy
import itertools
import math
import unittest
from collections import Counter

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shipping_packing import candidates


def item(sku='A', quantity=1, size=(1, 1, 1), weight=1, **extra):
    return {'sku': sku, 'quantity': quantity, 'length_cm': size[0],
            'width_cm': size[1], 'height_cm': size[2], 'weight_kg': weight, **extra}


def carton(key='box', inner=(4, 4, 4), outer=None, tare=0.2, limit=20, cost='1.00'):
    return {'id': key, 'name': key, 'inner_cm': list(inner),
            'outer_cm': list(outer or inner), 'tare_kg': tare,
            'max_weight_kg': limit, 'packaging_cost': cost}


class ShippingPackingTests(unittest.TestCase):
    def assert_valid(self, plans, rows, cartons, max_boxes=100):
        self.assertTrue(plans)
        self.assertLessEqual(len(plans), 32)
        originals = {row['sku']: row for row in rows}
        containers = {row['id']: row for row in cartons}
        self.assertEqual(len({p['id'] for p in plans}), len(plans))
        for plan in plans:
            counts = Counter()
            self.assertEqual(plan['input_units'], sum(row['quantity'] for row in rows))
            self.assertEqual(plan['box_count'], len(plan['boxes']))
            self.assertLessEqual(plan['box_count'], max_boxes)
            self.assertEqual(plan['complete'], not plan['unplaced'])
            volume = 0
            for box in plan['boxes']:
                source = containers[box['carton_id']]
                self.assertEqual(box['inner_cm'], source['inner_cm'])
                self.assertEqual(box['outer_cm'], source['outer_cm'])
                self.assertEqual(box['packaging_cost'], source['packaging_cost'])
                self.assertTrue(box['items'])
                weights, goods_volume = 0, 0
                volume += math.prod(source['outer_cm'])
                for placed in box['items']:
                    original = originals[placed['sku']]
                    counts[placed['sku']] += 1
                    size = tuple(original[k] for k in ('length_cm', 'width_cm', 'height_cm'))
                    allowed = set(itertools.permutations(size)) if original.get('rotation_allowed', True) else {size}
                    self.assertIn(tuple(placed['orientation_cm']), allowed)
                    self.assertEqual(placed['weight_kg'], original['weight_kg'])
                    self.assertEqual(placed['no_stack'], original.get('no_stack', False))
                    weights += placed['weight_kg']
                    goods_volume += math.prod(placed['orientation_cm'])
                    for position, length, boundary in zip(placed['position_cm'], placed['orientation_cm'], source['inner_cm']):
                        self.assertGreaterEqual(position, 0)
                        self.assertLessEqual(position + length, boundary + 1e-8)
                    if placed['no_stack']:
                        self.assertEqual(len(box['items']), 1)
                    x, y, z = placed['position_cm']
                    length, width, _ = placed['orientation_cm']
                    if z > 1e-8:
                        supported = any(
                            abs(other['position_cm'][2] + other['orientation_cm'][2] - z) < 1e-8
                            and other['position_cm'][0] <= x + 1e-8
                            and other['position_cm'][1] <= y + 1e-8
                            and other['position_cm'][0] + other['orientation_cm'][0] >= x + length - 1e-8
                            and other['position_cm'][1] + other['orientation_cm'][1] >= y + width - 1e-8
                            for other in box['items'] if other is not placed)
                        self.assertTrue(supported, 'an elevated item needs full footprint support')
                for first, second in itertools.combinations(box['items'], 2):
                    separated = any(
                        first['position_cm'][axis] + first['orientation_cm'][axis] <= second['position_cm'][axis] + 1e-8
                        or second['position_cm'][axis] + second['orientation_cm'][axis] <= first['position_cm'][axis] + 1e-8
                        for axis in range(3))
                    self.assertTrue(separated, 'units must never overlap')
                self.assertAlmostEqual(box['goods_weight_kg'], weights)
                self.assertAlmostEqual(box['gross_weight_kg'], weights + source['tare_kg'])
                self.assertLessEqual(box['gross_weight_kg'], source['max_weight_kg'] + 1e-8)
                self.assertAlmostEqual(box['volume_utilization_pct'], goods_volume / math.prod(source['inner_cm']) * 100, delta=0.051)
            self.assertAlmostEqual(plan['total_outer_volume_cm3'], volume)
            self.assertEqual(plan['placed_units'], sum(counts.values()))
            for missing in plan['unplaced']:
                self.assertTrue(missing['reasons'])
                counts[missing['sku']] += missing['quantity']
            self.assertEqual(counts, Counter({row['sku']: row['quantity'] for row in rows}))

    def test_multiple_skus_share_one_carton_without_losing_identity(self):
        rows = [item('A', 2, (2, 2, 2)), item('B', 2, (2, 2, 2))]
        boxes = [carton(inner=(4, 4, 2))]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(any(p['complete'] and p['box_count'] == 1 for p in plans))
        self.assertEqual({p['sku'] for p in plans[0]['boxes'][0]['items']}, {'A', 'B'})

    def test_same_sku_units_can_use_different_orientations(self):
        rows, boxes = [item(quantity=3, size=(2, 3, 1))], [carton(inner=(5, 4, 1))]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        one_box = next(p for p in plans if p['complete'] and p['box_count'] == 1)
        self.assertGreater(len({tuple(p['orientation_cm']) for p in one_box['boxes'][0]['items']}), 1)

    def test_stack_has_full_footprint_support_and_decimal_boundaries(self):
        rows = [item('wide', 2, (0.3, 0.2, 0.1)), item('small', 4, (0.1, 0.1, 0.1))]
        boxes = [carton(inner=(0.3, 0.2, 0.4))]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(any(p['complete'] and p['box_count'] == 1 for p in plans))

    def test_impossible_dimensions_are_returned_with_quantities(self):
        rows, boxes = [item('wide', 3, (5, 5, 5))], [carton(inner=(4, 4, 4))]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertEqual(plans[0]['unplaced'], [{'sku': 'wide', 'quantity': 3, 'reasons': ['DIMENSIONS_EXCEEDED']}])

    def test_tare_counts_towards_gross_weight_limit(self):
        rows, boxes = [item(quantity=3, weight=1)], [carton(tare=0.5, limit=2.5)]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(all(p['box_count'] == 2 for p in plans))
        heavy = candidates([item(weight=2.1)], boxes)
        self.assertEqual(heavy[0]['unplaced'][0]['reasons'], ['UNIT_OVERWEIGHT'])

    def test_weight_and_dimensions_must_fit_the_same_carton(self):
        rows = [item(size=(4, 4, 4), weight=3)]
        boxes = [carton('large', inner=(4, 4, 4), limit=2), carton('strong', inner=(2, 2, 2), limit=10)]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(all(not p['complete'] for p in plans))
        self.assertTrue(all(p['unplaced'][0]['reasons'] for p in plans))

    def test_rotation_can_be_disabled(self):
        boxes = [carton(inner=(2, 3, 1))]
        blocked = candidates([item(size=(3, 2, 1), rotation_allowed=False)], boxes)
        self.assertFalse(any(p['complete'] for p in blocked))
        rows = [item(size=(3, 2, 1))]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(all(p['complete'] for p in plans))

    def test_no_stack_units_reserve_their_entire_carton(self):
        rows = [item('fragile', 2, no_stack=True), item('normal', 2)]
        boxes = [carton()]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(all(p['complete'] and p['box_count'] == 3 for p in plans))

    def test_fixed_types_and_smaller_tail_carton_are_retained(self):
        rows = [item(quantity=5, weight=0)]
        boxes = [carton('small', inner=(1, 1, 1), cost='0.25'),
                 carton('large', inner=(4, 1, 1), cost='0.60')]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        type_lists = [sorted(b['carton_id'] for b in p['boxes']) for p in plans if p['complete']]
        self.assertIn(['small'] * 5, type_lists)
        self.assertIn(['large', 'large'], type_lists)
        self.assertIn(['large', 'small'], type_lists)
        self.assertEqual(len(type_lists), len({tuple(types) for types in type_lists}))

    def test_box_limit_reports_remaining_units_per_sku(self):
        rows = [item('A', 3), item('B', 2)]
        boxes = [carton(inner=(1, 1, 1))]
        plans = candidates(rows, boxes, max_boxes=2)
        self.assert_valid(plans, rows, boxes, max_boxes=2)
        self.assertEqual(plans[0]['placed_units'], 2)
        self.assertTrue(all('BOX_LIMIT_EXCEEDED' in u['reasons'] for u in plans[0]['unplaced']))

    def test_inputs_are_not_mutated_and_plan_ids_are_stable(self):
        rows, boxes = [item(quantity=3)], [carton()]
        before = copy.deepcopy((rows, boxes))
        plans = candidates(rows, boxes)
        self.assertEqual((rows, boxes), before)
        self.assertEqual(candidates(rows, boxes), plans)

    def test_changed_measurements_or_cost_do_not_reuse_a_stale_plan_id(self):
        baseline = candidates([item()], [carton()])[0]['id']
        changes = [([item(weight=2)], [carton()]),
                   ([item()], [carton(outer=(5, 5, 5))]),
                   ([item()], [carton(cost='2.00')]),
                   ([item()], [carton(limit=10)])]
        for rows, boxes in changes:
            with self.subTest(rows=rows, boxes=boxes):
                self.assertNotEqual(candidates(rows, boxes)[0]['id'], baseline)

    def test_five_hundred_units_are_accepted_without_unbounded_candidates(self):
        rows, boxes = [item(quantity=500, weight=0)], [carton(inner=(5, 1, 1))]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(any(p['complete'] and p['box_count'] == 100 for p in plans))

    def test_search_budget_exhaustion_reports_partial_results_honestly(self):
        rows = [item('fragment-' + str(i), 5,
                     (1 + i / 100, 1 + (i % 13) / 100, 1 + (i % 7) / 100), 0)
                for i in range(100)]
        boxes = [carton(inner=(20, 20, 20))]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(all(not p['complete'] and p['placed_units'] > 0 for p in plans))
        self.assertTrue(all(u['reasons'] == ['SEARCH_LIMIT_REACHED'] for p in plans for u in p['unplaced']))

    def test_decimal_mass_is_exported_without_accumulated_float_tails(self):
        rows = [item(quantity=96, weight=0.1)]
        boxes = [carton(inner=(100, 1, 1), tare=0.3, limit=9.9)]
        plans = candidates(rows, boxes)
        self.assert_valid(plans, rows, boxes)
        self.assertTrue(all(p['complete'] and p['box_count'] == 1 for p in plans))
        for plan in plans:
            self.assertEqual(str(plan['boxes'][0]['goods_weight_kg']), '9.6')
            self.assertEqual(str(plan['boxes'][0]['gross_weight_kg']), '9.9')

    def test_invalid_fields_and_nonfinite_numbers_are_rejected(self):
        invalid_items = [
            {'quantity': True}, {'quantity': 0}, {'quantity': 1.5}, {'quantity': 501},
            {'length_cm': 0}, {'width_cm': -1}, {'height_cm': float('nan')},
            {'weight_kg': float('inf')}, {'weight_kg': -0.1},
            {'rotation_allowed': 1}, {'no_stack': 'false'}, {'sku': ''},
            {'sku': 'bad\nname'}, {'unexpected': 1}, {'length_cm': '1'},
        ]
        for change in invalid_items:
            with self.subTest(change=change), self.assertRaises(ValueError):
                candidates([item(**change)], [carton()])
        invalid_cartons = [
            {'inner_cm': [1, 2]}, {'inner_cm': [1, 2, 0]}, {'outer_cm': [0.5, 4, 4]},
            {'tare_kg': -1}, {'tare_kg': float('inf')}, {'max_weight_kg': 0},
            {'packaging_cost': 'NaN'}, {'packaging_cost': '-1'}, {'packaging_cost': '1e2'},
            {'packaging_cost': 1}, {'id': ''}, {'name': ''}, {'unexpected': 1},
        ]
        for change in invalid_cartons:
            with self.subTest(change=change), self.assertRaises(ValueError):
                candidates([item()], [{**carton(), **change}])

    def test_collection_identity_and_count_limits_are_rejected(self):
        invalid = [([], [carton()], 100), ([item()], [], 100),
                   ([item(), item()], [carton()], 100),
                   ([item()], [carton(), carton()], 100),
                   ([item(str(i)) for i in range(101)], [carton()], 100),
                   ([item('A', 500), item('B')], [carton()], 100),
                   ([item()], [carton(str(i)) for i in range(13)], 100),
                   ([item()], [carton()], 0), ([item()], [carton()], 101),
                   ([item()], [carton()], True), ([item()], [carton()], 1.5)]
        for rows, boxes, maximum in invalid:
            with self.subTest(rows=len(rows), boxes=len(boxes), maximum=maximum), self.assertRaises(ValueError):
                candidates(rows, boxes, max_boxes=maximum)


if __name__ == '__main__':
    unittest.main()
