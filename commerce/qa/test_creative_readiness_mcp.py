"""Three real MCP clients share read-only preparation checks on an empty draft."""
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


class ReadinessMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name);cls.token='synthetic-preparation-read'
        (cls.state/'auth.token').write_text(cls.token)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_creative_readiness.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(150):
            try:
                cls.fixture=json.loads((cls.state/'readiness-fixture.json').read_text())
                cls.call('commerce_media_readiness',{'project_id':cls.fixture['project_id']});break
            except (OSError,ValueError,FileNotFoundError):time.sleep(.05)
        else:
            cls.process.terminate();cls.process.wait(timeout=10)
            raise AssertionError('isolated preparation server unavailable')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    def test_clients_discover_readonly_contract_and_do_not_create_work(self):
        before=self.call('commerce_task_list',{});project=self.call('commerce_creative_get',{'project_id':self.fixture['project_id']})
        expected=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                definition=tools['commerce_media_readiness'];self.assertTrue(definition['annotations']['readOnlyHint'])
                self.assertFalse(definition['annotations']['openWorldHint']);self.assertEqual(definition['inputSchema']['required'],['project_id'])
                result=self.rpc(process,'tools/call',{'name':'commerce_media_readiness','arguments':{'project_id':project['id']}})['result']
                self.assertFalse(result.get('isError'));value=result['structuredContent']
                self.assertFalse(value['generation_authorized']);self.assertFalse(value['formats']['product_main']['can_create_request'])
                common={k:value[k] for k in ('project_id','project_revision','checks','formats')}
                if expected is None:expected=common
                else:self.assertEqual(common,expected)
                self.assertNotIn(str(self.state),json.dumps(value))
                denied=self.rpc(process,'tools/call',{'name':'commerce_media_readiness','arguments':{'project_id':'0'*32}})['result']
                self.assertTrue(denied['isError'])
        self.assertEqual(self.call('commerce_task_list',{}),before)
        self.assertEqual(self.call('commerce_creative_get',{'project_id':project['id']})['revision'],project['revision'])
        self.assertEqual(self.call('commerce_media_overview',{'project_id':project['id']})['requests'],[])


if __name__=='__main__':unittest.main()
