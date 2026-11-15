"""Private setup and registered capability tools use one authenticated service."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from service import Commerce, TOOLS


class CapabilityHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name)
        class Handler(server.Handler):service=self.app;secret='synthetic-capability-auth'
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.port=patch.object(server,'PORT',self.http.server_port);self.port.start()
        self.origin='http://127.0.0.1:'+str(self.http.server_port)
        self.worker=threading.Thread(target=self.http.serve_forever,daemon=True);self.worker.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.worker.join()
        self.app.autonomy.stop();self.app.agent_runtime.stop();self.port.stop();self.tmp.cleanup()

    def request(self,path,data=None,authenticated=True):
        headers={'Content-Type':'application/json'}
        if authenticated:headers['Authorization']='Bearer synthetic-capability-auth'
        req=urllib.request.Request(self.origin+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=3) as r:return r.status,r.read().decode()
        except urllib.error.HTTPError as r:
            try:return r.code,r.read().decode()
            finally:r.close()

    def test_private_setup_and_configuration_reject_unauthenticated_access(self):
        for path,data in [('/capability-setup',None),('/v1/media/providers/configure',{}),('/v1/extensions/credentials',{})]:
            code,body=self.request(path,data,False);self.assertEqual(code,401);self.assertIn('authentication_required',body)
        code,page=self.request('/capability-setup');self.assertEqual(code,200);self.assertIn('capability-setup-root',page)
        self.assertNotIn('synthetic-capability-auth',page)

    def test_configuration_route_roundtrips_without_exposing_key_to_tools(self):
        code,raw=self.request('/v1/media/providers/configure',{'label':'Synthetic media','provider':'local','adapter':'generic_json_async',
            'base_url':'http://127.0.0.1:8188','model':'synthetic','media_kind':'image','enabled':False,'api_key':'synthetic-private-key',
            'capabilities':{'image_input':True},'protocol':{'submit_path':'/jobs','submit_body':{'model':'{{model}}','prompt':'{{prompt}}','images':'{{images}}'},'outputs_path':'outputs','output_base64_path':'base64'}})
        self.assertEqual(code,200,raw);profile=json.loads(raw);self.assertTrue(profile['key_configured']);self.assertNotIn('synthetic-private-key',raw)
        code,raw=self.request('/v1/invoke',{'tool':'commerce_media_provider_catalog','arguments':{},'client':'codex'})
        self.assertEqual(code,200);self.assertIn(profile['id'],raw);self.assertNotIn('synthetic-private-key',raw)
        for name,_,schema in TOOLS:
            if name.startswith(('commerce_extension_','commerce_media_provider_')):
                self.assertNotIn('api_key',schema.get('properties',{}));self.assertNotIn('credentials',name)

    def test_registered_extension_dispatch_and_core_task_share_result(self):
        entry=self.app.invoke('commerce_extension_save',{'definition':{'kind':'skill','name':'Synthetic read','spec':{'steps':[{'id':'status','uses':{'builtin':'commerce_model_list'}}]}}})
        run=self.app.invoke('commerce_extension_test',{'extension_id':entry['id'],'idempotency_key':'test'})
        self.app.extensions._process(run['id'])
        self.app.invoke('commerce_extension_enable',{'extension_id':entry['id'],'expected_version':entry['version'],'enabled':True})
        code,raw=self.request('/v1/invoke',{'tool':'commerce_extension_run','arguments':{'extension_id':entry['id'],'idempotency_key':'run'},'client':'harness'})
        self.assertEqual(code,200,raw);run=json.loads(raw);self.app.extensions._process(run['id'])
        read=self.app.invoke('commerce_extension_run_get',{'run_id':run['id']},'hermes')
        self.assertEqual(read['status'],'succeeded');self.assertEqual(self.app.core.invoke('commerce_task_get',{'task_id':run['task_id']})['status'],'completed')
        self.assertIn('project-default',json.dumps(read['output']))
        result=self.app.invoke('commerce_task_result',{'task_id':run['task_id']})
        self.assertEqual(result['extension_run_id'],run['id']);self.assertEqual(result['execution']['result']['output'],read['output'])
        pending=self.app.invoke('commerce_extension_run',{'extension_id':entry['id'],'idempotency_key':'cancel-via-core'})
        self.app.invoke('commerce_task_cancel',{'task_id':pending['task_id']})
        self.assertEqual(self.app.invoke('commerce_extension_run_get',{'run_id':pending['id']})['status'],'cancelled')


if __name__=='__main__':unittest.main()
