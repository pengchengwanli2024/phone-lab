"""Three actual stdio clients share one isolated frozen publication plan."""
import json,os,time,urllib.request
import test_owner_review_mcp as transport

class ListingSubmissionMCP(transport.OwnerReviewMCP):
    @classmethod
    def setUpClass(cls):
        old=os.environ.get('COMMERCE_QA_SUBMISSION');os.environ['COMMERCE_QA_SUBMISSION']='1'
        try:super().setUpClass()
        finally:
            if old is None:os.environ.pop('COMMERCE_QA_SUBMISSION',None)
            else:os.environ['COMMERCE_QA_SUBMISSION']=old
        cls.rid=cls.call('commerce_listing_release_get',cls.target)['request']['id']
    def test_three_clients_share_scoped_local_draft_and_readonly_annotations(self):
        self.call('commerce_listing_submission_probe',dict(request_id=self.rid))
        for _ in range(100):
            v=self.call('commerce_listing_submission_get',dict(request_id=self.rid))
            if v['ready_to_prepare']:break
            time.sleep(.05)
        self.assertTrue(v['ready_to_prepare'],v)
        plan=self.call('commerce_listing_submission_prepare',dict(request_id=self.rid,expected_request_sha256=v['request_sha256'],expected_before_sha256=v['before']['sha256'],idempotency_key='three-client-plan'))['plan']
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client)as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                self.assertTrue(tools['commerce_listing_submission_get']['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_listing_submission_probe']['annotations']['openWorldHint'])
                self.assertTrue(tools['commerce_listing_submission_submit']['annotations']['destructiveHint'])
                self.assertFalse(tools['commerce_listing_submission_prepare']['annotations']['openWorldHint'])
                result=self.rpc(process,'tools/call',dict(name='commerce_listing_submission_get',arguments=dict(request_id=self.rid)))['result'];self.assertFalse(result.get('isError'),result)
                self.assertEqual(result['structuredContent']['plan']['sha256'],plan['sha256'])
                denied=self.rpc(process,'tools/call',dict(name='commerce_listing_submission_submit',arguments=dict(plan_id=plan['id'],expected_event_sha256='',expected_plan_sha256=plan['sha256'],idempotency_key='deny-'+client,operator='Synthetic operator',confirmed=False)))['result'];self.assertTrue(denied['isError'])
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/qa-submission')as r:self.assertEqual(json.load(r)['writes'],0)
