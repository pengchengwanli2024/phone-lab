"""Sales-before-video policy over the real operating projection and local fixtures."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures


class OperatingVideoPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests()
        self.fixture.setUp()
        self.app = self.fixture.app
        self.target = dict(case_id=self.fixture.cid, platform='ozon', store_ref='ozon-live', market='RU')

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.app.autonomy.stop()
        self.fixture.tearDown()

    def get(self, **extra):
        return self.app.invoke('commerce_operating_pipeline_get', {**self.target, **extra}, 'test')

    @staticmethod
    def video(view):
        return next(stage for stage in view['stages'] if stage['id'] == 'ugc')

    def bind_media(self):
        project, asset = self.fixture.creative()
        brief = project['brief']
        brief['product_binding'] = dict(case_id=self.fixture.cid,
            source_sha256=self.app.product_workspace.sources(self.fixture.cid)[3])
        project = self.app.creative.save(project['id'], brief, project['revision'])
        self.app.organization.deliver(self.fixture.cid, project['id'], [asset['id']], 'video-policy-images')
        brief = project['brief']
        brief['product_binding']['source_sha256'] = self.app.product_workspace.sources(self.fixture.cid)[3]
        return self.app.creative.save(project['id'], brief, project['revision'])

    def test_unsold_product_defers_video_without_blocking_image_first_launch(self):
        with self.app.core.db() as db:
            before = db.execute('SELECT count(*) FROM creative_requests').fetchone()[0]
        result = self.get()
        video = self.video(result)
        self.assertEqual(video['acceptance_status'], 'deferred')
        self.assertFalse(video['required_for_goal'])
        self.assertFalse(video['automation_policy']['automatic_generation_allowed'])
        self.assertEqual(video['automation_policy']['strategy'], 'verified_product_sales_before_video')
        self.assertEqual(video['automation_policy']['sale_verification'], 'verified_product_sales_adapter_missing')
        self.assertTrue(video['automation_policy']['missing_sales_contract'])
        self.assertTrue(all(action['effect'] == 'read' for action in video['next_actions']))
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM creative_requests').fetchone()[0], before)

    def test_positive_self_reported_orders_are_visible_but_cannot_unlock_generation(self):
        project = self.bind_media()
        old = self.get()
        record = self.app.media.performance_save(project['id'], dict(period_start='2026-01-01T00:00:00Z',
            period_end='2026-01-02T00:00:00Z', source_ref='synthetic:unverified-sales-report', orders=10, returns=1), 'sales-report')
        result = self.get()
        policy = self.video(result)['automation_policy']
        self.assertEqual(policy['observations']['positive_reported_order_records'], 1)
        self.assertIn(record['id'], policy['observations']['reported_record_ids'])
        self.assertEqual(policy['observations']['reported_orders_verification'], 'self_reported_not_verified_product_sales')
        self.assertFalse(policy['automatic_generation_allowed'])
        self.assertEqual(self.video(result)['acceptance_status'], 'deferred')
        self.assertNotEqual(old['snapshot_sha256'], result['snapshot_sha256'])
        with self.assertRaisesRegex(ValueError, 'operating_snapshot_changed'):
            self.get(expected_snapshot_sha256=old['snapshot_sha256'])

    def test_fulfillment_counts_including_delivered_do_not_become_verified_sales(self):
        self.bind_media()
        self.app.live.configure({'orders_scope_confirmed': True})
        config = self.app.live.config()
        for status in ('awaiting_packaging', 'cancelled', 'delivered'):
            with self.subTest(status=status):
                self.app.live._publish(config['connection_id'], 'orders', fixtures.batch('orders', status=status), config, True)
                policy = self.video(self.get())['automation_policy']
                self.assertEqual(policy['observations']['fulfillment']['units'], 2)
                self.assertEqual(policy['observations']['fulfillment']['units_by_raw_status'], {status: 2})
                self.assertEqual(policy['observations']['fulfillment']['scope'], 'matching_product_and_fulfillment_only_not_settled_sales')
                self.assertFalse(policy['automatic_generation_allowed'])
                self.assertEqual(policy['sale_verification'], 'verified_product_sales_adapter_missing')

    def test_other_target_cannot_reuse_reported_orders_or_fulfillment_counts(self):
        project = self.bind_media()
        self.app.media.performance_save(project['id'], dict(period_start='2026-01-01T00:00:00Z',
            period_end='2026-01-02T00:00:00Z', source_ref='synthetic:unverified-sales-report', orders=10), 'sales-report')
        result = self.get(platform='shopify', store_ref='other-store', market='US')
        policy = self.video(result)['automation_policy']
        self.assertEqual(policy['observations']['status'], 'target_mismatch')
        self.assertEqual(policy['observations']['positive_reported_order_records'], 0)
        self.assertIsNone(policy['observations']['fulfillment'])
        self.assertFalse(policy['automatic_generation_allowed'])

    def test_stale_project_binding_cannot_supply_sales_observations(self):
        project = self.bind_media()
        self.app.media.performance_save(project['id'], dict(period_start='2026-01-01T00:00:00Z',
            period_end='2026-01-02T00:00:00Z', source_ref='synthetic:unverified-sales-report', orders=10), 'sales-report')
        self.app.organization.set_currency(self.fixture.cid, 'CNY')
        policy = self.video(self.get())['automation_policy']
        self.assertEqual(policy['observations']['status'], 'binding_stale')
        self.assertEqual(policy['observations']['positive_reported_order_records'], 0)
        self.assertFalse(policy['automatic_generation_allowed'])

    def test_other_ozon_store_cannot_reuse_product_fulfillment_snapshot(self):
        self.bind_media()
        policy = self.video(self.get(store_ref='different-ozon-store'))['automation_policy']
        self.assertEqual(policy['observations']['status'], 'store_scope_unverified')
        self.assertIsNone(policy['observations']['fulfillment'])
        self.assertFalse(policy['automatic_generation_allowed'])

    def test_stale_fulfillment_is_retained_as_stale_observation_without_unlocking(self):
        self.bind_media()
        config = self.app.live.config()
        snapshot = self.app.live.snapshot(config['connection_id'], 'orders')
        with self.app.core.db() as db:
            db.execute("UPDATE live_snapshots SET observed='2020-01-01T00:00:00+00:00' WHERE id=?", (snapshot['id'],))
        policy = self.video(self.get())['automation_policy']
        self.assertFalse(policy['observations']['fulfillment']['fresh'])
        self.assertFalse(policy['automatic_generation_allowed'])

    def test_periodic_review_does_not_turn_video_views_into_a_video_production_proposal(self):
        project = self.bind_media()
        self.app.media.performance_save(project['id'], dict(period_start='2026-01-01T00:00:00Z',
            period_end='2026-01-02T00:00:00Z', source_ref='synthetic:video-report',
            video_views=200, completed_views=100, orders=10), 'video-report')
        review = self.app.media.review_now(project['id'], 'after-sales-policy')
        self.assertFalse(any(proposal['kind'].endswith('_video') for proposal in review['recommendations']))
        self.assertFalse(review['video_policy']['automatic_generation_allowed'])
        self.assertTrue(review['deferred_recommendations'])
        self.assertFalse(any('proposed_spec' in proposal for proposal in review['deferred_recommendations']))

    def test_missing_click_metrics_falls_back_to_images_instead_of_video(self):
        project = self.bind_media()
        self.app.media.performance_save(project['id'], dict(period_start='2026-01-01T00:00:00Z',
            period_end='2026-01-02T00:00:00Z', source_ref='synthetic:impressions-only', impressions=200), 'no-clicks')
        review = self.app.media.review_now(project['id'], 'no-clicks')
        self.assertTrue(review['recommendations'])
        self.assertFalse(any(proposal['kind'].endswith('_video') for proposal in review['recommendations']))
        repeated = self.app.media.review_now(project['id'], 'no-clicks')
        self.assertEqual(review, repeated)

    def test_scheduled_review_preserves_previous_receipt_and_only_recommends_images(self):
        project = self.bind_media()
        self.app.media.performance_save(project['id'], dict(period_start='2026-01-01T00:00:00Z',
            period_end='2026-01-02T00:00:00Z', source_ref='synthetic:video-report',
            video_views=200, completed_views=100), 'video-report')
        old = self.app.media.review_now(project['id'], 'before-tick')
        schedule = self.app.media.policy_save(project['id'], 0, True, 1)
        self.app.media.tick(schedule['next_due'] + 1)
        overview = self.app.media.overview(project['id'])
        scheduled = next(review for review in overview['reviews'] if review['slot'].startswith('scheduled:'))
        self.assertFalse(any(proposal['kind'].endswith('_video') for proposal in scheduled['recommendations']))
        self.assertFalse(scheduled['video_policy']['automatic_generation_allowed'])
        self.assertEqual(old, self.app.media.review_now(project['id'], 'before-tick'))


if __name__ == '__main__':
    unittest.main()
