"""Optional scrcpy protocol helpers never claim a device without a valid jar."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_scrcpy import QUALITY, codec_string


class ScrcpyProtocol(unittest.TestCase):
    def test_h264_codec_string_from_sps(self):
        config = bytes.fromhex('000000016764001facb40b02df2f2905')
        self.assertEqual(codec_string(config), 'avc1.64001F')
        self.assertEqual(codec_string(b'\x00\x00\x01\x67\x42\xc0\x1e'), 'avc1.42C01E')
        self.assertEqual(codec_string(b''), 'avc1.42E01E')

    def test_quality_presets_are_bounded(self):
        for name in ('fast', 'balanced', 'sharp'):
            spec = QUALITY[name]
            self.assertGreaterEqual(spec['max_size'], 480)
            self.assertLessEqual(spec['max_size'], 1080)
            self.assertGreaterEqual(spec['max_fps'], 10)
            self.assertLessEqual(spec['max_fps'], 30)


if __name__ == '__main__':
    unittest.main()
