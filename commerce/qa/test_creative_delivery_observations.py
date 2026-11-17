"""Actual frames/audio checks use only isolated, explicitly synthetic media."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_product_media as fixtures
from creative_media_observations import inspect_output
from creative_review_frames import contact_sheet


class DeliveryObservations(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProductMediaTests(); self.fixture.setUp()
        self.studio = self.fixture.app.creative
        self.folder = Path(self.fixture.tmp.name)

    def tearDown(self):
        self.fixture.app.autonomy.stop(); self.fixture.tearDown()

    def video(self, visual='color=c=black:s=160x120:r=24', audio='anullsrc=r=48000:cl=mono'):
        path = self.folder / 'synthetic.mp4'
        args = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i', visual]
        if audio: args += ['-f', 'lavfi', '-i', audio]
        self.studio.run(args + ['-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-threads', '1']
                        + (['-c:a', 'aac'] if audio else ['-an']) + [path])
        return path, self.studio.probe(path)

    def test_real_black_frozen_and_silent_media_are_reported_without_semantic_claim(self):
        path, media = self.video()
        report = inspect_output(self.studio, path, media)
        self.assertEqual(report['status'], 'completed')
        self.assertTrue(report['decoded'])
        self.assertGreater(report['video']['black_duration_ms'], 1700)
        self.assertGreater(report['video']['frozen_duration_ms'], 1700)
        self.assertGreater(report['audio']['silent_duration_ms'], 1700)
        self.assertLess(report['audio']['peak_dbfs'], -80)
        self.assertIsNone(report['semantic_motion_verified'])
        self.assertNotIn(str(self.folder), json.dumps(report))

    def test_real_changing_frames_and_tone_are_distinguished_from_black_silence(self):
        path, media = self.video('testsrc2=s=160x120:r=24', 'sine=frequency=440:sample_rate=48000')
        report = inspect_output(self.studio, path, media)
        self.assertEqual(report['video']['black_duration_ms'], 0)
        self.assertEqual(report['video']['frozen_duration_ms'], 0)
        self.assertEqual(report['audio']['silent_duration_ms'], 0)
        self.assertLess(report['audio']['peak_dbfs'], 0)
        self.assertIsNone(report['semantic_motion_verified'])

    def test_no_audio_is_explicit_and_not_a_zero_level_measurement(self):
        path, media = self.video('color=c=blue:s=160x120:r=24', None)
        report = inspect_output(self.studio, path, media)
        self.assertEqual(report['audio']['status'], 'no_audio')
        self.assertIsNone(report['audio']['silent_duration_ms'])
        self.assertIsNone(report['audio']['peak_dbfs'])

    def test_missing_detector_falls_back_to_full_decode_and_discloses_unavailable(self):
        path, media = self.video()
        run = self.studio.run
        def unavailable(args, *rest):
            if any('blackdetect=' in str(a) for a in args):
                raise ValueError('creative_media_processing_failed')
            return run(args, *rest)
        with patch.object(self.studio, 'run', side_effect=unavailable):
            report = inspect_output(self.studio, path, media)
        self.assertEqual(report['status'], 'unavailable')
        self.assertTrue(report['decoded'])
        self.assertIsNone(report['video'])
        with patch.object(self.studio, 'run', side_effect=ValueError('creative_media_processing_failed')):
            with self.assertRaises(ValueError): inspect_output(self.studio, path, media)

    def test_contact_sheet_contains_actual_different_frames_and_bound_positions(self):
        path, media = self.video('color=c=black:s=160x120:r=24:d=1[a];color=c=blue:s=160x120:r=24:d=1[b];[a][b]concat=n=2:v=1:a=0', None)
        sheet, index = contact_sheet(self.studio, self.folder, 'synthetic-review', path, media)
        self.assertEqual(sheet.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(index['video_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(index['contact_sheet_sha256'], hashlib.sha256(sheet.read_bytes()).hexdigest())
        self.assertEqual(len(index['samples']), 8)
        self.assertTrue(index['times_are_approximate'])
        self.assertTrue(all(0 <= s['requested_ms'] < 2000 for s in index['samples']))
        def pixel(x, y):
            return self.studio.run(['ffmpeg', '-v', 'error', '-i', sheet, '-vf', f'crop=2:2:{x}:{y}', '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']).stdout
        self.assertLess(max(pixel(120, 80)), 12)
        blue = pixel(120, 280)
        self.assertGreater(blue[2], 180)
        self.assertLess(blue[0], 30)
        self.assertNotIn(str(self.folder), json.dumps(index))
