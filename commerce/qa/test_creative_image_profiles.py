"""Platform-specific image intent stays frozen and independent of video jobs."""
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_media_plugin_connections as fixtures


class ImageProfiles(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PluginConnections()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.p = self.fixture.fixture.direction()
        self.pid = self.p['id']

    def tearDown(self):
        self.fixture.tearDown()

    def create(self, options=None, kind='product_detail', key='profiled-image'):
        args = dict(project_id=self.pid, expected_revision=self.p['revision'], kind=kind, idempotency_key=key)
        if options is not None:
            args['image_options'] = options
        return self.app.invoke('commerce_media_request_create', args)

    def options(self, **values):
        return {'profile_id': 'ozon_ru', 'set_size': 6, 'label': '握柄特写', 'focus': '只展示原图可见的握柄细节。', **values}

    def test_ozon_portrait_focus_and_count_are_in_the_saved_request_and_plugin(self):
        r = self.create(self.options())
        self.assertEqual((r['spec']['width'], r['spec']['height']), (1536, 2048))
        self.assertEqual(r['spec']['image_options']['set_size'], 6)
        self.assertIn('只展示原图可见的握柄细节', r['spec']['prompt'])
        self.assertFalse(r['spec']['image_delivery']['publication_approved'])
        self.fixture.bind()
        plan = self.fixture.plugins.prepare(r['id'], self.p['revision'], 'lovart',
                                           [self.fixture.fixture.asset['id']], 1, 'profiled-plan')
        self.assertEqual(plan['tool_call']['arguments']['aspect_ratio'], '3:4')
        self.assertEqual(plan['generation_count'], 1)
        self.assertEqual(plan['tool_call']['arguments']['n'], 1)

    def test_set_planning_range_and_tiktok_us_limit_are_distinct(self):
        for count in (4, 11, True):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'image_set_size'):
                self.create(self.options(set_size=count), key='bad-count-' + str(count))
        with self.assertRaisesRegex(ValueError, 'image_platform_count'):
            self.create(self.options(profile_id='tiktok_us', set_size=10))
        r = self.create(self.options(profile_id='tiktok_us', set_size=9), key='tiktok-nine')
        self.assertEqual((r['spec']['width'], r['spec']['height']), (2048, 2048))
        self.assertEqual(r['spec']['image_delivery']['max_images'], 9)

    def test_same_key_reuses_snapshot_but_changed_focus_or_profile_is_rejected(self):
        one = self.create(self.options())
        self.assertEqual(self.create(self.options())['id'], one['id'])
        for options in (self.options(focus='只展示刷头'), self.options(profile_id='amazon_us')):
            with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
                self.create(options)

    def test_legacy_and_video_requests_keep_the_existing_contract(self):
        legacy = self.create()
        self.assertEqual((legacy['spec']['width'], legacy['spec']['height']), (1080, 1080))
        self.assertNotIn('image_delivery', legacy['spec'])
        with self.assertRaisesRegex(ValueError, 'image_options_video'):
            self.create(self.options(), kind='ugc_video', key='video-invalid')
        video = self.create(kind='ugc_video', key='legacy-video')
        self.assertEqual(video['spec']['duration_ms'], 30000)

    def test_unknown_rules_remain_unverified_and_wrong_tiktok_ratio_is_rejected(self):
        r = self.create(self.options(profile_id='woocommerce', aspect_ratio='3:4'))
        self.assertEqual(r['spec']['image_delivery']['verification'], 'store_or_category_rules_required')
        with self.assertRaisesRegex(ValueError, 'image_platform_ratio'):
            self.create(self.options(profile_id='tiktok_us', aspect_ratio='3:4'), key='wrong-ratio')

    def test_malformed_options_are_rejected_before_saving(self):
        for options in ([], self.options(profile_id={}), self.options(aspect_ratio=[]),
                        self.options(focus='x'*1001), self.options(focus='bad\x00text'),
                        self.options(extra='undeclared')):
            with self.subTest(options_type=type(options).__name__), self.assertRaises(ValueError):
                self.create(options)

    def test_local_image_output_uses_frozen_platform_canvas(self):
        for ratio,kind,size in [('3:4','product_main',(1536,2048)),('4:3','product_detail',(2048,1536))]:
            with self.subTest(ratio=ratio):
                r=self.create(self.options(aspect_ratio=ratio),kind=kind,key='canvas-'+kind)
                self.app.invoke('commerce_media_request_execute',{'request_id':r['id'],'expected_revision':self.p['revision'],
                                'asset_ids':[self.fixture.fixture.asset['id']]})
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    result=self.app.invoke('commerce_media_request_get',{'request_id':r['id']})
                    if result['status'] not in ('queued','running'):break
                    time.sleep(.05)
                self.assertEqual(result['status'],'awaiting_review')
                path,_,_=self.app.creative.asset(self.pid,result['assets'][0]['id'])
                import struct
                self.assertEqual(struct.unpack('>II',path.read_bytes()[16:24]),size)


if __name__ == '__main__':
    unittest.main()
