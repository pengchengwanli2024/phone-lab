"""Operating guidance reads real product modules and reuses durable workflows."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from research import canonical


class OperatingPipelineTests(unittest.TestCase):
    def test_projection_identifies_original_listing_version_for_ui_binding(self):
        value=self.get();listing=self.app.listings.get(**self.target)
        self.assertIn('listing_preview_sha256',value)
        self.assertEqual(value['listing_preview_sha256'],listing['preview_sha256'])
        self.assertEqual(value['listing_revision'],listing['revision'])

    def setUp(self):
        self.fixture = fixtures.OrganizationTests();self.fixture.setUp();self.app = self.fixture.app
        self.target = {'case_id': self.fixture.cid, 'platform': 'ozon', 'store_ref': 'ozon-live', 'market': 'RU'}

    def tearDown(self):
        self.app.agent_runtime.stop();self.app.autonomy.stop();self.fixture.tearDown()

    def get(self, **extra):
        return self.app.invoke('commerce_operating_pipeline_get', {**self.target, **extra}, 'test')

    @staticmethod
    def stage(value, ident):
        return next(s for s in value['stages'] if s['id'] == ident)

    def task_count(self):
        with self.app.core.db() as db: return db.execute('SELECT count(*) FROM tasks').fetchone()[0]

    def drain(self, run, at=None):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            self.app.extensions.tick(at=at);value = self.app.extensions.run_get(run['id'])
            if value['status'] not in ('queued', 'running'): return value
            time.sleep(.01)
        self.fail('Operating diagnostic workflow did not finish')

    def template(self):
        value = self.get()
        return self.app.invoke('commerce_operating_pipeline_template', {**self.target,
            'expected_snapshot_sha256': value['snapshot_sha256']}, 'test')

    def test_full_lifecycle_gaps_are_explicit_without_creating_work(self):
        before = self.task_count();value = self.get()
        ids = {s['id'] for s in value['stages']}
        self.assertTrue({'research', 'sourcing', 'economics', 'images', 'ugc', 'listing', 'growth',
            'service', 'procurement', 'logistics', 'settlement', 'brand', 'policy'} <= ids)
        self.assertEqual(self.task_count(), before)
        self.assertFalse(value['external_execution_allowed']);self.assertFalse(value['business_outcome_verified'])
        self.assertEqual(self.stage(value, 'economics')['acceptance_status'], 'needs_evidence')
        self.assertTrue(self.stage(value, 'policy')['missing'], 'A policy hold must name the missing evidence')
        for ident in ('growth', 'service', 'logistics', 'settlement', 'brand'):
            self.assertIn(self.stage(value, ident)['capability_status'], ('partial', 'missing'))
            self.assertNotEqual(self.stage(value, ident)['acceptance_status'], 'verified')
        self.assertFalse(self.stage(value, 'logistics')['required_for_goal'])
        self.assertIsNotNone(value['next_action']['tool'])
        self.app.validate(value['next_action']['tool'], value['next_action']['arguments'])

    def test_real_upstream_artifact_changes_next_step_without_fabricating_fact_verification(self):
        old = self.get();self.fixture.prepare_research();new = self.get()
        self.assertNotEqual(old['snapshot_sha256'], new['snapshot_sha256'])
        self.assertEqual(self.stage(new, 'research')['acceptance_status'], 'prepared')
        self.assertEqual(self.stage(new, 'research')['verification'], 'local_contract_checks_only')
        self.assertEqual(new['next_action']['stage_id'], 'sourcing')
        self.assertFalse(new['business_outcome_verified'])
        with self.assertRaisesRegex(ValueError, 'operating_snapshot_changed'):
            self.get(expected_snapshot_sha256=old['snapshot_sha256'])

    def test_target_market_change_cannot_reuse_old_research_or_compliance_acceptance(self):
        self.fixture.prepare_cost()
        elsewhere = self.get(platform='shopify', store_ref='shopify-pending', market='US')
        self.assertFalse(elsewhere['source_target_matches'])
        self.assertNotEqual(self.stage(elsewhere, 'research')['acceptance_status'], 'prepared')
        self.assertNotEqual(self.stage(elsewhere, 'policy')['acceptance_status'], 'prepared')
        self.assertFalse(elsewhere['business_outcome_verified'])

    def test_goal_dependencies_do_not_require_sales_to_prepare_launch(self):
        launch = self.get();operation = self.get(goal='operate');brand = self.get(goal='brand')
        self.assertFalse(self.stage(launch, 'settlement')['required_for_goal'])
        self.assertTrue(self.stage(operation, 'logistics')['required_for_goal'])
        self.assertTrue(self.stage(brand, 'brand')['required_for_goal'])
        self.assertFalse(operation['business_outcome_verified'])

    def test_changed_cost_draft_requires_calculation_instead_of_reusing_old_gate(self):
        values = self.fixture.prepare_cost();view = self.app.product_workspace.get(self.fixture.cid)
        values = {**values, 'price': values['price'] + 1}
        self.app.product_workspace.save(self.fixture.cid, 'cost', {'input': values}, 0, view['source_sha256'])
        result = self.get()
        self.assertEqual(self.stage(result, 'economics')['acceptance_status'], 'needs_calculation')

    def test_calculation_action_requires_current_currency_and_target(self):
        values = self.fixture.prepare_cost();view = self.app.product_workspace.get(self.fixture.cid)
        saved = self.app.product_workspace.save(self.fixture.cid, 'cost', {'input': values}, 0, view['source_sha256'])
        other_market = self.get(platform='shopify', store_ref='another-store', market='US')
        self.assertFalse(any(a['effect'] == 'local_prepare' for a in self.stage(other_market, 'economics')['next_actions']))
        self.app.product_workspace.save(self.fixture.cid, 'cost', {'input': {**values, 'currency': 'USD'}}, saved['revision'], view['source_sha256'])
        wrong_currency = self.get()
        self.assertFalse(any(a['effect'] == 'local_prepare' for a in self.stage(wrong_currency, 'economics')['next_actions']))

    def test_unknown_submission_takes_precedence_over_newer_stale_preparation(self):
        before = self.task_count()
        receipt = {'request_id': 'prior-request', 'current': False, 'decision': 'approved',
            'read_status': 'unknown', 'observation_status': None, 'submission_status': 'unknown', 'platform_submission_verified': False}
        with patch.object(self.app.listing_releases, 'summary', return_value=receipt):
            result = self.get()
        listing = self.stage(result, 'listing')
        self.assertEqual(listing['acceptance_status'], 'unknown')
        self.assertFalse(listing['source_current'])
        self.assertEqual(self.task_count(), before)

    def test_original_read_and_submission_states_cannot_be_hidden_by_stale_draft(self):
        for status in ('interrupted', 'unknown'):
            receipt = {'request_id': 'prior-read', 'current': False, 'decision': 'approved',
                'read_status': status, 'observation_status': None, 'platform_submission_verified': False}
            with self.subTest(read_status=status), patch.object(self.app.listing_releases, 'summary', return_value=receipt):
                self.assertEqual(self.stage(self.get(), 'listing')['acceptance_status'], 'unknown')
        for status in ('checking', 'submitting', 'accepted', 'interrupted_before_dispatch'):
            receipt = {'request_id': 'prior-submit', 'current': False, 'decision': 'approved',
                'read_status': 'not_requested', 'observation_status': None, 'submission_status': status,
                'platform_submission_verified': False}
            with self.subTest(submission_status=status), patch.object(self.app.listing_releases, 'summary', return_value=receipt):
                self.assertEqual(self.stage(self.get(), 'listing')['acceptance_status'], status)

    def test_stock_gate_does_not_become_other_market_procurement_acceptance(self):
        current = self.app.live.config()
        self.app.live._publish(current['connection_id'], 'orders', fixtures.batch('orders'), current, True)
        self.app.live._publish(current['connection_id'], 'stock', fixtures.batch('stock'), current, True)
        self.app.live.configure({'orders_scope_confirmed': True, 'stock_basis': 'present_minus_reserved', 'basis_confirmed': True})
        own = self.get(goal='operate')
        self.assertEqual(next(s for s in self.app.organization.board(self.fixture.cid)['stages'] if s['id'] == 'S8')['status'], 'PASS')
        self.assertNotEqual(self.stage(own, 'procurement')['acceptance_status'], 'prepared')
        elsewhere = self.get(platform='shopify', store_ref='another-store', market='US', goal='operate')
        procurement = self.stage(elsewhere, 'procurement')
        self.assertEqual(procurement['acceptance_status'], 'needs_target_evidence')
        self.assertEqual(procurement['evidence'], [])

    def test_unreadable_optional_media_binding_does_not_hide_other_operating_gaps(self):
        self.fixture.prepare_research();project, asset = self.fixture.creative()
        self.app.organization.deliver(self.fixture.cid, project['id'], [asset['id']], 'pipeline-delivery')
        brief = project['brief'];brief['product_binding'] = {'case_id': 'f' * 32, 'source_sha256': 'a' * 64}
        self.app.creative.save(project['id'], brief, project['revision'])
        value = self.get()
        self.assertEqual(self.stage(value, 'images')['acceptance_status'], 'failed')
        self.assertIn('关联素材项目', ' '.join(self.stage(value, 'ugc')['missing']))
        self.assertEqual(value['next_action']['stage_id'], 'sourcing')

    def test_older_unknown_submission_is_not_hidden_by_newer_local_application(self):
        from test_listing_submissions import ListingSubmissions
        fixture = ListingSubmissions();fixture.setUp()
        try:
            prepared = fixture.prepare();plan = fixture.s.plan(prepared['id'])
            fixture.s.event(plan, '', 'synthetic-unknown', 'synthetic_fault',
                {'status': 'unknown', 'dispatch_started': True, 'task_id': None, 'error': 'synthetic_outcome_unknown'})
            view = fixture.app.listings.get(**fixture.target)
            fixture.app.listing_releases.create(**fixture.target, expected_preview_sha256=view['preview_sha256'],
                note='Newer synthetic local draft', confirmed=True, idempotency_key='newer-local-application')
            value = fixture.app.invoke('commerce_operating_pipeline_get', fixture.target, 'test')
            self.assertEqual(self.stage(value, 'listing')['acceptance_status'], 'unknown')
            self.assertIn(fixture.rid, [r['request_id'] for r in value['unresolved_releases']])
            self.assertEqual(fixture.writes, [])
        finally:
            fixture.tearDown()

    def test_inactive_connection_and_incomplete_target_are_rejected(self):
        for extra in ({'market': ''}, {'store_ref': ''}, {'goal': 'buy_everything'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError): self.get(**extra)
        self.app.live.configure({'ozon_client_id': '654321'})
        with self.assertRaisesRegex(ValueError, 'case_not_found'): self.get()

    def test_template_is_readonly_uses_original_runtime_and_reports_business_hold(self):
        before = self.task_count();prepared = self.template();self.assertEqual(self.task_count(), before)
        self.assertFalse(prepared['execution_started'])
        ext = self.app.extensions.save(prepared['definition'])
        run = self.app.extensions.launch(ext['id'], **prepared['run_arguments'], idempotency_key='pipeline-test', test=True)
        checked = self.drain(run);self.assertEqual(checked['status'], 'succeeded')
        self.assertFalse(checked['output']['business_outcome_verified'])
        self.assertEqual(checked['usage']['model_calls'], 0)
        self.assertEqual(self.app.core.invoke('commerce_task_get', {'task_id': checked['task_id']})['status'], 'completed')
        self.assertEqual(self.task_count(), before + 1)

    def test_repeated_workflow_observes_changed_evidence_and_preserves_prior_receipt(self):
        prepared = self.template();ext = self.app.extensions.save(prepared['definition'])
        first = self.drain(self.app.extensions.launch(ext['id'], **prepared['run_arguments'], idempotency_key='first', test=True))
        self.app.extensions.enable(ext['id'], ext['version'], True);self.fixture.prepare_research()
        second = self.drain(self.app.extensions.launch(ext['id'], **prepared['run_arguments'], idempotency_key='second'))
        self.assertEqual(second['status'], 'succeeded')
        self.assertNotEqual(first['output']['snapshot_sha256'], second['output']['snapshot_sha256'])
        self.assertEqual(self.stage(second['output'], 'research')['acceptance_status'], 'prepared')
        old = self.app.extensions.run_get(first['id'])
        self.assertEqual(old['output'], first['output'])
        self.assertEqual(self.task_count(), 2)

    def test_builtin_rejects_same_case_with_other_store_or_market_scope(self):
        prepared = self.template();definition = copy.deepcopy(prepared['definition'])
        definition['spec']['steps'][0]['input']['store_ref'] = 'different-store'
        ext = self.app.extensions.save(definition)
        value = self.drain(self.app.extensions.launch(ext['id'], **prepared['run_arguments'], idempotency_key='wrong-target', test=True))
        self.assertEqual(value['status'], 'failed');self.assertEqual(value['error'], 'extension_scope_mismatch')

    def test_interval_slots_create_fresh_original_runs_without_replaying_prior_slot(self):
        prepared = self.template();ext = self.app.extensions.save(prepared['definition'])
        self.drain(self.app.extensions.launch(ext['id'], **prepared['run_arguments'], idempotency_key='schedule-test', test=True))
        self.app.extensions.enable(ext['id'], ext['version'], True)
        schedule = self.app.extensions.schedule_save({'extension_id': ext['id'], 'trigger': 'interval',
            'interval_seconds': 60, **prepared['run_arguments']})
        self.app.extensions.schedule_enable(schedule['id'], schedule['revision'], True)
        self.app.extensions.tick(at=1200)
        schedules = self.app.extensions.invoke('commerce_extension_schedule_list', {})['schedules']
        first_id = next(s for s in schedules if s['id'] == schedule['id'])['last_run_id']
        first = self.drain({'id': first_id}, at=1200)
        self.app.extensions.tick(at=1200)
        self.assertEqual(next(s for s in self.app.extensions.invoke('commerce_extension_schedule_list', {})['schedules'] if s['id'] == schedule['id'])['last_run_id'], first_id)
        self.fixture.prepare_research();self.app.extensions.tick(at=1260)
        second_id = next(s for s in self.app.extensions.invoke('commerce_extension_schedule_list', {})['schedules'] if s['id'] == schedule['id'])['last_run_id']
        second = self.drain({'id': second_id}, at=1260)
        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first['output']['snapshot_sha256'], second['output']['snapshot_sha256'])
        self.assertEqual(second['usage']['model_calls'], 0)

    def test_parser_and_template_are_readonly_mcp_tools(self):
        from operating_pipeline import READ_ONLY
        from service import TOOLS
        self.assertTrue(READ_ONLY <= {t[0] for t in TOOLS})
        self.assertEqual(READ_ONLY, {'commerce_operating_pipeline_get', 'commerce_operating_pipeline_template'})


if __name__ == '__main__': unittest.main()
