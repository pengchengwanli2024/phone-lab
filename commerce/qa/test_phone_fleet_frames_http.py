"""Real authenticated loopback routes with synthetic phone captures only."""
import http.client
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import test_phone_fleet_frames as fixtures


class FleetFrameHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FleetFrameTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fleet = self.fixture.fleet
        self.phone = self.fixture.add_phone()
        self.fixture.release.set()
        class Handler(server.Handler):
            fleet = self.fleet
            secret = 'synthetic-frame-test-token'
        self.http = server.CommerceHTTPServer(('127.0.0.1', 0), Handler)
        port = patch.object(server, 'PORT', self.http.server_port)
        port.start()
        self.addCleanup(port.stop)
        thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        thread.start()
        def close():
            self.http.shutdown()
            self.http.server_close()
            thread.join(timeout=3)
        self.addCleanup(close)

    def get(self, path='/phone/fleet/frame?id=synthetic-phone', *, authenticated=True, origin=None):
        headers = {}
        if authenticated:
            headers['Authorization'] = 'Bearer synthetic-frame-test-token'
        if origin:
            headers['Origin'] = origin
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
        try:
            connection.request('GET', path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_authentication_and_origin_checks_precede_capture(self):
        self.assertEqual(self.get(authenticated=False)[0], 401)
        self.assertEqual(self.get(origin='https://untrusted.invalid')[0], 403)
        self.assertEqual(self.phone.calls, 0)

    def test_original_route_returns_captured_bytes_without_browser_caching(self):
        self.get()
        self.fixture.drain()
        code, headers, body = self.get()
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(body, fixtures.PNG)
        self.assertEqual(self.phone.calls, 1)

    def test_expired_frame_returns_503_and_status_keeps_original_capture_time(self):
        captured_at = time.time() - 60
        self.fleet._snap['synthetic-phone'] = (captured_at, 'image/png', fixtures.PNG)
        with patch.object(self.fleet, '_warm'):
            code, _, body = self.get()
        self.assertEqual(code, 503)
        self.assertEqual(json.loads(body), {'error': 'phone_frame_unavailable'})
        code, _, body = self.get('/phone/fleet/status')
        self.assertEqual(code, 200)
        device = json.loads(body)['devices'][0]
        self.assertEqual(device['error'], 'phone_frame_unavailable')
        self.assertEqual(device['frame_at'], captured_at)

    def test_repeated_failed_requests_do_not_bypass_backoff(self):
        self.phone.result = (None, None)
        for _ in range(5):
            self.assertEqual(self.get()[0], 503)
            self.fixture.drain()
        self.assertEqual(self.phone.calls, 1)

    def test_unknown_device_does_not_fall_back_to_another_phone(self):
        self.assertEqual(self.get('/phone/fleet/frame?id=unknown')[0], 503)
        self.assertEqual(self.phone.calls, 0)


if __name__ == '__main__':
    unittest.main()
