"""Portable team data remains complete and inert at the untrusted text boundary."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def package_v2():
    return {
        'schema': 'phone-lab-team-v2', 'name': '示例协作团队',
        'instructions': '先核实证据，再归纳结论。', 'chief_key': 'lead',
        'profiles': [
            {'key': 'lead', 'name': '示例协调员', 'role_id': 'analyst',
             'instructions': '协调并汇总。', 'expertise': ['综合'],
             'playbook_keys': ['review'], 'skill_keys': ['evidence'], 'connector_keys': ['source']},
            {'key': 'reviewer', 'name': '示例复核员', 'role_id': 'analyst',
             'instructions': '复核证据。', 'expertise': ['核查'],
             'playbook_keys': [], 'skill_keys': [], 'connector_keys': []},
        ],
        'channels': [{'key': 'desk', 'name': '示例讨论', 'instructions': '引用可复核证据。',
            'members': ['lead', 'reviewer'], 'lead_key': 'lead',
            'routing': {'mode': 'collaborate', 'max_rounds': 2,
                        'rules': [{'keywords': ['核查'], 'member_keys': ['reviewer']}]},
            'responder': {'kind': 'lead', 'member_key': 'lead'}}],
        'playbooks': [{'key': 'review', 'name': '示例复核', 'instructions': '检查来源。', 'triggers': ['复核']}],
        'starter_notes': [{'profile_key': 'lead', 'name': 'MEMORY.md', 'content': '使用简短摘要。'}],
        'skills': [{'key': 'evidence', 'name': 'evidence', 'description': '记录证据的方法。', 'instructions': '只记录有来源的事实。'}],
        'connector_requirements': [{'key': 'source', 'label': 'Example Source', 'reason': '读取公开示例。', 'optional': True, 'status': 'unconfigured'}],
        'triggers': [{'key': 'review-trigger', 'name': '示例周复核', 'channel_key': 'desk', 'kind': 'weekly',
            'question': '复核示例证据', 'dispatch_mode': 'auto', 'max_rounds': 1,
            'schedule': {'weekday': 0, 'time': '09:00', 'timezone': 'Asia/Shanghai'}, 'enabled': False}],
    }


def botmrr_markdown():
    """Synthetic content in the official engineering.md/frontmatter layout."""
    return '''---
botmrr: 1
id: synthetic-engineering
release: 1.0.0
name: 示例工程团队
tagline: Review an example change.
summary: A synthetic portable crew.
category: Engineering
author:
  name: Example Author
  url: https://example.invalid
license: MIT
featured: true
tags:
  - review
outcomes:
  - An evidence based review.
setupMinutes: 3
requirements:
  apps:
    - slug: github
      label: GitHub
      reason: Read public example sources.
      optional: true
  capabilities:
    - agents
  platforms:
    - any
agents:
  - key: lead
    name: 示例协调员
    title: Example Lead
    description: Coordinate the example review.
    soul: |
      Preserve known facts.
      Ask when evidence is missing.
    appearance:
      color: purple
      mascotExpression: focused
    playbooks:
      - review
    skills:
      - example-evidence
    seed:
      memory:
        MEMORY.md: Prefer concise summaries.
  - key: reviewer
    name: 示例复核员
    description: Review the evidence.
    appearance:
      color: green
chiefOfStaff: lead
rooms:
  - key: desk
    name: Example Review Room
    members:
      - lead
      - reviewer
    bulletin: Cite evidence and return one result.
    defaultResponder:
      kind: agent
      agent: lead
routines:
  - key: daily-review
    name: Example daily review
    agent: reviewer
    prompt: Review the public example.
    runOn: maus
    schedule:
      type: daily
      time: "09:00"
      weekdays: [1, 2, 3, 4, 5]
    durationMinutes: 30
    enabledAfterInstall: true
playbooks:
  - key: review
    name: Example Review
    summary: Verify available evidence.
    triggers:
      - review
    instructions: >-
      Inspect the example.
      Cite available sources.
skills:
  version: 1
  entries:
    - name: example-evidence
      description: Record example evidence.
      source: Synthetic example source
      instructions: |
        ---
        name: example-evidence
        description: Record example evidence.
        ---
        Record only supported facts.
---

# Example blueprint

## Activation
Review the team before use.
## Mission
Review the synthetic example.
## Outcomes
Return one supported result.
## Connections
Use the normal local authorization flow.
## Team
Coordinate and review.
## Chief of Staff
The lead owns the final answer.
## Completion rule
Separate known facts and missing evidence.
'''


class PackageTests(unittest.TestCase):
    def parser(self):
        spec = importlib.util.find_spec('assistant_team_packages')
        self.assertIsNotNone(spec, 'portable package parser is not implemented')
        import assistant_team_packages
        return assistant_team_packages

    def preview(self, value):
        content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return self.parser().preview_package(content, role_ids={'analyst'}, default_role_id='analyst')

    def test_full_v2_roundtrip_preserves_routing_notes_skills_checklist_and_paused_trigger(self):
        package = package_v2()
        preview = self.preview(package)
        self.assertEqual(preview['package']['chief_key'], 'lead')
        self.assertEqual(preview['package']['channels'][0]['routing'], package['channels'][0]['routing'])
        self.assertEqual(preview['package']['starter_notes'], package['starter_notes'])
        self.assertEqual(preview['package']['skills'], package['skills'])
        self.assertEqual(preview['package']['connector_requirements'], package['connector_requirements'])
        self.assertFalse(preview['package']['triggers'][0]['enabled'])
        self.assertFalse(preview['execution_started'])
        for format in ('json', 'markdown'):
            with self.subTest(format=format):
                exported = self.parser().export_package(package, format=format, role_ids={'analyst'})
                again = self.preview(exported['content'])
                self.assertEqual(again['package'], preview['package'])
                self.assertEqual(again['sha256'], preview['sha256'])

    def test_v1_json_and_fenced_markdown_remain_compatible(self):
        value = {'schema': 'phone-lab-team-v1', 'name': '示例旧团队',
                 'profiles': [{'key': 'p0', 'name': '示例成员', 'role_id': 'analyst', 'instructions': '只分析。'}],
                 'channels': [{'name': '示例频道', 'instructions': '', 'members': ['p0']}]}
        for content in (json.dumps(value), '# Example\n\n```json\n' + json.dumps(value) + '\n```\n'):
            p = self.preview(content)
            self.assertEqual(p['package']['schema'], 'phone-lab-team-v2')
            self.assertEqual(p['package']['profiles'][0]['role_id'], 'analyst')
            self.assertEqual(p['package']['channels'][0]['routing']['mode'], 'all')
            self.assertEqual(p['package']['channels'][0]['members'], ['p0'])

    def test_enabled_import_is_explicitly_paused(self):
        value = package_v2(); value['triggers'][0]['enabled'] = True
        preview = self.preview(value)
        self.assertFalse(preview['package']['triggers'][0]['enabled'])
        self.assertTrue(any('paused' in w for w in preview['warnings']))

    def test_rejects_unknown_privilege_fields_at_every_boundary(self):
        for target, key, data in (
            ('root', 'credentials', {'secret': 'synthetic'}), ('profile', 'model_ids', ['project-default']),
            ('channel', 'context', {'demo': False}), ('root', 'history', []),
            ('profile', 'tool_grants', ['shell']), ('skill', 'command', 'echo example'),
            ('trigger', 'discussion_id', 'synthetic-discussion'), ('root', 'unknownExtension', {}),
        ):
            value = package_v2()
            targets = {'root': value, 'profile': value['profiles'][0], 'channel': value['channels'][0],
                       'skill': value['skills'][0], 'trigger': value['triggers'][0]}
            targets[target][key] = data
            with self.subTest(target=target, key=key), self.assertRaises(ValueError):
                self.preview(value)

    def test_rejects_broken_references_duplicate_keys_and_invalid_routes(self):
        changes = [
            lambda v: v.update(chief_key='missing'),
            lambda v: v['profiles'].append(copy.deepcopy(v['profiles'][0])),
            lambda v: v['channels'][0].update(members=['lead', 'lead']),
            lambda v: v['channels'][0].update(lead_key='missing'),
            lambda v: v['channels'][0]['routing']['rules'][0].update(member_keys=['missing']),
            lambda v: v['channels'][0]['routing'].update(max_rounds=4),
            lambda v: v['profiles'][0].update(skill_keys=['missing']),
            lambda v: v['profiles'][0].update(playbook_keys=['missing']),
            lambda v: v['profiles'][0].update(connector_keys=['missing']),
            lambda v: v['triggers'][0].update(channel_key='missing'),
            lambda v: v['starter_notes'][0].update(profile_key='missing'),
        ]
        for change in changes:
            value = package_v2(); change(value)
            with self.subTest(change=changes.index(change)), self.assertRaises(ValueError):
                self.preview(value)

    def test_duplicate_json_keys_are_not_last_value_wins(self):
        content = json.dumps(package_v2()).replace('"schema":', '"schema":"phone-lab-team-v2", "schema":', 1)
        with self.assertRaises(ValueError): self.preview(content)

    def test_unicode_is_preserved_but_normalized_collisions_and_invisible_controls_reject(self):
        value = package_v2(); value['profiles'][0]['name'] = '团队 Café'
        self.assertEqual(self.preview(value)['package']['profiles'][0]['name'], '团队 Café')
        value['profiles'][1]['key'] = 'e\u0301'; value['profiles'][0]['key'] = 'é'
        with self.assertRaises(ValueError): self.preview(value)
        value = package_v2(); value['instructions'] = 'unseen\u202echange'
        with self.assertRaises(ValueError): self.preview(value)

    def test_secrets_and_private_paths_reject_without_echoing_content(self):
        for secret in ('sk-' + 'a' * 24, 'api_key=' + 'x' * 24, 'Authorization: Bearer ' + 'z' * 20,
                       '/Users/example/private', 'ghp_' + 'x' * 25, 'https://example.invalid/?token=example'):
            value = package_v2(); value['starter_notes'][0]['content'] = secret
            with self.subTest(secret=secret[:10]):
                with self.assertRaises(ValueError) as caught:
                    self.preview(value)
                self.assertNotIn(secret, str(caught.exception))

    def test_limits_count_utf8_bytes_and_validate_trigger_dates_and_zones(self):
        value = package_v2(); value['instructions'] = '中' * 8001
        with self.assertRaises(ValueError): self.preview(value)
        with self.assertRaises(ValueError): self.preview('中' * 30000)
        for schedule in ({'weekday': 7, 'time': '09:00', 'timezone': 'UTC'},
                         {'weekday': 1, 'time': '25:00', 'timezone': 'UTC'},
                         {'weekday': 1, 'time': '09:00', 'timezone': 'Not/AZone'}):
            value = package_v2(); value['triggers'][0]['schedule'] = schedule
            with self.subTest(schedule=schedule), self.assertRaises(ValueError): self.preview(value)

    def test_official_frontmatter_shape_retains_chief_rooms_playbooks_notes_and_inert_requirements(self):
        preview = self.preview(botmrr_markdown())
        value = preview['package']
        self.assertEqual(preview['source_format'], 'botmrr-markdown-v1')
        self.assertEqual(value['chief_key'], 'lead')
        self.assertEqual(value['channels'][0]['members'], ['lead', 'reviewer'])
        self.assertEqual(value['channels'][0]['responder'], {'kind': 'lead', 'member_key': 'lead'})
        self.assertEqual(value['channels'][0]['lead_key'], 'lead')
        self.assertEqual(value['channels'][0]['routing']['mode'], 'auto')
        self.assertIn('## Completion rule', value['instructions'])
        self.assertIn('Ask when evidence is missing.', value['profiles'][0]['instructions'])
        self.assertEqual(value['profiles'][0]['playbook_keys'], ['review'])
        self.assertEqual(value['profiles'][0]['skill_keys'], ['example-evidence'])
        self.assertIn('Inspect the example. Cite available sources.', value['playbooks'][0]['instructions'])
        self.assertEqual(value['starter_notes'], [{'profile_key': 'lead', 'name': 'MEMORY.md', 'content': 'Prefer concise summaries.'}])
        self.assertEqual(value['connector_requirements'][0]['status'], 'unconfigured')
        self.assertIn('Record only supported facts.', value['skills'][0]['instructions'])
        self.assertEqual(value['triggers'][0]['kind'], 'deferred')
        self.assertEqual(value['triggers'][0]['source_spec']['schedule']['type'], 'daily')
        self.assertFalse(value['triggers'][0]['enabled'])
        self.assertFalse(value['triggers'][0]['source_spec']['enabledAfterInstall'])
        self.assertTrue(any('unconfigured' in w for w in preview['warnings']))
        exported = self.parser().export_package(value)
        self.assertEqual(self.preview(exported['content'])['package'], value)

    def test_yaml_alias_anchor_tag_duplicates_and_excessive_depth_are_rejected(self):
        attacks = ['name: &name Example', 'name: *name', 'name: !!python/object:example {}',
                   'name: Example\nname: Other', 'name: !custom Example',
                   'name: ' + '[' * 30 + 'x' + ']' * 30]
        for attack in attacks:
            content = botmrr_markdown().replace('name: 示例工程团队', attack, 1)
            with self.subTest(attack=attack), self.assertRaises(ValueError): self.preview(content)

    def test_foreign_unknown_execution_fields_missing_sections_and_references_reject(self):
        for content in (
            botmrr_markdown().replace('chiefOfStaff: lead', 'chiefOfStaff: missing'),
            botmrr_markdown().replace('    soul: |', '    model: synthetic-model\n    soul: |'),
            botmrr_markdown().replace('      color: purple', '      color: purple\n      command: synthetic'),
            botmrr_markdown().replace('## Mission', '## Missing'),
            botmrr_markdown().replace('    playbooks:\n      - review', '    playbooks:\n      - unknown'),
        ):
            with self.subTest(content=content[:60]), self.assertRaises(ValueError): self.preview(content)

    def test_all_local_trigger_kinds_roundtrip_paused_and_reject_saved_event_bindings(self):
        for kind, schedule in (
            ('manual', {}), ('webhook', {}),
            ('once', {'at': '2030-01-01T08:00:00+08:00'}),
            ('interval', {'start_at': '2030-01-01T08:00:00Z', 'interval_seconds': 60}),
        ):
            value = package_v2(); value['triggers'][0].update(kind=kind, schedule=schedule, enabled=True)
            with self.subTest(kind=kind):
                parsed = self.preview(value)['package']['triggers'][0]
                self.assertEqual(parsed['schedule'], schedule)
                self.assertFalse(parsed['enabled'])
        value = package_v2(); value['triggers'][0].update(kind='after_discussion', schedule={'discussion_id': 'example'})
        with self.assertRaises(ValueError): self.preview(value)

    def test_after_discussion_without_history_binding_is_retained_as_explicit_requirement(self):
        value = package_v2(); value['triggers'][0].update(kind='after_discussion', schedule={}, enabled=True)
        preview = self.preview(value)
        trigger = preview['package']['triggers'][0]
        self.assertEqual(trigger['kind'], 'deferred')
        self.assertEqual(trigger['reason'], 'requires_discussion_binding')
        self.assertEqual(trigger['source_spec'], {'kind': 'after_discussion', 'schedule': {}})
        self.assertFalse(trigger['enabled'])
        self.assertTrue(any('requires_discussion_binding' in warning for warning in preview['warnings']))
        exported = self.parser().export_package(preview['package'])
        self.assertEqual(self.preview(exported['content'])['package'], preview['package'])
        value['triggers'][0]['channel_key'] = None
        with self.assertRaises(ValueError): self.preview(value)

    def test_channel_default_playbook_survives_roundtrip_and_unknown_reference_rejects(self):
        value = package_v2(); value['channels'][0]['playbook_key'] = 'review'
        preview = self.preview(value)
        self.assertEqual(preview['package']['channels'][0]['playbook_key'], 'review')
        exported = self.parser().export_package(preview['package'])
        self.assertEqual(self.preview(exported['content'])['package']['channels'][0]['playbook_key'], 'review')
        value['channels'][0]['playbook_key'] = 'missing'
        with self.assertRaises(ValueError): self.preview(value)

    def test_local_keyword_and_rule_bounds_match_runtime_import_contract(self):
        for edit in (
            lambda v: v['profiles'][0].update(expertise=['x' * 41]),
            lambda v: v['profiles'][0].update(expertise=['example' + str(i) for i in range(17)]),
            lambda v: v['profiles'][0].update(expertise=['example\nother']),
            lambda v: v['channels'][0]['routing']['rules'][0].update(keywords=['x' * 41]),
            lambda v: v['channels'][0]['routing'].update(rules=[{'keywords': ['example'], 'member_keys': ['lead']}] * 13),
        ):
            value = package_v2(); edit(value)
            with self.subTest(edit=edit), self.assertRaises(ValueError): self.preview(value)

    def test_local_timestamp_contract_rejects_year_or_grammar_not_accepted_by_runtime(self):
        for at in ('2030-01-01T08:00+08:00', '1999-01-01T08:00:00Z', '2101-01-01T08:00:00Z',
                   '2030-01-01T08:00:00.1234567Z'):
            value = package_v2(); value['triggers'][0].update(kind='once', schedule={'at': at})
            with self.subTest(at=at), self.assertRaises(ValueError): self.preview(value)

    def test_foreign_long_title_is_retained_in_instructions_with_bounded_expertise_warning(self):
        title = 'A long synthetic title ' * 3
        preview = self.preview(botmrr_markdown().replace('Example Lead', title))
        self.assertIn(title.rstrip(), preview['package']['profiles'][0]['instructions'])
        self.assertLessEqual(len(preview['package']['profiles'][0]['expertise'][0]), 40)
        self.assertTrue(any('expertise' in warning for warning in preview['warnings']))

    def test_encoded_credentials_and_known_secret_shapes_are_not_carried_as_inert_text(self):
        for secret in ('https://example.invalid/?api%5Fkey=synthetic',
                       'https://example.invalid/?key=synthetic',
                       '-----BEGIN PRIVATE KEY-----', 'xoxb-' + '1' * 24,
                       'AKIA' + 'A' * 16):
            value = package_v2(); value['instructions'] = secret
            with self.subTest(secret=secret[:20]), self.assertRaises(ValueError): self.preview(value)

    def test_deferred_source_spec_does_not_hide_unknown_privileges_or_broken_references(self):
        source = {'key': 'foreign', 'name': 'Example foreign routine', 'agent': 'reviewer',
                  'prompt': 'Review the example.', 'runOn': 'cloud',
                  'schedule': {'type': 'cron', 'expression': '0 9 * * 1', 'timeZone': 'UTC'},
                  'enabledAfterInstall': False}
        value = package_v2(); value['triggers'][0] = {
            'key': 'foreign', 'name': 'Example foreign routine', 'kind': 'deferred', 'channel_key': 'desk',
            'question': 'Review the example.', 'source_spec': source, 'reason': 'unsupported_upstream_schedule'}
        parsed = self.preview(value)['package']
        self.assertEqual(parsed['triggers'][0]['source_spec'], source)
        for edit in (
            lambda s: s.update(agent='missing'),
            lambda s: s.update(room='missing'),
            lambda s: s['schedule'].update(command='synthetic'),
            lambda s: s['schedule'].update(expression={'credentials': 'synthetic'}),
            lambda s: s.update(trigger={'type': 'event', 'event': {'model': 'synthetic'}}),
        ):
            bad = copy.deepcopy(value); edit(bad['triggers'][0]['source_spec'])
            with self.subTest(edit=edit), self.assertRaises(ValueError): self.preview(bad)

    def test_maximum_member_count_and_aggregate_normalized_bytes_remain_bounded(self):
        value = package_v2()
        for i in range(3):
            value['profiles'].append({'key': 'extra' + str(i), 'name': '示例成员', 'role_id': 'analyst', 'instructions': ''})
            value['channels'][0]['members'].append('extra' + str(i))
        with self.assertRaises(ValueError): self.preview(value)
        value = package_v2()
        for i in range(24):
            value['starter_notes'].append({'profile_key': 'reviewer', 'name': 'example-' + str(i) + '.md', 'content': '中' * 1000})
        with self.assertRaises(ValueError): self.preview(value)

    def test_long_foreign_blueprint_is_preserved_as_bounded_starter_notes(self):
        content = botmrr_markdown() + '\n## Example appendix\n' + ('Synthetic guidance. ' * 500)
        preview = self.preview(content)
        blueprint = ''.join(note['content'] for note in preview['package']['starter_notes'] if note['name'].startswith('blueprint-'))
        self.assertIn('## Activation', blueprint)
        self.assertIn('## Example appendix', blueprint)
        self.assertTrue(blueprint.endswith('Synthetic guidance. ' * 500))
        self.assertLessEqual(len(preview['package']['instructions']), 8000)

    def test_foreign_listing_metadata_cannot_hide_credential_or_execution_objects(self):
        content = botmrr_markdown().replace('category: Engineering',
            'category:\n  command: synthetic\n  credentials:\n    value: synthetic')
        with self.assertRaises(ValueError): self.preview(content)

    def test_scalar_frontmatter_values_cannot_hide_unsupported_structures(self):
        for original, replacement in (
            ('featured: true', 'featured:\n  unexpected: synthetic'),
            ('  name: Example Author', '  name:\n    unexpected: synthetic'),
            ('  - review\noutcomes:', '  - nested: synthetic\noutcomes:'),
        ):
            content = botmrr_markdown().replace(original, replacement)
            with self.subTest(original=original), self.assertRaises(ValueError): self.preview(content)

    def test_windows_line_endings_have_the_same_normalized_hash(self):
        windows = botmrr_markdown().replace('\n', '\r\n')
        self.assertEqual(self.preview(windows)['sha256'], self.preview(botmrr_markdown())['sha256'])


if __name__ == '__main__':
    unittest.main()
