"""Synthetic A2UI contracts; no marketplace data or credentials."""
import copy
import sys
import tempfile
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a2ui.cost import CostSurfaces, validate_surface, CATALOG_ID
from commerce_core import Core
from operations_analysis import unit_economics

INPUT = dict(currency='CNY', price=100, purchase_cost=30, domestic_shipping=2,
             packaging=1, fulfillment_cost=10, electronic_fee=1,
             commission_rate=.1, payment_rate=.01, return_rate=.02, ad_rate=.05)


class CostSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.surfaces = CostSurfaces(Core(Path(self.tmp.name) / 'state.sqlite'), unit_economics)

    def test_v1_catalog_and_empty_surface(self):
        surface = self.surfaces.create()
        self.assertTrue(validate_surface(surface['messages']))
        self.assertEqual(surface['messages'][0]['version'], '1.0')
        self.assertEqual(surface['messages'][0]['createSurface']['catalogId'], CATALOG_ID)
        self.assertEqual(surface['input'], {})
        self.assertIsNone(surface['result'])

    def test_reject_components_actions_and_old_wire_fields(self):
        original = self.surfaces.create()['messages']
        for mutate in (
            lambda m: m[0].update(version='v0.9'),
            lambda m: m[0]['createSurface']['components'][0].update(component='HTML'),
            lambda m: m[0]['createSurface']['components'][0].update(html='<script>bad()</script>'),
            lambda m: next(c for c in m[0]['createSurface']['components'] if c['component']=='Button')['action']['event'].update(name='commerce_task_create'),
            lambda m: m[0]['createSurface'].update(catalogId='https://example.org/evil'),
        ):
            value = copy.deepcopy(original)
            mutate(value)
            with self.assertRaises(ValueError): validate_surface(value)

    def test_real_calculation_recompute_and_shared_task(self):
        surface = self.surfaces.create()
        updated = self.surfaces.update(surface['surface_id'], 0, INPUT, calculate=True)
        self.assertEqual(updated['result']['contribution'], 38)
        self.assertEqual(updated['result'], unit_economics(INPUT))
        self.assertEqual(updated['result']['data_source'], 'caller_input')
        self.assertEqual(self.surfaces.get(surface['surface_id']), updated)
        edited = self.surfaces.update(surface['surface_id'], 1, dict(INPUT, purchase_cost=40))
        self.assertIsNone(edited['result'])
        result = self.surfaces.update(surface['surface_id'], 2, edited['input'], calculate=True)
        self.assertEqual(result['result']['contribution'], 28)
        task = self.surfaces.core.invoke('commerce_task_get', {'task_id':surface['task_id']})
        self.assertEqual(task['input']['surface_id'], surface['surface_id'])
        self.assertEqual(task['status'], 'queued')

    def test_missing_invalid_stale_and_disabled(self):
        surface = self.surfaces.create()
        held = self.surfaces.update(surface['surface_id'], 0, {}, calculate=True)
        self.assertEqual(held['result']['status'], 'HOLD')
        self.assertIn('currency', held['result']['missing'])
        for bad in (dict(INPUT, commission_rate=1.1), dict(INPUT, price=-1), dict(INPUT, currency='usd'), dict(INPUT, price=True), dict(INPUT, price=float('nan')), dict(INPUT, x=1)):
            with self.assertRaises(ValueError): self.surfaces.update(surface['surface_id'], 1, bad, calculate=True)
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.surfaces.update(surface['surface_id'], 0, INPUT)
        self.surfaces.set_enabled(False)
        with self.assertRaisesRegex(ValueError, 'a2ui_disabled'): self.surfaces.create()
        self.assertEqual(self.surfaces.get(surface['surface_id'])['result']['status'], 'HOLD')

    def test_concurrent_edit_rejects_loser_and_survives_new_service(self):
        surface = self.surfaces.create()
        def edit(price):
            try: return self.surfaces.update(surface['surface_id'], 0, dict(INPUT, price=price))
            except ValueError as exc: return str(exc)
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(edit, (100, 120)))
        self.assertEqual(sum(isinstance(v, dict) for v in values), 1)
        self.assertIn('a2ui_revision_conflict', values)
        restored = CostSurfaces(self.surfaces.core, unit_economics).get(surface['surface_id'])
        self.assertEqual(restored['revision'], 1)

    def test_tree_size_bindings_and_event_boundaries(self):
        original = self.surfaces.create()['messages']
        for mutate in (
            lambda m: m[0]['createSurface']['components'][0]['children'].append('root'),
            lambda m: m[0]['createSurface']['components'].append({'id':'orphan','component':'Text','text':'data'}),
            lambda m: m[0]['createSurface']['components'][3].update(value={'path':'/input/currency'}),
            lambda m: m[0]['createSurface']['components'][3].update(value={'@path':'/__proto__/x'}),
        ):
            bad=copy.deepcopy(original);mutate(bad)
            with self.assertRaises(ValueError): validate_surface(bad)
        sid=original[0]['createSurface']['surfaceId']
        event={'version':'1.0','action':{'name':'commerce.cost.calculate','surfaceId':sid,'sourceComponentId':'calculate','timestamp':'invalid','context':{}}}
        with self.assertRaisesRegex(ValueError,'action_forbidden'):self.surfaces.action(event,0,INPUT)

    def test_surface_creation_failure_does_not_leave_orphan_task(self):
        with self.surfaces.core.db() as db:
            db.execute("CREATE TRIGGER reject_surface BEFORE INSERT ON a2ui_cost_surfaces BEGIN SELECT RAISE(ABORT,'synthetic_failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.surfaces.create()
        self.assertEqual(self.surfaces.core.invoke('commerce_task_list', {})['tasks'], [])


if __name__ == '__main__': unittest.main()
