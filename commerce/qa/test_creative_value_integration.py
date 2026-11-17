"""New requests reuse only unchanged local shots and deliver actual review media."""
import copy
import hashlib
import json
from pathlib import Path
import time
import unittest
import zipfile

import test_product_media as fixtures


class CreativeValueIntegration(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProductMediaTests(); self.fixture.setUp()
        self.app = self.fixture.app; self.p = self.fixture.direction(); self.pid = self.p['id']
        self.original = self.app.media.request_create(self.pid, self.p['revision'], 'showcase_video', 'new-integration-original')
        self.editing = {'aspect_ratio': '16:9', 'keep_source_audio': False,
                        'shots': [{'source_index': i, 'source_start_ms': 0, 'duration_ms': 500,
                                   'caption': '合成镜头 ' + str(i)} for i in range(5)]}

    def tearDown(self):
        self.app.autonomy.stop(); self.fixture.tearDown()

    def render_new(self, key, editing=None):
        request = self.app.media.request_edit(request_id=self.original['id'], expected_request_sha256=self.original['request_sha256'],
            editing=editing or self.editing, idempotency_key=key)
        self.app.media.request_execute(request['id'], self.p['revision'], [self.fixture.asset['id']] * 5)
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            result = self.app.media.request_get(request['id'])
            if result['status'] not in ('queued', 'running'): break
            time.sleep(.05)
        self.assertEqual(result['status'], 'awaiting_review', result)
        return result

    def test_new_jobs_reuse_unchanged_shots_invalidate_edits_and_reject_corrupt_cache(self):
        cold = self.render_new('new-cold')
        self.assertEqual(cold['quality_report']['render_reuse']['reused_shot_indexes'], [])
        self.assertEqual(cold['quality_report']['render_reuse']['rendered_shot_indexes'], list(range(5)))
        warm = self.render_new('new-warm')
        self.assertNotEqual(cold['job_id'], warm['job_id'])
        self.assertEqual(warm['quality_report']['render_reuse']['reused_shot_indexes'], list(range(5)))
        editing = copy.deepcopy(self.editing); editing['shots'][2]['caption'] = '仅修改第三个合成镜头'
        changed = self.render_new('new-caption-change', editing)
        self.assertEqual(changed['quality_report']['render_reuse']['reused_shot_indexes'], [0, 1, 3, 4])
        self.assertEqual(changed['quality_report']['render_reuse']['rendered_shot_indexes'], [2])
        key = cold['quality_report']['render_reuse']['shots'][0]['key']
        (self.app.creative.root / '.shot-cache' / (key + '.mp4')).write_bytes(b'synthetic cache corruption')
        repaired = self.render_new('new-after-cache-corruption')
        self.assertEqual(repaired['quality_report']['render_reuse']['rendered_shot_indexes'], [0])
        self.assertEqual(self.app.media.request_get(cold['id']), cold)
        self.assertEqual(self.app.media.request_get(self.original['id'])['job_id'], None)

    def test_delivery_registers_bound_frame_overview_and_observations_in_same_package(self):
        result = self.render_new('new-delivery-review')
        quality = result['quality_report']
        self.assertEqual(quality['media_observations']['status'], 'completed')
        self.assertEqual(quality['media_observations']['audio']['status'], 'no_audio')
        self.assertIsNone(quality['semantic_motion_verified'])
        self.assertTrue(quality['human_review_required'])
        assets = {a['kind']: a for a in result['delivery_assets']}
        self.assertIn('review_contact_sheet', assets); self.assertIn('review_frame_index', assets)
        sheet = self.app.creative.asset(self.pid, assets['review_contact_sheet']['id'])[0]
        index = json.loads(self.app.creative.asset(self.pid, assets['review_frame_index']['id'])[0].read_text())
        self.assertEqual(index['video_sha256'], result['assets'][0]['sha256'])
        self.assertEqual(index['contact_sheet_sha256'], hashlib.sha256(sheet.read_bytes()).hexdigest())
        self.assertEqual(index, quality['review_frames'])
        package = self.app.creative.asset(self.pid, assets['delivery_package']['id'])[0]
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(archive.read('review-frames.png'), sheet.read_bytes())
            self.assertEqual(json.loads(archive.read('review-frames.json')), index)
            self.assertEqual(json.loads(archive.read('quality-report.json')), quality)
            self.assertEqual(json.loads(archive.read('manifest.json'))['quality_report'], quality)
