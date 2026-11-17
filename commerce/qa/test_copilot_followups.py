"""Durable follow-ups exercise the real local runner with synthetic models only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from copilot.followups import CopilotFollowups


def answer(text='Synthetic answer'):
    return {'provider': 'synthetic', 'model': 'synthetic', 'decision': {
        'phase': 'answer', 'answer': text, 'questions': [], 'evidence_refs': [], 'proposals': []}}


class CopilotFollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.chat = self.app.copilot
        self.thread = self.chat.open({'module': 'intelligence', 'demo': True}, 'open')
        self.first = self.chat.send(self.thread['id'], '请解释海运提单', self.thread['context_sha256'], 'first')
        self.queue = self.chat.followups

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.temp.cleanup()

    def add(self, message='请再解释装箱单', **extra):
        return self.queue.add(thread_id=self.thread['id'], message=message,
            context_sha256=self.thread['context_sha256'], after_run_id=extra.pop('after_run_id', self.first['latest_run']['id']),
            idempotency_key=extra.pop('idempotency_key', 'next'), **extra)

    def snapshot(self):
        return self.queue.snapshot(self.thread['id'])

    def complete(self):
        with patch('agent_runtime.model.invoke', return_value=answer()) as model:
            self.assertTrue(self.app.agent_runtime.run_once())
        return model

    def test_add_is_idempotent_durable_and_does_not_start_a_model(self):
        with patch('agent_runtime.model.invoke') as model:
            with ThreadPoolExecutor(max_workers=3) as workers:
                values = list(workers.map(lambda _: self.add(), range(3)))
            ids = {v['items'][0]['id'] for v in values}
            self.assertEqual(len(ids), 1)
            model.assert_not_called()
        self.assertEqual(CopilotFollowups(self.chat).snapshot(self.thread['id'])['items'][0]['message'], '请再解释装箱单')
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.add(message='different')
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 1)

    def test_fifo_waits_for_current_response_and_dispatches_exactly_once(self):
        self.add(); self.add('最后说明两者区别', idempotency_key='last')
        self.complete()
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 1)
        model = self.complete()
        self.assertEqual(model.call_args.args[0]['question'], '请再解释装箱单')
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 2)
        self.complete()
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 3)
        self.assertFalse(self.app.agent_runtime.run_once())
        self.assertEqual([i['status'] for i in self.snapshot()['items']], ['sent', 'sent'])

    def test_edit_move_cancel_and_stale_revision_protect_another_window(self):
        self.add(); q = self.add('第二条', idempotency_key='two'); first, second = q['items']
        q = self.queue.change(self.thread['id'], second['id'], q['revision'], 'move_up')
        self.assertEqual(q['items'][0]['id'], second['id'])
        with self.assertRaisesRegex(ValueError, 'followup_changed'):
            self.queue.change(self.thread['id'], first['id'], q['revision'] - 1, 'cancel')
        q = self.queue.change(self.thread['id'], first['id'], q['revision'], 'edit', message='修改后的问题')
        q = self.queue.change(self.thread['id'], second['id'], q['revision'], 'cancel')
        self.complete(); model = self.complete()
        self.assertEqual(model.call_args.args[0]['question'], '修改后的问题')
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 2)

    def test_failed_or_unknown_response_pauses_until_explicit_resume(self):
        self.add()
        with patch('agent_runtime.model.invoke', side_effect=ValueError('agent_provider_outcome_unknown')):
            self.app.agent_runtime.run_once()
        self.assertFalse(self.app.agent_runtime.run_once())
        q = self.snapshot(); self.assertTrue(q['paused'])
        self.assertEqual(q['items'][0]['status'], 'held')
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 1)
        self.queue.resume(self.thread['id'], q['revision'], self.thread['context_sha256'])
        self.complete()
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 2)
        self.assertEqual(self.chat.get(self.thread['id'])['turns'][0]['run']['status'], 'unknown')

    def test_context_drift_is_held_and_queue_bounds_are_enforced(self):
        for i in range(8): self.add(str(i), idempotency_key='bounded-' + str(i))
        with self.assertRaisesRegex(ValueError, 'followup_queue_full'):
            self.add(idempotency_key='too-many')
        self.complete()
        self.chat.context(self.thread['id'], {'module': 'orders', 'demo': True}, self.thread['context_sha256'])
        self.assertFalse(self.app.agent_runtime.run_once())
        self.assertTrue(self.snapshot()['paused'])
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 1)

    def test_a_dispatch_failure_rolls_back_partial_run_and_turn(self):
        self.add(); self.complete()
        with patch.object(self.app.market_research, 'bind_send', side_effect=ValueError('synthetic_dispatch_failure')):
            self.assertFalse(self.queue.dispatch_one())
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_turns').fetchone()[0], 1)
        self.assertEqual(self.snapshot()['items'][0]['status'], 'held')

    def test_steer_reaches_next_model_step_in_same_run_without_extra_run(self):
        captured = []
        def provider(context, *args, **kwargs):
            captured.append(context)
            if len(captured) == 1:
                self.add('请改成三点说明', mode='steer', idempotency_key='steer')
            return answer()
        with patch('agent_runtime.model.invoke', side_effect=provider):
            self.app.agent_runtime.run_once()
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[1]['followup_instructions'][0]['message'], '请改成三点说明')
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 1)
        self.assertEqual(self.snapshot()['items'][0]['status'], 'included')

    def test_late_final_step_steer_is_retained_as_not_received(self):
        captured = []
        def provider(context, *args, **kwargs):
            captured.append(context)
            self.add('补充-' + str(len(captured)), mode='steer', idempotency_key='steer-' + str(len(captured)))
            return answer()
        with patch('agent_runtime.model.invoke', side_effect=provider):
            self.app.agent_runtime.run_once()
        self.assertEqual(len(captured), 3)
        q = self.snapshot(); late = q['items'][-1]
        self.assertEqual(late['status'], 'not_received')
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 1)
        self.queue.change(self.thread['id'], late['id'], q['revision'], 'queue')
        self.complete()
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 2)

    def test_other_thread_anchor_and_unknown_arguments_are_rejected(self):
        other = self.chat.open({'module': 'intelligence', 'demo': True}, 'other')
        other_run = self.chat.send(other['id'], '解释术语', other['context_sha256'], 'other-send')
        with self.assertRaisesRegex(ValueError, 'followup_anchor_changed'):
            self.add(after_run_id=other_run['latest_run']['id'])
        with self.assertRaisesRegex(ValueError, 'invalid_arguments'):
            self.chat.invoke('commerce_copilot_followup_add', {'url': 'https://example.com'})

    def test_malformed_material_ids_are_rejected_without_a_partial_queue(self):
        for bad in ([{}], [[]], [None], 'not-an-array', ['a'*32, 'a'*32]):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                self.add(material_ids=bad)
        self.assertEqual(self.snapshot()['items'], [])

    def test_budget_rejection_does_not_acknowledge_an_unsent_supplement(self):
        self.add(mode='steer')
        with patch.object(self.app.chain_budget, 'model_step', side_effect=ValueError('agent_chain_budget_exhausted')), patch('agent_runtime.model.invoke') as model:
            self.app.agent_runtime.run_once()
            model.assert_not_called()
        self.assertEqual(self.snapshot()['items'][0]['status'], 'not_received')

    def test_recovery_settles_unreceived_supplement_and_pauses_queue(self):
        self.add(mode='steer')
        self.add('下一轮',idempotency_key='queue')
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='running',owner='dead' WHERE id=?", (self.first['latest_run']['id'],))
        with patch('agent_runtime.threading.Thread'):
            self.app.agent_runtime.start(recover=True)
        self.assertEqual(self.chat.get(self.thread['id'])['latest_run']['status'], 'interrupted')
        self.assertEqual([item['status'] for item in self.snapshot()['items']], ['not_received','held'])

    def test_cancelling_a_terminal_run_does_not_pause_its_followups(self):
        self.complete(); self.add()
        self.app.agent_runtime.cancel(self.first['latest_run']['id'])
        self.assertEqual(self.snapshot()['items'][0]['status'], 'queued')
        self.complete()
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'], 2)

    def test_native_handoff_offers_queue_until_actual_supplement_receipts_exist(self):
        with self.app.core.db() as db:
            row = db.execute('SELECT payload FROM agent_runs WHERE id=?',(self.first['latest_run']['id'],)).fetchone()
            payload = json.loads(row[0]); payload['model_route']['provider'] = 'host_native'
            db.execute('UPDATE agent_runs SET payload=? WHERE id=?',(json.dumps(payload),self.first['latest_run']['id']))
        self.assertFalse(self.snapshot()['can_steer'])
        with self.assertRaisesRegex(ValueError,'steer_unavailable'):self.add(mode='steer')
        self.assertEqual(self.add()['items'][0]['status'],'queued')

    def test_queued_capabilities_keep_the_checked_version_and_reject_registry_drift(self):
        selected=self.chat.capabilities.check(self.thread['context'],['mcp:commerce'])
        self.add(capability_ids=selected['capability_ids'],expected_capability_sha256=selected['selection_sha256'])
        self.complete()
        self.assertTrue(self.queue.dispatch_one())
        with self.app.core.db() as db:
            payload=json.loads(db.execute('SELECT payload FROM agent_runs ORDER BY rowid DESC LIMIT 1').fetchone()[0])
        self.assertEqual(payload['capability_selection'],selected)

    def test_queued_capability_drift_is_held_without_a_partial_run(self):
        selected=self.chat.capabilities.check(self.thread['context'],['mcp:commerce'])
        self.add(capability_ids=selected['capability_ids'],expected_capability_sha256=selected['selection_sha256'])
        self.complete()
        with patch.object(self.chat.capabilities,'freeze',side_effect=ValueError('copilot_capability_changed')):
            self.assertFalse(self.queue.dispatch_one())
        self.assertEqual(self.snapshot()['items'][0]['status'],'held')
        self.assertEqual(self.chat.get(self.thread['id'])['total_turns'],1)

    def test_steer_cannot_change_the_frozen_capability_selection(self):
        selected=self.chat.capabilities.check(self.thread['context'],['mcp:commerce'])
        with self.assertRaisesRegex(ValueError,'steer_capability_requires_queue'):
            self.add(mode='steer',capability_ids=selected['capability_ids'],expected_capability_sha256=selected['selection_sha256'])


if __name__ == '__main__': unittest.main()
