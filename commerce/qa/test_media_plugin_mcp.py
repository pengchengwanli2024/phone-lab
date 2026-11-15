"""Actual MCP clients share one unsubmitted, account-pinned plugin brief."""
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


class PluginMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name)
        cls.token='synthetic-plugin-mcp';(cls.state/'auth.token').write_text(cls.token)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_extensible_runtime.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(150):
            try:
                if cls.call('commerce_media_provider_catalog',{})['profiles']:break
            except (OSError,ValueError,FileNotFoundError):pass
            time.sleep(.05)
        else:raise AssertionError('isolated plugin server unavailable')
        cls.fixture=json.loads((cls.state/'extensible-fixture.json').read_text())
        body={'provider':'lovart','expected_revision':0,'link_id':'link_synthetic_mcp','account_label':'Synthetic selected account',
              'connection_status':'available_to_host','observed_at':time.time(),'model':'synthetic-image','model_parameters':{}}
        request=urllib.request.Request('http://127.0.0.1:'+str(cls.port)+'/v1/media/plugins/configure',data=json.dumps(body).encode(),
            headers={'Authorization':'Bearer '+cls.token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=3) as response:assert response.status==200

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    def test_all_clients_revalidate_the_same_unsubmitted_plan(self):
        p=self.call('commerce_creative_get',{'project_id':self.fixture['project_id']})
        plan=self.call('commerce_media_plugin_plan_prepare',{'request_id':self.fixture['image_request'],'expected_revision':p['revision'],
            'provider':'lovart','expected_connection_revision':1,'asset_ids':[self.fixture['asset_id']],'idempotency_key':'same-plugin-plan'})
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('commerce_media_plugin_plan_get','commerce_media_plugin_plan_list','commerce_media_plugin_plan_validate'):
                    self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_media_plugin_plan_prepare']['annotations']['readOnlyHint'])
                self.assertFalse(tools['commerce_media_plugin_plan_prepare']['annotations']['openWorldHint'])
                self.assertNotIn('commerce_media_plugin_configure',tools)
                def call(name,args):
                    value=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result'];self.assertFalse(value.get('isError'),str(value));return value['structuredContent']
                current=call('commerce_media_plugin_plan_get',{'plan_id':plan['id']})
                self.assertEqual(current['plan_sha256'],plan['plan_sha256']);self.assertEqual(current['tool_call']['arguments']['link_id'],'link_synthetic_mcp')
                self.assertFalse(current['external_generation_submitted'])
                self.assertTrue(call('commerce_media_plugin_plan_validate',{'plan_id':plan['id'],'expected_plan_sha256':plan['plan_sha256']})['current'])
        self.assertEqual(self.call('commerce_media_provider_jobs',{'request_id':plan['request_id']})['jobs'],[])


if __name__=='__main__':unittest.main()
