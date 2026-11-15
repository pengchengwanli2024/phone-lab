"""Local fake HTTP services exercise real bounded plugin transports."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_extension_runtime import RuntimeCase

class Handler(BaseHTTPRequestHandler):
    hits=[]
    def log_message(self,*args):pass
    def do_GET(self):
        self.hits.append(('GET',self.path,self.headers.get('Authorization')))
        if self.path.startswith('/redirect'):
            self.send_response(302);self.send_header('Location','/json');self.end_headers();return
        data={'observed':True,'api_key':'must-redact','echo':'private-test-key','authorization':self.headers.get('Authorization')}
        raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.hits.append(('POST',payload,self.headers.get('Authorization')))
        if self.path=='/mcp':
            if payload['method']=='notifications/initialized':
                self.send_response(202);self.end_headers();return
            result={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'fixture','version':'1'}} if payload['method']=='initialize' else {'structuredContent':{'received':payload['params']['arguments'],'tool':payload['params']['name']}}
            payload={'jsonrpc':'2.0','id':payload['id'],'result':result}
        else:payload={'receipt':'remote-fixture','input':payload}
        raw=json.dumps(payload).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class Network(RuntimeCase):
    def setUp(self):
        super().setUp();Handler.hits=[];self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();super().tearDown()
    def plugin(self,path='/json',effect='read',transport='http'):
        return self.call('save',definition={'kind':'plugin','name':'Synthetic HTTP','spec':{'transport':transport,'endpoint':self.url+path,'tool':'fixture','effect':effect}})
    def test_json_http_real_receipt_and_private_credentials_redaction(self):
        ext=self.plugin();self.app.configure_credentials({'extension_id':ext['id'],'expected_version':1,'api_key':'private-test-key'})
        run=self.call('test',extension_id=ext['id'],idempotency_key='http');result=self.drain(run)
        self.assertEqual(result['status'],'succeeded');self.assertTrue(result['output']['observed']);self.assertEqual(result['output']['api_key'],'[redacted]');self.assertEqual(result['output']['echo'],'[redacted]')
        self.assertNotIn('private-test-key',json.dumps(result));self.assertEqual(Handler.hits[0][2],'Bearer private-test-key')
    def test_external_write_test_never_sends_and_approval_binds_input(self):
        ext=self.plugin('/write','external_write');test=self.call('test',extension_id=ext['id'],idempotency_key='dry');self.assertEqual(self.drain(test)['output']['status'],'validation_only');self.assertEqual(Handler.hits,[])
        self.call('enable',extension_id=ext['id'],expected_version=1,enabled=True)
        run=self.call('run',extension_id=ext['id'],input={'amount':2},idempotency_key='write');pending=self.drain(run);self.assertEqual(pending['status'],'awaiting_approval');self.assertEqual(Handler.hits,[])
        approval=pending['approval']
        with self.assertRaisesRegex(ValueError,'approval_mismatch'):self.call('run_approve',run_id=run['id'],step_id=approval['step_id'],input_sha256='0'*64,decision='approve')
        self.call('run_approve',run_id=run['id'],step_id=approval['step_id'],input_sha256=approval['input_sha256'],decision='approve');result=self.drain(run)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['output']['receipt'],'remote-fixture');self.assertEqual(len(Handler.hits),1)
        again=self.call('run',extension_id=ext['id'],input={'amount':2},idempotency_key='again');self.assertEqual(self.drain(again)['status'],'awaiting_approval')
    def test_redirect_is_not_followed(self):
        ext=self.plugin('/redirect');result=self.drain(self.call('test',extension_id=ext['id'],idempotency_key='redirect'))
        self.assertEqual(result['status'],'failed');self.assertEqual(len(Handler.hits),1)
    def test_mcp_fixed_tool_real_json_exchange(self):
        ext=self.plugin('/mcp',transport='mcp_http');result=self.drain(self.call('test',extension_id=ext['id'],input={'q':'synthetic'},idempotency_key='mcp'))
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['output'],{'received':{'q':'synthetic'},'tool':'fixture'});self.assertEqual(len(Handler.hits),3)
    def test_write_output_contract_does_not_block_honest_structure_only_test(self):
        ext=self.call('save',definition={'kind':'plugin','name':'Write contract','output_schema':{'type':'object','properties':{'receipt':{'type':'string'}},'required':['receipt']},'spec':{'transport':'http','tool':'fixture','endpoint':self.url+'/write','effect':'external_write'}})
        result=self.drain(self.call('test',extension_id=ext['id'],idempotency_key='write-output-contract'))
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['test_mode'],'structure_only');self.assertEqual(Handler.hits,[])
        self.assertEqual(self.call('get',extension_id=ext['id'])['test_verification'],'structure_only')
    def test_secret_config_is_not_a_public_mcp_tool(self):
        from extension_runtime import definitions
        names={x[0] for x in definitions(lambda p,r:{'properties':p,'required':r},{'type':'string'})}
        self.assertNotIn('commerce_extension_configure_credentials',names)

if __name__=='__main__':unittest.main()
