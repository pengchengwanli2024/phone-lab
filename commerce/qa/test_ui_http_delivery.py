"""Real HTTP negotiation with an isolated synthetic service; no external calls."""
import gzip
import http.client
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


class HtmlDeliveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='commerce-delivery-')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            cls.port = listener.getsockname()[1]
        cls.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('react_workbench_fixture.py'))],
            env={**os.environ, 'COMMERCE_STATE': cls.work.name, 'COMMERCE_PORT': str(cls.port)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError('Synthetic delivery fixture exited')
            try:
                if cls.request('/v1/health')[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(.1)
        cls.tearDownClass()
        raise RuntimeError('Synthetic delivery fixture did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=10)
        cls.work.cleanup()

    @classmethod
    def request(cls, path='/', accept=None, authenticated=True):
        connection = http.client.HTTPConnection('127.0.0.1', cls.port, timeout=15)
        headers = {'Authorization': 'Bearer synthetic-workbench-preview'} if authenticated else {}
        if accept is not None:
            headers['Accept-Encoding'] = accept
        try:
            connection.request('GET', path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_negotiated_html_is_byte_identical_after_decode(self):
        status, plain_headers, plain = self.request(accept='identity')
        code, headers, encoded = self.request(accept='gzip, deflate, br')
        self.assertEqual((status, code), (200, 200))
        self.assertEqual(headers.get('Content-Encoding'), 'gzip')
        self.assertEqual(gzip.decompress(encoded), plain)
        self.assertLess(len(encoded), len(plain))
        self.assertEqual(int(headers['Content-Length']), len(encoded))
        self.assertIn('Accept-Encoding', headers['Vary'])
        for name in ('Content-Type', 'Content-Security-Policy', 'Cache-Control'):
            self.assertEqual(headers[name], plain_headers[name])

    def test_explicit_rejection_overrides_wildcard(self):
        for accept in (None, 'br', 'gzip;q=0', 'gzip;q=0, *;q=1', 'gzip;q=invalid'):
            with self.subTest(accept=accept):
                status, headers, body = self.request(accept=accept)
                self.assertEqual(status, 200)
                self.assertNotIn('Content-Encoding', headers)
                self.assertTrue(body.startswith(b'<!doctype html>'))

    def test_case_quality_and_wildcard_are_accepted(self):
        for accept in ('GZip; q=0.8', '*;q=0.5'):
            with self.subTest(accept=accept):
                code, headers, body = self.request(accept=accept)
                self.assertEqual(code, 200)
                self.assertEqual(headers.get('Content-Encoding'), 'gzip')
                self.assertTrue(gzip.decompress(body).startswith(b'<!doctype html>'))

    def test_json_and_authentication_errors_keep_existing_representation(self):
        for path, auth, expected in (('/v1/health', True, 200), ('/', False, 401)):
            with self.subTest(path=path, authenticated=auth):
                code, headers, body = self.request(path, accept='gzip', authenticated=auth)
                self.assertEqual(code, expected)
                self.assertNotIn('Content-Encoding', headers)
                self.assertIn('application/json', headers['Content-Type'])
                self.assertTrue(body.startswith(b'{'))


if __name__ == '__main__':
    unittest.main()
