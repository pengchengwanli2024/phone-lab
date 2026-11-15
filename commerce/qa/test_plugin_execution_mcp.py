"""Real HTTP/stdio host handoff and actual file adoption, with synthetic output GET."""
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


class PluginExecutionMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name)
        cls.token='synthetic-plugin-execution';(cls.state/'auth.token').write_text(cls.token)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_plugin_execution.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(150):
            try:
                if cls.call('commerce_media_provider_catalog',{})['profiles']:break
            except (OSError,ValueError,FileNotFoundError):pass
            time.sleep(.05)
        else:
            cls.process.terminate();cls.process.wait(timeout=10)
            raise AssertionError('isolated plugin execution unavailable: '+cls.process.stderr.read().decode()[-1500:])
        cls.fixture=json.loads((cls.state/'extensible-fixture.json').read_text())
        req=urllib.request.Request('http://127.0.0.1:'+str(cls.port)+'/v1/media/plugins/configure',
            data=json.dumps({'provider':'lovart','expected_revision':0,'link_id':'link_synthetic_mcp','account_label':'Synthetic selected account',
                'connection_status':'available_to_host','observed_at':time.time(),'model':'synthetic-image','model_parameters':{}}).encode(),
            headers={'Authorization':'Bearer '+cls.token,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=3) as response:assert response.status==200

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    def test_three_clients_share_once_only_grant_real_file_and_task_receipt(self):
        p=self.call('commerce_creative_get',{'project_id':self.fixture['project_id']})
        plan=self.call('commerce_media_plugin_plan_prepare',{'request_id':self.fixture['image_request'],'expected_revision':p['revision'],
            'provider':'lovart','expected_connection_revision':1,'asset_ids':[self.fixture['asset_id']],'idempotency_key':'mcp-plan'})
        execution=self.call('commerce_media_plugin_execution_start',{'plan_id':plan['id'],'expected_plan_sha256':plan['plan_sha256'],'idempotency_key':'mcp-start'})
        with self.mcp('codex') as process:
            tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
            for name in ('get','list','poll_packet'):self.assertTrue(tools['commerce_media_plugin_execution_'+name]['annotations']['readOnlyHint'])
            self.assertTrue(tools['commerce_media_plugin_execution_begin']['annotations']['openWorldHint'])
            self.assertFalse(tools['commerce_media_plugin_execution_start']['annotations']['openWorldHint'])
            args={'execution_id':execution['id'],'expected_plan_sha256':plan['plan_sha256'],'decision':'approve'}
            self.assertFalse(self.rpc(process,'tools/call',{'name':'commerce_media_plugin_execution_approve','arguments':args})['result'].get('isError'))
        claim=self.call('commerce_media_plugin_execution_claim',{'execution_id':execution['id'],'host_id':'hermes','idempotency_key':'mcp-claim'})
        auth={'execution_id':execution['id'],'claim_token':claim['claim_token']}
        self.call('commerce_media_plugin_execution_record_transfer',{**auth,'asset_id':self.fixture['asset_id'],'remote_reference':{'type':'url','url':'https://assets.lovart.ai/synthetic-upload.png'},'idempotency_key':'mcp-upload'})
        packet=self.call('commerce_media_plugin_execution_begin',auth)
        self.assertEqual(packet['submission_grant'],'once_only')
        receipt={'status':'completed','task_ids':['synthetic-task'],'project_id':'synthetic-project',
            'outputs':[{'url':'https://synthetic-results.lovart.ai/result.png?signature='+'a'*400}]}
        current=self.call('commerce_media_plugin_execution_receipt',{**auth,'receipt':receipt,'idempotency_key':'mcp-complete'})
        self.assertEqual(current['status'],'retrieving');self.assertFalse(current['actual_bytes_verified'])
        with self.mcp('harness') as process:
            denied=self.rpc(process,'tools/call',{'name':'commerce_media_plugin_execution_begin','arguments':auth})['result']
            self.assertTrue(denied['isError'])
        (self.state/'allow-plugin-download').touch()
        for _ in range(150):
            current=self.call('commerce_media_plugin_execution_get',{'execution_id':execution['id']})
            if current['status']=='awaiting_review':break
            time.sleep(.05)
        self.assertEqual(current['status'],'awaiting_review',current)
        self.assertTrue(current['actual_bytes_verified']);self.assertEqual(len(current['assets']),1)
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                value=self.rpc(process,'tools/call',{'name':'commerce_task_result','arguments':{'task_id':execution['task_id']}})['result']
                self.assertFalse(value.get('isError'));r=value['structuredContent']
                self.assertEqual(r['execution']['operation'],'media_plugin');self.assertEqual(r['task']['status'],'completed')
                self.assertTrue(r['execution']['result']['actual_bytes_verified'])
                self.assertNotIn('signature=',json.dumps(r));self.assertNotIn(claim['claim_token'],json.dumps(r))
        replay=self.call('commerce_media_plugin_execution_receipt',{**auth,'receipt':receipt,'idempotency_key':'mcp-repeated-complete'})
        self.assertEqual(replay['status'],'awaiting_review')
        self.assertEqual(replay['assets'],current['assets'])


if __name__=='__main__':unittest.main()
