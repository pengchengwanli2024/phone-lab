"""Real stdio MCP and HTTP share one opt-in local sample gate."""
import time
import unittest
import test_media_plugin_mcp as fixture


class DeliveryMCP(unittest.TestCase):
    setUpClass=classmethod(fixture.PluginMCP.setUpClass.__func__)
    tearDownClass=classmethod(fixture.PluginMCP.tearDownClass.__func__)
    call=classmethod(fixture.PluginMCP.call.__func__)
    mcp=fixture.PluginMCP.mcp
    rpc=fixture.PluginMCP.rpc

    def test_clients_share_hash_bound_sample_gate_without_external_submission(self):
        p=self.call('commerce_creative_get',{'project_id':self.fixture['project_id']})
        root=self.call('commerce_media_request_get',{'request_id':self.fixture['video_request']})
        requirements={'source_policy':'allow_stills','audio_policy':'no_audio','allow_looping':False,'sample_duration_ms':1000}
        with self.mcp('codex')as process:
            tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
            self.assertFalse(tools['commerce_media_delivery_prepare']['annotations']['readOnlyHint'])
            self.assertFalse(tools['commerce_media_delivery_prepare']['annotations']['openWorldHint'])
            self.assertTrue(tools['commerce_media_request_get']['annotations']['readOnlyHint'])
            result=self.rpc(process,'tools/call',{'name':'commerce_media_delivery_prepare','arguments':{'request_id':root['id'],'expected_request_sha256':root['request_sha256'],'asset_ids':[self.fixture['asset_id']]*5,'requirements':requirements,'idempotency_key':'new-mcp-family'}})['result']
            self.assertFalse(result.get('isError'),result);pair=result['structuredContent']
        with self.mcp('harness')as process:
            result=self.rpc(process,'tools/call',{'name':'commerce_media_request_execute','arguments':{'request_id':pair['full']['id'],'expected_revision':p['revision'],'asset_ids':[self.fixture['asset_id']]*5}})['result']
            self.assertTrue(result['isError']);self.assertIn('sample_approval_required',result['content'][0]['text'])
        self.assertIsNone(self.call('commerce_media_request_get',{'request_id':pair['full']['id']})['job_id'])
        with self.mcp('hermes')as process:
            result=self.rpc(process,'tools/call',{'name':'commerce_media_request_execute','arguments':{'request_id':pair['sample']['id'],'expected_revision':p['revision'],'asset_ids':[self.fixture['asset_id']]}})['result']
            self.assertFalse(result.get('isError'),result)
        end=time.monotonic()+30
        while time.monotonic()<end:
            sample=self.call('commerce_media_request_get',{'request_id':pair['sample']['id']})
            if sample['status']not in ('queued','running'):break
            time.sleep(.05)
        self.assertEqual(sample['status'],'awaiting_review',sample)
        with self.mcp('harness')as process:
            result=self.rpc(process,'tools/call',{'name':'commerce_media_request_review','arguments':{'request_id':sample['id'],'expected_result_sha256':sample['result_sha256'],'decision':'approved','note':'合成MCP验收已观看核对','sample_review':{'watched':True,'matches_commitment':True,'commitment_sha256':sample['delivery']['commitment_sha256']}}})['result']
            self.assertFalse(result.get('isError'),result)
        self.assertEqual(self.call('commerce_media_request_get',{'request_id':pair['full']['id']})['delivery']['gate'],'ready')
        # The unedited full plan also cannot escape into provider/plugin creation.
        video_profile=next(x for x in self.call('commerce_media_provider_catalog',{})['profiles']if x['media_kind']=='video')
        attempts=[('commerce_media_provider_generate',{'request_id':pair['full']['id'],'profile_id':video_profile['id'],'expected_profile_revision':video_profile['revision'],'asset_ids':[self.fixture['asset_id']],'idempotency_key':'must-not-submit'}),('commerce_media_plugin_plan_prepare',{'request_id':pair['full']['id'],'expected_revision':p['revision'],'provider':'lovart','expected_connection_revision':1,'asset_ids':[self.fixture['asset_id']],'idempotency_key':'must-not-prepare-plugin'})]
        with self.mcp('harness')as process:
            for name,args in attempts:
                result=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result']
                self.assertTrue(result['isError']);self.assertIn('creative_edit_local_render_required',result['content'][0]['text'])
        self.assertEqual(self.call('commerce_media_provider_jobs',{'request_id':pair['full']['id']})['jobs'],[])
