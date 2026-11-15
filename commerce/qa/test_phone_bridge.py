"""Phone mirror helpers and control gates stay explicit and local."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phone_bridge
from phone_bridge import JpegFramer, PhoneBridge, jpeg_size, pixel, png_size


def jpeg(width=8, height=16):
    return (b'\xff\xd8\xff\xc0' + (17).to_bytes(2, 'big') + b'\x08'
            + height.to_bytes(2, 'big') + width.to_bytes(2, 'big') + b'\x03'
            + b'\x00' * 9 + b'\xff\xd9')


def png(width=8, height=16):
    return (b'\x89PNG\r\n\x1a\n' + (13).to_bytes(4, 'big') + b'IHDR'
            + width.to_bytes(4, 'big') + height.to_bytes(4, 'big'))


class Frames(unittest.TestCase):
    def test_framer_splits_across_chunks_and_ignores_surrounding_bytes(self):
        first, second = jpeg(8, 16), jpeg(10, 20)
        framer = JpegFramer()
        self.assertEqual(framer.feed(b'not-a-frame' + first[:7]), [])
        self.assertEqual(framer.feed(first[7:] + b'\r\n' + second), [first, second])
        self.assertEqual(framer.feed(b'\xff'), [])
        self.assertEqual(framer.feed(b'\xd8tail\xff\xd9'), [b'\xff\xd8tail\xff\xd9'])

    def test_dimension_parsers_do_not_trust_invalid_data(self):
        self.assertEqual(jpeg_size(jpeg(1080, 2256)), (1080, 2256))
        self.assertEqual(png_size(png(540, 1128)), (540, 1128))
        for value in [b'', b'<svg/>', b'\xff\xd8', png()[:20]]:
            self.assertIsNone(jpeg_size(value))
            self.assertIsNone(png_size(value))

    def test_points_are_normalized_and_bounded(self):
        self.assertEqual(pixel(0, 1080), 0)
        self.assertEqual(pixel(1, 1080), 1079)
        self.assertEqual(pixel(0.5, 1080), 540)
        for value in [-0.01, 1.01, 'left', None, float('nan')]:
            with self.assertRaisesRegex(ValueError, 'phone_point_invalid'):
                pixel(value, 1080)


class Gates(unittest.TestCase):
    def test_missing_config_is_not_reported_as_online(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            config.write_text('{}')
            with patch.object(phone_bridge, 'CONFIG', config):
                bridge = PhoneBridge()
                try:
                    device = bridge.status()['devices'][0]
                    self.assertFalse(device['configured'])
                    self.assertFalse(device['online'])
                    self.assertEqual(device['error'], 'phone_not_configured')
                    with self.assertRaisesRegex(ValueError, 'phone_not_configured'):
                        bridge.control({'action': 'start'})
                finally:
                    bridge.stop()

    def test_input_is_rejected_before_any_device_command_without_control(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            config.write_text('{"android_serial": "synthetic-device"}')
            with patch.object(phone_bridge, 'CONFIG', config), patch('phone_bridge.subprocess.run') as run:
                bridge = PhoneBridge()
                try:
                    with self.assertRaisesRegex(ValueError, 'phone_control_required'):
                        bridge.input({'action': 'tap', 'x': 0.5, 'y': 0.5})
                    run.assert_not_called()
                finally:
                    bridge.stop()

    def test_tap_uses_zero_distance_swipe_and_clamps_text(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            config.write_text('{"android_serial": "synthetic-device"}')
            with patch.object(phone_bridge, 'CONFIG', config), patch('phone_bridge.subprocess.run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = b''
                run.return_value.stderr = b''
                bridge = PhoneBridge()
                bridge._control = object()
                bridge._probe_size = lambda: (1080, 2256)
                try:
                    bridge.input({'action': 'tap', 'x': 0.5, 'y': 0.5})
                    command = run.call_args.args[0]
                    self.assertEqual(command[-5:], ['540', '1128', '540', '1128', '60'])
                    self.assertIn('swipe', command)
                    bridge.input({'action': 'text', 'text': 'a b'})
                    self.assertEqual(run.call_args.args[0][-1], 'input text a%sb')
                    with self.assertRaisesRegex(ValueError, 'phone_text_ascii_only'):
                        bridge.input({'action': 'text', 'text': '中文'})
                    with self.assertRaisesRegex(ValueError, 'phone_key_unknown'):
                        bridge.input({'action': 'key', 'key': 'power'})
                    with self.assertRaisesRegex(ValueError, 'phone_action_invalid'):
                        bridge.control({'action': 'open'})
                finally:
                    bridge.stop()


    def test_quality_presets_and_dpad_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            config.write_text('{}')
            with patch.object(phone_bridge, 'CONFIG', config):
                bridge = PhoneBridge()
                try:
                    self.assertEqual(bridge.settings({'quality': 'sharp'})['devices'][0]['quality'], 'sharp')
                    self.assertEqual(bridge.settings({'quality': 'fast'})['devices'][0]['quality'], 'fast')
                    with self.assertRaisesRegex(ValueError, 'phone_quality_invalid'):
                        bridge.settings({'quality': 'ultra'})
                    self.assertEqual(phone_bridge.KEYS['up'], 19)
                    self.assertEqual(phone_bridge.KEYS['right'], 22)
                finally:
                    bridge.stop()


if __name__ == '__main__':
    unittest.main()