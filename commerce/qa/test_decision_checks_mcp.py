"""Real loopback HTTP and stdio MCP calls for the stateless decision checks."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('commerce_selection_scorecard', 'commerce_demand_trend_assess', 'commerce_competitor_changes',
         'commerce_shipment_reconcile', 'commerce_experiment_evaluate')
EXPERIMENT = {'primary_metric': 'conversion', 'changed_variables': ['main image'], 'higher_is_better': True,
              'baseline': {'trials': 1000, 'successes': 100}, 'variant': {'trials': 1000, 'successes': 150}}


class DecisionChecksMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.tmp.name)
        cls.token = 'synthetic-decision-checks-token'
        (cls.state / 'auth.token').write_text(cls.token)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.env = dict(os.environ, COMMERCE_STATE=str(cls.state), COMMERCE_PORT=str(cls.port),
                       NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cls.process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], env=cls.env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(200):
                try:
                    cls.call('commerce_task_list', {})
                    break
                except (OSError, ValueError):
                    time.sleep(.05)
            else:
                raise RuntimeError('isolated_commerce_start_failed')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.process.stderr.close()
        cls.tmp.cleanup()

    @classmethod
    def call(cls, name, args, token=None):
        request = urllib.request.Request(f'http://127.0.0.1:{cls.port}/v1/invoke',
            data=json.dumps({'tool': name, 'arguments': args, 'client': 'test'}).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token or cls.token)})
        with cls.opener.open(request, timeout=10) as response:
            return json.load(response)

    @contextmanager
    def mcp(self, client):
        process = subprocess.Popen([sys.executable, str(ROOT / 'mcp_server.py'), client], env=self.env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertIn('result', self.rpc(process, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}}))
            yield process
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()

    def rpc(self, process, method, params):
        process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 15)
        self.assertTrue(ready, 'MCP response deadline')
        return json.loads(process.stdout.readline())

    def test_three_stdio_clients_discover_readonly_tools_and_get_the_same_result(self):
        direct = self.call('commerce_experiment_evaluate', {'input': EXPERIMENT})
        self.assertEqual(direct['outcome'], 'VARIANT_FAVORED')
        for client in ('codex', 'hermes', 'harness'):
            with self.subTest(client=client), self.mcp(client) as process:
                listed = {tool['name']: tool for tool in self.rpc(process, 'tools/list', {})['result']['tools']}
                for name in NAMES:
                    annotations = listed[name]['annotations']
                    self.assertTrue(annotations['readOnlyHint'], name)
                    self.assertFalse(annotations['destructiveHint'], name)
                    self.assertFalse(annotations['openWorldHint'], name)
                    self.assertEqual(listed[name]['inputSchema']['required'], ['input'])
                result = self.rpc(process, 'tools/call', {'name': 'commerce_experiment_evaluate',
                                                          'arguments': {'input': EXPERIMENT}})['result']
                self.assertFalse(result['isError'])
                self.assertEqual(result['structuredContent'], direct)
                rejected = self.rpc(process, 'tools/call', {'name': 'commerce_shipment_reconcile',
                                                            'arguments': {'input': {}}})['result']
                self.assertTrue(rejected['isError'])
        self.assertEqual(self.call('commerce_task_list', {})['tasks'], [])

    def test_http_requires_the_local_token_and_reports_invalid_input(self):
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.call('commerce_experiment_evaluate', {'input': EXPERIMENT}, token='wrong-token')
        self.assertIn(denied.exception.code, (401, 403))
        denied.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.call('commerce_selection_scorecard', {'input': {'candidates': []}})
        self.assertEqual(invalid.exception.code, 400)
        self.assertIn('decision_invalid_candidates', invalid.exception.read().decode())
        invalid.exception.close()


if __name__ == '__main__':
    unittest.main()
