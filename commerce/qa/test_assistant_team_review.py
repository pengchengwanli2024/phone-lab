"""Independent root integration review: isolated storage and synthetic receipts only."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from test_assistant_team_packages import package_v2


class TeamIntegrationReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Commerce(self.tmp.name)
        self.addCleanup(self.app.agent_runtime.stop)
        self.addCleanup(self.app.autonomy.stop)
        self.team = self.app.assistant_team
        self.role = self.app.agent_runtime.roles()[0]['id']

    def portable(self):
        value = package_v2()
        for profile in value['profiles']:
            profile['role_id'] = self.role
        return value

    def install(self, value=None, key='review-import'):
        content = json.dumps(value or self.portable(), ensure_ascii=False)
        preview = self.team.package_preview(content)
        return self.team.package_import(content, preview['sha256'], key)

    def trigger_update(self, trigger, **changes):
        fields = ('id', 'name', 'kind', 'channel_id', 'channel_revision', 'question',
                  'dispatch_mode', 'max_rounds', 'schedule')
        value = {key: trigger[key] for key in fields}
        if trigger.get('playbook_key'):
            value['playbook_key'] = trigger['playbook_key']
        return self.team.triggers.save({**value, **changes}, trigger['revision'])

    def test_export_reads_latest_saved_trigger_definition(self):
        installed = self.install()
        self.trigger_update(installed['triggers'][0], schedule={'weekday': 2, 'time': '13:30', 'timezone': 'UTC'},
                            question='Review the updated synthetic brief.')
        exported = self.team.package_export(name='示例团队', preset_id=installed['preset']['id'], version=2)
        trigger = exported['package']['triggers'][0]
        self.assertEqual(trigger['schedule'], {'weekday': 2, 'time': '13:30', 'timezone': 'UTC'})
        self.assertEqual(trigger['question'], 'Review the updated synthetic brief.')
        self.assertFalse(trigger['enabled'])

    def test_export_includes_local_triggers_added_to_installed_channels(self):
        installed = self.install(); channel = installed['channels'][0]
        self.team.triggers.save({'name': '新增示例触发器', 'kind': 'manual', 'channel_id': channel['id'],
            'channel_revision': channel['revision'], 'question': 'Review the example.',
            'dispatch_mode': 'all', 'max_rounds': 1, 'schedule': {}})
        exported = self.team.package_export(name='示例团队', preset_id=installed['preset']['id'], version=2)
        self.assertIn('新增示例触发器', [t['name'] for t in exported['package']['triggers']])

    def test_export_responder_tracks_current_lead_without_invalid_reference(self):
        installed = self.install(); old = installed['channels'][0]
        channel = {k: old[k] for k in ('id', 'name', 'instructions', 'context', 'member_ids', 'routing')}
        channel['routing']['lead_id'] = installed['profiles'][1]['id']
        self.team.channel_save(channel, old['revision'])
        exported = self.team.package_export(name='示例团队', preset_id=installed['preset']['id'], version=2)
        portable = exported['package']['channels'][0]
        self.assertEqual(portable['lead_key'], 'reviewer')
        self.assertEqual(portable['responder']['member_key'], 'reviewer')

    def test_mentions_responder_metadata_survives_an_unchanged_full_preset_export(self):
        value = self.portable(); value['channels'][0]['responder'] = {'kind': 'mentions'}
        value['channels'][0]['routing']['mode'] = 'auto'
        installed = self.install(value)
        exported = self.team.package_export(name='示例团队', preset_id=installed['preset']['id'], version=2)
        self.assertEqual(exported['package']['channels'][0]['responder'], {'kind': 'mentions'})

    def test_channel_default_playbook_is_imported_and_exported(self):
        value = self.portable(); value['channels'][0]['playbook_key'] = 'review'
        installed = self.install(value)
        self.assertEqual(installed['channels'][0].get('playbook_key'), 'review')
        exported = self.team.package_export(name='示例团队', preset_id=installed['preset']['id'], version=2)
        self.assertEqual(exported['package']['channels'][0]['playbook_key'], 'review')

    def test_standalone_channel_export_includes_its_local_triggers(self):
        profile = self.team.profile_save({'name': 'Example member', 'role_id': self.role, 'instructions': '',
            'model_ids': [], 'enabled': False})
        channel = self.team.channel_save({'name': 'Example room', 'instructions': '',
            'context': {'module': 'overview', 'demo': True}, 'member_ids': [profile['id']]})
        self.team.triggers.save({'name': '独立频道触发器', 'kind': 'manual', 'channel_id': channel['id'],
            'channel_revision': channel['revision'], 'question': 'Review the example.',
            'dispatch_mode': 'all', 'max_rounds': 1, 'schedule': {}})
        exported = self.team.package_export(name='Example team', channel_id=channel['id'], version=2)
        self.assertIn('独立频道触发器', [t['name'] for t in exported['package']['triggers']])

    def test_import_failure_rolls_back_entire_preset_profiles_channels_and_earlier_triggers(self):
        value = self.portable()
        value['triggers'].append({**copy.deepcopy(value['triggers'][0]), 'key': 'second'})
        content = json.dumps(value, ensure_ascii=False)
        preview = self.team.package_preview(content)
        original = self.team.triggers.save
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(None)
            if len(calls) == 2:
                raise ValueError('synthetic_import_failure')
            return original(*args, **kwargs)
        with patch.object(self.team.triggers, 'save', side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, 'synthetic_import_failure'):
                self.team.package_import(content, preview['sha256'], 'review-atomic-failure')
        with self.app.core.db() as db:
            for table in ('assistant_team_presets', 'assistant_team_profiles', 'assistant_team_channels',
                          'assistant_team_triggers', 'assistant_team_imports', 'agent_runs', 'copilot_threads'):
                with self.subTest(table=table):
                    self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_after_discussion_template_retains_requirement_without_binding_real_history(self):
        value = self.portable()
        value['triggers'][0].update(kind='after_discussion', schedule={})
        installed = self.install(value)
        self.assertFalse(installed['execution_started'])
        self.assertEqual(installed['triggers'], [])
        trigger = installed['preset']['package']['triggers'][0]
        self.assertEqual(trigger['kind'], 'deferred')
        self.assertEqual(trigger['reason'], 'requires_discussion_binding')

    def test_export_does_not_restore_old_definition_after_mapped_trigger_moves_outside_team(self):
        installed = self.install()
        other = self.team.channel_save({'name': 'Outside example room', 'instructions': '',
            'context': {'module': 'overview', 'demo': True},
            'member_ids': [p['id'] for p in installed['profiles']]})
        self.trigger_update(installed['triggers'][0], channel_id=other['id'], channel_revision=other['revision'])
        exported = self.team.package_export(name='示例团队', preset_id=installed['preset']['id'], version=2)
        self.assertNotIn('review-trigger', [t['key'] for t in exported['package']['triggers']])

    def test_import_does_not_bind_models_grants_or_real_scope(self):
        installed = self.install()
        for profile in installed['profiles']:
            self.assertFalse(profile['enabled'])
            self.assertEqual(profile['model_ids'], [])
        for channel in installed['channels']:
            self.assertEqual(channel['context'], {'module': 'overview', 'demo': True})
        for trigger in installed['triggers']:
            self.assertFalse(trigger['enabled'])
            self.assertIsNone(trigger['pins'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM copilot_threads').fetchone()[0], 0)

    def test_legacy_export_runs_the_same_secret_checks_as_v2(self):
        profile = self.team.profile_save({'name': 'Example member', 'role_id': self.role,
            'instructions': 'https://example.invalid/?api%5Fkey=synthetic', 'model_ids': [], 'enabled': False})
        channel = self.team.channel_save({'name': 'Example room', 'instructions': '',
            'context': {'module': 'overview', 'demo': True}, 'member_ids': [profile['id']]})
        for version in (1, 2):
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.team.package_export(name='Example team', channel_id=channel['id'], version=version)

    def test_unicode_portable_playbook_reference_imports_without_runtime_contract_failure(self):
        value = self.portable()
        value['playbooks'][0]['key'] = '示例复核'
        value['profiles'][0]['playbook_keys'] = ['示例复核']
        value['channels'][0]['playbook_key'] = '示例复核'
        value['triggers'][0]['playbook_key'] = '示例复核'
        installed = self.install(value)
        self.assertEqual(installed['triggers'][0]['playbook_key'], '示例复核')

    def test_later_collaboration_steps_never_use_a_changed_business_scope(self):
        profiles = [self.team.profile_save({'name': name, 'role_id': self.role, 'instructions': 'Review the example.',
            'model_ids': ['project-default'], 'enabled': True}) for name in ('Example One', 'Example Two')]
        channel = self.team.channel_save({'name': 'Example room', 'instructions': 'Review evidence.',
            'context': {'module': 'overview', 'demo': True}, 'member_ids': [p['id'] for p in profiles],
            'routing': {'mode': 'collaborate', 'lead_id': profiles[1]['id'], 'rules': [], 'max_rounds': 1}})
        first = self.team.discussion_start(channel['id'], channel['revision'], '解释示例流程', 'review-freeze')
        run_id = first['members'][0]['run_id']
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='running',owner=?,expires=? WHERE id=?",
                       (self.app.agent_runtime.owner, time.time() + 60, run_id))
        self.app.agent_runtime.finish(run_id, 'completed', {'answer': 'Synthetic evidence receipt.'}, [])
        changed = {k: channel[k] for k in ('id', 'name', 'instructions', 'context', 'member_ids', 'routing')}
        changed['context'] = {'module': 'overview', 'demo': False}
        self.team.channel_save(changed, channel['revision'])
        self.team.tick()
        result = self.team.discussion_get(first['id'])
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['stopped_reason'], 'team_channel_scope_changed')
        self.assertEqual(len(result['members']), 1)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
