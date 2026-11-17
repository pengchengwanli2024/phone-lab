"""Read-only container comparisons using real packing, tariffs and SQLite."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from shipping_models import model_payload
from shipping_rates import COLUMNS
from shipping_workbench import READ_ONLY, ShippingWorkbench, definitions


MODEL_IDS = ('container-20gp', 'container-40gp', 'container-40hq')


class ShippingCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(Path(self.tmp.name) / 'compare.sqlite')
        self.workbench = ShippingWorkbench(self.core)

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, mode='warehouse'):
        return {'mode':mode, 'origin':'CN', 'destination':'RU', 'ship_date':'2026-11-16',
                'packaging_currency':'CNY', 'synthetic':True,
                'items':[{'group_id':'ORDER-A', 'recipient_ref':'RECIPIENT-A' if mode == 'buyer' else '',
                          'sku':'DEMO-A', 'quantity':5, 'length_cm':10, 'width_cm':10,
                          'height_cm':10, 'weight_kg':1, 'rotation_allowed':False, 'no_stack':False}],
                'cartons':[model_payload(ident, {'id':'edited-'+str(i), 'name':'Edited '+ident,
                            'inner_cm':[length,10,10], 'outer_cm':[length+2,12,12],
                            'door_cm':[10,10], 'tare_kg':1, 'max_weight_kg':100,
                            'packaging_cost':'2'})
                           for i,(ident,length) in enumerate(zip(MODEL_IDS,(20,30,40)))]}

    def rate_book(self, **overrides):
        row=dict(id='DEMO-RATE', name='Synthetic', mode='both', origin='CN', destination='RU',
                 currency='CNY', valid_from='2026-01-01', valid_until='2026-12-31',
                 basis='weight', divisor='0', round_step='1', min_charge='0', unit_price='10',
                 base_fee='0', shipment_fee='5', fuel_pct='0', other_fee='0',
                 max_weight_kg='0', max_length_cm='0', max_girth_cm='0',
                 included_fees='基础运费', excluded_fees='税费待核实') | overrides
        stream=io.StringIO(); writer=csv.DictWriter(stream,fieldnames=COLUMNS)
        writer.writeheader(); writer.writerow(row); content=stream.getvalue()
        preview=self.workbench.preview_rates(content,'synthetic:compare.csv',True)
        return self.workbench.import_rates(content,'synthetic:compare.csv',preview['sha256'],True)

    def compare(self, data):
        self.assertIn('commerce_shipping_compare',READ_ONLY,'Comparison must be available as a read-only API')
        return self.workbench.invoke('commerce_shipping_compare', {'input':data})

    def counts(self):
        with self.core.db() as db:
            return tuple(db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                         for table in ('shipping_plans','shipping_rate_books'))

    def test_comparison_is_registered_read_only_and_never_persists_repeated_previews(self):
        data=self.payload(); data['rate_book_id']=self.rate_book()['id']
        saved=self.workbench.create_plan(data)
        self.assertEqual(self.counts(),(1,1))
        before=deepcopy(data)
        first=self.compare(data); second=self.compare(data)
        self.assertEqual(self.counts(),(1,1))
        self.assertEqual(data,before)
        self.assertEqual(first['input_sha256'],second['input_sha256'])
        self.assertFalse(first['persisted'])
        self.assertTrue(first['synthetic'])
        self.assertIn('commerce_shipping_compare',READ_ONLY)
        tools=definitions(lambda *args:args)
        self.assertIn('commerce_shipping_compare',[row[0] for row in tools])
        for column in first['models']:
            self.assertFalse(column['plan']['persisted'])
            with self.assertRaisesRegex(ValueError,'shipping_plan_not_found'):
                self.workbench.get_plan(column['plan']['id'])
        self.assertEqual(self.workbench.get_plan(saved['id'])['sha256'],saved['sha256'])

    def test_three_models_independently_pack_all_goods_and_report_literal_costs_and_utilization(self):
        data=self.payload(); data['rate_book_id']=self.rate_book()['id']
        columns=self.compare(data)['models']
        self.assertEqual([row['model_id'] for row in columns],list(MODEL_IDS))
        for row,expected in zip(columns,((3,6000,83.3333333333,'85.00','6.00','91.00'),
                                         (2,6000,83.3333333333,'75.00','4.00','79.00'),
                                         (2,8000,62.5,'75.00','4.00','79.00'))):
            summary=row['summary']; count,capacity,utilization,shipping,packaging,total=expected
            self.assertEqual(row['status'],'ready')
            self.assertEqual(row['selected_variant'],'cost')
            self.assertEqual(summary['box_count'],count)
            self.assertEqual(summary['placed_units'],5)
            self.assertEqual(summary['unplaced_units'],0)
            self.assertEqual(summary['cargo_volume_cm3'],5000)
            self.assertEqual(summary['capacity_volume_cm3'],capacity)
            self.assertAlmostEqual(summary['volume_utilization_pct'],utilization,places=6)
            self.assertEqual((summary['shipping_cost'],summary['packaging_cost'],summary['total_cost']),
                             (shipping,packaging,total))
            self.assertEqual(summary['currency'],'CNY')
            self.assertTrue(summary['complete'])
            self.assertEqual(row['plan']['input']['items'],data['items'])
            self.assertEqual(len(row['plan']['input']['cartons']),1)
            boxes=row['plan']['variants']['cost']['groups'][0]['boxes']
            self.assertEqual(sum(len(box['items']) for box in boxes),5)
            self.assertEqual({box['model_id'] for box in boxes},{row['model_id']})

    def test_missing_rates_and_blank_packaging_cost_never_invent_zero_total(self):
        for with_rate in (False,True):
            data=self.payload()
            if with_rate:data['rate_book_id']=self.rate_book()['id']
            for model in data['cartons']:model['packaging_cost']=''
            for row in self.compare(data)['models']:
                self.assertEqual(row['status'],'ready')
                self.assertEqual(row['selected_variant'],'space')
                self.assertTrue(row['summary']['complete'])
                for key in ('shipping_cost','packaging_cost','total_cost'):
                    self.assertIsNone(row['summary'][key])

    def test_missing_model_uses_canonical_reference_with_unknown_packaging(self):
        data=self.payload(); data['cartons']=data['cartons'][:1]
        rows=self.compare(data)['models']
        self.assertEqual(rows[0]['model']['inner_cm'],[20,10,10])
        self.assertEqual(rows[1]['model']['inner_cm'],[1203.2,235.2,239.5])
        self.assertEqual(rows[2]['model']['inner_cm'],[1203.2,235,270])
        self.assertEqual(rows[1]['model']['packaging_cost'],'')
        self.assertIsNone(rows[1]['summary']['total_cost'])
        self.assertEqual(rows[1]['summary']['placed_units'],5)
        self.assertEqual(self.counts(),(0,0))

    def test_edited_physical_model_and_legacy_id_match_survive_comparison(self):
        data=self.payload(); data['cartons'][0].pop('model_id'); data['cartons'][0]['id']=MODEL_IDS[0]
        row=self.compare(data)['models'][0]
        self.assertEqual(row['model']['inner_cm'],[20,10,10])
        self.assertEqual(row['plan']['input']['cartons'][0]['inner_cm'],[20,10,10])
        self.assertEqual(row['summary']['box_count'],3)
        self.assertEqual(row['model']['reference']['status'],'customized_reference')

    def test_empty_model_selection_uses_three_references_with_independent_snapshots(self):
        data=self.payload(); data['cartons']=[]
        result=self.compare(data)
        self.assertEqual([row['summary']['placed_units'] for row in result['models']],[5,5,5])
        self.assertEqual([row['model']['packaging_cost'] for row in result['models']],['','',''])
        result['models'][0]['plan']['input']['items'][0]['quantity']=99
        result['models'][0]['model']['inner_cm'][0]=1
        self.assertEqual(data['items'][0]['quantity'],5)
        self.assertEqual(data['cartons'],[])
        self.assertEqual(result['models'][1]['plan']['input']['items'][0]['quantity'],5)
        self.assertEqual(result['models'][0]['plan']['input']['cartons'][0]['inner_cm'][0],590)

    def test_duplicate_model_match_errors_that_column_instead_of_using_first(self):
        data=self.payload(); duplicate=deepcopy(data['cartons'][0]); duplicate['id']='other-copy'
        data['cartons'].append(duplicate)
        result=self.compare(data)
        self.assertEqual(result['models'][0]['status'],'error')
        self.assertIn('duplicate',result['models'][0]['error'])
        self.assertIsNone(result['models'][0]['plan'])
        self.assertIsNone(result['models'][0]['summary']['total_cost'])
        self.assertEqual([row['status'] for row in result['models'][1:]],['ready','ready'])

    def test_no_fit_door_and_weight_failures_retain_reasons_and_unknown_costs(self):
        for mutation,reason in (({'door_cm':[9,10]},'DOOR_OPENING_EXCEEDED'),
                                ({'max_weight_kg':1},'UNIT_OVERWEIGHT'),
                                ({'inner_cm':[9,10,10],'door_cm':[10,10]},'DIMENSIONS_EXCEEDED')):
            data=self.payload(); data['rate_book_id']=self.rate_book()['id']
            data['cartons'][0].update(mutation)
            row=self.compare(data)['models'][0]
            self.assertEqual(row['status'],'ready')
            self.assertFalse(row['summary']['complete'])
            self.assertEqual(row['summary']['placed_units'],0)
            self.assertEqual(row['summary']['unplaced_units'],5)
            self.assertIsNone(row['summary']['volume_utilization_pct'])
            self.assertEqual(row['summary']['capacity_volume_cm3'],0)
            self.assertEqual(row['summary']['cargo_volume_cm3'],0)
            missing=row['plan']['variants']['space']['groups'][0]['unplaced']
            self.assertIn(reason,missing[0]['reasons'])
            for key in ('shipping_cost','packaging_cost','total_cost'):
                self.assertIsNone(row['summary'][key])

    def test_partial_plan_keeps_placed_geometry_but_no_misleading_full_order_cost(self):
        data=self.payload(); data['rate_book_id']=self.rate_book()['id']
        oversized=deepcopy(data['items'][0]); oversized.update(sku='OVERSIZED',quantity=1,length_cm=50)
        data['items'].append(oversized)
        row=self.compare(data)['models'][0]
        self.assertEqual(row['summary']['placed_units'],5)
        self.assertEqual(row['summary']['unplaced_units'],1)
        self.assertEqual(row['summary']['box_count'],3)
        self.assertEqual(row['summary']['cargo_volume_cm3'],5000)
        self.assertAlmostEqual(row['summary']['volume_utilization_pct'],83.3333333333,places=6)
        self.assertEqual(len(row['plan']['variants']['space']['groups'][0]['boxes']),3)
        for key in ('shipping_cost','packaging_cost','total_cost'):
            self.assertIsNone(row['summary'][key])

    def test_buyer_orders_remain_separate_in_each_model(self):
        data=self.payload('buyer'); data['items'][0]['quantity']=1
        other=deepcopy(data['items'][0]); other.update(group_id='ORDER-B',recipient_ref='RECIPIENT-B')
        data['items'].append(other)
        for row in self.compare(data)['models']:
            self.assertEqual(row['summary']['box_count'],2)
            groups=row['plan']['variants'][row['selected_variant']]['groups']
            self.assertEqual([(group['group_id'],group['recipient_ref']) for group in groups],
                             [('ORDER-A','RECIPIENT-A'),('ORDER-B','RECIPIENT-B')])
            self.assertEqual([group['placed_units'] for group in groups],[1,1])

    def test_tariff_route_currency_date_and_weight_filters_are_preserved(self):
        for overrides in ({'destination':'OTHER'}, {'currency':'USD'},
                          {'valid_until':'2026-11-15'}, {'max_weight_kg':'1'}):
            data=self.payload(); data['rate_book_id']=self.rate_book(**overrides)['id']
            for row in self.compare(data)['models']:
                self.assertIsNone(row['summary']['shipping_cost'])
                self.assertIsNone(row['summary']['total_cost'])
                self.assertEqual(row['selected_variant'],'space')
                self.assertTrue(row['summary']['complete'])

    def test_input_changes_recompute_quantity_geometry_and_quote(self):
        data=self.payload(); data['rate_book_id']=self.rate_book()['id']
        first=self.compare(data)
        data['items'][0]['quantity']=1; data['items'][0]['length_cm']=5
        second=self.compare(data)
        self.assertNotEqual(first['input_sha256'],second['input_sha256'])
        self.assertEqual(second['models'][0]['summary']['box_count'],1)
        self.assertEqual(second['models'][0]['summary']['cargo_volume_cm3'],500)
        self.assertEqual(second['models'][0]['summary']['total_cost'],'27.00')
        data['rate_book_id']=self.rate_book(unit_price='20')['id']
        third=self.compare(data)
        self.assertEqual(third['models'][0]['summary']['total_cost'],'47.00')
        self.assertEqual(self.counts(),(0,2))

    def test_preview_can_be_explicitly_saved_and_exported_through_existing_immutable_contract(self):
        data=self.payload(); data['rate_book_id']=self.rate_book()['id']
        column=self.compare(data)['models'][1]
        saved=self.workbench.create_plan(column['plan']['input'])
        self.assertNotIn('persisted',saved)
        self.assertEqual(self.counts(),(1,1))
        exported=self.workbench.export(saved['id'],column['selected_variant'],'json',saved['sha256'])
        document=json.loads(exported['content'])
        self.assertEqual(document['plan']['variants']['cost']['total_cost'],'79.00')
        self.assertEqual(document['selected_variant'],'cost')
        self.assertEqual(self.workbench.get_plan(saved['id']),saved)

    def test_malformed_common_input_is_rejected_before_column_work(self):
        for mutate in (lambda data:data.update(mode='invalid'),
                       lambda data:data.update(items=[]),
                       lambda data:data.update(cartons='invalid'),
                       lambda data:data.update(cartons=[{}]*13),
                       lambda data:data['items'][0].update(quantity=501),
                       lambda data:data['items'][0].update(length_cm=0),
                       lambda data:data['items'][0].update(length_cm=10**400),
                       lambda data:data.update(extra='not allowed')):
            data=self.payload(); mutate(data)
            with self.assertRaises(ValueError):self.compare(data)
        self.assertEqual(self.counts(),(0,0))


if __name__ == '__main__':unittest.main()
