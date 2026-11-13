"""The native broker is a bearer-only local control plane, not a chat tool."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from service import Commerce


class HostWorkerHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name)
        class PrivateHandler(server.Handler):
            service=self.app
            secret='synthetic-worker-secret'
        self.http=ThreadingHTTPServer(('127.0.0.1',0),PrivateHandler)
        self.port=patch.object(server,'PORT',self.http.server_address[1]);self.port.start()
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();self.port.stop()
        self.app.agent_runtime.stop();self.tmp.cleanup()

    def call(self,headers):
        body=json.dumps({'operation':'register','arguments':{'host_id':'dsh','provider':'synthetic','model':'synthetic'}}).encode()
        req=urllib.request.Request(f'http://127.0.0.1:{self.http.server_address[1]}/v1/host-worker',data=body,
            headers={'Content-Type':'application/json',**headers})
        try:
            with urllib.request.urlopen(req,timeout=3) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:return error.code,json.load(error)

    def test_owner_browser_cookie_cannot_register_a_native_worker(self):
        code,body=self.call({'Cookie':'commerce_session=synthetic-worker-secret'})
        self.assertEqual(code,401)
        self.assertEqual(self.app.host_execution.listing()['hosts'],[])

    def test_bearer_broker_registers_metadata_without_enqueuing_a_task(self):
        code,body=self.call({'Authorization':'Bearer synthetic-worker-secret'})
        self.assertEqual(code,200)
        self.assertEqual(body['host_id'],'dsh')
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],0)


if __name__=='__main__':unittest.main()
