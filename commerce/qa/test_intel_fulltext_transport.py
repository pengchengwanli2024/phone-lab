"""Three real stdio adapters return the same local fulltext evidence via HTTP."""
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

ROOT = Path(__file__).resolve().parents[1]


class FullTextTransport(unittest.TestCase):
    call = classmethod(transport.AdoptionMCP.call.__func__)
    mcp = transport.AdoptionMCP.mcp
    rpc = transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.tmp.name)
        cls.token = 'synthetic-workbench-preview'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            cls.port = sock.getsockname()[1]
        cls.env = dict(os.environ, COMMERCE_STATE=str(cls.state), COMMERCE_PORT=str(cls.port), COMMERCE_QA_INTEL='1')
        cls.process = subprocess.Popen([sys.executable,str(ROOT/'qa/react_workbench_fixture.py')],
                                      env=cls.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                if cls.call('commerce_intel_search', {'query':'合成文章'})['total'] == 1:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.05)
        cls.tearDownClass()
        raise AssertionError('isolated intelligence fixture did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.process.stderr.close()
        cls.tmp.cleanup()

    def test_three_clients_share_exact_evidence_and_readonly_contract(self):
        expected = self.call('commerce_intel_search', {'query':'合成文章'})['items'][0]['search_match']
        before = self.call('commerce_task_list', {})['tasks']
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client), self.mcp(client) as process:
                descriptor = next(t for t in self.rpc(process,'tools/list',{})['result']['tools'] if t['name']=='commerce_intel_search')
                self.assertTrue(descriptor['annotations']['readOnlyHint'])
                result = self.rpc(process,'tools/call',{'name':'commerce_intel_search','arguments':{'query':'合成文章'}})['result']
                self.assertFalse(result.get('isError'),str(result))
                self.assertEqual(result['structuredContent']['items'][0]['search_match'],expected)
        self.assertEqual(self.call('commerce_task_list',{})['tasks'],before)


if __name__ == '__main__':
    unittest.main()
