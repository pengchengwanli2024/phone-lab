"""Behavior checks for private shipping estimates and version-bound exports."""
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from shipping_workbench import ShippingWorkbench


class ShippingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(Path(self.tmp.name) / 'test.sqlite')
        self.w = ShippingWorkbench(self.core)

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, mode='warehouse'):
        return {'mode':mode,'origin':'CN','destination':'RU','ship_date':'2026-11-16',
                'packaging_currency':'CNY','rate_book_id':'','synthetic':True,
                'items':[{'group_id':'DEMO-1','recipient_ref':'RECIPIENT-A' if mode=='buyer' else '',
                          'sku':sku,'quantity':12,'length_cm':20,'width_cm':10,'height_cm':10,
                          'weight_kg':.4,'rotation_allowed':True,'no_stack':False}
                         for sku in ['DEMO-A','DEMO-B']],
                'cartons':[{'id':'large','name':'大箱','inner_cm':[60,40,40],'outer_cm':[62,42,42],
                            'tare_kg':1.2,'max_weight_kg':20,'packaging_cost':'8'},
                           {'id':'medium','name':'中箱','inner_cm':[40,30,40],'outer_cm':[42,32,42],
                            'tare_kg':.9,'max_weight_kg':20,'packaging_cost':'6'}]}

    def rates(self):
        from shipping_rates import COLUMNS
        row=dict(id='DEMO-RATE',name='演示',mode='both',origin='CN',destination='RU',currency='CNY',
                 valid_from='2026-01-01',valid_until='2026-12-31',basis='weight',divisor='5000',
                 round_step='.5',min_charge='0',unit_price='30',base_fee='0',shipment_fee='0',
                 fuel_pct='0',other_fee='0',max_weight_kg='20',max_length_cm='0',max_girth_cm='0',
                 included_fees='基础运费',excluded_fees='税费、偏远费、保险')
        s=io.StringIO();writer=csv.DictWriter(s,fieldnames=COLUMNS);writer.writeheader();writer.writerow(row)
        content=s.getvalue()
        preview=self.w.preview_rates(content,'synthetic:rates.csv',True)
        return self.w.import_rates(content,'synthetic:rates.csv',preview['sha256'],True)

    def test_missing_rates_preserve_space_but_no_cost(self):
        plan=self.w.create_plan(self.payload())
        self.assertIsNone(plan['variants']['cost'])
        self.assertTrue(plan['variants']['space']['complete'])
        self.assertEqual(plan['input_units'],24)
        self.assertFalse(plan['shipment_submitted'])
        self.assertTrue(plan['review_required'])

    def test_preview_requires_exact_source_and_content_and_persists_once(self):
        book=self.rates()
        self.assertEqual(len(self.w.state()['rate_books']),1)
        self.assertEqual(self.w.rate_book(book['id'])['sha256'],book['sha256'])
        with self.assertRaisesRegex(ValueError,'preview_changed'):
            self.w.import_rates('invalid','source','0'*64,False)

    def test_mixed_goods_cheapest_plan_and_snapshot_export_survive_restart(self):
        data=self.payload();data['rate_book_id']=self.rates()['id']
        plan=self.w.create_plan(data)
        cost=plan['variants']['cost']
        self.assertEqual(cost['box_count'],1)
        self.assertEqual(cost['total_cost'],'351.00')
        self.assertEqual({x['sku'] for x in cost['groups'][0]['boxes'][0]['items']},{'DEMO-A','DEMO-B'})
        reloaded=ShippingWorkbench(self.core).get_plan(plan['id'])
        self.assertEqual(reloaded['sha256'],plan['sha256'])
        export=self.w.export(plan['id'],'cost','csv',plan['sha256'])
        self.assertIn('DEMO-A',export['content'])
        self.assertEqual(export['plan_sha256'],plan['sha256'])
        with self.assertRaisesRegex(ValueError,'plan_changed'):
            self.w.export(plan['id'],'cost','csv','0'*64)

    def test_buyer_orders_never_share_cartons_and_conflicting_recipients_rejected(self):
        data=self.payload('buyer');data['items'][1]['group_id']='DEMO-2'
        plan=self.w.create_plan(data)
        self.assertEqual(len(plan['variants']['space']['groups']),2)
        data['items'][1]['group_id']='DEMO-1';data['items'][1]['recipient_ref']='RECIPIENT-B'
        with self.assertRaisesRegex(ValueError,'recipient_conflict'):
            self.w.create_plan(data)

    def test_plan_rejects_invalid_modes_missing_recipient_and_excessive_units(self):
        for mutate in [lambda d:d.update(mode='unknown'),
                       lambda d:d['items'][0].update(quantity=501),
                       lambda d:d['items'][0].update(weight_kg=float('nan'))]:
            data=self.payload();mutate(data)
            with self.assertRaises(ValueError):self.w.create_plan(data)
        data=self.payload('buyer');data['items'][0]['recipient_ref']=''
        with self.assertRaisesRegex(ValueError,'recipient'):
            self.w.create_plan(data)

    def test_safe_csv_and_html_exports_retain_quantities_and_coordinates(self):
        data=self.payload();data['items'][0]['sku']='=DANGEROUS()';data['cartons'][0]['name']='<img src=x onerror=alert(1)>'
        plan=self.w.create_plan(data)
        output=self.w.export(plan['id'],'space','csv',plan['sha256'])
        rows=list(csv.reader(io.StringIO(output['content'])))
        self.assertTrue(any("'=DANGEROUS()" in cell for row in rows for cell in row))
        html=self.w.export(plan['id'],'space','html',plan['sha256'])['content']
        self.assertNotIn('<img src=x',html)
        self.assertIn('DEMO-B',html)

    def test_csv_intake_produces_values_that_can_be_calculated_directly(self):
        data=self.payload()
        for kind in ('items','cartons'):
            template=self.w.template(kind)
            data[kind]=self.w.preview_input(kind,template['content'])['rows']
        plan=self.w.create_plan(data)
        self.assertTrue(plan['variants']['space']['complete'])
        self.assertEqual(plan['input_units'],20)

    def test_packaging_cost_rounds_per_box_without_a_tariff(self):
        data=self.payload()
        data['items']=data['items'][:1];data['items'][0]['quantity']=2
        data['cartons']=[{'id':'one','name':'一件箱','inner_cm':[20,10,10],'outer_cm':[22,12,12],
                         'tare_kg':.1,'max_weight_kg':1,'packaging_cost':'1.005'}]
        result=self.w.create_plan(data)
        self.assertEqual(result['variants']['space']['packaging_cost'],'2.02')


if __name__=='__main__':unittest.main()
