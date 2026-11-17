"""Only verified, project-scoped local clips can be reused by new jobs."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_product_media as fixtures
from creative_shot_cache import ShotCache


class CreativeShotCache(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProductMediaTests(); self.fixture.setUp()
        self.studio = self.fixture.app.creative
        self.pid = self.fixture.pid
        self.source = Path(self.fixture.tmp.name) / 'synthetic-clip.mp4'
        self.studio.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                         'color=c=blue:s=160x120:r=24', '-t', '0.5', '-an', '-c:v', 'libx264',
                         '-threads', '1', '-pix_fmt', 'yuv420p', self.source])
        self.expected = self.studio.probe(self.source)
        self.cache = ShotCache(self.studio)
        self.key = self.cache.key(self.pid, {'source_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
                                               'caption': 'synthetic', 'keep_source_audio': False})
        self.output = self.studio.folder(self.pid) / 'reused.mp4'

    def tearDown(self):
        self.fixture.app.autonomy.stop(); self.fixture.tearDown()

    def test_verified_hit_copies_bytes_without_sharing_an_inode(self):
        self.assertTrue(self.cache.store(self.pid, self.key, self.source, 'synthetic-job'))
        hit = self.cache.restore(self.pid, self.key, self.output, self.expected)
        self.assertEqual(hit['origin_job_id'], 'synthetic-job')
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())
        self.assertNotEqual(self.output.stat().st_ino, (self.cache.base / (self.key + '.mp4')).stat().st_ino)
        self.output.write_bytes(b'synthetic local modification')
        self.assertIsNotNone(self.cache.restore(self.pid, self.key, self.output, self.expected))
        self.assertEqual(self.output.read_bytes(), self.source.read_bytes())

    def test_corruption_and_incompatible_media_are_misses(self):
        self.cache.store(self.pid, self.key, self.source, 'synthetic-job')
        self.assertIsNone(self.cache.restore(self.pid, self.key, self.output, {**self.expected, 'width': 320}))
        self.assertFalse(self.output.exists())
        (self.cache.base / (self.key + '.mp4')).write_bytes(b'corrupt synthetic cache')
        self.assertIsNone(self.cache.restore(self.pid, self.key, self.output, self.expected))
        self.assertFalse(self.output.exists())

    def test_another_project_cannot_reuse_an_entry_even_with_its_key(self):
        self.cache.store(self.pid, self.key, self.source, 'synthetic-job')
        self.assertIsNone(self.cache.restore('a' * 32, self.key, self.output, self.expected))
        self.assertFalse(self.output.exists())

    def test_cache_is_bounded_and_evicts_only_owned_entries(self):
        self.cache.limit = self.source.stat().st_size + 1
        self.cache.store(self.pid, self.key, self.source, 'synthetic-job')
        second = self.cache.key(self.pid, {'caption': 'changed synthetic caption'})
        self.assertTrue(self.cache.store(self.pid, second, self.source, 'new-synthetic-job'))
        self.assertIsNone(self.cache.restore(self.pid, self.key, self.output, self.expected))
        self.assertIsNotNone(self.cache.restore(self.pid, second, self.output, self.expected))
        self.assertLessEqual(sum(p.stat().st_size for p in self.cache.base.glob('*.mp4')), self.cache.limit)

    def test_disabled_or_symlinked_storage_does_not_change_source_or_write_outside(self):
        with patch.dict('os.environ', {'COMMERCE_CREATIVE_SHOT_CACHE_MB': '0'}):
            disabled = ShotCache(self.studio)
        self.assertFalse(disabled.store(self.pid, self.key, self.source, 'synthetic-job'))
        outside = Path(self.fixture.tmp.name) / 'outside'; outside.mkdir()
        self.cache.base.symlink_to(outside, target_is_directory=True)
        self.assertFalse(self.cache.store(self.pid, self.key, self.source, 'synthetic-job'))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertGreater(self.source.stat().st_size, 0)
