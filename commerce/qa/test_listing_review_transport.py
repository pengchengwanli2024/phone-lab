"""Three real stdio clients share exact preparation and local review versions."""
import unittest
import test_business_completion_mcp as transport


class ListingReviewTransport(unittest.TestCase):
    call=classmethod(transport.BusinessMCP.call.__func__)
    mcp=transport.BusinessMCP.mcp
    rpc=transport.BusinessMCP.rpc
    setUpClass=classmethod(transport.BusinessMCP.setUpClass.__func__)
    tearDownClass=classmethod(transport.BusinessMCP.tearDownClass.__func__)

    def test_three_clients_share_directory_review_and_batch_read_contracts(self):
        target=dict(case_id=self.cid,platform='shopify',store_ref='synthetic-independent-store',market='US')
        saved=None;review_sha=None;before=self.call('commerce_task_list',{})['tasks']
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client)as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('commerce_listing_directory','commerce_listing_reconcile','commerce_intel_article_plan','commerce_intel_article_batch_get','commerce_intel_article_batch_list'):
                    self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_listing_review']['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_intel_article_batch_start']['annotations']['openWorldHint'])
                def call(name,args):
                    result=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result'];self.assertFalse(result.get('isError'),str(result));return result['structuredContent']
                if saved is None:
                    view=call('commerce_listing_get',target)
                    saved=call('commerce_listing_save',{**target,'payload':view['payload'],'expected_revision':view['revision'],'expected_source_sha256':view['source_sha256']})
                view=call('commerce_listing_reconcile',target)
                if review_sha is None:
                    receipt=call('commerce_listing_review',{**target,'expected_comparison_sha256':view['comparison_sha256'],'expected_review_sha256':'','decision':'needs_changes','note':'Synthetic missing provider acceptance','confirmed':True,'idempotency_key':'synthetic-shared-review'})
                    review_sha=receipt['sha256']
                view=call('commerce_listing_reconcile',target);self.assertEqual(view['review']['sha256'],review_sha);self.assertTrue(view['review']['current'])
                directory=call('commerce_listing_directory',{'demo':True});self.assertEqual(directory['items'][0]['target'],target)
                plan=call('commerce_intel_article_plan',{'filters':{},'limit':5});self.assertFalse(plan['fetch_started'])
                self.assertFalse(view['platform_submission_verified'])
        self.assertEqual(self.call('commerce_task_list',{})['tasks'],before)


if __name__=='__main__':unittest.main()
