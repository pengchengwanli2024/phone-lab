"""Isolated real HTTP/stdio acceptance; synthetic provider, no installed-host claim."""
import json
import os
from pathlib import Path
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
sys.path.insert(0, str(ROOT))
from protocols.a2ui import validate_surface


class CopilotTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='commerce-transport-')
        cls.state = Path(cls.temp.name) / 'state'
        cls.state.mkdir(mode=0o700)
        cls.secret = 'synthetic-transport-acceptance-only'
        (cls.state / 'auth.token').write_text(cls.secret)
        (cls.state / 'auth.token').chmod(0o600)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            cls.port = listener.getsockname()[1]
        cls.origin = f'http://127.0.0.1:{cls.port}'
        cls.env = {**os.environ, 'COMMERCE_STATE': str(cls.state), 'COMMERCE_PORT': str(cls.port)}
        cls.process = None
        try:
            cls.start_server()
        except Exception:
            cls.stop_server()
            cls.temp.cleanup()
            raise

    @classmethod
    def start_server(cls):
        cls.process = subprocess.Popen([sys.executable, str(ROOT / 'qa/fixture_copilot.py')],
            env=cls.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise AssertionError('isolated synthetic service exited')
            try:
                cls.http('/v1/health')
                return
            except (OSError, ValueError):
                time.sleep(.05)
        raise AssertionError('isolated synthetic service startup deadline')

    @classmethod
    def stop_server(cls):
        if cls.process is not None and cls.process.poll() is None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        cls.temp.cleanup()

    @classmethod
    def http(cls, path, data=None, auth=True, headers=None):
        body = None if data is None else json.dumps(data).encode()
        request_headers = {'Content-Type': 'application/json'}
        if auth:
            request_headers['Authorization'] = 'Bearer ' + cls.secret
        request_headers.update(headers or {})
        request = urllib.request.Request(cls.origin + path, data=body, headers=request_headers)
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.load(response)

    @classmethod
    def call(cls, name, arguments=None):
        return cls.http('/v1/invoke', {'tool': name, 'arguments': arguments or {}, 'client': 'test'})

    @classmethod
    def a2a(cls, method, params):
        return cls.http('/a2a', {'jsonrpc': '2.0', 'id': 'synthetic-rpc', 'method': method, 'params': params})

    def send(self, message_id, text, context_id=None):
        message = {'kind': 'message', 'role': 'user', 'messageId': message_id,
                   'parts': [{'kind': 'text', 'text': text}]}
        if context_id is not None:
            message['contextId'] = context_id
        response = self.a2a('message/send', {'message': message})
        self.assertNotIn('error', response)
        return response['result']

    def poll(self, ident, expected):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = self.a2a('tasks/get', {'id': ident})
            self.assertNotIn('error', result)
            task = result['result']
            if task['status']['state'] in expected:
                return task
            self.assertNotIn(task['status']['state'], {'failed', 'rejected'})
            time.sleep(.05)
        self.fail('synthetic task completion deadline')

    def test_01_discovery_auth_and_host_origin(self):
        rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'tasks/get', 'params': {'id': 'absent'}}
        for path, data in [('/.well-known/agent-card.json', None), ('/a2a', rpc)]:
            for auth, headers, code in [(False, {}, 401), (True, {'Origin': 'https://hostile.example'}, 403),
                                        (True, {'Host': 'hostile.example'}, 403)]:
                with self.subTest(route=path, status=code):
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        self.http(path, data, auth=auth, headers=headers)
                    self.assertEqual(raised.exception.code, code)
                    raised.exception.close()
        card = self.http('/.well-known/agent-card.json')
        self.assertEqual(card['url'], self.origin + '/a2a')
        self.assertEqual(card['protocolVersion'], '0.3.0')
        self.assertEqual(card['preferredTransport'], 'JSONRPC')
        self.assertEqual(card['securitySchemes']['localBearer'], {'type': 'http', 'scheme': 'bearer'})
        self.assertTrue(card['security'])
        self.assertFalse(card['capabilities']['streaming'])
        self.assertFalse(card['capabilities']['pushNotifications'])

    def test_02_http_idempotent_context_followup_and_surfaces(self):
        # Optional knowledge failure does not block discovery, send or runner reads.
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.call('commerce_knowledge_list')
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()
        self.assertEqual(self.call('commerce_status')['version'], '0.1.0')
        task = self.send('http-first', 'Inspect current runtime')
        self.assertEqual(self.send('http-first', 'Inspect current runtime')['id'], task['id'])
        completed = self.poll(task['id'], {'completed'})
        parts = completed['artifacts'][0]['parts']
        self.assertEqual(parts[0]['kind'], 'text')
        data = next(part['data'] for part in parts if part['kind'] == 'data')
        self.assertEqual(data['a2uiVersion'], '0.8')
        self.assertTrue(validate_surface(data['messages']))
        followup = self.send('http-followup', 'Explain the previous evidence', task['contextId'])
        self.assertNotEqual(followup['id'], task['id'])
        self.assertEqual(followup['contextId'], task['contextId'])
        self.poll(followup['id'], {'completed'})
        self.assertEqual(self.send('http-first', 'Inspect current runtime')['id'], task['id'])
        thread = self.call('commerce_copilot_get', {'thread_id': task['contextId']})
        self.assertEqual(len(thread['turns']), 2)
        self.assertEqual({t['run']['id'] for t in thread['turns']}, {task['id'], followup['id']})
        changed = self.call('commerce_copilot_context', {'thread_id': thread['id'],
            'expected_context_sha256': thread['context_sha256'], 'context': {'module': 'products', 'demo': True}})
        self.assertNotEqual(changed['context_sha256'], thread['context_sha256'])
        self.assertEqual(self.send('http-first', 'Inspect current runtime')['id'], task['id'])
        self.assertEqual(self.call('commerce_copilot_get', {'thread_id': thread['id']})['total_turns'], 2)

    def test_03_cancel_running_and_reconstruct_server(self):
        task = self.send('http-slow', 'slow synthetic cancellable request')
        self.poll(task['id'], {'working'})
        canceled = self.a2a('tasks/cancel', {'id': task['id']})
        self.assertNotIn('error', canceled)
        self.poll(task['id'], {'canceled'})
        self.stop_server()
        self.start_server()
        restored = self.a2a('tasks/get', {'id': task['id']})['result']
        self.assertEqual(restored['status']['state'], 'canceled')
        self.assertEqual(restored['contextId'], task['contextId'])
        self.assertEqual(self.send('http-slow', 'slow synthetic cancellable request')['id'], task['id'])
        self.assertEqual(len(self.call('commerce_copilot_get', {'thread_id': task['contextId']})['turns']), 1)

    def rpc(self, process, method, params=None):
        request = {'jsonrpc': '2.0', 'id': 'acceptance', 'method': method, 'params': params or {}}
        process.stdin.write(json.dumps(request) + '\n')
        process.stdin.flush()
        ready, _, _ = select.select([process.stdout], [], [], 15)
        self.assertTrue(ready, 'stdio MCP response deadline')
        response = json.loads(process.stdout.readline())
        self.assertNotIn('error', response)
        return response['result']

    def mcp_call(self, process, name, arguments=None):
        result = self.rpc(process, 'tools/call', {'name': name, 'arguments': arguments or {}})
        self.assertFalse(result.get('isError'), 'synthetic MCP tool failed')
        return result['structuredContent']

    def test_04_three_stdio_clients_share_threads_runs_and_annotations(self):
        clients = []
        names = ['codex', 'hermes', 'harness']
        expected = {'commerce_copilot_' + suffix for suffix in ['open', 'list', 'get', 'send', 'context', 'cancel', 'apply']}
        try:
            for name in names:
                process = subprocess.Popen([sys.executable, str(ROOT / 'mcp_server.py'), name], env=self.env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
                clients.append(process)
                hello = self.rpc(process, 'initialize', {'protocolVersion': '2025-11-25',
                    'clientInfo': {'name': 'synthetic-' + name, 'version': '1'}, 'capabilities': {}})
                self.assertEqual(hello['protocolVersion'], '2025-11-25')
                self.assertEqual(hello['serverInfo']['name'], 'commerce-backend')
                tools = {t['name']: t for t in self.rpc(process, 'tools/list')['tools'] if t['name'].startswith('commerce_copilot_')}
                self.assertEqual(set(tools), expected)
                for tool_name, tool in tools.items():
                    annotation = tool['annotations']
                    self.assertEqual(annotation['readOnlyHint'], tool_name in {'commerce_copilot_list', 'commerce_copilot_get'})
                    self.assertEqual(annotation['openWorldHint'], tool_name == 'commerce_copilot_send')
                    self.assertFalse(annotation['destructiveHint'])
            thread = self.mcp_call(clients[0], 'commerce_copilot_open', {'context': {'module': 'orders', 'demo': True}, 'idempotency_key': 'three-clients'})
            self.assertEqual(thread['turns'], [])
            run_ids = []
            for index, process in enumerate(clients):
                current = self.mcp_call(process, 'commerce_copilot_get', {'thread_id': thread['id']})
                self.assertEqual(current['id'], thread['id'])
                self.assertEqual(len(current['turns']), index)
                sent = self.mcp_call(process, 'commerce_copilot_send', {'thread_id': thread['id'],
                    'context_sha256': current['context_sha256'], 'message': 'Inspect scoped evidence turn ' + str(index),
                    'idempotency_key': 'client-turn-' + str(index)})
                ident = sent['latest_run']['id']
                run_ids.append(ident)
                self.poll(ident, {'completed'})
            for process in clients:
                shared = self.mcp_call(process, 'commerce_copilot_get', {'thread_id': thread['id']})
                self.assertEqual([t['run']['id'] for t in shared['turns']], run_ids)
                self.assertTrue(all(t['run']['result']['provider'] == 'synthetic-no-network' for t in shared['turns']))
            self.assertTrue(set(names) <= set(self.call('commerce_status')['clients']))
        finally:
            for process in clients:
                process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                process.stdout.close()

    def test_05_report_scope_is_preserved_over_http(self):
        report = self.call('commerce_report_create', {'demo': True, 'platform': 'amazon', 'market': 'US',
            'store_id': 'amazon-demo', 'idempotency_key': 'transport-scoped-report'})
        self.assertEqual(report['scope']['platform'], 'amazon')
        self.assertEqual(report['scope']['store_id'], 'amazon-demo')
        self.assertEqual(report['scope']['market'], 'US')
        self.assertIn('28,640', report['content'])
        self.assertNotIn('128,640', report['content'])


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CopilotTransport)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    # Persist only synthetic outcomes; no tokens, state paths, run IDs or logs.
    destination = ROOT.parent / '.commerce-state/verification/assistant-upgrade-20261112/copilot-transport-result.json'
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_text(json.dumps({'status': 'passed' if result.wasSuccessful() else 'failed',
        'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'provider': 'synthetic-no-network', 'transports': ['HTTP', 'stdio MCP'],
        'stdio_client_labels': ['codex', 'hermes', 'harness'],
        'installed_host_compatibility_verified': False, 'external_writes': False,
        'checks': ['authenticated discovery and RPC', 'host/origin rejection', 'idempotent message identity',
            'completed synthetic artifacts with valid A2UI', 'context followup and frozen-context replay', 'running cancellation',
            'server reconstruction persistence', 'three stdio clients share thread/run state',
            'seven copilot tool annotations', 'optional knowledge failure isolation', 'report scope filters']},
        ensure_ascii=False, indent=2) + '\n')
    sys.exit(0 if result.wasSuccessful() else 1)
