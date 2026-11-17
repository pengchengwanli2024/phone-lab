"""Reusable assistants and internal rooms reuse the original run ledger."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from assistant_team import AssistantTeams


class AssistantTeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.team = getattr(self.app, 'assistant_team', None) or AssistantTeams(self.app)
        self.app.assistant_team = self.team
        self.role = self.app.agent_runtime.roles()[0]['id']

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.app.autonomy.stop()
        self.temp.cleanup()

    def profile(self, name='物流顾问', **changes):
        return self.team.profile_save({'name': name, 'role_id': self.role,
            'instructions': '用中文先说明已知事实，再列出待核对事项。',
            'model_ids': ['project-default'], 'enabled': True, **changes})

    def channel(self, profiles, **changes):
        return self.team.channel_save({'name': '运营讨论', 'instructions': '只分析，不执行经营写入。',
            'context': {'module': 'overview', 'demo': True}, 'member_ids': [p['id'] for p in profiles], **changes})

    def count(self, table):
        with self.app.core.db() as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_saving_profiles_and_channels_never_starts_models_or_tasks(self):
        with patch('agent_runtime.model.invoke') as model:
            profile = self.profile(); self.channel([profile]); self.team.catalog()
        model.assert_not_called()
        self.assertEqual(self.count('agent_runs'), 0)
        self.assertEqual(self.count('tasks'), 0)

    def test_revision_conflict_does_not_overwrite_another_edit(self):
        p = self.profile()
        update = {k: p[k] for k in ('id', 'name', 'role_id', 'instructions', 'model_ids', 'enabled')}
        update['name'] = '新版物流顾问'
        saved = self.team.profile_save(update, p['revision'])
        with self.assertRaisesRegex(ValueError, 'team_revision_changed'):
            self.team.profile_save(update, p['revision'])
        self.assertEqual(self.team.catalog()['profiles'][0]['sha256'], saved['sha256'])

    def test_open_thread_freezes_role_instructions_and_uses_original_copilot(self):
        p = self.profile(); c = self.channel([p])
        opened = self.team.thread_open(p['id'], 'open-one', c['id'])
        thread = opened['thread']
        self.assertEqual(self.count('copilot_threads'), 1)
        self.assertEqual(self.count('agent_runs'), 0)
        again = self.team.thread_open(p['id'], 'open-one', c['id'])
        self.assertEqual(again['thread']['id'], thread['id'])
        changed = {k: p[k] for k in ('id', 'name', 'role_id', 'instructions', 'model_ids', 'enabled')}
        changed['instructions'] = '更新只影响新会话。'
        self.team.profile_save(changed, p['revision'])
        sent = self.app.copilot.send(thread['id'], '解释海运提单的含义', thread['context_sha256'], 'send-one')
        seen = []
        def generate(payload, *args, **kwargs):
            seen.append(payload)
            return {'decision': {'phase': 'answer', 'answer': '提单是运输凭证。', 'questions': [],
                    'proposals': [], 'evidence_refs': [], 'ui': []}, 'provider': 'synthetic', 'model': 'synthetic'}
        with patch('agent_runtime.model.invoke', side_effect=generate):
            self.app.agent_runtime.run_once()
        result = self.app.copilot.get(thread['id'])
        self.assertEqual(result['latest_run']['status'], 'completed')
        self.assertEqual(seen[0]['assistant_team']['profile']['instructions'], p['instructions'])
        self.assertEqual(result['latest_run']['role']['id'], self.role)
        self.assertEqual(result['latest_run']['id'], sent['latest_run']['id'])

    def test_startup_backup_is_chosen_before_any_dispatch(self):
        p = self.profile(model_ids=['project-default', 'project-auto'])
        original_catalog = self.app.models.catalog
        def catalog():
            value = original_catalog()
            value['models'] = [dict(id='project-default', label='Unavailable primary', selectable=False, revision='0'),
                               dict(id='project-auto', label='Available backup', selectable=True, revision='0')]
            return value
        with patch.object(self.app.models, 'catalog', side_effect=catalog), \
                patch.object(self.app.models, 'snapshot', return_value={'provider': 'hermes', 'model': 'synthetic'}):
            opened = self.team.thread_open(p['id'], 'backup')
        self.assertEqual(opened['route']['selected_model_id'], 'project-auto')
        self.assertEqual(opened['route']['reason'], 'startup_backup')
        self.assertEqual(self.count('agent_runs'), 0)

    def test_disabled_member_cannot_start_a_conversation(self):
        p = self.profile(enabled=False)
        with self.assertRaisesRegex(ValueError, 'team_profile_disabled'):
            self.team.thread_open(p['id'], 'disabled')
        self.assertEqual(self.count('copilot_threads'), 0)

    def test_disabling_a_profile_blocks_new_turns_in_its_existing_conversation(self):
        p = self.profile(); opened = self.team.thread_open(p['id'], 'before-disable')
        data = {k: p[k] for k in ('id', 'name', 'role_id', 'instructions', 'model_ids', 'enabled')}
        data['enabled'] = False
        self.team.profile_save(data, p['revision'])
        thread = opened['thread']
        with self.assertRaisesRegex(ValueError, 'team_profile_disabled'):
            self.app.copilot.send(thread['id'], '解释海运提单的含义', thread['context_sha256'], 'after-disable')
        self.assertEqual(self.count('agent_runs'), 0)

    def test_group_dispatch_is_explicit_atomic_and_idempotent(self):
        first = self.profile(); second = self.profile('成本顾问'); channel = self.channel([first, second])
        result = self.team.discussion_start(channel['id'], channel['revision'], '解释海运提单的含义', 'group-one')
        self.assertEqual(len(result['members']), 2)
        self.assertEqual(self.count('agent_runs'), 2)
        replay = self.team.discussion_start(channel['id'], channel['revision'], '解释海运提单的含义', 'group-one')
        self.assertEqual(result['id'], replay['id'])
        self.assertEqual(self.count('agent_runs'), 2)
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.team.discussion_start(channel['id'], channel['revision'], '另一个问题', 'group-one')
        cancelled = self.team.discussion_cancel(result['id'])
        self.assertEqual(cancelled['status'], 'cancelled')

    def test_failed_group_preflight_does_not_leave_partial_threads_or_runs(self):
        first = self.profile(); second = self.profile('未启用成员', enabled=False); channel = self.channel([first, second])
        with self.assertRaisesRegex(ValueError, 'team_profile_disabled'):
            self.team.discussion_start(channel['id'], channel['revision'], '解释海运提单的含义', 'bad-group')
        self.assertEqual(self.count('agent_runs'), 0)
        self.assertEqual(self.count('copilot_threads'), 0)

    def test_queue_limit_rolls_back_every_member_instead_of_leaving_partial_dispatch(self):
        first = self.profile(); second = self.profile('成本顾问'); channel = self.channel([first, second])
        for index in range(7):
            self.app.agent_runtime.create('解释海运提单的含义', self.role, 'runtime', 'existing-' + str(index))
        with self.assertRaisesRegex(ValueError, 'agent_queue_full'):
            self.team.discussion_start(channel['id'], channel['revision'], '解释海运提单的含义', 'full-group')
        self.assertEqual(self.count('agent_runs'), 7)
        self.assertEqual(self.count('copilot_threads'), 0)

    def test_discussion_status_preserves_unknown_instead_of_calling_it_done(self):
        p = self.profile(); c = self.channel([p])
        result = self.team.discussion_start(c['id'], c['revision'], '解释海运提单的含义', 'unknown-group')
        run = result['members'][0]['run_id']
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='unknown' WHERE id=?", (run,))
        self.assertEqual(self.team.discussion_get(result['id'])['status'], 'unknown')

    def test_discussion_follows_research_successor_and_cancels_the_same_original_task(self):
        p = self.profile(); c = self.channel([p], context={'module': 'research', 'market': 'RU', 'demo': False})
        discussion = self.team.discussion_start(c['id'], c['revision'], '请调研俄罗斯厨房收纳用品并保存候选商品', 'research-group')
        original = discussion['members'][0]['run_id']
        current = self.app.market_research.for_run(original)
        self.assertIsNotNone(current)
        with self.app.core.atomic() as db:
            job = self.app.market_research._load(db, current['task_id'])
            job['status'] = 'failed'; self.app.market_research._save(db, job)
            db.execute("UPDATE agent_runs SET status='interrupted' WHERE id=?", (original,))
        current = self.app.market_research.get(current['task_id'])
        resumed = self.app.market_research.resume(current['task_id'], current['revision'], 'explicit-research-resume')
        observed = self.team.discussion_get(discussion['id'])
        self.assertEqual(observed['members'][0]['run_id'], resumed['run_id'])
        self.assertEqual(observed['members'][0]['original_run_id'], original)
        self.assertEqual(observed['status'], 'queued')
        stopped = self.team.discussion_cancel(discussion['id'])
        self.assertEqual(stopped['status'], 'cancelled')
        self.assertEqual(self.app.market_research.get(current['task_id'])['status'], 'cancelled')
        self.assertEqual(self.count('tasks'), 1)

    def test_package_preview_import_and_export_never_transfer_execution_authority(self):
        p = self.profile(); c = self.channel([p])
        exported = self.team.package_export(c['id'], '物流团队')
        portable = json.dumps(exported['package'], ensure_ascii=False)
        for forbidden in ('model_ids', 'context', 'credential', 'thread_id', 'run_id', 'enabled'):
            self.assertNotIn('"' + forbidden + '"', portable)
        preview = self.team.package_preview(exported['content'])
        self.assertEqual(preview['counts'], {'profiles': 1, 'channels': 1})
        imported = self.team.package_import(exported['content'], preview['sha256'], 'import-one')
        again = self.team.package_import(exported['content'], preview['sha256'], 'import-one')
        self.assertEqual(imported, again)
        self.assertFalse(imported['profiles'][0]['enabled'])
        self.assertEqual(imported['profiles'][0]['model_ids'], [])
        self.assertNotEqual(imported['profiles'][0]['id'], p['id'])
        self.assertEqual(self.count('agent_runs'), 0)
        self.assertEqual(self.count('tasks'), 0)
        with self.assertRaisesRegex(ValueError, 'team_package_changed'):
            self.team.package_import(exported['content'], '0' * 64, 'changed')

    def test_package_unknown_fields_and_private_data_are_rejected(self):
        p = self.profile(); c = self.channel([p]); package = self.team.package_export(c['id'], '测试')['package']
        package['credentials'] = {'token': 'synthetic-value'}
        with self.assertRaisesRegex(ValueError, 'team_invalid_package'):
            self.team.package_preview(json.dumps(package))
        del package['credentials']; package['profiles'][0]['instructions'] = 'password=synthetic-value'
        with self.assertRaisesRegex(ValueError, 'team_package_private_data'):
            self.team.package_preview(json.dumps(package))

    def test_package_bearer_credentials_are_rejected_at_export_and_preview(self):
        p = self.profile(instructions='Authorization: Bearer SYNTHETIC_NOT_A_REAL_CREDENTIAL_123')
        c = self.channel([p])
        with self.assertRaisesRegex(ValueError, 'team_package_private_data'):
            self.team.package_export(c['id'], '测试')

    def test_package_whitespace_keys_fail_preview_instead_of_failing_during_import(self):
        p = self.profile(); c = self.channel([p]); package = self.team.package_export(c['id'], '测试')['package']
        package['profiles'][0]['key'] = ' p0 '
        with self.assertRaisesRegex(ValueError, 'team_invalid_package'):
            self.team.package_preview(json.dumps(package))


if __name__ == '__main__':
    unittest.main()
