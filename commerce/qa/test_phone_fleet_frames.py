"""Fleet capture integration with synthetic phones and bounded real threads."""
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_fleet import PhoneFleet
from phone_frame_policy import FrameCapturePolicy
from phone_bridge import PhoneBridge

PNG = (b'\x89PNG\r\n\x1a\n' + (13).to_bytes(4, 'big') + b'IHDR'
       + (100).to_bytes(4, 'big') + (200).to_bytes(4, 'big'))


class SyntheticPhone:
    def __init__(self, release, result=('image/png', PNG)):
        self.release = release
        self.result = result
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        if not self.release.wait(3):
            raise TimeoutError('synthetic capture timed out')
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def status(self, start_pipeline=False):
        return {'devices': [{'online': True, 'mode': 'idle', 'error': ''}]}

    def stop(self):
        pass


class FleetFrameTests(unittest.TestCase):
    def setUp(self):
        with patch('phone_fleet._primary_serial', return_value=''), \
                patch.object(PhoneFleet, '_watch_ios', return_value=None):
            self.fleet = PhoneFleet()
        self.fleet._refresh = lambda: None
        self.release = threading.Event()
        self.phones = {}
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.release.set()
        self.drain()
        self.fleet.stop()

    def wait_for(self, predicate):
        until = time.monotonic() + 3
        while not predicate() and time.monotonic() < until:
            time.sleep(.005)
        self.assertTrue(predicate(), 'Synthetic capture did not settle')

    def drain(self):
        self.wait_for(lambda: not self.fleet._snap_running)

    def add_phone(self, ident='synthetic-phone', result=('image/png', PNG)):
        phone = SyntheticPhone(self.release, result)
        self.phones[ident] = phone
        self.fleet._android[ident] = phone
        self.fleet._meta[ident] = {'kind': 'android', 'label': ident, 'model': 'Synthetic'}
        self.fleet._snap_locks[ident] = threading.Lock()
        return phone

    def test_twelve_phones_start_at_most_three_captures(self):
        for i in range(12):
            ident = 'synthetic-' + str(i)
            self.add_phone(ident)
            self.fleet.snapshot(ident)
        self.wait_for(lambda: sum(p.calls for p in self.phones.values()) >= 3)
        self.assertEqual(len(self.fleet._snap_running), 3)
        self.assertEqual(sum(p.calls for p in self.phones.values()), 3)

    def test_failed_capture_backs_off_instead_of_retrying_every_request(self):
        phone = self.add_phone(result=(None, None))
        self.release.set()
        for _ in range(8):
            self.fleet.snapshot('synthetic-phone')
            self.drain()
        self.assertEqual(phone.calls, 1)

    def test_fresh_cache_is_reused_without_starting_another_capture(self):
        phone = self.add_phone()
        self.release.set()
        self.fleet.snapshot('synthetic-phone')
        self.drain()
        self.assertEqual(self.fleet.snapshot('synthetic-phone'), ('image/png', PNG))
        self.assertEqual(phone.calls, 1)

    def test_expired_frame_is_unavailable_and_status_marks_delay(self):
        self.add_phone()
        self.fleet._snap['synthetic-phone'] = (time.time() - 60, 'image/png', PNG)
        with patch.object(self.fleet, '_warm'):
            self.assertEqual(self.fleet.snapshot('synthetic-phone'), (None, None))
        status = self.fleet.status()['devices'][0]
        self.assertEqual(status['error'], 'phone_frame_unavailable')
        self.assertLess(status['frame_at'], time.time() - 50)

    def test_clock_rollback_does_not_turn_old_cache_into_a_fresh_frame(self):
        self.add_phone()
        self.fleet._snap['synthetic-phone'] = (time.time() + 60, 'image/png', PNG)
        with patch.object(self.fleet, '_warm'):
            self.assertEqual(self.fleet.snapshot('synthetic-phone'), (None, None))

    def test_bridge_cannot_refresh_the_fleet_from_a_future_dated_stream_frame(self):
        with patch.object(PhoneBridge, '_ensure_tools_path'), patch.object(PhoneBridge, '_watch_control'):
            bridge = PhoneBridge(serial='synthetic-capture')
        bridge._frame = PNG
        bridge._mime = 'image/png'
        bridge._frame_at = time.time() + 60
        with patch.object(bridge, '_adb', return_value=''):
            self.assertEqual(bridge.snapshot(), (None, None))

    def test_unknown_id_never_starts_a_capture_thread(self):
        with patch('phone_fleet.threading.Thread') as thread:
            self.assertEqual(self.fleet.snapshot('unknown'), (None, None))
        self.fleet._snap_running.discard('unknown')
        thread.assert_not_called()

    def test_disconnected_device_cannot_be_resurrected_by_a_late_capture(self):
        phone = self.add_phone()
        self.fleet.snapshot('synthetic-phone')
        self.wait_for(lambda: phone.calls == 1)
        self.fleet._android_devices = lambda: []
        self.fleet._ios_devices = lambda: []
        self.fleet._empty_since['android'] = time.time() - 10
        self.fleet._discovered_at = 0
        PhoneFleet._refresh(self.fleet)
        self.assertNotIn('synthetic-phone', self.fleet._meta)
        self.release.set()
        self.drain()
        self.assertNotIn('synthetic-phone', self.fleet._snap)

    def test_stop_discards_late_capture_and_refuses_further_discovery(self):
        phone = self.add_phone()
        self.fleet.snapshot('synthetic-phone')
        self.wait_for(lambda: phone.calls == 1)
        self.fleet.stop()
        self.release.set()
        self.drain()
        self.assertEqual(self.fleet._snap, {})
        with patch.object(self.fleet, '_android_devices') as discover:
            PhoneFleet._refresh(self.fleet)
        discover.assert_not_called()

    def test_discovery_alone_does_not_capture_phone_screens(self):
        self.fleet._android_devices = lambda: [('synthetic-device', 'Synthetic')]
        self.fleet._ios_devices = lambda: []
        with patch('phone_fleet.PhoneBridge') as bridge, patch.object(self.fleet, '_warm') as warm:
            PhoneFleet._refresh(self.fleet)
        self.assertTrue(bridge.called)
        warm.assert_not_called()

    def test_delayed_worker_does_not_capture_a_reconnected_generation(self):
        phone = self.add_phone()
        self.release.set()
        with patch('phone_fleet.threading.Thread') as thread:
            self.fleet.snapshot('synthetic-phone')
        work = thread.call_args.kwargs['target']
        self.fleet._snap_locks['synthetic-phone'] = threading.Lock()
        work()
        self.assertEqual(phone.calls, 0)
        self.assertEqual(self.fleet._snap, {})

    def test_capture_exception_is_sanitized_and_backed_off(self):
        phone = self.add_phone(result=RuntimeError('private-synthetic-device-detail'))
        self.release.set()
        for _ in range(2):
            self.fleet.snapshot('synthetic-phone')
            self.drain()
        self.assertEqual(phone.calls, 1)
        self.assertEqual(self.fleet.status()['devices'][0]['error'], 'phone_frame_unavailable')

    def test_thread_start_failure_releases_the_slot_and_marks_capture_unavailable(self):
        self.add_phone()
        with patch('phone_fleet.threading.Thread', side_effect=RuntimeError('cannot start thread')):
            self.assertEqual(self.fleet.snapshot('synthetic-phone'), (None, None))
        self.assertEqual(self.fleet._snap_running, set())
        self.assertEqual(self.fleet.status()['devices'][0]['error'], 'phone_frame_unavailable')

    def test_repeated_wall_refreshes_eventually_capture_all_twelve_phones(self):
        now = [100.0]
        self.fleet._capture_policy = FrameCapturePolicy(clock=lambda: now[0])
        self.release.set()
        for i in range(12):
            self.add_phone('synthetic-' + str(i))
        for _ in range(4):
            for ident in self.phones:
                self.fleet.snapshot(ident)
                self.drain()
            now[0] += 2
            for ident, cached in list(self.fleet._snap.items()):
                self.fleet._snap[ident] = (time.time() - 3, *cached[1:])
        self.assertTrue(all(phone.calls for phone in self.phones.values()))

    def test_ios_stale_cache_uses_the_same_unavailable_contract(self):
        ident = 'synthetic-ios'
        self.fleet._meta[ident] = {'kind': 'ios', 'label': 'Synthetic', 'model': 'Synthetic'}
        self.fleet._ios[ident] = object()
        self.fleet._snap_locks[ident] = threading.Lock()
        self.fleet._snap[ident] = (time.time() - 60, 'image/png', PNG)
        with patch.object(self.fleet, '_warm'):
            self.assertEqual(self.fleet.snapshot(ident), (None, None))
        self.assertEqual(self.fleet.status()['devices'][0]['error'], 'phone_frame_unavailable')


if __name__ == '__main__':
    unittest.main()
