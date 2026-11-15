"""Three actual MCP clients share one explicit video content review version."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import test_paos_mcp as transport

ROOT=Path(__file__).resolve().parents[1]


class VideoReviewMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name);cls.token='synthetic-video-review'
        (cls.state/'auth.token').write_text(cls.token)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_extensible_runtime.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(150):
            try:
                if cls.call('commerce_media_provider_catalog',{})['profiles']:break
            except (OSError,ValueError,FileNotFoundError):pass
            time.sleep(.05)
        else:
            cls.process.terminate();cls.process.wait(timeout=10)
            raise AssertionError('isolated review server unavailable')
        cls.fixture=json.loads((cls.state/'extensible-fixture.json').read_text())
        req=urllib.request.Request('http://127.0.0.1:'+str(cls.port)+'/v1/media/plugins/configure',
            data=json.dumps({'provider':'heygen','expected_revision':0,'link_id':'','account_label':'Synthetic video account',
                'connection_status':'available_to_host','observed_at':time.time(),'model':'heygen-video-1','model_parameters':{}}).encode(),
            headers={'Authorization':'Bearer '+cls.token,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=3) as response:assert response.status==200

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    def test_review_contract_shared_immutable_version_without_generation_or_tasks(self):
        project=self.call('commerce_creative_get',{'project_id':self.fixture['project_id']})
        before=self.call('commerce_task_list',{})
        plan=self.call('commerce_media_plugin_plan_prepare',{'request_id':self.fixture['video_request'],'expected_revision':project['revision'],
            'provider':'heygen','expected_connection_revision':1,'asset_ids':[self.fixture['asset_id']],'idempotency_key':'mcp-video-plan'})
        content={'presenter_mode':'faceless','presenter_description':'','use_scene':'合成厨房台面场景','speech_mode':'none','script_text':'',
            'shots':[{'index':i,'framing':s['framing'],'action':s['action']} for i,s in enumerate(plan['source_request']['spec']['shots'])],
            'claims_confirmed':True}
        args={'plan_id':plan['id'],'expected_plan_sha256':plan['plan_sha256'],'content':content,'idempotency_key':'shared-video-review'}
        seen=[]
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                descriptor=tools['commerce_media_plugin_plan_review_video'];self.assertFalse(descriptor['annotations']['readOnlyHint'])
                self.assertFalse(descriptor['annotations']['openWorldHint']);self.assertIn('content',descriptor['inputSchema']['required'])
                self.assertIn('claims_confirmed',descriptor['inputSchema']['properties']['content']['required'])
                reply=self.rpc(process,'tools/call',{'name':'commerce_media_plugin_plan_review_video','arguments':args})['result']
                self.assertFalse(reply.get('isError'),reply);reviewed=reply['structuredContent'];seen.append(reviewed['id'])
                self.assertEqual(reviewed['source_plan_id'],plan['id']);self.assertEqual(reviewed['blockers'],[])
                self.assertTrue(reviewed['video_review']['operator_reviewed']);self.assertFalse(reviewed['external_generation_submitted'])
        self.assertEqual(len(set(seen)),1)
        self.assertEqual(self.call('commerce_task_list',{}),before)
        self.assertEqual(self.call('commerce_creative_get',{'project_id':project['id']})['revision'],project['revision'])
        self.assertEqual(self.call('commerce_media_plugin_execution_list',{'request_id':self.fixture['video_request']})['executions'],[])


if __name__=='__main__':unittest.main()
