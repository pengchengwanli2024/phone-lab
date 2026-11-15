"""Synthetic durable follow-ups; checks never execute the watched work."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from service import Commerce, TOOLS
import test_attention as attention_fixture

NOW = 1800000000


def date(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


class Followups(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.fixture = attention_fixture.Attention(); self.fixture.app = self.app; self.fixture.counter = 0
        self.clock = patch('followups.time.time', return_value=NOW)
        self.clock.start()

    def tearDown(self):
        self.clock.stop(); self.app.agent_runtime.stop(); self.temp.cleanup()

    def targets(self, **args):
        return self.app.invoke('commerce_followup_targets', args)

    def create(self, target, key='create', due=NOW+60):
        return self.app.invoke('commerce_followup_create', {'target': target, 'due_at': date(due), 'idempotency_key': key})

    def source(self):
        return next(t['target'] for t in self.targets()['targets'] if t['target']['kind']=='public_source' and t['target']['ref']=='usgs')

    def task(self):
        task = self.app.core.invoke('commerce_task_create', {'kind': 'report', 'input': {'title': '合成结果检查'}, 'idempotency_key': 'watched-task'})
        return task, next(t['target'] for t in self.targets()['targets'] if t['target']['kind']=='task_result')

    def test_registered_targets_are_bounded_local_reads_without_scheduling(self):
        self.assertIn('commerce_followup_targets', {name for name,_,_ in TOOLS})
        self.fixture.run_record(questions=['请补齐合成资料'])
        with patch('agent_runtime.model.invoke') as model, patch('intelligence.fetch') as fetch:
            result = self.targets()
        self.assertTrue(any(t['target']['kind']=='attention' for t in result['targets']))
        self.assertTrue(any(t['target']['kind']=='public_source' for t in result['targets']))
        self.assertFalse(any(t['target']['kind']=='public_source' for t in self.targets(demo=True)['targets']))
        self.assertEqual(self.app.invoke('commerce_followup_list', {})['items'], [])
        model.assert_not_called(); fetch.assert_not_called()

    def test_target_discovery_collects_attention_once_for_the_whole_catalog(self):
        for _ in range(12):self.fixture.run_record(questions=['合成待补充资料'])
        with patch.object(self.app.attention, '_collect', wraps=self.app.attention._collect) as collect:
            result = self.targets()
        self.assertEqual(sum(t['target']['kind']=='attention' for t in result['targets']), 12)
        self.assertEqual(collect.call_count, 1)

    def test_task_catalog_filters_mode_before_its_bound_and_discloses_truncation(self):
        demo_task = self.app.core.invoke('commerce_task_create', {'kind':'report','input':{'title':'较早的合成任务','demo':True},'idempotency_key':'older-demo'})
        for index in range(100):
            self.app.core.invoke('commerce_task_create', {'kind':'report','input':{'demo':False},'idempotency_key':'real-'+str(index)})
        result = self.targets(demo=True)
        self.assertIn(demo_task['id'], [t['target']['ref'] for t in result['targets']])
        self.assertTrue(result['complete'])
        for index in range(100):
            self.app.core.invoke('commerce_task_create', {'kind':'report','input':{'demo':True},'idempotency_key':'demo-'+str(index)})
        result = self.targets(demo=True)
        self.assertEqual(sum(t['target']['kind']=='task_result' for t in result['targets']), 100)
        self.assertFalse(result['complete'])
        self.assertTrue(result['truncated'])

    def test_create_is_idempotent_even_after_due_time_and_conflicts_do_not_reschedule(self):
        target = self.source(); first = self.create(target)
        with patch('followups.time.time', return_value=NOW+120):
            self.assertEqual(self.create(target)['id'], first['id'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.create(target, due=NOW+90)
        with self.assertRaisesRegex(ValueError, 'already_scheduled'):
            self.create(target, key='another')
        self.assertEqual(len(self.app.invoke('commerce_followup_list', {})['items']), 1)

    def test_timezones_and_unknown_targets_are_validated(self):
        target = self.source()
        for due in ('2026-11-13T12:00:00', 'not-a-date', date(NOW-1)):
            with self.assertRaises(ValueError):
                self.app.invoke('commerce_followup_create', {'target': target, 'due_at': due, 'idempotency_key': due})
        for bad in ({**target, 'kind': 'shell'}, {**target, 'command': 'ignored'}, {**target, 'ref': 'arbitrary-url'}, {**target, 'version_sha256': '0'*64}):
            with self.assertRaises(ValueError):self.create(bad)

    def test_due_check_survives_service_recreation_and_is_done_once_after_a_long_sleep(self):
        saved = self.create(self.source())
        other = Commerce(self.temp.name)
        self.assertEqual(other.followups.tick(at=NOW+59), 0)
        self.assertEqual(other.followups.tick(at=NOW+86400), 1)
        self.assertEqual(other.followups.tick(at=NOW+90000), 0)
        value = other.invoke('commerce_followup_get', {'followup_id': saved['id']})
        self.assertEqual(value['state'], 'checked')
        self.assertEqual(value['receipt']['condition'], 'unchanged')
        with other.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM followup_checks').fetchone()[0], 1)

    def test_concurrent_ticks_commit_only_one_check(self):
        saved = self.create(self.source())
        with ThreadPoolExecutor(max_workers=4) as pool:
            checks = list(pool.map(lambda _: self.app.followups.tick(at=NOW+61), range(4)))
        self.assertEqual(sum(checks), 1)
        self.assertEqual(self.app.invoke('commerce_followup_get', {'followup_id': saved['id']})['state'], 'checked')

    def test_reschedule_and_cancel_are_revision_bound_and_do_not_cancel_original_work(self):
        task, target = self.task(); saved = self.create(target)
        changed = self.app.invoke('commerce_followup_reschedule', {'followup_id': saved['id'], 'expected_revision': saved['revision'], 'due_at': date(NOW+180)})
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.app.invoke('commerce_followup_cancel', {'followup_id': saved['id'], 'expected_revision': saved['revision']})
        self.assertEqual(self.app.followups.tick(at=NOW+100), 0)
        cancelled = self.app.invoke('commerce_followup_cancel', {'followup_id': saved['id'], 'expected_revision': changed['revision']})
        self.assertEqual(cancelled['state'], 'cancelled')
        self.assertEqual(self.app.followups.tick(at=NOW+1000), 0)
        self.assertEqual(self.app.core.invoke('commerce_task_get', {'task_id':task['id']})['status'], 'queued')

    def test_task_results_are_observed_without_execution_or_model_calls(self):
        task, target = self.task(); saved = self.create(target)
        self.app.autonomy.request(task['id'], 'report')
        self.app.autonomy.work(NOW+10)  # The original explicit fixture work completes before the check.
        with patch('agent_runtime.model.invoke') as model, patch.object(self.app.autonomy, 'request', side_effect=AssertionError('must not execute')):
            self.app.followups.tick(at=NOW+61)
        result = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertEqual(result['receipt']['condition'], 'ready')
        model.assert_not_called()
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM task_runs').fetchone()[0], 1)

    def test_a_completion_marker_without_a_receipt_is_not_reported_as_a_new_result(self):
        task, target = self.task(); saved = self.create(target)
        with self.app.core.db() as db:db.execute("UPDATE tasks SET status='completed' WHERE id=?", (task['id'],))
        self.app.followups.tick(at=NOW+61)
        value = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertEqual(value['receipt']['condition'], 'needs_attention')
        self.assertFalse(value['receipt']['observed']['receipt_available'])

    def test_unknown_result_stays_unknown_without_retry(self):
        task, target = self.task(); saved = self.create(target)
        with self.app.core.db() as db:db.execute("UPDATE tasks SET status='unknown' WHERE id=?", (task['id'],))
        self.app.followups.tick(at=NOW+61)
        value = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertEqual(value['receipt']['condition'], 'outcome_unknown')
        self.assertEqual(self.app.core.invoke('commerce_task_get', {'task_id':task['id']})['status'], 'unknown')

    def test_new_saved_source_snapshot_is_reported_without_fetching(self):
        saved = self.create(self.source())
        with self.app.core.db() as db:
            db.execute('INSERT OR REPLACE INTO intel_sources VALUES (?,?)', ('usgs', json.dumps({'last_success':NOW+20,'payload_sha256':'a'*64,'status':'ok'})))
        with patch('intelligence.fetch', side_effect=AssertionError('must not fetch')):
            self.app.followups.tick(at=NOW+61)
        value = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertEqual(value['receipt']['condition'], 'ready')
        self.assertFalse(value['receipt']['business_verified'])

    def test_an_older_source_snapshot_is_not_reported_as_a_new_success(self):
        with self.app.core.db() as db:db.execute('INSERT INTO intel_sources VALUES (?,?)',
            ('usgs',json.dumps({'last_success':NOW-10,'payload_sha256':'a'*64})))
        saved = self.create(self.source())
        with self.app.core.db() as db:db.execute('UPDATE intel_sources SET state=? WHERE id=?',
            (json.dumps({'last_success':NOW-100,'payload_sha256':'b'*64}),'usgs'))
        self.app.followups.tick(at=NOW+61)
        value = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertEqual(value['receipt']['condition'], 'needs_attention')

    def test_demo_targets_and_followup_receipts_keep_their_original_data_mode(self):
        self.fixture.run_record(questions=['合成范围资料'], demo=True)
        target = next(t['target'] for t in self.targets(demo=True)['targets'] if t['target']['kind']=='attention')
        saved = self.create(target)
        self.assertEqual(self.app.invoke('commerce_followup_list', {})['items'], [])
        self.app.followups.tick(at=NOW+61)
        self.assertEqual(self.app.invoke('commerce_attention_list', {'include_followups':True})['items'], [])
        self.assertTrue(any(i['source']=='followup' for i in self.app.invoke('commerce_attention_list', {'demo':True,'include_followups':True})['items']))

    def test_later_context_changes_disable_an_already_saved_receipt_action(self):
        thread = self.fixture.thread(); self.fixture.run_record(thread=thread, questions=['补充原资料'])
        target = next(t['target'] for t in self.targets()['targets'] if t['target']['kind']=='attention')
        saved = self.create(target); self.app.followups.tick(at=NOW+61)
        original = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertIsNotNone(original['current_action'])
        self.app.copilot.context(thread['id'], {'module':'products'}, thread['context_sha256'])
        current = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertIsNone(current['current_action'])
        self.assertEqual(current['receipt'], original['receipt'])

    def test_context_changes_remove_original_actions_and_do_not_rebind_to_a_new_scope(self):
        thread = self.fixture.thread()
        self.fixture.run_record(thread=thread, questions=['请补齐原资料'])
        target = next(t['target'] for t in self.targets()['targets'] if t['target']['kind']=='attention')
        saved = self.create(target)
        changed = self.app.copilot.context(thread['id'], {'module':'products'}, thread['context_sha256'])
        self.app.copilot.context(thread['id'], thread['context'], changed['context_sha256'])
        self.app.followups.tick(at=NOW+61)
        value = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.assertEqual(value['receipt']['condition'], 'scope_changed')
        self.assertIsNone(value['receipt']['action'])

    def test_optional_attention_projection_and_ack_preserve_old_client_contract(self):
        saved = self.create(self.source()); self.app.followups.tick(at=NOW+61)
        self.assertEqual(self.app.invoke('commerce_attention_list', {})['items'], [])
        result = self.app.invoke('commerce_attention_list', {'include_followups':True})
        self.assertEqual(result['items'][0]['source'], 'followup')
        self.assertEqual(result['items'][0]['action'], {'type':'followup','id':saved['id']})
        current = self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})
        self.app.invoke('commerce_followup_ack', {'followup_id':saved['id'], 'expected_revision':current['revision']})
        self.assertEqual(self.app.invoke('commerce_attention_list', {'include_followups':True})['items'], [])

    def test_receipt_insert_failure_rolls_back_the_check_for_safe_restart(self):
        saved = self.create(self.source())
        with self.app.core.db() as db:db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON followup_checks BEGIN SELECT RAISE(ABORT,'synthetic interruption'); END")
        with self.assertRaises(Exception):self.app.followups.tick(at=NOW+61)
        self.assertEqual(self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})['state'], 'scheduled')
        with self.app.core.db() as db:db.execute('DROP TRIGGER fail_receipt')
        self.assertEqual(Commerce(self.temp.name).followups.tick(at=NOW+62), 1)

    def test_existing_runtime_clock_processes_due_checks_without_source_collection(self):
        saved = self.create(self.source())
        with patch('intelligence.fetch', side_effect=AssertionError('must not fetch')):
            self.app.autonomy.tick(at=NOW+61, collect=False)
        self.assertEqual(self.app.invoke('commerce_followup_get', {'followup_id':saved['id']})['state'], 'checked')


if __name__ == '__main__':unittest.main()
