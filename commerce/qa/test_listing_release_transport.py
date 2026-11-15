"""Three stdio clients share local application/receipt versions; no cloud calls."""
import unittest
import test_business_completion_mcp as transport


class ListingReleaseTransport(unittest.TestCase):
    call=classmethod(transport.BusinessMCP.call.__func__)
    mcp=transport.BusinessMCP.mcp
    rpc=transport.BusinessMCP.rpc
    setUpClass=classmethod(transport.BusinessMCP.setUpClass.__func__)
    tearDownClass=classmethod(transport.BusinessMCP.tearDownClass.__func__)

    def test_three_clients_observe_identical_frozen_application_and_keep_publication_denied(self):
        target=dict(case_id=self.cid,platform='ozon',store_ref='ozon-live',market='RU');request_id=None;sha=None
        tasks=self.call('commerce_task_list',{})['tasks']
        for client in ('codex','hermes','harness'):
            with self.mcp(client)as proc:
                tools={t['name']:t for t in self.rpc(proc,'tools/list',{})['result']['tools']}
                for n in ('commerce_listing_release_get','commerce_listing_release_export'):self.assertTrue(tools[n]['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_listing_release_create']['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_listing_release_refresh']['annotations']['openWorldHint'])
                self.assertTrue(tools['commerce_listing_release_image']['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_listing_release_image']['annotations']['openWorldHint'])
                self.assertFalse(tools['commerce_listing_release_image']['annotations']['destructiveHint'])
                def call(name,args):
                    result=self.rpc(proc,'tools/call',{'name':name,'arguments':args})['result'];self.assertFalse(result.get('isError'),str(result));return result['structuredContent']
                if request_id is None:
                    plan=call('commerce_listing_get',target)
                    plan['payload']['fields']['image_refs']=['https://example.com/synthetic-review-image.png']
                    plan=call('commerce_listing_save',{**target,'payload':plan['payload'],'expected_revision':plan['revision'],'expected_source_sha256':plan['source_sha256']})
                    request_id=call('commerce_listing_release_create',{**target,'expected_preview_sha256':plan['preview_sha256'],'note':'Synthetic shared application','confirmed':True,'idempotency_key':'shared-release'})['id']
                response=call('commerce_listing_release_get',{**target,'request_id':request_id})
                self.assertEqual(response['export_formats'],['json','html']);value=response['request']
                if sha is None:sha=value['sha256']
                self.assertEqual(value['sha256'],sha);self.assertFalse(value['platform_submission_verified']);self.assertIn('professional_gate',value['missing'])
                call('commerce_listing_release_export',{'request_id':request_id,'expected_event_sha256':value['event_sha256']})
                self.assertEqual(tools['commerce_listing_release_export']['inputSchema']['properties']['format']['enum'],['json','html'])
                readable=call('commerce_listing_release_export',{'request_id':request_id,'expected_event_sha256':value['event_sha256'],'format':'html'})
                self.assertTrue(readable['content'].startswith('<!doctype html>'));self.assertIn(sha,readable['content'])
                self.assertNotIn('<script',readable['content']);self.assertIn('尚未通过',readable['content'])
                image=self.rpc(proc,'tools/call',{'name':'commerce_listing_release_image','arguments':{'request_id':request_id,'expected_request_sha256':value['sha256'],'index':0}})['result']
                self.assertTrue(image['isError']);self.assertIn('listing_review_demo_no_network',str(image))
        self.assertEqual(tasks,self.call('commerce_task_list',{})['tasks'])


if __name__=='__main__':unittest.main()
