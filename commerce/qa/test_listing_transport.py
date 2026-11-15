"""Real HTTP and three stdio clients share exact listing preparation versions."""
import json
import unittest
import test_business_completion_mcp as business_transport


class ListingTransport(unittest.TestCase):
    call=classmethod(business_transport.BusinessMCP.call.__func__)
    mcp=business_transport.BusinessMCP.mcp
    rpc=business_transport.BusinessMCP.rpc
    setUpClass=classmethod(business_transport.BusinessMCP.setUpClass.__func__)
    tearDownClass=classmethod(business_transport.BusinessMCP.tearDownClass.__func__)

    def test_three_clients_share_saved_target_and_export_has_no_platform_receipt(self):
        target=dict(case_id=self.cid,platform='ozon',store_ref='synthetic-mcp-store',market='RU')
        version=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('commerce_listing_get','commerce_listing_export','commerce_store_workbench'):
                    self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_listing_save']['annotations']['readOnlyHint'])
                def call(name,args):
                    result=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result']
                    self.assertFalse(result.get('isError'),str(result));return result['structuredContent']
                view=call('commerce_listing_get',target)
                if version is None:
                    view=call('commerce_listing_save',{**target,'payload':view['payload'],'expected_revision':view['revision'],'expected_source_sha256':view['source_sha256']})
                    version=view['preview_sha256']
                self.assertEqual(view['preview_sha256'],version)
                exported=call('commerce_listing_export',{**target,'expected_preview_sha256':version})
                self.assertEqual(json.loads(exported['content'])['platform_submission'],'not_performed')
                denied=self.rpc(process,'tools/call',{'name':'commerce_listing_get','arguments':{**target,'case_id':'outside-current-connection'}})['result']
                self.assertTrue(denied['isError'])


if __name__=='__main__':unittest.main()
