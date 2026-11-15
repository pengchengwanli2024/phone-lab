"""Real HTTP and three stdio clients against one isolated synthetic service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import test_copilot_transport as transport


class AttentionTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = transport.CopilotTransport
        cls.fixture.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def test_read_only_discovery_and_same_http_records_on_three_stdio_clients(self):
        original = self.fixture.call('commerce_attention_list')
        self.assertEqual(original['items'], [])
        root = Path(__file__).resolve().parents[1]
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'commerce_attention_list', 'arguments': {}}},
        ]
        for client in ('codex', 'hermes', 'harness'):
            done = subprocess.run([sys.executable, str(root / 'mcp_server.py'), client],
                env=self.fixture.env, input=''.join(json.dumps(m) + '\n' for m in messages),
                capture_output=True, text=True, timeout=15, check=True)
            replies = [json.loads(line) for line in done.stdout.splitlines()]
            tools = {tool['name']: tool for tool in replies[1]['result']['tools']}
            for name in ('commerce_attention_list', 'commerce_attention_get'):
                self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertFalse(tools[name]['annotations']['openWorldHint'])
            self.assertFalse(replies[2]['result']['isError'])
            self.assertEqual(replies[2]['result']['structuredContent']['items'], original['items'])


if __name__ == '__main__':
    unittest.main()
