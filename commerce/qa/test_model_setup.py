"""Actual HTTP setup guards and private credential handling; no external service."""
from pathlib import Path
import json,sys,tempfile,threading,unittest,urllib.request,urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from service import Commerce

class PrivateModelSetup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
        self.old_port=server.PORT
        class Handler(server.Handler):pass
        Handler.service=self.app;Handler.secret='synthetic-model-http'
        self.http=server.CommerceHTTPServer(('127.0.0.1',0),Handler);server.PORT=self.http.server_port
        self.worker=threading.Thread(target=self.http.serve_forever,daemon=True);self.worker.start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.worker.join();server.PORT=self.old_port;self.app.agent_runtime.stop();self.temp.cleanup()
    def request(self,path,data=None,auth=True,origin=None):
        headers={'Content-Type':'application/json'}
        if auth:headers['Authorization']='Bearer synthetic-model-http'
        if origin:headers['Origin']=origin
        req=urllib.request.Request(f'http://127.0.0.1:{self.http.server_port}'+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=5)as r:return r.status,r.read().decode()
        except urllib.error.HTTPError as e:
            with e:return e.code,e.read().decode()
    def test_setup_and_writes_require_same_local_auth_and_origin(self):
        self.assertEqual(self.request('/model-setup',auth=False)[0],401)
        self.assertEqual(self.request('/v1/models/configure',{},auth=False)[0],401)
        self.assertEqual(self.request('/v1/models/configure',{},origin='https://untrusted.example')[0],403)
        code,body=self.request('/model-setup');self.assertEqual(code,200);self.assertIn('模型与本地服务',body)
    def test_key_is_accepted_only_by_private_route_and_not_returned(self):
        data={'label':'私有测试配置','engine':'custom','base_url':'http://127.0.0.1:1/v1','model':'test-only','api_key':'PRIVATE_HTTP_KEY_SENTINEL'}
        code,raw=self.request('/v1/models/configure',data);self.assertEqual(code,200);self.assertNotIn(data['api_key'],raw)
        row=json.loads(raw);self.assertFalse(row['enabled'])
        code,raw=self.request('/v1/invoke',{'tool':'commerce_model_list','arguments':{},'client':'browser'});self.assertEqual(code,200);self.assertNotIn(data['api_key'],raw)
        self.assertEqual(self.request('/v1/invoke',{'tool':'commerce_model_configure','arguments':data})[0],400)
        secrets=list(Path(self.temp.name,'model-credentials').glob('*.json'));self.assertEqual(len(secrets),1);self.assertEqual(secrets[0].stat().st_mode&0o777,0o600)
        self.assertNotIn(data['api_key'],Path(self.temp.name,'commerce.sqlite').read_bytes().decode(errors='ignore'))
    def test_missing_test_and_stale_revisions_cannot_enable(self):
        _,raw=self.request('/v1/models/configure',{'label':'测试','engine':'vllm','base_url':'http://127.0.0.1:1/v1','model':'test-only'});p=json.loads(raw)
        code,raw=self.request('/v1/models/enabled',{'model_id':p['id'],'expected_revision':p['revision'],'enabled':True});self.assertEqual(code,400);self.assertEqual(json.loads(raw)['error'],'model_not_ready')
        code,raw=self.request('/v1/models/configure',{'id':p['id'],'expected_revision':'0','label':'旧页面','engine':'vllm','base_url':'http://127.0.0.1:1/v1','model':'test-only'});self.assertEqual(code,400);self.assertEqual(json.loads(raw)['error'],'model_profile_changed')

if __name__=='__main__':unittest.main()
