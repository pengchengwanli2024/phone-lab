"""Integrated API continuity; one Store, task ledger and official Catalog."""
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from test_a2ui_cost import INPUT


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.app=Commerce(self.tmp.name)
    def call(self,operation,**args):return self.app.invoke('commerce_a2ui_'+operation,args,'test')
    def create(self):return self.call('create',idempotency_key='stable-create')
    def test_create_replays_original_identity_and_current_revision(self):
        surface=self.create();self.call('update',surface_id=surface['surface_id'],revision='0',input=INPUT,idempotency_key='save')
        again=self.create();self.assertEqual(again['surface_id'],surface['surface_id']);self.assertEqual(again['revision'],1)
        self.assertEqual(len(self.app.core.invoke('commerce_task_list',{})['tasks']),1)
    def test_mutation_replay_does_not_advance_version_and_conflicts_reject(self):
        surface=self.create();args=dict(surface_id=surface['surface_id'],revision='0',input=INPUT,idempotency_key='save')
        first=self.call('update',**args);self.assertEqual(self.call('update',**args),first)
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.call('update',**{**args,'input':{**INPUT,'price':200}})
    def test_concurrent_create_creates_one_shared_task(self):
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:self.create(),range(4)))
        self.assertEqual(len({x['surface_id'] for x in results}),1)
        self.assertEqual(len(self.app.core.invoke('commerce_task_list',{})['tasks']),1)
    def test_restart_lists_original_surface_without_creating_tasks(self):
        original=self.create();other=Commerce(self.tmp.name)
        items=other.invoke('commerce_a2ui_list',{})['surfaces']
        self.assertEqual(items[0]['surface_id'],original['surface_id'])
    def test_store_capacity_does_not_leave_orphan_task(self):
        surface=self.create()
        with self.app.core.db() as db:
            for n in range(511):db.execute('INSERT INTO a2ui_cost_surfaces VALUES (?,?,0,?,NULL)',('cost_'+format(n,'032x'),'capacity-test','{}'))
        with self.assertRaisesRegex(ValueError,'a2ui_capacity_reached'):self.call('create',idempotency_key='over-capacity')
        self.assertEqual(len(self.app.core.invoke('commerce_task_list',{})['tasks']),1)

if __name__=='__main__':unittest.main()
