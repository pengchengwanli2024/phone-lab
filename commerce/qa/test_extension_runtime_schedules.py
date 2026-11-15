"""Durable schedule events, rising edges and bounded after-run ancestry."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_extension_runtime import RuntimeCase

class Schedules(RuntimeCase):
    def enable_schedule(self,**value):
        schedule=self.call('schedule_save',schedule=value)
        return self.call('schedule_enable',schedule_id=schedule['id'],expected_revision=schedule['revision'],enabled=True)
    def test_after_run_processes_each_unhandled_source_without_repeating(self):
        source=self.ready(name='Source');target=self.ready(name='Target')
        schedule=self.enable_schedule(extension_id=target['id'],trigger='after_run',after_extension_id=source['id'])
        first=self.call('run',extension_id=source['id'],idempotency_key='source1');self.drain(first)
        second=self.call('run',extension_id=source['id'],idempotency_key='source2');self.drain(second)
        for _ in range(3):
            self.app.tick()
            runs=[r for r in self.call('run_list',extension_id=target['id'])['runs'] if not r['test']]
            for run in runs:self.drain(run)
        self.assertEqual(len(runs),2);self.assertTrue(all(r['schedule_id']==schedule['id'] for r in runs))
    def test_condition_is_rising_edge_and_interval_sampled(self):
        source=self.ready(name='Condition source');target=self.ready(name='Condition target')
        schedule=self.enable_schedule(extension_id=target['id'],trigger='condition',after_extension_id=source['id'],interval_seconds=60,condition={'op':'eq','left':{'$ref':'output.mode'},'right':'unconfigured'})
        self.app.tick(at=60)
        self.assertEqual([r for r in self.call('run_list',extension_id=target['id'])['runs'] if not r['test']],[])
        run=self.call('run',extension_id=source['id'],idempotency_key='observation');self.drain(run)
        self.app.tick(at=120);targets=[r for r in self.call('run_list',extension_id=target['id'])['runs'] if not r['test']];self.assertEqual(len(targets),1);self.drain(targets[0])
        self.app.tick(at=180);self.assertEqual(len([r for r in self.call('run_list',extension_id=target['id'])['runs'] if not r['test']]),1)
    def test_schedule_disabled_after_enqueue_cancels_its_pending_task(self):
        ext=self.ready();schedule=self.enable_schedule(extension_id=ext['id'],trigger='interval',interval_seconds=60)
        self.app._schedule_tick(1000);runs=[r for r in self.call('run_list',extension_id=ext['id'])['runs'] if not r['test']];self.assertEqual(len(runs),1)
        self.call('schedule_enable',schedule_id=schedule['id'],expected_revision=schedule['revision'],enabled=False)
        self.assertEqual(self.call('run_get',run_id=runs[0]['id'])['status'],'cancelled')

    def test_manual_schedule_runs_saved_scope_input_budget_once(self):
        ext=self.ready();schedule=self.enable_schedule(extension_id=ext['id'],trigger='manual',input={'saved':True},scope={'case_id':'case-fixture'},budget={'max_steps':2,'max_model_calls':0})
        run=self.call('schedule_run',schedule_id=schedule['id'],expected_revision=schedule['revision'],idempotency_key='manual')
        same=self.call('schedule_run',schedule_id=schedule['id'],expected_revision=schedule['revision'],idempotency_key='manual')
        self.assertEqual(run['id'],same['id']);self.assertEqual(run['input'],{'saved':True});self.assertEqual(run['scope'],{'case_id':'case-fixture'});self.assertEqual(run['budget']['max_steps'],2);self.assertEqual(run['schedule_id'],schedule['id'])
        self.assertEqual(self.drain(run)['status'],'succeeded')
    def test_after_run_cycle_stops_at_ancestor_instead_of_ping_pong(self):
        left=self.ready(name='Left');right=self.ready(name='Right')
        self.enable_schedule(extension_id=left['id'],trigger='after_run',after_extension_id=right['id'])
        self.enable_schedule(extension_id=right['id'],trigger='after_run',after_extension_id=left['id'])
        run=self.call('run',extension_id=left['id'],idempotency_key='cycle-root');self.drain(run)
        for _ in range(8):
            self.app.tick()
            actual=[r for r in self.call('run_list')['runs'] if not r['test']]
            for value in actual:
                if value['status'] in ('queued','running'):self.drain(value)
        self.assertEqual(len(actual),3)

if __name__=='__main__':unittest.main()
