"""Actual stdio -> authenticated shared HTTP -> calculator, isolated state."""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a2ui.cost import CATALOG_ID
from test_a2ui_cost import INPUT

ROOT = Path(__file__).resolve().parents[1]


class SharedMCP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]; sock.close()
        self.env = dict(os.environ, COMMERCE_STATE=self.tmp.name, COMMERCE_PORT=str(port))

    def tearDown(self):
        descriptor = Path(self.tmp.name) / 'runtime.json'
        if descriptor.exists():
            pid=json.loads(descriptor.read_text())['pid']
            try: os.kill(pid, signal.SIGTERM)
            except ProcessLookupError: pass
            # The isolated service drains workers after SIGTERM. Wait before
            # removing its directory, otherwise late log writes race rmtree.
            until=time.monotonic()+5
            while time.monotonic()<until:
                try:os.kill(pid,0)
                except ProcessLookupError:break
                time.sleep(.05)
            else:
                os.kill(pid,signal.SIGKILL)
                time.sleep(.1)
        self.tmp.cleanup()

    def session(self, client, messages, supports=False):
        init = {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {'a2ui': {'1.0': {'supportedCatalogIds': [CATALOG_ID]}}} if supports else {}}}
        payload = [init] + [dict(message, id=i+2) for i, message in enumerate(messages)]
        result = subprocess.run([sys.executable, str(ROOT / 'mcp_server.py'), client], input=''.join(json.dumps(dict(jsonrpc='2.0', **m))+'\n' for m in payload), text=True, capture_output=True, env=self.env, timeout=30)
        self.assertEqual(result.returncode, 0)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies), len(payload))
        return [r['result'] for r in replies]

    def call(self, client, name, args=None, supports=False):
        return self.session(client, [{'method': 'tools/call', 'params': {'name': name, 'arguments': args or {}}}], supports)[1]

    def test_three_clients_share_surface_task_and_real_calculation(self):
        created = self.call('codex', 'commerce_a2ui_create', supports=True)
        self.assertFalse(created['isError'])
        self.assertEqual(created['content'][1]['resource']['mimeType'], 'application/a2ui+json')
        surface = created['structuredContent']; sid = surface['surface_id']
        for client in ('codex', 'hermes', 'harness'):
            self.assertEqual(self.call(client, 'commerce_a2ui_get', {'surface_id': sid})['structuredContent']['task_id'], surface['task_id'])
            task = self.call(client, 'commerce_task_get', {'task_id': surface['task_id']})['structuredContent']
            self.assertEqual(task['input']['surface_id'], sid)
        event = {'version': '1.0', 'action': {'name': 'commerce.cost.calculate', 'surfaceId': sid, 'sourceComponentId': 'calculate', 'timestamp': '2026-01-01T00:00:00Z', 'context': {}}}
        result = self.call('hermes', 'commerce_a2ui_action', {'event': event, 'revision': '0', 'input': INPUT})
        self.assertFalse(result['isError'])
        self.assertEqual(result['structuredContent']['result']['contribution'], 38)
        self.assertIn('38.00 CNY', result['content'][0]['text'])
        self.assertEqual(len(result['content']), 1)  # No assumed native rendering.
        ordinary = self.call('harness', 'commerce_unit_economics', {'input': INPUT})
        # The current shared service adds a fresh evidence envelope around the
        # same calculator. Compare every calculator field, retaining metadata.
        self.assertEqual({key: ordinary['structuredContent'][key] for key in result['structuredContent']['result']}, result['structuredContent']['result'])
        self.assertEqual(json.loads(ordinary['content'][0]['text']), ordinary['structuredContent'])
        resources = self.session('harness', [{'method': 'resources/read', 'params': {'uri': 'a2ui://commerce/cost/'+sid}}])[1]
        self.assertEqual(json.loads(resources['contents'][0]['text'])[0]['version'], '1.0')
        for name in ('commerce_task_create', 'evil', 'commerce.cost.calculate'):
            bad = json.loads(json.dumps(event)); bad['action']['name'] = name
            if name == 'commerce.cost.calculate': bad['action']['sourceComponentId'] = 'root'
            response = self.call('codex', 'commerce_a2ui_action', {'event': bad, 'revision': '1', 'input': INPUT})
            self.assertTrue(response['isError'])
        tools = self.session('codex', [{'method': 'tools/list'}])[1]['tools']
        self.assertTrue(next(t for t in tools if t['name']=='commerce_a2ui_get')['annotations']['readOnlyHint'])
        self.assertFalse(next(t for t in tools if t['name']=='commerce_a2ui_action')['annotations']['readOnlyHint'])


if __name__ == '__main__': unittest.main()
