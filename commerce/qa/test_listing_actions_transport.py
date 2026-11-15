"""The three actual stdio clients discover bounded image actions without a write."""
import unittest
import test_business_completion_mcp as transport

class ListingActionsTransport(unittest.TestCase):
    call=classmethod(transport.BusinessMCP.call.__func__)
    mcp=transport.BusinessMCP.mcp
    rpc=transport.BusinessMCP.rpc
    setUpClass=classmethod(transport.BusinessMCP.setUpClass.__func__)
    tearDownClass=classmethod(transport.BusinessMCP.tearDownClass.__func__)
    def test_client_annotations_and_demo_cannot_reach_the_real_shop(self):
        before=self.call('commerce_task_list',{})['tasks']
        for client in ('codex','hermes','harness'):
            with self.mcp(client)as p:
                tools={t['name']:t for t in self.rpc(p,'tools/list',{})['result']['tools']}
                self.assertTrue(tools['commerce_listing_action_get']['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_listing_action_directory']['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_listing_action_directory']['annotations']['openWorldHint'])
                directory=self.rpc(p,'tools/call',{'name':'commerce_listing_action_directory','arguments':{'demo':True}})['result']
                self.assertFalse(directory.get('isError'));self.assertEqual(directory['structuredContent']['items'],[])
                self.assertTrue(tools['commerce_listing_action_submit']['annotations']['openWorldHint'])
                self.assertTrue(tools['commerce_listing_action_submit']['annotations']['destructiveHint'])
                result=self.rpc(p,'tools/call',{'name':'commerce_listing_action_refresh','arguments':{'case_id':self.cid}})['result']
                self.assertTrue(result['isError']);self.assertIn('listing_action_real_existing_product_required',str(result))
        self.assertEqual(self.call('commerce_task_list',{})['tasks'],before)

if __name__=='__main__':unittest.main()
