"""Real loopback HTTP and stdio MCP calls using private synthetic state."""
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


class AdoptionMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.tmp.name)
        cls.token = 'synthetic-paos-adoption-token'
        (cls.state / 'auth.token').write_text(cls.token)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.env = dict(os.environ, COMMERCE_STATE=str(cls.state), COMMERCE_PORT=str(cls.port))
        cls.process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], env=cls.env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
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
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    @contextmanager
    def mcp(self, client):
        process = subprocess.Popen([sys.executable, str(ROOT / 'mcp_server.py'), client], env=self.env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            result = self.rpc(process, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}})
            self.assertIn('result', result)
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

    def test_three_mcp_clients_discover_and_call_readonly_packing(self):
        payload = {'container': {'length_cm': 10, 'width_cm': 10, 'height_cm': 10, 'max_weight_kg': 5},
                   'items': [{'sku': 'SYNTHETIC-A', 'length_cm': 5, 'width_cm': 5, 'height_cm': 5,
                              'weight_kg': 1, 'quantity': 2}]}
        for client in ('codex', 'hermes', 'harness'):
            with self.subTest(client=client), self.mcp(client) as process:
                tools = self.rpc(process, 'tools/list', {})['result']['tools']
                descriptor = next(t for t in tools if t['name'] == 'commerce_packing_estimate')
                self.assertTrue(descriptor['annotations']['readOnlyHint'])
                self.assertFalse(descriptor['annotations']['openWorldHint'])
                self.assertIn('input', descriptor['inputSchema']['required'])
                result = self.rpc(process, 'tools/call', {'name': 'commerce_packing_estimate', 'arguments': {'input': payload}})['result']
                self.assertFalse(result['isError'])
                self.assertEqual(result['structuredContent']['placed_units'], 2)
                rejected = self.rpc(process, 'tools/call', {'name': 'commerce_packing_estimate', 'arguments': {'input': {}}})['result']
                self.assertTrue(rejected['isError'])
        self.assertEqual(self.call('commerce_task_list', {})['tasks'], [])

    def test_cross_client_review_result_is_shared_and_exportable(self):
        doc = self.call('commerce_business_template', {'kind': 'reviews'})['document']
        doc['records'] = [{'id': 'synthetic-r1', 'text': 'Сборка сложная, запах', 'rating': 2}]
        source = self.call('commerce_business_import', {'document': doc, 'idempotency_key': 'review-source'})
        with self.mcp('codex') as process:
            analysis = self.rpc(process, 'tools/call', {'name': 'commerce_business_analyze', 'arguments': {
                'source_ids': [source['source_id']], 'idempotency_key': 'review-analysis'}})['result']['structuredContent']
        with self.mcp('hermes') as process:
            loaded = self.rpc(process, 'tools/call', {'name': 'commerce_business_get', 'arguments': {
                'draft_id': analysis['id']}})['result']['structuredContent']
        with self.mcp('harness') as process:
            result = self.rpc(process, 'tools/call', {'name': 'commerce_business_export', 'arguments': {
                'draft_id': analysis['id']}})['result']['structuredContent']
        self.assertEqual(loaded['draft'], analysis['draft'])
        self.assertTrue(loaded['draft']['content']['sample_insufficient'])
        self.assertEqual(json.loads(result['content'])['draft']['draft']['content']['total_records'], 1)

    def test_packing_uses_existing_authentication_boundary(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call('commerce_packing_estimate', {'input': {}}, token='invalid-synthetic-token')
        self.assertEqual(error.exception.code, 401)
        error.exception.close()

    def test_round2_import_and_memory_cross_the_same_three_mcp_entries(self):
        with self.mcp('codex') as process:
            tools = self.rpc(process, 'tools/list', {})['result']['tools']
            by_name = {t['name']: t for t in tools}
            for name in ['commerce_order_import_get', 'commerce_workflow_plan_get', 'commerce_memory_get', 'commerce_memory_search']:
                self.assertTrue(by_name[name]['annotations']['readOnlyHint'])
            for name in ['commerce_order_import_confirm', 'commerce_memory_confirm', 'commerce_workflow_plan_save']:
                self.assertFalse(by_name[name]['annotations']['readOnlyHint'])
            body = {'filename': 'synthetic-mcp.csv', 'content': 'order,sku,date,qty,price,currency\nSYN-1,A,2026-11-01,2,1.25,CNY\n',
                    'scope': {'platform': 'ozon', 'store_ref': 'synthetic-store', 'market': 'RU'}, 'synthetic': True,
                    'field_mapping': {'order_id': 'order', 'sku': 'sku', 'order_date': 'date', 'quantity': 'qty', 'unit_price': 'price', 'currency': 'currency'},
                    'idempotency_key': 'mcp-preview'}
            batch = self.rpc(process, 'tools/call', {'name': 'commerce_order_import_preview', 'arguments': body})['result']['structuredContent']
        with self.mcp('hermes') as process:
            saved = self.rpc(process, 'tools/call', {'name': 'commerce_order_import_confirm', 'arguments': {
                'batch_id': batch['id'], 'expected_sha256': batch['sha256'], 'confirmed': True, 'idempotency_key': 'mcp-confirm'}})['result']['structuredContent']
        self.assertEqual(saved['accepted_count'], 1)
        with self.mcp('harness') as process:
            result = self.rpc(process, 'tools/call', {'name': 'commerce_orders_list', 'arguments': {
                'demo': True, 'import_batch_id': batch['id']}})['result']['structuredContent']
            self.assertEqual(result['orders'][0]['amount'], '2.50')
        doc = self.call('commerce_business_template', {'kind': 'facts'})['document']
        doc['records'] = [{'key': 'material', 'value': 'synthetic cotton'}]
        source = self.call('commerce_business_import', {'document': doc, 'idempotency_key': 'memory-source'})
        with self.mcp('codex') as process:
            fact = self.rpc(process, 'tools/call', {'name': 'commerce_memory_propose', 'arguments': {
                'content': 'Synthetic source states cotton', 'bindings': [{'source_id': source['source_id'], 'version': source['version'],
                    'sha256': source['sha256'], 'record_key': 'material', 'quote': 'cotton'}], 'idempotency_key': 'memory-fact'}})['result']['structuredContent']
        with self.mcp('hermes') as process:
            fact = self.rpc(process, 'tools/call', {'name': 'commerce_memory_confirm', 'arguments': {
                'memory_id': fact['id'], 'expected_revision': fact['revision'], 'expected_sha256': fact['sha256'], 'confirmed': True,
                'idempotency_key': 'memory-fact-confirm'}})['result']['structuredContent']
        with self.mcp('harness') as process:
            summary = self.rpc(process, 'tools/call', {'name': 'commerce_memory_summarize', 'arguments': {
                'fact_ids': [fact['id']], 'title': 'Synthetic summary', 'idempotency_key': 'memory-summary'}})['result']['structuredContent']
            self.assertEqual(summary['layer'], 'L3')


if __name__ == '__main__':
    unittest.main()
