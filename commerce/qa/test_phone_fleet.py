"""Fleet helpers: hashed ids, stable labels and per-device lease keys."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'commerce'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'monitor'))
from phone_fleet import PhoneFleet, _clean, _device_id
from control import Lease
from unittest.mock import patch


class FakeBridge:
    def __init__(self, serial=None, lease_key=None):
        self.serial, self.lease_key = serial, lease_key
        self.controlling = False
        self.inputs = []

    def status(self, start_pipeline=False):
        return {'devices': [{'online': True, 'mode': 'idle', 'quality': 'balanced', 'width': 100, 'height': 200,
                             'controlling': self.controlling, 'control_remaining': 0,
                             'capabilities': {'tap': True, 'swipe': True, 'key': True, 'text': 'ascii', 'multi_touch': False},
                             'error': ''}]}

    def snapshot(self):
        return 'image/png', b'\x89PNG\r\n\x1a\n' + b'x' * 16

    def control(self, payload):
        self.controlling = payload.get('action') == 'start'

    def input(self, payload):
        self.inputs.append(payload)
        return {'ok': True}

    def frames(self):
        return iter(())

    def stop(self):
        pass


class FleetUnit(unittest.TestCase):
    def test_device_ids_are_stable_and_hashed(self):
        first = _device_id('a', '1e31f3a8')
        self.assertEqual(first, _device_id('a', '1e31f3a8'))
        self.assertNotEqual(first, _device_id('a', 'other'))
        self.assertTrue(first.startswith('a'))
        self.assertNotIn('1e31f3a8', first)

    def test_labels_disambiguate_duplicates(self):
        fleet = PhoneFleet()
        rows = [('one', 'iPhone'), ('two', 'iPhone'), ('three', 'Pixel')]
        self.assertEqual(fleet._labels(rows), [('one', 'iPhone 1'), ('two', 'iPhone 2'), ('three', 'Pixel')])

    def test_lease_keys_are_bounded(self):
        self.assertEqual(Lease('android', 'serial', key='android-a123').key, 'android-a123')
        with self.assertRaises(ValueError):
            Lease('android', 'serial', key='../escape')

    def test_clean_text_has_no_control_bytes(self):
        self.assertEqual(_clean('  vivo\nNEX  '), 'vivoNEX')

    def test_two_android_devices_get_independent_bridges(self):
        fleet = PhoneFleet()
        fleet._android_devices = lambda: [('serial-one', 'Phone'), ('serial-two', 'Phone')]
        fleet._ios_devices = lambda: []
        with patch('phone_fleet.PhoneBridge', FakeBridge):
            status = fleet.status()
            self.assertEqual(len(status['devices']), 2)
            self.assertEqual([item['label'] for item in status['devices']], ['Phone 1', 'Phone 2'])
            self.assertEqual(len({item['id'] for item in status['devices']}), 2)
            first = status['devices'][0]['id']
            fleet.control({'id': first, 'action': 'start'})
            self.assertTrue(fleet.status()['devices'][0]['controlling'])
            fleet.control({'id': first, 'action': 'end'})
        fleet.stop()


if __name__ == '__main__':
    unittest.main()