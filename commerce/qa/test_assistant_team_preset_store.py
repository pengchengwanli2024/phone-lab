"""Complete portable data is installed atomically and remains non-executing."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from test_assistant_team_packages import package_v2


class PresetStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Commerce(self.tmp.name)
        self.addCleanup(self.app.agent_runtime.stop)
        self.addCleanup(self.app.autonomy.stop)
        self.team = self.app.assistant_team
        self.package = package_v2()
        for profile in self.package['profiles']:
            profile['role_id'] = self.app.agent_runtime.roles()[0]['id']

    def install(self, key='install-one'):
        content = json.dumps(self.package, ensure_ascii=False)
        preview = self.team.package_preview(content)
        return self.team.package_import(content, preview['sha256'], key)

    def count(self, name):
        with self.app.core.db() as db:
            return db.execute('SELECT count(*) FROM ' + name).fetchone()[0]

    def test_complete_install_is_paused_and_contains_no_execution_grant(self):
        result = self.install()
        self.assertEqual(self.count('agent_runs'), 0)
        self.assertEqual(self.count('tasks'), 0)
        self.assertEqual(len(result['triggers']), 1)
        self.assertFalse(result['triggers'][0]['enabled'])
        self.assertTrue(all(not p['enabled'] and not p['model_ids'] for p in result['profiles']))
        self.assertEqual(result, self.install())
        preset = self.team.catalog()['presets'][0]
        self.assertEqual(preset['package']['skills'], self.package['skills'])
        self.assertEqual(preset['package']['starter_notes'], self.package['starter_notes'])
        self.assertEqual(preset['package']['connector_requirements'][0]['status'], 'unconfigured')

    def test_enable_member_carries_inert_full_preset_context_into_original_thread(self):
        result = self.install(); profile = result['profiles'][0]
        data = {k: profile[k] for k in ('id', 'name', 'role_id', 'instructions', 'model_ids', 'enabled')}
        data.update(enabled=True, model_ids=['project-default'])
        self.team.profile_save(data, profile['revision'])
        opened = self.team.thread_open(profile['id'], 'open-preset-member', result['channels'][0]['id'])
        context = self.team.prompt_context(opened['binding'])['preset_context']
        self.assertEqual(context['playbooks'], self.package['playbooks'])
        self.assertEqual(context['starter_notes'], self.package['starter_notes'])
        self.assertFalse(context['tools_or_credentials_granted'])
        self.assertEqual(self.count('agent_runs'), 0)

    def test_import_rolls_back_every_new_record_if_trigger_install_fails(self):
        with patch.object(self.team.triggers, 'save', side_effect=ValueError('synthetic_import_failure')):
            with self.assertRaisesRegex(ValueError, 'synthetic_import_failure'):
                self.install()
        for table in ('assistant_team_profiles', 'assistant_team_channels', 'assistant_team_presets', 'assistant_team_imports', 'assistant_team_triggers'):
            self.assertEqual(self.count(table), 0, table)

    def test_full_export_uses_current_trigger_edits_and_pauses_them(self):
        result = self.install(); trigger = result['triggers'][0]
        edited = {k: trigger[k] for k in ('id', 'name', 'kind', 'channel_id', 'channel_revision', 'question', 'dispatch_mode', 'max_rounds', 'schedule')}
        edited.update(question='使用新版本的问题。', schedule={'weekday': 2, 'time': '10:30', 'timezone': 'Asia/Shanghai'})
        self.team.triggers.save(edited, trigger['revision'])
        exported = self.team.package_export(name='新团队', preset_id=result['preset']['id'], version=2)
        item = exported['package']['triggers'][0]
        self.assertEqual(item['question'], edited['question'])
        self.assertEqual(item['schedule'], edited['schedule'])
        self.assertFalse(item['enabled'])
        self.assertNotIn('discussion_id', exported['content'])
        for private in ('model_ids', 'profile_map', 'pins', 'credential_ref'):
            self.assertNotIn('"' + private + '"', exported['content'])

    def test_channel_default_playbook_roundtrips(self):
        self.package['channels'][0]['playbook_key'] = 'review'
        result = self.install()
        self.assertEqual(result['channels'][0]['playbook_key'], 'review')
        exported = self.team.package_export(name='预设', preset_id=result['preset']['id'], version=2)
        self.assertEqual(exported['package']['channels'][0]['playbook_key'], 'review')


if __name__ == '__main__':
    unittest.main()
