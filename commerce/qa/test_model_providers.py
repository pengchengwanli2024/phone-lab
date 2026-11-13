"""Model profile, conversation selection and real bounded HTTP adapter contracts."""
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,sys,tempfile,threading,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce

class Endpoint(BaseHTTPRequestHandler):
    requests=[]
    mode='ok'
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).requests.append({'path':self.path,'body':body,'authorization':self.headers.get('Authorization')})
        if type(self).mode=='slow':time.sleep(1.2)
        if type(self).mode=='redirect':
            self.send_response(307);self.send_header('Location','http://127.0.0.1:1/leak');self.send_header('Content-Length','0');self.end_headers();return
        data=json.loads(body['messages'][-1]['content'])
        if data.get('connectivity_test'):value={'ok':True}
        elif not data.get('observations'):value={'phase':'inspect','calls':[{'tool':'commerce_runtime_status','arguments':{}}]}
        else:value={'phase':'answer','answer':'合成模型已读取当前允许的运行状态。','questions':[],'evidence_refs':['R1'],'proposals':[]}
        if body.get('response_format',{}).get('type')=='json_schema':
            if value.get('phase')=='inspect':value['calls']=[{'tool':c['tool'],'arguments_json':json.dumps(c['arguments'])} for c in value['calls']]
            value={'decision':value}
        content='not JSON' if type(self).mode=='bad_json' else json.dumps(value,ensure_ascii=False)
        raw=json.dumps({'model':body['model'],'choices':[{'message':{'content':content},'finish_reason':'stop'}]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except BrokenPipeError:pass

class ModelProviders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Endpoint);cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.worker.join()
    def setUp(self):
        Endpoint.requests=[];Endpoint.mode='ok';self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
        self.thread=self.app.copilot.open({'module':'overview','demo':True},'model-chat')
    def tearDown(self):self.app.agent_runtime.stop();self.temp.cleanup()
    def save(self,**kw):
        return self.app.models.configure({'label':'合成本地模型','engine':'llama_cpp','base_url':f'http://127.0.0.1:{self.server.server_port}/v1','model':'synthetic-local','api_key':'SECRET_MODEL_TEST','json_mode':True,**kw})
    def ready(self,**kw):
        p=self.save(**kw);self.app.models.test(p['id'],p['revision']);return self.app.models.set_enabled(p['id'],True,p['revision'])
    def select(self,p,revision='0'):
        return self.app.invoke('commerce_copilot_model',{'thread_id':self.thread['id'],'model_id':p['id'],'expected_revision':revision})
    def send(self,key='send'):
        return self.app.copilot.send(self.thread['id'],'核对当前运行状态',self.thread['context_sha256'],key)
    def test_legacy_default_is_visible_without_changing_private_route(self):
        self.assertTrue(hasattr(self.app,'models'),'Project model registry is missing')
        result=self.app.invoke('commerce_model_list',{})
        self.assertEqual(result['models'][0]['id'],'project-default')
        self.assertEqual(self.app.copilot.get(self.thread['id'])['model_selection']['model_id'],'project-default')
        self.assertEqual(Endpoint.requests,[])
    def test_configuration_and_probe_are_separate_and_keys_never_return(self):
        p=self.save();self.assertFalse(p['enabled']);self.assertEqual(Endpoint.requests,[])
        self.assertNotIn('SECRET_MODEL_TEST',json.dumps(self.app.models.catalog()))
        with self.assertRaisesRegex(ValueError,'model_not_ready'):self.select(p)
        tested=self.app.models.test(p['id'],p['revision']);self.assertEqual(tested['test_status'],'passed')
        p=self.app.models.set_enabled(p['id'],True,p['revision']);self.assertTrue(p['enabled'])
        self.assertEqual(Endpoint.requests[0]['path'],'/v1/chat/completions')
        self.assertEqual(Endpoint.requests[0]['authorization'],'Bearer SECRET_MODEL_TEST')
        self.assertNotIn('SECRET_MODEL_TEST',Path(self.temp.name,'commerce.sqlite').read_bytes().decode(errors='ignore'))
    def test_selection_persists_and_real_adapter_keeps_parent_tool_boundaries(self):
        p=self.ready();selected=self.select(p);self.assertEqual(selected['model_selection']['model_id'],p['id'])
        sent=self.send();self.assertEqual(sent['latest_run']['model_choice']['model'],'synthetic-local')
        with self.assertRaisesRegex(ValueError,'active_run'):self.app.models.select(self.thread['id'],'project-default','1')
        self.assertTrue(self.app.agent_runtime.run_once())
        done=self.app.copilot.get(self.thread['id']);self.assertEqual(done['latest_run']['status'],'completed')
        self.assertEqual(done['latest_run']['result']['observations'][0]['tool'],'commerce_runtime_status')
        self.assertEqual(done['latest_run']['result']['model'],'synthetic-local')
        self.assertEqual(len(Endpoint.requests),3)
        self.assertTrue(all(not r['body'].get('tools') for r in Endpoint.requests))
        self.assertEqual(Commerce(self.temp.name).copilot.get(self.thread['id'])['model_selection']['model_id'],p['id'])
    def test_queued_request_freezes_profile_and_retry_uses_original_run(self):
        p=self.ready();self.select(p);sent=self.send();run=sent['latest_run']['id']
        self.save(id=p['id'],expected_revision=p['revision'],model='different-model')
        self.assertEqual(self.send()['latest_run']['id'],run)
        self.app.agent_runtime.run_once();done=self.app.agent_runtime.get(run)
        self.assertEqual(done['result']['model'],'synthetic-local')
        self.assertEqual(done['model_choice']['profile_revision'],p['revision'])
    def test_stale_configuration_and_selection_are_rejected(self):
        p=self.ready();self.select(p)
        with self.assertRaisesRegex(ValueError,'model_selection_changed'):self.select(p)
        with self.assertRaisesRegex(ValueError,'model_profile_changed'):self.save(id=p['id'],expected_revision='0')
        self.assertEqual(self.app.copilot.get(self.thread['id'])['total_turns'],0)
    def test_bad_endpoints_redirects_and_invalid_model_outputs_fail_without_fallback(self):
        for endpoint in ['file:///tmp/model','http://user:pass@127.0.0.1/v1','http://169.254.169.254/v1','http://example.com/v1','https://example.com/v1?key=secret']:
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):self.save(base_url=endpoint)
        p=self.save();Endpoint.mode='redirect'
        with self.assertRaisesRegex(ValueError,'model_test_failed'):self.app.models.test(p['id'],p['revision'])
        self.assertEqual(len(Endpoint.requests),1)
        Endpoint.mode='ok';self.app.models.test(p['id'],p['revision']);self.app.models.set_enabled(p['id'],True,p['revision']);self.select(p);sent=self.send();Endpoint.mode='bad_json'
        self.app.agent_runtime.run_once();failed=self.app.agent_runtime.get(sent['latest_run']['id']);self.assertEqual(failed['status'],'failed')
        self.assertNotIn('SECRET_MODEL_TEST',json.dumps(failed))
    def test_explicit_disable_blocks_queued_generation(self):
        p=self.ready();self.select(p);sent=self.send();self.app.models.set_enabled(p['id'],False,p['revision']);before=len(Endpoint.requests)
        self.app.agent_runtime.run_once();self.assertEqual(len(Endpoint.requests),before)
        self.assertEqual(self.app.agent_runtime.get(sent['latest_run']['id'])['status'],'failed')

    def test_vllm_and_custom_json_modes_use_the_same_validated_task_contract(self):
        for engine,json_mode in [('vllm',True),('custom',False)]:
            with self.subTest(engine=engine):
                p=self.ready(engine=engine,json_mode=json_mode)
                current=self.app.copilot.get(self.thread['id'])['model_selection']['revision']
                self.select(p,current);sent=self.send(engine);self.app.agent_runtime.run_once()
                self.assertEqual(self.app.agent_runtime.get(sent['latest_run']['id'])['status'],'completed')
                body=Endpoint.requests[-1]['body']
                if engine=='vllm':
                    spec=body['response_format']['json_schema']['schema'];self.assertEqual(spec['properties']['decision']['anyOf'][0]['properties']['calls']['maxItems'],2)
                else:self.assertNotIn('response_format',body)

    def test_cancellation_stops_the_owned_http_process_without_resubmit(self):
        p=self.ready();self.select(p);sent=self.send();Endpoint.mode='slow'
        worker=threading.Thread(target=self.app.agent_runtime.run_once);worker.start()
        deadline=time.monotonic()+3
        while len(Endpoint.requests)<2 and time.monotonic()<deadline:time.sleep(.02)
        self.app.agent_runtime.cancel(sent['latest_run']['id']);worker.join(3)
        self.assertFalse(worker.is_alive());self.assertEqual(self.app.agent_runtime.get(sent['latest_run']['id'])['status'],'cancelled')
        self.assertEqual(len(Endpoint.requests),2)

    def test_model_catalog_preserves_client_validation_and_invalid_selection(self):
        with self.assertRaisesRegex(ValueError,'invalid_client'):self.app.invoke('commerce_model_list',{},'untrusted')
        with self.assertRaisesRegex(ValueError,'model_profile_not_found'):self.app.models.select(self.thread['id'],'unknown','0')
        self.assertEqual(self.app.copilot.get(self.thread['id'])['model_selection']['revision'],'0')

    def test_snapshot_pin_detects_other_tab_selection_and_profile_changes(self):
        original=self.app.copilot.get(self.thread['id'])['model_selection']['sha256'];p=self.ready();self.select(p)
        with self.app.core.db()as db:
            with self.assertRaisesRegex(ValueError,'copilot_model_changed'):self.app.models.snapshot(db,thread_id=self.thread['id'],expected_sha256=original)
        current=self.app.copilot.get(self.thread['id'])['model_selection']['sha256']
        with self.app.core.db()as db:self.assertEqual(self.app.models.snapshot(db,thread_id=self.thread['id'],expected_sha256=current)['model'],'synthetic-local')
        self.save(id=p['id'],expected_revision=p['revision'],model='other-model')
        with self.app.core.db()as db:
            with self.assertRaisesRegex(ValueError,'copilot_model_changed'):self.app.models.snapshot(db,thread_id=self.thread['id'],expected_sha256=current)

if __name__=='__main__':unittest.main()
