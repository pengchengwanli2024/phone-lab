import json
import builtins
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from service import Commerce
from intel_live import IntelLive, parse_flights, parse_vessel, parse_quote, ais_proxy


class IntelLiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        self.live = IntelLive(self.app.core, Path(self.tmp.name))
        self.config = {'AISSTREAM_API_KEY': None, 'OPENSKY_CLIENT_ID': None, 'OPENSKY_CLIENT_SECRET': None, 'OPENSKY_LICENSE_CONFIRMED': True, 'OPENSKY_USE_CASE': ''}
        configured = patch.object(self.live, '_config', return_value=self.config)
        configured.start()
        self.addCleanup(configured.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_do_not_fetch_and_missing_ship_key_is_explicit(self):
        with patch('intel_live.fetch_json', side_effect=AssertionError('read fetched')):
            result = self.live.get()
        self.assertEqual(result['sources']['vessels']['status'], 'requires_config')
        self.assertEqual(result['sources']['flights']['items'], [])
        self.assertNotIn('secret', json.dumps(result))

    def test_flights_validate_coordinates_timestamps_units_and_filter_before_cap(self):
        now = int(time.time())
        rows = [[f'{i:06x}', 'TEST ', 'China', now, now, 110, 30, 1000, False, 100, 90] for i in range(800)]
        rows += [['ffffff', 'OUT', 'US', now, now, -80, 40, 500, False, 50, 0], ['bad', '', '', now, now, 999, 30, 0, False, 0, 0]]
        parsed = parse_flights({'time': now, 'states': rows})
        self.assertEqual(len(parsed), 801)
        self.assertEqual(parsed[0]['speed_kmh'], 360)
        self.live._save('flights', {'items': parsed, 'observed_at': now})
        found = self.live.get(bounds={'west': -90, 'east': -70, 'south': 35, 'north': 45})['sources']['flights']
        self.assertEqual(found['matched'], 1)
        self.assertEqual(found['items'][0]['id'], 'flight-ffffff')
        self.assertEqual(self.live.get(query='ffffff')['sources']['flights']['matched'], 1)
        with self.assertRaisesRegex(ValueError, 'invalid_intel_map_bounds'):
            self.live.get(bounds={'west': 900, 'east': 1, 'south': 0, 'north': 10})

    def test_failed_refresh_keeps_last_good_snapshot_and_does_not_fake_success(self):
        self.live._save('flights', {'items': [], 'observed_at': int(time.time()), 'last_success': time.time()})
        with patch('intel_live.fetch_json', side_effect=ValueError('upstream_http_429')):
            self.live._run('flights')
        source = self.live.get()['sources']['flights']
        self.assertEqual(source['status'], 'failed')
        self.assertTrue(source['last_success'])
        self.assertEqual(source['error'], 'upstream_http_429')
        self.assertGreater(source['next_refresh'], time.time())

    def test_stale_positions_are_excluded_and_delayed_quotes_are_labelled(self):
        now = int(time.time())
        self.live._save('flights', {'items': [{'id': 'old', 'observed_at': now - 4000, 'location': {'lon': 1, 'lat': 1}}], 'observed_at': now - 4000})
        result = self.live.get()['sources']['flights']
        self.assertEqual(result['items'], [])
        self.assertEqual(result['status'], 'stale')
        meta = {'regularMarketPrice': 100, 'regularMarketTime': now - 10000, 'currency': 'USD', 'regularMarketChangePercent': -2}
        q = parse_quote({'chart': {'result': [{'meta': meta, 'timestamp': [now-86400, now], 'indicators': {'quote': [{'close': [99, 100]}]}}]}}, '^GSPC', '标普500')
        self.assertEqual(q['change_percent'], -2)
        self.assertEqual(q['timeliness'], 'provider_delayed_or_last_session')

    def test_ais_normalization_unknown_course_and_no_secret_echo(self):
        raw = {'MessageType': 'PositionReport', 'MetaData': {'MMSI': 123456789, 'ShipName': '<test>', 'time_utc': '2026-11-14 03:30:00.123 +0000 UTC'}, 'Message': {'PositionReport': {'Longitude': 121, 'Latitude': 31, 'Sog': 10, 'Cog': 360, 'TrueHeading': 511}}}
        row = parse_vessel(raw)
        self.assertEqual(row['speed_kmh'], 18.52)
        self.assertIsNone(row['heading'])
        raw['Message']['PositionReport']['Longitude'] = 181
        self.assertIsNone(parse_vessel(raw))

    def test_refresh_single_flight_and_cooldown_shared_across_clients(self):
        with patch('intel_live.threading.Thread') as worker:
            first = self.live.refresh('flights')
            second = self.live.refresh('flights')
        self.assertEqual(first['sources']['flights']['refresh_status'], 'running')
        self.assertEqual(second['sources']['flights']['refresh_status'], 'running')
        self.assertEqual(worker.call_count, 1)

    @unittest.skipUnless(importlib.util.find_spec('websockets'), 'AIS uses optional isolated worker environment')
    def test_ais_uses_server_side_subscription_and_bounded_window(self):
        raw = {'MessageType': 'PositionReport', 'MetaData': {'MMSI': 123456789, 'time_utc': '2026-11-14 03:30:00+00:00'}, 'Message': {'PositionReport': {'Longitude': 121, 'Latitude': 31}}}
        with patch('websockets.sync.client.connect') as connect, patch('intel_live.time.monotonic', side_effect=[0, 1, 2, 20]):
            socket = connect.return_value.__enter__.return_value
            socket.recv.return_value = json.dumps(raw)
            result = self.live._vessels('synthetic-test-key')
        subscription = json.loads(socket.send.call_args.args[0])
        self.assertEqual(subscription['APIKey'], 'synthetic-test-key')
        self.assertEqual(subscription['FilterMessageTypes'], ['PositionReport', 'StandardClassBPositionReport'])
        self.assertEqual(len(result['items']), 1)
        self.assertNotIn('synthetic-test-key', json.dumps(result))

    def test_stdlib_service_uses_existing_worker_and_never_places_key_in_argv(self):
        original_import = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == 'websockets.sync.client':
                raise ImportError()
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=importing), patch('intel_live.Path.is_file', return_value=True), patch('intel_live.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({'items': [], 'observed_at': 123})
            self.assertEqual(self.live._vessels('synthetic-pipe-only')['observed_at'], 123)
        self.assertNotIn('synthetic-pipe-only', str(run.call_args.args))
        self.assertIn('synthetic-pipe-only', run.call_args.kwargs['input'])
        self.assertEqual(run.call_args.kwargs['timeout'], 30)

    def test_missing_optional_ais_worker_stays_unavailable_without_starting_a_process(self):
        original_import = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == 'websockets.sync.client':
                raise ImportError()
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=importing), patch('intel_live.Path.is_file', return_value=False), patch('intel_live.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, '^ais_client_unavailable$'):
                self.live._vessels('synthetic-pipe-only')
        run.assert_not_called()

    def test_operational_flight_refresh_requires_explicit_provider_license(self):
        self.config['OPENSKY_LICENSE_CONFIRMED'] = False
        with patch('intel_live.fetch_json', side_effect=AssertionError('unlicensed refresh')), patch('intel_live.threading.Thread') as worker:
            result = self.live.refresh('flights')
            self.assertEqual(result['sources']['flights']['status'], 'requires_authorization')
            self.assertEqual(result['sources']['flights']['mode'], 'evaluation_snapshot')
            worker.assert_not_called()

    def test_local_development_requires_explicit_manual_sample_and_keeps_cooldown(self):
        self.config.update(OPENSKY_LICENSE_CONFIRMED=False, OPENSKY_USE_CASE='local_development')
        with patch('intel_live.threading.Thread') as worker:
            auto = self.live.refresh()
            self.assertEqual(auto['sources']['flights']['mode'], 'local_evaluation')
            self.assertFalse(any(call.kwargs.get('name') == 'intel-live-flights' for call in worker.call_args_list))
            self.assertFalse(auto['sources']['flights']['last_attempt'])
            self.live.refresh('flights', evaluation=True)
            flight_calls = [call for call in worker.call_args_list if call.kwargs.get('name') == 'intel-live-flights']
            self.assertEqual(len(flight_calls), 1)
            self.assertEqual(flight_calls[0].kwargs['args'], ('flights', True))
            self.live.running.discard('flights')
            self.live.refresh('flights', evaluation=True)
            self.assertEqual(len([call for call in worker.call_args_list if call.kwargs.get('name') == 'intel-live-flights']), 1)
        with self.assertRaisesRegex(ValueError, 'invalid_intel_live_evaluation'):
            self.live.refresh('all', evaluation=True)

    def test_explicit_development_sample_calls_provider_without_claiming_license(self):
        self.config.update(OPENSKY_LICENSE_CONFIRMED=False, OPENSKY_USE_CASE='local_development')
        with patch('intel_live.fetch_json', return_value={'time': int(time.time()), 'states': []}) as fetch:
            self.live._run('flights', evaluation=True)
        fetch.assert_called_once()
        state = self.live.get()['sources']['flights']
        self.assertEqual(state['status'], 'evaluation')
        self.assertTrue(state['last_success'])

    def test_position_availability_distinguishes_expired_scope_and_never_received(self):
        self.assertEqual(self.live.get()['sources']['flights']['availability'], 'never_received')
        now = time.time()
        rows = [{'id': 'test', 'observed_at': now-3601, 'location': {'lon': 121, 'lat': 31}}]
        self.live._save('flights', {'items': rows, 'last_success': now-3600})
        expired = self.live.get()['sources']['flights']
        self.assertEqual(expired['availability'], 'expired')
        self.assertEqual(expired['expired_count'], 1)
        rows[0]['observed_at'] = now
        self.live._save('flights', {'items': rows, 'last_success': now})
        outside = self.live.get(bounds={'west': -90, 'east': -70, 'south': 0, 'north': 40})['sources']['flights']
        self.assertEqual(outside['availability'], 'outside_filter')
        self.assertEqual(outside['fresh_count'], 1)

    def test_local_session_is_bounded_stoppable_and_never_recovers_after_restart(self):
        self.config.update(OPENSKY_LICENSE_CONFIRMED=False, OPENSKY_USE_CASE='local_development')
        with patch('intel_live.time.time', return_value=10000), patch('intel_live.threading.Thread') as worker:
            result = self.live.refresh('flights', evaluation_session='start', minutes=60)
            session = result['sources']['flights']['evaluation_session']
            self.assertTrue(session['active'])
            self.assertEqual(session['until'], 13600)
            self.assertEqual(worker.call_count, 1)
            self.live.running.discard('flights')
            self.live.refresh('flights', evaluation_session='stop')
        with patch('intel_live.time.time', return_value=11000), patch('intel_live.threading.Thread') as worker:
            self.live.refresh('flights')
            worker.assert_not_called()
            self.assertFalse(self.live.get()['sources']['flights']['evaluation_session']['active'])
        restarted = IntelLive(self.app.core, Path(self.tmp.name))
        self.assertFalse(restarted.get()['sources']['flights']['evaluation_session']['active'])

    def test_session_expiry_cannot_trigger_another_provider_request(self):
        self.config.update(OPENSKY_LICENSE_CONFIRMED=False, OPENSKY_USE_CASE='local_development')
        with patch('intel_live.time.time', return_value=10000), patch('intel_live.threading.Thread'):
            self.live.refresh('flights', evaluation_session='start', minutes=5)
        self.live.running.discard('flights')
        with patch('intel_live.time.time', return_value=10301), patch('intel_live.fetch_json') as fetch:
            self.live._run('flights', evaluation=True, evaluation_deadline=10300)
            fetch.assert_not_called()
            self.assertFalse(self.live.get()['sources']['flights']['evaluation_session']['active'])
        for minutes in [True, 0, 61, '60']:
            with self.assertRaises(ValueError):
                self.live.refresh('flights', evaluation_session='start', minutes=minutes)

    def test_session_start_is_idempotent_and_ordinary_refresh_stops_at_deadline(self):
        self.config.update(OPENSKY_LICENSE_CONFIRMED=False, OPENSKY_USE_CASE='local_development')
        with patch('intel_live.time.time', return_value=10000), patch('intel_live.threading.Thread'):
            self.live.refresh('flights', evaluation_session='start', minutes=5)
        self.live.running.discard('flights')
        with patch('intel_live.time.time', return_value=10030), patch('intel_live.threading.Thread') as worker:
            value = self.live.refresh('flights', evaluation_session='start', minutes=60)
            self.assertEqual(value['sources']['flights']['evaluation_session']['until'], 10300)
            worker.assert_not_called()
        with patch('intel_live.time.time', return_value=11000), patch('intel_live.threading.Thread') as worker:
            value = self.live.refresh('flights')
            worker.assert_not_called()
            self.assertTrue(value['sources']['flights']['evaluation_session']['ended'])

    def test_vessel_failure_backs_off_and_never_echoes_provider_exceptions(self):
        self.config['AISSTREAM_API_KEY'] = 'synthetic-pipe-only'
        for attempt in range(1, 4):
            with patch.object(self.live, '_vessels', side_effect=ValueError('unsafe-provider-secret')), patch('intel_live.uniform', return_value=1), patch('intel_live.time.time', return_value=10000):
                self.live._run('vessels')
            source = self.live.get()['sources']['vessels']
            self.assertEqual(source['error'], 'upstream_unavailable')
            self.assertEqual(source['next_refresh'], 10000 + 60 * 2 ** attempt)
            self.assertNotIn('unsafe-provider-secret', json.dumps(source))
        self.assertIsNone(parse_vessel({'MessageType': 'PositionReport', 'MetaData': [], 'Message': 'bad'}))

    def test_ais_reuses_https_proxy_and_honors_explicit_websocket_proxy(self):
        with patch('intel_live.getproxies', return_value={'socks': 'socks5://localhost:1', 'https': 'http://localhost:2'}), patch('intel_live.proxy_bypass', return_value=False):
            self.assertEqual(ais_proxy(), 'http://localhost:2')
        with patch('intel_live.getproxies', return_value={'wss': 'http://localhost:3', 'https': 'http://localhost:2'}), patch('intel_live.proxy_bypass', return_value=False):
            self.assertEqual(ais_proxy(), 'http://localhost:3')


if __name__ == '__main__':
    unittest.main()
