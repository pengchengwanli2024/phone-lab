"""Model selection, unknown cost and container admission boundary checks."""
import copy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from shipping_packing import candidates
from shipping_workbench import CARTON_COLUMNS, MODEL_COLUMNS, ShippingWorkbench


def model(**updates):
    return {'id': 'custom-container', 'name': 'Custom container', 'kind': 'container',
            'model_id': 'custom', 'inner_cm': [20, 10, 10], 'outer_cm': [22, 12, 12],
            'tare_kg': 1, 'max_weight_kg': 20, 'packaging_cost': '',
            'door_cm': [6, 8], **updates}


def goods(**updates):
    return {'sku': 'A', 'quantity': 1, 'length_cm': 8, 'width_cm': 7,
            'height_cm': 5, 'weight_kg': 1, 'rotation_allowed': True, **updates}


class ShippingModelTests(unittest.TestCase):
    def api(self):
        try:
            import shipping_models
        except ModuleNotFoundError as exc:
            if exc.name != 'shipping_models':
                raise
            self.fail('The reusable physical model catalog is not implemented')
        return shipping_models

    def test_preset_selection_returns_independent_editable_rows_without_prices(self):
        api = self.api()
        catalog = api.model_catalog()
        self.assertEqual(catalog['units'], {'length': 'cm', 'weight': 'kg'})
        self.assertTrue(catalog['editable'])
        self.assertEqual({r['id'] for r in catalog['models']}, {
            'carton-s', 'carton-m', 'carton-l',
            'container-20gp', 'container-40gp', 'container-40hq'})
        for entry in catalog['models']:
            row = api.model_payload(entry['id'])
            self.assertEqual(row['packaging_cost'], '')
            self.assertEqual(row['model_id'], entry['id'])
            result = candidates([goods(length_cm=1, width_cm=1, height_cm=1)], [row])
            self.assertTrue(result[0]['complete'])
            if row['kind'] == 'container':
                self.assertEqual(row['reference']['status'], 'reference')
                self.assertTrue(all(u.startswith('https://www.hapag-lloyd.com/') for u in row['reference']['source_urls']))
            else:
                self.assertEqual(row['reference']['status'], 'illustrative')
        catalog['models'][0]['inner_cm'][0] = 1
        self.assertEqual(api.model_payload('carton-s')['inner_cm'], [30, 20, 20])

    def test_customizing_preset_preserves_source_and_marks_changed_physical_values(self):
        api = self.api()
        changed = api.model_payload('container-20gp', {'inner_cm': [580, 235.2, 239.5]})
        self.assertEqual(changed['reference']['status'], 'customized_reference')
        self.assertIn('https://www.hapag-lloyd.com/en/services-information/cargo-fleet/container/20-standard.html', changed['reference']['source_urls'])
        self.assertEqual(api.model_payload('container-20gp')['inner_cm'], [590, 235.2, 239.5])
        priced = api.model_payload('container-20gp', {'packaging_cost': '12'})
        self.assertEqual(priced['reference']['status'], 'reference')

    def test_metadata_and_unknown_cost_survive_solver_output(self):
        row = model(reference={'status': 'custom', 'source_name': 'User measurements',
                               'source_urls': [], 'checked_on': '2026-11-16', 'note': ''})
        original = copy.deepcopy(row)
        try:
            plans = candidates([goods()], [row])
        except ValueError as exc:
            self.fail(f'The solver rejected a model with unknown packaging cost: {exc}')
        box = plans[0]['boxes'][0]
        self.assertEqual(box['kind'], 'container')
        self.assertEqual(box['model_id'], 'custom')
        self.assertEqual(box['reference']['source_name'], 'User measurements')
        self.assertEqual(box['door_cm'], [6, 8])
        self.assertEqual(box['max_weight_kg'], 20)
        self.assertEqual(box['packaging_cost'], '')
        self.assertEqual(row, original)

    def test_candidate_metadata_cannot_mutate_other_candidate_snapshots(self):
        first = model(id='first', packaging_cost='1',
                      reference={'status': 'custom', 'source_name': 'Original', 'source_urls': []})
        second = model(id='second', inner_cm=[30, 10, 10], outer_cm=[32, 12, 12],
                       packaging_cost='2')
        plans = candidates([goods(quantity=2, no_stack=True)], [first, second])
        outputs = [box for plan in plans for box in plan['boxes'] if box['carton_id'] == 'first']
        self.assertGreaterEqual(len(outputs), 2)
        outputs[0]['reference']['source_name'] = 'Edited output'
        self.assertEqual(outputs[1]['reference']['source_name'], 'Original')

    def test_container_admission_checks_door_in_actual_placement_orientation(self):
        row = model(packaging_cost='0')
        try:
            rejected = candidates([goods(rotation_allowed=False)], [row])[0]
        except ValueError as exc:
            self.fail(f'Container door admission is not implemented: {exc}')
        self.assertFalse(rejected['complete'])
        self.assertEqual(rejected['unplaced'][0]['reasons'], ['DOOR_OPENING_EXCEEDED'])
        admitted = candidates([goods()], [row])[0]
        self.assertTrue(admitted['complete'])
        placed = admitted['boxes'][0]['items'][0]['orientation_cm']
        self.assertLessEqual(placed[1], 6)
        self.assertLessEqual(placed[2], 8)

    def test_extended_model_fields_are_strictly_validated(self):
        api = self.api()
        mutations = [
            {'kind': 'ship'}, {'model_id': ''}, {'door_cm': [11, 8]},
            {'door_cm': [6, True]}, {'door_cm': [6]}, {'unknown': 1},
            {'reference': {'status': 'verified'}},
            {'reference': {'status': 'custom', 'source_name': 'x', 'source_urls': ['javascript:alert(1)']}},
            {'packaging_cost': None}, {'packaging_cost': '-1'},
        ]
        for updates in mutations:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                api.normalize_model(model(**updates))


class ShippingModelWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(Path(self.tmp.name) / 'test.sqlite')
        self.w = ShippingWorkbench(self.core)

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self):
        return {'mode': 'warehouse', 'origin': 'CN', 'destination': 'RU',
                'ship_date': '2026-11-16', 'packaging_currency': 'CNY', 'synthetic': True,
                'items': [{'group_id': 'BATCH', 'recipient_ref': '', **goods()}],
                'cartons': [model()]}

    def test_state_exposes_editable_model_catalog(self):
        self.assertIn('model_catalog', self.w.state())
        self.assertEqual(len(self.w.state()['model_catalog']['models']), 6)

    def test_unknown_packaging_cost_keeps_geometry_and_prevents_total_cost_claim(self):
        data = self.payload()
        content = self.w.template('rates')['content']
        preview = self.w.preview_rates(content, 'synthetic:rates', True)
        data['origin'] = '示例发货地'; data['destination'] = '示例目的地'
        data['rate_book_id'] = self.w.import_rates(content, 'synthetic:rates', preview['sha256'], True)['id']
        try:
            plan = self.w.create_plan(data)
        except ValueError as exc:
            self.fail(f'Unknown packaging cost must preserve the space plan: {exc}')
        self.assertTrue(plan['variants']['space']['complete'])
        self.assertIsNone(plan['variants']['space']['packaging_cost'])
        self.assertIsNone(plan['variants']['cost'])
        self.assertIsNone(plan['variants']['space']['total_cost'])
        data['cartons'][0]['packaging_cost'] = '0'
        confirmed = self.w.create_plan(data)
        self.assertIsNotNone(confirmed['variants']['cost'])
        self.assertEqual(confirmed['variants']['cost']['packaging_cost'], '0.00')

    def test_models_and_references_survive_history_json_and_csv(self):
        data = self.payload()
        data['cartons'][0]['reference'] = {'status': 'custom', 'source_name': 'Measured', 'source_urls': []}
        try:
            plan = self.w.create_plan(data)
        except ValueError as exc:
            self.fail(f'Model metadata is not accepted by the workbench: {exc}')
        restored = ShippingWorkbench(self.core).get_plan(plan['id'])
        box = restored['variants']['space']['groups'][0]['boxes'][0]
        self.assertEqual(box['reference']['source_name'], 'Measured')
        exported = self.w.export(plan['id'], 'space', 'json', plan['sha256'])
        self.assertEqual(json.loads(exported['content'])['plan']['input']['cartons'], data['cartons'])
        content = self.w.export(plan['id'], 'space', 'csv', plan['sha256'])['content'].removeprefix('\ufeff')
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(rows[0]['model_kind'], 'container')
        self.assertEqual(rows[0]['model_id'], 'custom')
        self.assertEqual(rows[0]['door_width_cm'], '6.0')
        self.assertEqual(json.loads(rows[0]['model_reference_json'])['source_name'], 'Measured')

    def test_legacy_carton_csv_and_extended_model_csv_are_both_accepted(self):
        legacy = self.w.template('cartons')['content']
        self.assertEqual(len(self.w.preview_input('cartons', legacy)['rows']), 2)
        columns = CARTON_COLUMNS + ['kind', 'model_id', 'door_width_cm', 'door_height_cm', 'reference_json']
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerow(['CUSTOM', 'Container', 20, 10, 10, 22, 12, 12, 1, 20, '',
                         'container', 'custom', 6, 8,
                         json.dumps({'status': 'custom', 'source_name': 'Measured', 'source_urls': []})])
        try:
            parsed = self.w.preview_input('cartons', stream.getvalue())['rows']
        except ValueError as exc:
            self.fail(f'Extended model CSV is not accepted: {exc}')
        self.assertEqual(parsed[0]['door_cm'], [6, 8])
        data = self.payload(); data['cartons'] = parsed
        self.assertTrue(self.w.create_plan(data)['variants']['space']['complete'])

    def test_models_template_roundtrips_reference_rows_without_inventing_costs(self):
        try:
            template = self.w.template('models')
        except ValueError as exc:
            self.fail(f'The editable model CSV template is missing: {exc}')
        cells = list(csv.reader(io.StringIO(template['content'].removeprefix('\ufeff'))))
        self.assertEqual(cells[0], MODEL_COLUMNS)
        self.assertTrue(template['synthetic'])
        parsed = self.w.preview_input('cartons', template['content'])['rows']
        self.assertEqual({row['kind'] for row in parsed}, {'carton', 'container'})
        self.assertTrue(all(row['packaging_cost'] == '' for row in parsed))
        container = next(row for row in parsed if row['kind'] == 'container')
        self.assertEqual(container['model_id'], 'container-20gp')
        self.assertEqual(container['door_cm'], [234, 229.2])
        self.assertEqual(container['reference']['status'], 'reference')
        self.assertIn('https://www.hapag-lloyd.com/en/services-information/cargo-fleet/container/20-standard.html', container['reference']['source_urls'])
        data = self.payload(); data['cartons'] = parsed
        self.assertTrue(self.w.create_plan(data)['variants']['space']['complete'])
        legacy = self.w.template('cartons')['content'].removeprefix('\ufeff')
        self.assertEqual(next(csv.reader(io.StringIO(legacy))), CARTON_COLUMNS)

    def test_registered_template_tool_accepts_models_and_intake_keeps_cartons_kind(self):
        from service import Commerce
        service = Commerce(Path(self.tmp.name) / 'registered-tools')
        try:
            template = service.invoke('commerce_shipping_template', {'kind': 'models'}, client='test')
        except ValueError as exc:
            self.fail(f'The registered tool schema still rejects models templates: {exc}')
        parsed = service.invoke('commerce_shipping_input_preview',
                                {'kind': 'cartons', 'content': template['content']}, client='test')
        self.assertEqual(parsed['kind'], 'cartons')
        self.assertEqual(parsed['row_count'], 2)
        with self.assertRaises(ValueError):
            service.invoke('commerce_shipping_template', {'kind': 'unsupported'}, client='test')


if __name__ == '__main__':
    unittest.main()
