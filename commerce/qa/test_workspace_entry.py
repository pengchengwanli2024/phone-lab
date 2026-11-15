"""Actual HTTP entry routing; no business service, accounts, or external calls."""
import http.client
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class WorkspaceEntry(unittest.TestCase):
    def test_canonical_entries_share_the_workspace_and_legacy_remains_explicit(self):
        class Handler(server.Handler):
            secret = 'synthetic-entry-only'

        httpd = server.CommerceHTTPServer(('127.0.0.1', 0), Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server, 'PORT', port):
                for path in ('/', '/workspace', '/phones', '/?tab=orders&demo=true', '/legacy'):
                    with self.subTest(path=path):
                        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                        try:
                            connection.request('GET', path, headers={'Authorization': 'Bearer synthetic-entry-only'})
                            response = connection.getresponse()
                            body = response.read().decode()
                            self.assertEqual(response.status, 200)
                            if path == '/legacy':
                                self.assertTrue('<div id="app"' in body, 'Explicit legacy entry must retain its original application')
                            else:
                                self.assertTrue('<div id="root"' in body, 'Canonical entry must render the shared workspace')
                                self.assertIn("frame-src 'self' about:", response.getheader('Content-Security-Policy'))
                        finally:
                            connection.close()
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                try:
                    connection.request('GET', '/')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 401)
                    response.read()
                finally:
                    connection.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
