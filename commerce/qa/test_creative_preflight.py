"""Production checks use real private files; synthetic footage proves no motion claims."""
from copy import deepcopy
from pathlib import Path
import subprocess
import unittest
import wave
from unittest.mock import patch

import test_product_media as fixtures


class CreativePreflight(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProductMediaTests(); self.fixture.setUp()
        self.app = self.fixture.app; self.p = self.fixture.direction(); self.pid = self.p['id']
        self.request = self.app.media.request_create(self.pid, self.p['revision'], 'showcase_video', 'preflight')

    def tearDown(self):
        self.app.autonomy.stop(); self.fixture.tearDown()

    def inspect(self, asset_ids=None, **extra):
        return self.app.invoke('commerce_media_request_preflight', {
            'request_id': self.request['id'], 'expected_revision': self.p['revision'],
            'asset_ids': asset_ids or [self.fixture.asset['id']] * 5, **extra})

    def footage(self, seconds=1):
        path = Path(self.fixture.tmp.name) / 'synthetic-static-video.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=blue:s=160x120:r=24', '-t', str(seconds), '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(path)], check=True)
        return self.app.creative.register(self.pid, 'product_video', path, {'source_ref': 'synthetic:static-video'})

    def test_read_only_preflight_reports_stills_and_no_audio_without_jobs(self):
        before = self.app.creative.get(self.pid)
        report = self.inspect()
        self.assertTrue(report['can_render'])
        self.assertEqual(report['delivery_kind'], 'still_image_video_draft')
        self.assertEqual(report['summary']['still_duration_ms'], 30000)
        self.assertEqual(report['summary']['video_duration_ratio'], 0)
        self.assertIsNone(report['semantic_motion_verified'])
        self.assertIn('no_output_audio', [x['code'] for x in report['warnings']])
        self.assertEqual(report, self.inspect())
        self.assertEqual(self.app.creative.get(self.pid), before)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM creative_jobs').fetchone()[0], 0)

    def test_duration_weighting_and_real_probe_reveal_looping_without_calling_it_motion(self):
        video = self.footage()
        report = self.inspect([self.fixture.asset['id'], self.fixture.asset['id'], video['id'], self.fixture.asset['id'], self.fixture.asset['id']])
        self.assertEqual(report['summary']['video_duration_ms'], 12000)
        self.assertEqual(report['summary']['video_duration_ratio'], .4)
        self.assertEqual(report['summary']['looped_shot_indexes'], [2])
        self.assertEqual(report['shots'][2]['source_duration_ms'], 1000)
        self.assertIsNone(report['semantic_motion_verified'])

    def test_edited_clip_range_is_rejected_before_starting_a_job(self):
        video = self.footage()
        editing = {'aspect_ratio': '9:16', 'keep_source_audio': False,
                   'shots': [{'source_index': i, 'source_start_ms': 900, 'duration_ms': 500, 'caption': ''} for i in range(5)]}
        self.request = self.app.media.request_edit(request_id=self.request['id'], expected_request_sha256=self.request['request_sha256'], editing=editing, idempotency_key='range')
        report = self.inspect([video['id']] * 5)
        self.assertFalse(report['can_render'])
        self.assertIn('creative_clip_range_exceeded', [x['code'] for x in report['errors']])
        with self.assertRaisesRegex(ValueError, 'creative_clip_range_exceeded'):
            self.app.media.request_execute(self.request['id'], self.p['revision'], [video['id']] * 5)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM creative_jobs').fetchone()[0], 0)

    def test_changed_and_cross_project_assets_and_stale_requests_are_rejected(self):
        self.app.creative.asset(self.pid, self.fixture.asset['id'])[0].write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'creative_asset_changed'):
            self.inspect()
        other = self.app.creative.create(deepcopy(fixtures.BRIEF), 'another')
        with self.assertRaisesRegex(ValueError, 'creative_asset_not_found'):
            self.app.media.request_preflight(self.request['id'], self.p['revision'], [other['id']] * 5)
        brief = deepcopy(self.p['brief']); brief['product']['name'] = 'Another synthetic product'
        self.app.creative.save(self.pid, brief, self.p['revision'])
        with self.assertRaisesRegex(ValueError, 'creative_request_stale'):
            self.inspect()

    def test_missing_tool_is_a_blocker_and_no_private_paths_are_returned(self):
        with patch('creative_tools.command', side_effect=ValueError('creative_local_tool_unavailable')):
            report = self.inspect()
        self.assertFalse(report['can_render'])
        self.assertIn('creative_local_tool_unavailable', [x['code'] for x in report['errors']])
        self.assertNotIn(self.fixture.tmp.name, str(report))

    def test_preserving_audio_on_stills_explicitly_reports_a_silent_track(self):
        editing = {'aspect_ratio': '9:16', 'keep_source_audio': True,
                   'shots': [{'source_index': i, 'source_start_ms': 0, 'duration_ms': 500, 'caption': ''} for i in range(5)]}
        self.request = self.app.media.request_edit(request_id=self.request['id'], expected_request_sha256=self.request['request_sha256'], editing=editing, idempotency_key='silence')
        report = self.inspect()
        self.assertTrue(report['summary']['output_has_audio'])
        self.assertIn('silent_output_audio', [x['code'] for x in report['warnings']])

    def test_short_audio_exposes_silent_tail_using_real_audio_duration(self):
        path = Path(self.fixture.tmp.name) / 'synthetic-audio.wav'
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
            audio.writeframes(b'\0\0' * 8000)
        asset = self.app.creative.register(self.pid, 'audio', path, {'source_ref': 'synthetic:audio'})
        report = self.inspect(audio_asset_id=asset['id'])
        self.assertTrue(report['can_render']); self.assertEqual(report['summary']['audio_duration_ms'], 1000)
        self.assertIn({'code': 'audio_padded_with_silence', 'duration_ms': 29000}, report['warnings'])
        with self.assertRaisesRegex(ValueError, 'creative_product_media_required'):
            self.inspect([asset['id']] * 5, audio_asset_id=asset['id'])

    def test_invalid_timeline_and_overlong_captions_cannot_pass_preflight(self):
        from creative_preflight import inspect
        spec = deepcopy(self.request['spec']); spec['shots'][2]['start_ms'] += 100
        spec['script']['hook'] = 'x' * 101
        report = inspect(self.app.creative, self.pid, spec, [self.fixture.asset['id']] * 5)
        self.assertFalse(report['can_render'])
        self.assertIn('creative_timeline_invalid', [x['code'] for x in report['errors']])
        self.assertIn('creative_caption_too_long_shorten_product_facts', [x['code'] for x in report['errors']])

    def test_output_review_rejects_dimension_duration_audio_or_missing_decode(self):
        from creative_preflight import output_review
        report = self.inspect(); media = {'duration_seconds': 30, 'width': 720, 'height': 1280, 'has_audio': False}
        for changes, decoded in [({'width': 1280}, True), ({'duration_seconds': 31}, True), ({'has_audio': True}, True), ({}, False)]:
            with self.subTest(changes=changes, decoded=decoded):
                result = output_review(report, self.request['spec'], {**media, **changes}, 'a' * 64, decoded=decoded)
                self.assertEqual(result['technical_status'], 'failed')
        self.assertEqual(output_review(report, self.request['spec'], media, 'a' * 64, decoded=True)['technical_status'], 'passed')


if __name__ == '__main__':
    unittest.main()
