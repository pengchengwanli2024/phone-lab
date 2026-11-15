"""Synthetic behavior checks for review evidence and bounded packing estimates."""
from itertools import combinations
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class Adoption(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def reviews(self, rows, key, origin='private-export:synthetic-reviews'):
        doc = self.app.business.template('reviews')['document']
        doc.update(records=rows, origin_ref=origin)
        return self.app.invoke('commerce_business_import', {
            'document': doc, 'idempotency_key': key})['source_id']

    def analyze(self, ids, key='analysis'):
        return self.app.invoke('commerce_business_analyze', {
            'source_ids': ids, 'idempotency_key': key})

    def test_reviews_deduplicate_overlapping_batches_and_preserve_evidence(self):
        row = {'id': 'synthetic-r1', 'text': '包装破损，尺寸不适用', 'rating': 1}
        a = self.reviews([row], 'a')
        b = self.reviews([row, {'id': 'synthetic-r2', 'text': '普通评论', 'rating': None}], 'b')
        result = self.analyze([a, b])
        content = result['draft']['content']
        self.assertEqual(content['input_records'], 3)
        self.assertEqual(content['total_records'], 2)
        self.assertEqual(content['duplicate_records'], 1)
        self.assertEqual(content['rating_counts']['1'], 1)
        self.assertEqual(content['missing_rating'], 1)
        self.assertTrue(content['sample_insufficient'])
        self.assertIn('不足20', content['notice'])
        evidence = content['topics'][0]['evidence'][0]
        self.assertIn(evidence['source_id'], [a, b])
        self.assertEqual(evidence['record_id'], row['id'])
        self.assertEqual(content['pain_points']['count'], 1)
        exported = json.loads(self.app.invoke('commerce_business_export', {'draft_id': result['id']})['content'])
        self.assertEqual(len(exported['sources']), 2)
        self.assertFalse(result['external_execution_allowed'])
        self.assertEqual(self.analyze([a, b]), result)
        self.assertEqual(Commerce(self.tmp.name).business.get(result['id'])['draft'], result['draft'])

    def test_duplicate_identity_conflicts_reject_without_saving_analysis(self):
        a = self.reviews([{'id': 'r1', 'text': '质量好', 'rating': 5}], 'a')
        b = self.reviews([{'id': 'r1', 'text': '质量差', 'rating': 1}], 'b')
        with self.app.core.db() as db:
            before = db.execute('SELECT count(*) FROM business_drafts').fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'business_review_identity_conflict'):
            self.analyze([a, b])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM business_drafts').fetchone()[0], before)
        c = self.reviews([{'id': 'r1', 'text': '质量差', 'rating': 1}], 'c', 'private-export:other-source')
        self.assertEqual(self.analyze([a, c])['draft']['content']['total_records'], 2)

    def test_multilingual_topics_and_known_rating_denominators(self):
        rows = [
            {'id': 'zh', 'text': '安装困难，材质有气味', 'rating': None},
            {'id': 'ru', 'text': 'Сборка сложная, неприятный запах материала', 'rating': 2},
            {'id': 'en', 'text': 'Assembly is easy and the material feels good', 'rating': 5},
            {'id': 'unmatched', 'text': 'business profit catalogue', 'rating': None},
        ]
        content = self.analyze([self.reviews(rows, 'rows')])['draft']['content']
        topics = {t['label']: t for t in content['topics']}
        self.assertEqual(topics['安装与装配']['count'], 3)
        self.assertEqual(topics['材质与气味']['count'], 3)
        self.assertEqual(topics['安装与装配']['rated_count'], 2)
        self.assertEqual(topics['安装与装配']['average_rating'], 3.5)
        self.assertEqual(content['unmatched'], 1)
        self.assertFalse(self.analyze([self.reviews(rows, 'second')], 'second-analysis')['preflight']['semantic_accuracy_verified'])

    def test_sample_threshold_uses_unique_reviews(self):
        rows = [{'id': str(i), 'text': '质量好', 'rating': 5} for i in range(20)]
        a = self.reviews(rows, 'a')
        b = self.reviews(rows, 'b')
        content = self.analyze([a, b])['draft']['content']
        self.assertFalse(content['sample_insufficient'])
        self.assertEqual(content['total_records'], 20)
        self.assertEqual(content['duplicate_records'], 20)
        self.assertIn('不代表', content['notice'])

    @staticmethod
    def payload(**item_changes):
        return {'container': {'length_cm': 10, 'width_cm': 10, 'height_cm': 10, 'max_weight_kg': 5},
                'items': [{'sku': 'SYNTHETIC-A', 'length_cm': 5, 'width_cm': 5, 'height_cm': 5,
                           'weight_kg': 1, 'quantity': 8, **item_changes}]}

    def pack(self, data):
        return self.app.invoke('commerce_packing_estimate', {'input': data})

    def assert_geometry(self, result, data):
        container = data['container']
        for box in result['boxes']:
            self.assertLessEqual(box['total_weight_kg'], container['max_weight_kg'])
            for item in box['items']:
                for start, length, bound in zip(item['position_cm'], item['orientation_cm'],
                        [container['length_cm'], container['width_cm'], container['height_cm']]):
                    self.assertGreaterEqual(start, 0)
                    self.assertLessEqual(start + length, bound + 1e-9)
            for a, b in combinations(box['items'], 2):
                self.assertTrue(any(a['position_cm'][i] + a['orientation_cm'][i] <= b['position_cm'][i] + 1e-9 or
                                    b['position_cm'][i] + b['orientation_cm'][i] <= a['position_cm'][i] + 1e-9
                                    for i in range(3)), 'packing boxes overlap')

    def test_packing_weight_volume_and_positions(self):
        data = self.payload()
        result = self.pack(data)
        self.assertEqual(result['status'], 'ESTIMATED')
        self.assertEqual(result['placed_units'], 8)
        self.assertEqual(result['box_count'], 2)
        self.assertEqual(sum(len(b['items']) for b in result['boxes']), 8)
        self.assertTrue(result['review_required'])
        self.assertFalse(result['marketplace_writes'])
        self.assert_geometry(result, data)
        data['container']['max_weight_kg'] = 10
        result = self.pack(data)
        self.assertEqual(result['box_count'], 1)
        self.assertEqual(result['boxes'][0]['volume_utilization_pct'], 100)

    def test_oversize_and_overweight_never_allocate_a_box(self):
        for changes, reason in [({'weight_kg': 6}, 'UNIT_OVERWEIGHT'),
                                ({'length_cm': 11}, 'DIMENSIONS_EXCEEDED')]:
            with self.subTest(changes=changes):
                result = self.pack(self.payload(**changes))
                self.assertEqual(result['status'], 'NO_FIT')
                self.assertEqual(result['box_count'], 0)
                self.assertEqual(result['unplaced_units'], 8)
                self.assertIn(reason, result['unplaced'][0]['reasons'])

    def test_rotation_box_limit_and_no_stack_are_explicit(self):
        data = self.payload(length_cm=8, width_cm=4, height_cm=6, quantity=1)
        data['container'].update(length_cm=6, width_cm=8, height_cm=4)
        self.assertEqual(self.pack(data)['placed_units'], 1)
        data['items'][0]['rotation_allowed'] = False
        self.assertEqual(self.pack(data)['placed_units'], 0)
        data = self.payload(no_stack=True, quantity=2)
        data['items'].append({**data['items'][0], 'sku': 'SYNTHETIC-B', 'quantity': 1, 'no_stack': False})
        result = self.pack(data)
        self.assertEqual(result['box_count'], 3)
        self.assert_geometry(result, data)
        data['max_boxes'] = 1
        result = self.pack(data)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual(result['unplaced_units'], 2)
        self.assertIn('BOX_LIMIT_EXCEEDED', result['unplaced'][0]['reasons'])

    def test_packing_rejects_nonfinite_bool_missing_and_excessive_inputs(self):
        for field, value in [('length_cm', 0), ('width_cm', True), ('weight_kg', float('nan')),
                             ('quantity', 501), ('quantity', 1.5), ('rotation_allowed', 'yes')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.pack(self.payload(**{field: value}))
        for bad in [{}, {**self.payload(), 'extra': 1}, {**self.payload(), 'max_boxes': True}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.pack(bad)
        data = self.payload(quantity=300)
        data['items'].append({**data['items'][0], 'sku': 'SYNTHETIC-B'})
        with self.assertRaisesRegex(ValueError, 'packing_unit_limit'):
            self.pack(data)

    def test_mixed_geometry_and_fractional_weight_stays_feasible(self):
        data = self.payload(quantity=20, length_cm=3.3, width_cm=2.1, height_cm=1.7, weight_kg=0.3)
        data['container']['max_weight_kg'] = 0.9
        data['items'].append({**data['items'][0], 'sku': 'SYNTHETIC-B', 'quantity': 12, 'height_cm': 2.5})
        result = self.pack(data)
        self.assertEqual(result['placed_units'], 32)
        self.assert_geometry(result, data)


if __name__ == '__main__':
    unittest.main()
