"""Real shared HTTP and three stdio clients, without upstream metadata calls."""
import unittest
import test_business_completion_mcp as transport


class ListingSchemaTransport(unittest.TestCase):
    call=classmethod(transport.BusinessMCP.call.__func__)
    mcp=transport.BusinessMCP.mcp
    rpc=transport.BusinessMCP.rpc
    setUpClass=classmethod(transport.BusinessMCP.setUpClass.__func__)
    tearDownClass=classmethod(transport.BusinessMCP.tearDownClass.__func__)

    def test_all_clients_discover_local_schema_and_cannot_write_a_marketplace(self):
        target=dict(case_id=self.cid,platform='ozon',store_ref='ozon-live',market='RU');values=[]
        for client in ('codex','hermes','harness'):
            with self.mcp(client)as proc:
                tools={t['name']:t for t in self.rpc(proc,'tools/list',{})['result']['tools']}
                self.assertTrue(tools['commerce_listing_schema_get']['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_listing_schema_refresh']['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_listing_schema_refresh']['annotations']['openWorldHint'])
                result=self.rpc(proc,'tools/call',{'name':'commerce_listing_schema_get','arguments':target})['result']
                self.assertFalse(result.get('isError'));values.append(result['structuredContent'])
                result=self.rpc(proc,'tools/call',{'name':'commerce_listing_schema_refresh','arguments':{**target,'resource':'tree'}})['result']
                self.assertTrue(result['isError']);self.assertIn('listing_schema_demo_no_network',str(result))
        self.assertEqual(values[0],values[1]);self.assertEqual(values[1],values[2]);self.assertFalse(values[0]['external_execution_allowed'])


if __name__=='__main__':unittest.main()
