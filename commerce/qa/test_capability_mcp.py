"""Three real stdio clients read one isolated capability registry and run."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import test_paos_mcp as transport

ROOT=Path(__file__).resolve().parents[1]


class CapabilityMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name)
        cls.token='synthetic-capability-mcp';(cls.state/'auth.token').write_text(cls.token)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_extensible_runtime.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(150):
            try:
                if cls.call('commerce_media_provider_catalog',{})['profiles']:break
            except (OSError,ValueError,FileNotFoundError):pass
            time.sleep(.05)
        else:raise AssertionError('isolated capability server unavailable')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    def test_client_discovery_and_shared_immutable_identity(self):
        entry=self.call('commerce_extension_save',{'definition':{'kind':'skill','name':'Synthetic shared read','spec':{'steps':[{'id':'models','uses':{'builtin':'commerce_model_list'}}]}}})
        run=self.call('commerce_extension_test',{'extension_id':entry['id'],'idempotency_key':'same-test'})
        for _ in range(60):
            result=self.call('commerce_extension_run_get',{'run_id':run['id']})
            if result['status']=='succeeded':break
            time.sleep(.05)
        self.assertEqual(result['status'],'succeeded')
        profiles=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('commerce_extension_list','commerce_extension_get','commerce_extension_run_get','commerce_media_provider_catalog','commerce_media_provider_jobs'):
                    self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                for name in ('commerce_extension_run','commerce_extension_schedule_run','commerce_media_provider_generate'):
                    self.assertTrue(tools[name]['annotations']['openWorldHint']);self.assertFalse(tools[name]['annotations']['readOnlyHint'])
                self.assertNotIn('commerce_extension_credentials',tools);self.assertNotIn('commerce_media_provider_configure',tools)
                def call(name,args):
                    value=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result'];self.assertFalse(value.get('isError'),str(value));return value['structuredContent']
                current=call('commerce_extension_run_get',{'run_id':run['id']});self.assertEqual(current['task_id'],run['task_id']);self.assertEqual(current['output'],result['output'])
                catalog=call('commerce_media_provider_catalog',{})
                ids=[p['id'] for p in catalog['profiles']]
                if profiles is None:profiles=ids
                self.assertEqual(ids,profiles)


if __name__=='__main__':unittest.main()
