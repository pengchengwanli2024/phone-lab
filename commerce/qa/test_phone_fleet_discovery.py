"""CoreDevice pairing history alone must not create an online phone card."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_fleet import PhoneFleet


class IosDiscoveryTests(unittest.TestCase):
    def discover(self, connection):
        row = {'identifier': 'synthetic-coredevice',
               'hardwareProperties': {'reality': 'physical', 'udid': 'synthetic-ios', 'marketingName': 'Synthetic iPhone'},
               'connectionProperties': connection}
        done = subprocess.CompletedProcess([], 0, json.dumps({'result': {'devices': [row]}}).encode())
        with patch('phone_fleet.subprocess.run', return_value=done), patch('phone_fleet.Path.exists', return_value=True):
            return PhoneFleet._ios_devices(object())

    def test_historically_paired_phone_without_transport_is_not_online(self):
        self.assertEqual(self.discover({'pairingState': 'paired', 'tunnelState': 'unavailable'}), [])

    def test_connected_paired_physical_phone_is_available(self):
        rows = self.discover({'pairingState': 'paired', 'tunnelState': 'connected'})
        self.assertEqual(rows, [('synthetic-ios', 'Synthetic iPhone', 'synthetic-coredevice')])

    def test_missing_or_connecting_transport_is_not_confirmed_online(self):
        for tunnel in (None, 'connecting', 'disconnected'):
            connection = {'pairingState': 'paired'}
            if tunnel is not None:
                connection['tunnelState'] = tunnel
            with self.subTest(tunnel=tunnel):
                self.assertEqual(self.discover(connection), [])

    def test_connected_phone_still_requires_pairing(self):
        self.assertEqual(self.discover({'pairingState': 'unpaired', 'tunnelState': 'connected'}), [])


if __name__ == '__main__':
    unittest.main()
