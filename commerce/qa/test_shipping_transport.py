"""Authenticated loopback and actual three-client MCP shipping round trips."""
import csv
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_paos_mcp as transport
import test_shipping_workbench as fixtures


class ShippingTransport(unittest.TestCase):
    setUpClass=classmethod(transport.AdoptionMCP.setUpClass.__func__)
    tearDownClass=classmethod(transport.AdoptionMCP.tearDownClass.__func__)
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    def test_http_import_create_export_and_authentication(self):
        template=self.call('commerce_shipping_template',{'kind':'rates'})
        raw=list(csv.DictReader(io.StringIO(template['content'].removeprefix('\ufeff'))))
        row=raw[0];row.update(origin='CN',destination='RU',valid_from='2026-01-01',valid_until='2026-12-31',currency='CNY')
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(row));writer.writeheader();writer.writerow(row)
        intake={'content':output.getvalue(),'source_ref':'synthetic:transport.csv','synthetic':True}
        preview=self.call('commerce_shipping_rates_preview',intake)
        book=self.call('commerce_shipping_rates_import',{**intake,'expected_sha256':preview['sha256']})
        payload=fixtures.ShippingTests.payload(self);payload['rate_book_id']=book['id']
        plan=self.call('commerce_shipping_plan_create',{'input':payload})
        self.assertIsNotNone(plan['variants']['cost'])
        exported=self.call('commerce_shipping_export',{'plan_id':plan['id'],'variant':'cost','format':'csv','expected_sha256':plan['sha256']})
        self.assertIn('DEMO-A',exported['content'])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.call('commerce_shipping_state',{},token='invalid-synthetic-token')
        self.assertEqual(caught.exception.code,401);caught.exception.close()

    def test_three_mcp_clients_discover_read_and_create_same_plan(self):
        plan=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                self.assertTrue(tools['commerce_shipping_export']['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_shipping_plan_create']['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_shipping_rates_import']['annotations']['openWorldHint'])
                if plan is None:
                    result=self.rpc(process,'tools/call',{'name':'commerce_shipping_plan_create','arguments':{'input':fixtures.ShippingTests.payload(self)}})['result']
                    self.assertFalse(result['isError']);plan=result['structuredContent']
                else:
                    result=self.rpc(process,'tools/call',{'name':'commerce_shipping_plan_get','arguments':{'plan_id':plan['id']}})['result']
                    self.assertFalse(result['isError']);self.assertEqual(result['structuredContent']['sha256'],plan['sha256'])
        self.assertFalse(plan['shipment_submitted'])

    def test_shipping_csv_above_legacy_body_limit_and_other_tools_stay_bounded(self):
        template=self.call('commerce_shipping_template',{'kind':'rates'})
        row=next(csv.DictReader(io.StringIO(template['content'].removeprefix('\ufeff'))))
        row.update(included_fees='X'*1000,excluded_fees='Y'*1000)
        output=io.StringIO();writer=csv.DictWriter(output,fieldnames=list(row));writer.writeheader()
        for i in range(80):writer.writerow({**row,'id':'RATE-'+str(i)})
        self.assertGreater(len(output.getvalue()),131072)
        preview=self.call('commerce_shipping_rates_preview',{'content':output.getvalue(),'source_ref':'synthetic:large.csv','synthetic':True})
        self.assertEqual(preview['rate_count'],80)
        with self.assertRaises(urllib.error.HTTPError) as caught:self.call('commerce_status',{'pad':'x'*150000})
        self.assertEqual(caught.exception.code,413);caught.exception.close()

    def test_large_readonly_comparison_keeps_buyer_groups_and_creates_no_drafts(self):
        payload=fixtures.ShippingTests.payload(self,'buyer')
        payload['items']=[{'group_id':'组'*125+f'{i//5:03}',
            'recipient_ref':'收'*125+f'{i//5:03}','sku':'货'*125+f'{i:03}',
            'quantity':1,'length_cm':10,'width_cm':10,'height_cm':10,
            'weight_kg':1,'rotation_allowed':True,'no_stack':False} for i in range(100)]
        self.assertGreater(len(json.dumps({'tool':'commerce_shipping_compare','arguments':{'input':payload}}).encode()),131072)
        before=self.call('commerce_shipping_state',{})
        result=self.call('commerce_shipping_compare',{'input':payload})
        self.assertEqual(len(result['models']),3)
        for column in result['models']:
            self.assertEqual(column['summary']['placed_units'],100)
            self.assertEqual(len(column['plan']['variants']['space']['groups']),20)
        self.assertEqual(self.call('commerce_shipping_state',{}),before)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.call('commerce_shipping_compare',{'input':payload},token='invalid-synthetic-token')
        self.assertEqual(caught.exception.code,401);caught.exception.close()

    def test_three_mcp_clients_expose_comparison_as_readonly_and_share_its_contract(self):
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                self.assertTrue(tools['commerce_shipping_compare']['annotations']['readOnlyHint'])
                result=self.rpc(process,'tools/call',{'name':'commerce_shipping_compare','arguments':{'input':fixtures.ShippingTests.payload(self)}})['result']
                self.assertFalse(result['isError']);self.assertFalse(result['structuredContent']['persisted'])
                self.assertEqual(len(result['structuredContent']['models']),3)


if __name__=='__main__':unittest.main()
