"""Exercise real loopback SSE and subprocess transport without model charges."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json
import sys
import threading
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model_providers.inference import invoke

class Endpoint(BaseHTTPRequestHandler):
    requests=[]
    mode='sse'
    def log_message(self,*args):pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));type(self).requests.append(data)
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        text=json.dumps({'phase':'answer','answer':'第一段随后第二段','questions':[],'evidence_refs':[],'proposals':[],'ui':[]},ensure_ascii=False)
        for delta in (text[:35],text[35:48],text[48:]):
            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':delta},'finish_reason':None}]})+'\n\n').encode());self.wfile.flush();time.sleep(.08)
        if type(self).mode=='truncated':return
        self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()

class StreamTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Endpoint)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.worker.join()
    def setUp(self):Endpoint.requests=[];Endpoint.mode='sse'
    def config(self):return {'base_url':f'http://127.0.0.1:{self.server.server_port}/v1','model':'synthetic','json_mode':True}
    def test_real_deltas_arrive_before_invocation_returns(self):
        from generative.streaming import capture,Preview
        events=[];done=False
        def receive(event):
            self.assertFalse(done);events.append(event)
        with capture(Preview(receive,[]).feed):result=invoke({'observations':[]},lambda:False,self.config())
        done=True
        self.assertTrue(Endpoint.requests[0]['stream'])
        self.assertEqual(result['decision']['answer'],'第一段随后第二段')
        self.assertEqual(''.join(e['delta'] for e in events if e['type']=='answer_delta'),'第一段随后第二段')
        self.assertGreater(len([e for e in events if e['type']=='answer_delta']),1)
    def test_truncated_stream_keeps_unknown_and_never_retries(self):
        from generative.streaming import capture
        Endpoint.mode='truncated'
        with capture(lambda _:None),self.assertRaisesRegex(ValueError,'outcome_unknown'):
            invoke({'observations':[]},lambda:False,self.config())
        self.assertEqual(len(Endpoint.requests),1)

if __name__=='__main__':unittest.main()
