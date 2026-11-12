"""A bound Surface is a view over the original product checkpoint and artifacts."""
import sqlite3
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a2ui.cost import CostSurfaces, dispatch, validate_surface
import test_organization as fixtures


class ProductBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.app, self.case_id = self.fixture.app, self.fixture.cid
        self.values = self.fixture.prepare_cost()
        self.workspace = self.app.product_workspace
        self.surfaces = CostSurfaces(self.app.core, self.app.a2ui.calculator, workspace=self.workspace)

    def snapshot(self):
        return self.workspace.get(self.case_id)

    def create(self, key='open-bound'):
        return self.surfaces.create(key, case_id=self.case_id, expected_source_sha256=self.snapshot()['source_sha256'])

    def change(self, surface, data=None, calculate=False, key='change', **overrides):
        args = dict(ident=surface['surface_id'], revision=surface['revision'], data=self.values if data is None else data,
                    calculate=calculate, idempotency_key=key, case_id=self.case_id,
                    expected_source_sha256=surface['binding']['source_sha256'])
        args.update(overrides)
        return self.surfaces.update(**args)

    def test_open_reuses_case_surface_and_original_tasks_without_new_business_truth(self):
        own = self.app.core.invoke('commerce_task_create', {'idempotency_key':'bound-original-task', 'kind':'analysis', 'input':{'organization_case':self.case_id}})
        before = self.app.core.invoke('commerce_task_list', {})['tasks']
        first, second = self.create(), self.create('different-open-key')
        self.assertEqual(first['surface_id'], second['surface_id'])
        self.assertEqual(first['binding']['case_id'], self.case_id)
        self.assertEqual(first['revision'], self.snapshot()['forms']['cost']['revision'])
        self.assertEqual(first['input'], self.values)
        self.assertEqual(first['task_ids'], [own['id']])
        self.assertFalse(first['task_created'])
        self.assertEqual(self.app.core.invoke('commerce_task_list', {})['tasks'], before)
        self.assertTrue(validate_surface(first['messages']))
        with self.app.core.db() as db:
            raw = db.execute('SELECT input,result FROM a2ui_cost_surfaces WHERE id=?', (first['surface_id'],)).fetchone()
        self.assertEqual(tuple(raw), ('{}', None))

    def test_update_and_calculate_use_product_cas_and_artifact_handoff(self):
        surface = self.create()
        saved = self.change(surface, dict(self.values, price=120), key='save-input')
        self.assertIsNone(saved['result'])
        current = self.snapshot()
        self.assertEqual(current['forms']['cost']['payload']['input']['price'], 120)
        self.assertEqual(saved['revision'], current['forms']['cost']['revision'])
        calculated = self.change(saved, dict(self.values, price=120), True, 'calculate')
        self.assertEqual(calculated['result']['status'], 'CALCULATED')
        self.assertAlmostEqual(calculated['result']['contribution'], 54.4)
        self.assertEqual(self.app.organization.artifact(self.case_id, 'economics')['payload']['price'], 120)
        self.assertEqual(calculated['binding']['source_sha256'], self.snapshot()['source_sha256'])
        self.assertEqual(calculated['revision'], self.snapshot()['forms']['cost']['revision'])
        restored = CostSurfaces(self.app.core, self.app.a2ui.calculator, workspace=self.workspace).get(surface['surface_id'])
        self.assertEqual(restored, calculated)

    def test_stale_source_preserves_input_and_rejects_old_action(self):
        saved = self.change(self.create(), key='saved-before-source-change')
        research = self.fixture.research()
        research['record']['fields']['title']['zh'] = '更新后的合成资料'
        self.app.organization.record(self.case_id, 'research', research, 'bound-source-changed')
        current = self.surfaces.get(saved['surface_id'])
        self.assertTrue(current['binding']['stale'])
        self.assertEqual(current['input'], self.values)
        self.assertIsNone(current['result'])
        with self.assertRaisesRegex(ValueError, 'workspace_source_changed'):
            self.change(saved, calculate=True)
        self.assertEqual(self.snapshot()['forms']['cost']['payload']['input'], self.values)
        confirmed = self.change(current, key='save-after-reading-current-source')
        self.assertFalse(confirmed['binding']['stale'])
        self.assertIsNone(confirmed['result'])
        calculated = self.change(confirmed, calculate=True, key='calculate-current-source')
        self.assertEqual(calculated['result']['contribution'], 38)

    def test_external_edit_and_cross_case_cannot_overwrite(self):
        surface = self.create()
        self.workspace.save(self.case_id, 'cost', {'input':dict(self.values, price=150)}, surface['revision'], surface['binding']['source_sha256'])
        with self.assertRaisesRegex(ValueError, 'form_draft_conflict'):
            self.change(surface)
        current = self.surfaces.get(surface['surface_id'])
        with self.assertRaisesRegex(ValueError, 'a2ui_case_mismatch'):
            self.change(current, case_id='another-case')
        self.assertEqual(self.snapshot()['forms']['cost']['payload']['input']['price'], 150)

    def test_missing_scope_and_revoked_connection_reject_even_replay(self):
        surface = self.create()
        with self.assertRaisesRegex(ValueError, 'a2ui_binding_required'):
            self.surfaces.update(surface['surface_id'], surface['revision'], self.values)
        self.change(surface, key='revoked-replay')
        self.app.live.configure({'ozon_client_id':'654321'})
        with self.assertRaisesRegex(ValueError, 'case_not_found'): self.surfaces.get(surface['surface_id'])
        with self.assertRaisesRegex(ValueError, 'case_not_found'): self.change(surface, key='revoked-replay')

    def test_unknown_retry_returns_original_receipt_without_repeating_handoff(self):
        surface = self.create()
        first = self.change(surface, calculate=True, key='exact-calculation')
        count = self.snapshot()['forms']['cost']['revision']
        replay = self.change(surface, calculate=True, key='exact-calculation')
        self.assertEqual(replay, first)
        self.assertEqual(self.snapshot()['forms']['cost']['revision'], count)
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.change(surface, dict(self.values, price=200), True, 'exact-calculation')

    def test_receipt_failure_rolls_back_product_checkpoint(self):
        surface = self.create()
        before = self.snapshot()['forms']['cost']
        with self.app.core.db() as db:
            db.execute("CREATE TRIGGER bound_receipt_failure BEFORE INSERT ON a2ui_requests WHEN NEW.request_key='fail-receipt' BEGIN SELECT RAISE(ABORT,'synthetic_receipt_failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.change(surface, key='fail-receipt')
        self.assertEqual(self.snapshot()['forms']['cost'], before)

    def test_calculation_receipt_failure_rolls_back_original_artifact_and_source(self):
        surface = self.create()
        before = self.snapshot()
        with self.app.core.db() as db:
            db.execute("CREATE TRIGGER bound_calculation_failure BEFORE INSERT ON a2ui_requests WHEN NEW.request_key='fail-calculation' BEGIN SELECT RAISE(ABORT,'synthetic_calculation_failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.change(surface, dict(self.values, price=120), True, 'fail-calculation')
        current = self.snapshot()
        self.assertEqual(current['forms']['cost'], before['forms']['cost'])
        self.assertEqual(current['artifacts']['economics']['id'], before['artifacts']['economics']['id'])
        self.assertEqual(current['source_sha256'], before['source_sha256'])

    def test_concurrent_bound_open_and_edit_reuse_original_cas(self):
        with ThreadPoolExecutor(3) as pool:
            opened = list(pool.map(lambda n:self.create('parallel-open-'+str(n)), range(3)))
        self.assertEqual(len({s['surface_id'] for s in opened}), 1)
        self.assertEqual(opened[0]['task_ids'], [])
        self.assertIsNone(opened[0]['task_id'])
        def update(price):
            try: return self.change(opened[0], dict(self.values, price=price), key='parallel-'+str(price))
            except ValueError as exc: return str(exc)
        with ThreadPoolExecutor(2) as pool:
            updated = list(pool.map(update, (120,150)))
        self.assertEqual(sum(isinstance(v,dict) for v in updated), 1)
        self.assertIn('form_draft_conflict', updated)
        self.assertEqual(self.app.core.invoke('commerce_task_list', {})['tasks'], [])

    def test_replay_cannot_present_older_receipt_as_current_after_external_edit(self):
        surface = self.create()
        saved = self.change(surface, key='old-receipt')
        self.workspace.save(self.case_id, 'cost', {'input':dict(self.values,price=200)}, saved['revision'], saved['binding']['source_sha256'])
        with self.assertRaisesRegex(ValueError, 'form_draft_conflict'):
            self.change(surface, key='old-receipt')
        self.assertEqual(self.snapshot()['forms']['cost']['payload']['input']['price'], 200)

    def test_bound_listing_and_reopen_recheck_connection_and_internal_transaction_flag_is_not_public(self):
        surface = self.create()
        self.app.live.configure({'ozon_client_id':'654321'})
        self.assertEqual(self.surfaces.listing()['surfaces'], [])
        with self.assertRaisesRegex(ValueError, 'case_not_found'):
            self.surfaces.create('open-bound', case_id=self.case_id, expected_source_sha256=surface['binding']['source_sha256'])
        with self.assertRaisesRegex(ValueError, 'invalid_arguments'):
            self.app.invoke('commerce_workspace_save', {'case_id':self.case_id,'form':'cost','payload':{'input':self.values},'expected_revision':0,'expected_source_sha256':'0'*64,'_reuse':True})

    def test_bound_missing_input_holds_and_dispatch_contract(self):
        surface = self.create()
        held = self.change(surface, {'currency':'CNY', 'price':100}, True, 'missing-input')
        self.assertEqual(held['result']['status'], 'HOLD')
        self.assertIn('purchase_cost', held['result']['missing'])
        current = dispatch(self.surfaces, 'commerce_a2ui_create', {'case_id':self.case_id, 'expected_source_sha256':held['binding']['source_sha256']})
        self.assertEqual(current['surface_id'], held['surface_id'])
        event={'version':'1.0','action':{'surfaceId':held['surface_id'],'name':'commerce.cost.calculate','sourceComponentId':'calculate','timestamp':'2026-01-01T00:00:00Z','context':{}}}
        calculated = dispatch(self.surfaces, 'commerce_a2ui_action', {'event':event,'revision':str(current['revision']),'input':self.values,'case_id':self.case_id,'expected_source_sha256':current['binding']['source_sha256'],'idempotency_key':'action-bound'})
        self.assertEqual(calculated['result']['contribution'],38)


if __name__ == '__main__': unittest.main()
