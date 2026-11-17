"""Actual local HTTP handoff/authentication; no browser or hardware actions."""
import http.client
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from service import Commerce


class PhoneManagementHTTP(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        class Handler(server.Handler):
            service = self.app
            secret = 'synthetic-phone-handoff'
        self.http = server.CommerceHTTPServer(('127.0.0.1', 0), Handler)
        self.port = patch.object(server, 'PORT', self.http.server_port)
        self.port.start()
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        self.app.autonomy.stop(); self.app.agent_runtime.stop()
        self.port.stop(); self.temp.cleanup()

    def call(self, path, *, body=None, auth=False, cookie=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if auth: headers['Authorization'] = 'Bearer synthetic-phone-handoff'
        if cookie: headers['Cookie'] = cookie
        if origin: headers['Origin'] = origin
        c = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=8)
        try:
            c.request('POST' if body is not None else 'GET', path, body=json.dumps(body) if body is not None else None, headers=headers)
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read().decode()
        finally: c.close()

    def test_registered_open_tool_and_one_use_phone_ticket(self):
        self.assertEqual(self.call('/phones')[0], 401)
        with patch('runtime.PORT', self.http.server_port), patch('phone_management.webbrowser.open', return_value=True) as browser:
            code, _, raw = self.call('/v1/invoke', auth=True, body={'tool': 'commerce_phone_open', 'arguments': {}})
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(raw)['opened'])
        target = urlsplit(browser.call_args.args[0])
        ticket_path = target.path + '?' + target.query
        code, headers, body = self.call(ticket_path)
        self.assertEqual(code, 303)
        self.assertEqual(headers['Location'], '/phones')
        self.assertEqual(body, '')
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        self.assertEqual(self.call('/phones', cookie=cookie)[0], 200)
        self.assertEqual(self.call(ticket_path, cookie=cookie)[0], 401)

    def test_auth_origin_expiry_and_no_arbitrary_destination(self):
        with patch('phone_management.webbrowser.open') as browser:
            request = {'tool': 'commerce_phone_open', 'arguments': {}}
            self.assertEqual(self.call('/v1/invoke', body=request)[0], 401)
            self.assertEqual(self.call('/v1/invoke', body=request, auth=True, origin='https://untrusted.example')[0], 403)
            self.assertEqual(self.call('/v1/invoke', body={**request, 'arguments': {'url': 'https://untrusted.example'}}, auth=True)[0], 400)
            browser.assert_not_called()
        ticket = self.app.live.new_setup_ticket()
        self.app.live.tickets[ticket] = time.monotonic() - 1
        self.assertEqual(self.call('/phones?ticket=' + ticket)[0], 401)
        self.assertEqual(self.call('/phones?ticket=invalid')[0], 401)

    def test_three_mcp_adapters_discover_only_the_bounded_open_action(self):
        Path(self.temp.name, 'auth.token').write_text('synthetic-phone-handoff')
        messages = [{'id': 1, 'method': 'initialize', 'params': {}}, {'id': 2, 'method': 'tools/list'}]
        for host in ('harness', 'codex', 'hermes'):
            with self.subTest(host=host):
                result = subprocess.run([sys.executable, str(Path(server.__file__).with_name('mcp_server.py')), host],
                    input='\n'.join(json.dumps(message) for message in messages) + '\n', text=True, capture_output=True, timeout=20,
                    env={**os.environ, 'COMMERCE_STATE': self.temp.name, 'COMMERCE_PORT': str(self.http.server_port)})
                self.assertEqual(result.returncode, 0)
                replies = {item['id']: item for line in result.stdout.splitlines() if (item := json.loads(line))}
                tool = next(item for item in replies[2]['result']['tools'] if item['name'] == 'commerce_phone_open')
                self.assertEqual(tool['inputSchema']['properties'], {})
                self.assertFalse(tool['inputSchema']['additionalProperties'])
                self.assertFalse(tool['annotations']['readOnlyHint'])
                self.assertTrue(tool['annotations']['openWorldHint'])
