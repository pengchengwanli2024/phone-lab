"""Template upgrades do not change the identity of an accepted production request."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_product_media as media_fixture
from creative_direction import specification


class RequestReplay(unittest.TestCase):
    def setUp(self):
        self.fixture = media_fixture.ProductMediaTests()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.project = self.fixture.direction()

    def tearDown(self):
        self.app.autonomy.stop()
        self.fixture.tearDown()

    def create(self, kind='product_main', key='upgrade-replay'):
        return self.app.media.request_create(self.fixture.pid, self.project['revision'], kind, key)

    def test_retry_uses_saved_spec_after_a_template_upgrade_for_every_format(self):
        for kind in ('product_main', 'product_detail', 'usage_scene', 'ugc_video'):
            def legacy(project, selected):
                value = deepcopy(specification(project, selected))
                value['prompt'] += '\nSynthetic legacy template.'
                value['width'] = 640
                return value
            key = 'upgrade-' + kind
            with patch('creative_workflow.specification', side_effect=legacy):
                original = self.create(kind, key)
            replay = self.create(kind, key)
            self.assertEqual(replay['id'], original['id'])
            self.assertEqual(replay['request_sha256'], original['request_sha256'])
            self.assertEqual(replay['spec'], original['spec'])

    def test_new_key_uses_new_template_but_same_key_different_kind_is_rejected(self):
        original = self.create()
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.create('usage_scene')
        new = self.create(key='new-design-version')
        self.assertNotEqual(new['id'], original['id'])
        self.assertEqual(new['spec'], specification(self.app.media.project(self.fixture.pid), 'product_main'))

    def test_corrupted_saved_spec_is_not_reused(self):
        original = self.create()
        changed = deepcopy(original)
        changed['spec']['prompt'] += '\nSynthetic corruption without updating its digest.'
        with self.app.core.db() as db:
            db.execute('UPDATE creative_requests SET document=? WHERE id=?', (json.dumps(changed), original['id']))
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.create()


if __name__ == '__main__':
    unittest.main()
