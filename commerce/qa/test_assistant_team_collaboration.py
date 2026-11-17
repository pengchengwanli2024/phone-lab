"""Actual Copilot/run-ledger integration with synthetic bounded model replies."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class TeamCollaborationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Commerce(self.tmp.name)
        self.team = self.app.assistant_team
        self.addCleanup(self.app.agent_runtime.stop)
        self.addCleanup(self.app.autonomy.stop)
        self.role = self.app.agent_runtime.roles()[0]['id']
        self.profiles = [self.team.profile_save({'name': name, 'role_id': self.role,
            'instructions': '只回答当前问题。', 'model_ids': ['project-default'],
            'enabled': True, 'expertise': [term]}) for name, term in [('物流顾问', '运输'), ('成本顾问', '毛利')]]
        self.channel = self.team.channel_save({'name': '合成协作频道', 'instructions': '不执行经营写入。',
            'context': {'module': 'overview', 'demo': True}, 'member_ids': [p['id'] for p in self.profiles],
            'routing': {'mode': 'auto', 'lead_id': self.profiles[1]['id'], 'rules': [], 'max_rounds': 1}})

    def ask(self, mode='collaborate', key='discussion-one', **kw):
        return self.team.discussion_start(self.channel['id'], self.channel['revision'],
            '解释海运提单的含义', key, mode=mode, **kw)

    def count_runs(self):
        with self.app.core.db() as db:
            return db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]

    def answer_one(self, answer='合成回答', question=None, seen=None):
        def invoke(payload, *args, **kw):
            if seen is not None:
                seen.append(payload)
            return {'decision': {'phase': 'answer', 'answer': answer, 'questions': [question] if question else [],
                'proposals': [], 'evidence_refs': [], 'ui': []}, 'provider': 'synthetic', 'model': 'synthetic'}
        with patch('agent_runtime.model.invoke', side_effect=invoke):
            self.assertTrue(self.app.agent_runtime.run_once())

    def test_auto_uses_lead_and_explains_selection(self):
        result = self.ask('auto')
        self.assertEqual(result['routing_decision']['reason'], 'lead_fallback')
        self.assertEqual([m['profile_id'] for m in result['members']], [self.profiles[1]['id']])
        self.assertEqual(self.count_runs(), 1)

    def test_sequential_context_and_final_summary_use_original_turns(self):
        result = self.ask()
        self.assertEqual(self.count_runs(), 1)
        seen = []
        self.answer_one('前序真实合成答案', seen=seen)
        for _ in range(3):
            self.team.discussion_get(result['id'])
        self.assertEqual(self.count_runs(), 1, 'reads must not start next work')
        self.team.tick()
        self.assertEqual(self.count_runs(), 2)
        self.answer_one('第二位的贡献', seen=seen)
        self.assertEqual(seen[-1]['assistant_team']['collaboration']['prior_answers'][0]['answer'], '前序真实合成答案')
        self.team.tick()
        self.assertEqual(self.count_runs(), 3)
        self.answer_one('负责人汇总', seen=seen)
        self.assertEqual(seen[-1]['assistant_team']['collaboration']['kind'], 'synthesis')
        self.team.tick()
        final = self.team.discussion_get(result['id'])
        self.assertEqual(final['status'], 'completed')
        self.assertEqual(final['final_answer'], '负责人汇总')
        self.assertEqual(final['budget'], {'max_member_requests': 3, 'used_member_requests': 3})
        self.team.tick()
        self.assertEqual(self.count_runs(), 3)

    def test_finished_member_before_scheduler_tick_keeps_client_polling(self):
        first = self.ask()
        self.answer_one('首位贡献完成。')
        self.team.tick()
        self.answer_one('需要补充。', '请补充核对范围。')
        # The next scheduler tick persists the pause. Until then the serial
        # plan is still running; a transient partial status stops UI polling.
        before_tick = self.team.discussion_get(first['id'])
        self.assertEqual(before_tick['members'][-1]['status'], 'awaiting_input')
        self.assertEqual(before_tick['status'], 'running')
        self.assertEqual(self.count_runs(), 2, 'reading must not advance work')
        self.team.tick()
        paused = self.team.discussion_get(first['id'])
        self.assertEqual(paused['status'], 'awaiting_input')
        self.assertEqual(self.count_runs(), 2)

    def test_duplicate_send_and_ticks_do_not_add_requests(self):
        first = self.ask()
        self.assertEqual(first['id'], self.ask()['id'])
        for _ in range(3):
            self.team.tick()
        self.assertEqual(self.count_runs(), 1)

    def test_unknown_stops_chain_without_replay(self):
        first = self.ask(); run = first['members'][0]['run_id']
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='running',owner=?,expires=? WHERE id=?", (self.app.agent_runtime.owner, time.time() + 60, run))
        self.app.agent_runtime.finish(run, 'unknown', {'error': 'synthetic_outcome_unknown'}, [])
        for _ in range(3):
            self.team.tick()
        result = self.team.discussion_get(first['id'])
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(self.count_runs(), 1)
        self.assertEqual(self.app.agent_runtime.get(run)['status'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'team_discussion_requires_review'):
            self.team.discussion_advance(first['id'], expected_updated=result['updated'])

    def test_cancel_between_steps_prevents_summary_dispatch(self):
        first = self.ask(); self.answer_one()
        result = self.team.discussion_cancel(first['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.team.tick()
        self.assertEqual(self.count_runs(), 1)

    def test_profile_disable_stops_unstarted_step(self):
        first = self.ask(); self.answer_one()
        profile = self.profiles[1]
        self.team.profile_save({k: (False if k == 'enabled' else profile[k]) for k in
            ('id', 'name', 'role_id', 'instructions', 'model_ids', 'enabled')}, profile['revision'])
        self.team.tick()
        result = self.team.discussion_get(first['id'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.count_runs(), 1)

    def test_configuration_stays_frozen_for_later_steps(self):
        first = self.ask(); self.answer_one()
        profile = self.profiles[1]
        changed = {k: profile[k] for k in ('id', 'name', 'role_id', 'instructions', 'model_ids', 'enabled')}
        changed['instructions'] = '后续新讨论才用此说明。'
        self.team.profile_save(changed, profile['revision'])
        self.team.tick()
        seen = []; self.answer_one(seen=seen)
        self.assertEqual(seen[0]['assistant_team']['profile']['instructions'], profile['instructions'])

    def test_input_pause_requires_explicit_resume_after_original_reply(self):
        first = self.ask(); self.answer_one('需要补充。', '请补充希望说明的范围。')
        self.team.tick()
        paused = self.team.discussion_get(first['id'])
        self.assertEqual(paused['status'], 'awaiting_input')
        thread = self.app.copilot.get(paused['members'][0]['thread_id'])
        self.app.copilot.send(thread['id'], '只解释海运提单的定义。', thread['context_sha256'], 'user-followup')
        self.answer_one('已补充的定义。')
        self.team.tick()
        self.assertEqual(self.count_runs(), 2)
        resumed = self.team.discussion_advance(first['id'], expected_updated=paused['updated'])
        self.team.tick()
        self.assertEqual(self.count_runs(), 3)
        self.assertEqual(resumed['stopped_reason'], None)
        with self.assertRaisesRegex(ValueError, 'team_discussion_changed'):
            self.team.discussion_advance(first['id'], expected_updated=paused['updated'])


if __name__ == '__main__':
    unittest.main()
