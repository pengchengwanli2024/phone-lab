"""Actual local HTTP/stdio contracts; no upstream reads."""
import unittest
import test_business_completion_mcp as transport

class CatalogSyncTransport(unittest.TestCase):
    call=classmethod(transport.BusinessMCP.call.__func__)
    mcp=transport.BusinessMCP.mcp
    rpc=transport.BusinessMCP.rpc
    setUpClass=classmethod(transport.BusinessMCP.setUpClass.__func__)
    tearDownClass=classmethod(transport.BusinessMCP.tearDownClass.__func__)
    def test_three_clients_share_local_status_and_synthetic_refresh_is_denied(self):
        before=self.call('commerce_task_list',{})['tasks'];views=[]
        for client in ('codex','hermes','harness'):
            with self.mcp(client)as proc:
                tools={t['name']:t for t in self.rpc(proc,'tools/list',{})['result']['tools']}
                for name in ('commerce_catalog_store_status','commerce_cost_scenarios_get'):self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_catalog_store_refresh']['annotations']['openWorldHint'])
                result=self.rpc(proc,'tools/call',{'name':'commerce_catalog_store_status','arguments':{}})['result'];self.assertFalse(result.get('isError'))
                view=result['structuredContent'];views.append(view)
                result=self.rpc(proc,'tools/call',{'name':'commerce_catalog_store_refresh','arguments':{'case_id':self.cid,'expected_stock_sha256':view['stock_sha256']}})['result']
                self.assertTrue(result['isError']);self.assertIn('catalog_sync_scope',str(result))
        self.assertEqual(views[0],views[1]);self.assertEqual(views[1],views[2]);self.assertEqual(self.call('commerce_task_list',{})['tasks'],before)

if __name__=='__main__':unittest.main()
