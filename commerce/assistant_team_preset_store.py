"""Immutable portable team installations; no credentials, execution grants or history."""
import json
import re
import time
import uuid

from agent_runtime.policy import canonical
from assistant_team_packages import preview_package, normalize_package, export_package


class TeamPresets:
    def __init__(self, teams):
        self.teams = teams
        self.service = teams.service
        self.core = teams.core

    def _options(self):
        roles = {r['id'] for r in self.service.agent_runtime.roles()}
        return {'role_ids': roles, 'default_role_id': 'conductor' if 'conductor' in roles else sorted(roles)[0]}

    def _get(self, db, ident):
        row = db.execute('SELECT document FROM assistant_team_presets WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('team_preset_not_found')
        return json.loads(row[0])

    def preview(self, content):
        # Keep v1's preview/hash/count contract for existing CLI and API clients.
        if not isinstance(content, str) or len(content) > 65536:
            raise ValueError('team_invalid_package')
        raw = content.strip()
        if not raw.startswith('---'):
            if not raw.startswith('{'):
                blocks = re.findall(r'^```json\s*\n([\s\S]*?)^```\s*$', raw, re.M)
                raw = blocks[0] if len(blocks) == 1 else ''
            try:
                value = json.loads(raw)
            except (ValueError, TypeError, RecursionError):
                value = None
            if isinstance(value, dict) and value.get('schema') == 'phone-lab-team-v1':
                legacy = self.teams._legacy_package_preview(content)
                preview_package(content, **self._options())  # strict duplicate/encoding checks too
                return legacy
        return preview_package(content, **self._options())

    def import_package(self, content, expected_sha256, idempotency_key):
        self.service.copilot.key(idempotency_key)
        preview = self.preview(content)
        if preview['sha256'] != expected_sha256:
            raise ValueError('team_package_changed')
        package = normalize_package(preview['package'], **self._options())
        with self.core.atomic(reuse=True) as db:
            old = db.execute('SELECT package_sha,result FROM assistant_team_imports WHERE idem=?', (idempotency_key,)).fetchone()
            if old:
                if old[0] != preview['sha256']:
                    raise ValueError('idempotency_conflict')
                return json.loads(old[1])
            if db.execute('SELECT count(*) FROM assistant_team_presets').fetchone()[0] >= 24:
                raise ValueError('team_limit_reached')
            ident = 'preset_' + uuid.uuid4().hex[:16]
            record = {'id': ident, 'name': package['name'], 'package': package, 'profile_map': {},
                      'channel_map': {}, 'trigger_map': {}, 'created': time.time(), 'source_format': preview.get('source_format', 'legacy-v1')}
            db.execute('INSERT INTO assistant_team_presets VALUES(?,?,?)', (ident, canonical(record), record['created']))
            profiles, channels, triggers = [], [], []
            for item in package['profiles']:
                profile = self.teams.profile_save({**{k: item[k] for k in ('name', 'role_id', 'instructions', 'expertise')},
                                                   'model_ids': [], 'enabled': False})
                data = {k: v for k, v in profile.items() if k not in ('id', 'revision', 'updated', 'sha256')}
                data.update(preset_id=ident, preset_key=item['key'])
                db.execute('UPDATE assistant_team_profiles SET document=? WHERE id=?', (canonical(data), profile['id']))
                profile = self.teams._get(db, 'profiles', profile['id'])
                record['profile_map'][item['key']] = profile['id']; profiles.append(profile)
            mapping = record['profile_map']
            for item in package['channels']:
                routing = item['routing']
                channel = self.teams.channel_save({'name': item['name'], 'instructions': item['instructions'],
                    'context': {'module': 'overview', 'demo': True}, 'member_ids': [mapping[k] for k in item['members']],
                    'routing': {'mode': routing['mode'], 'lead_id': mapping[item['lead_key']] if item.get('lead_key') else mapping[item['members'][0]],
                        'mentions_only': item['responder']['kind'] == 'mentions',
                        'rules': [{'keywords': r['keywords'], 'member_ids': [mapping[k] for k in r['member_keys']]} for r in routing['rules']],
                        'max_rounds': routing['max_rounds']}})
                data = {k: v for k, v in channel.items() if k not in ('id', 'revision', 'updated', 'sha256')}
                data.update(preset_id=ident, preset_key=item['key'])
                db.execute('UPDATE assistant_team_channels SET document=? WHERE id=?', (canonical(data), channel['id']))
                if item.get('playbook_key'):
                    data['playbook_key'] = item['playbook_key']
                    db.execute('UPDATE assistant_team_channels SET document=? WHERE id=?', (canonical(data), channel['id']))
                channel = self.teams._get(db, 'channels', channel['id'])
                record['channel_map'][item['key']] = channel['id']; channels.append(channel)
            for item in package['triggers']:
                if item['kind'] == 'deferred':
                    continue
                channel_id = record['channel_map'][item['channel_key']]
                channel = self.teams._get(db, 'channels', channel_id)
                trigger = self.teams.triggers.save({'name': item['name'], 'kind': item['kind'],
                    'channel_id': channel_id, 'channel_revision': channel['revision'], 'question': item['question'],
                    'dispatch_mode': item['dispatch_mode'], 'max_rounds': item['max_rounds'], 'schedule': item['schedule'],
                    **({'playbook_key': item['playbook_key']} if item.get('playbook_key') else {})})
                record['trigger_map'][item['key']] = trigger['id']; triggers.append(trigger)
            db.execute('UPDATE assistant_team_presets SET document=? WHERE id=?', (canonical(record), ident))
            result = {'status': 'imported', 'profiles': profiles, 'channels': channels, 'triggers': triggers,
                      'preset': record, 'package_sha256': preview['sha256'], 'execution_started': False}
            db.execute('INSERT INTO assistant_team_imports VALUES(?,?,?)', (idempotency_key, preview['sha256'], canonical(result)))
            return result

    def playbook(self, channel, key):
        if not key:
            return None
        if not isinstance(key, str) or not channel.get('preset_id'):
            raise ValueError('team_playbook_not_found')
        with self.core.db() as db:
            preset = self._get(db, channel['preset_id'])
        found = next((p for p in preset['package']['playbooks'] if p['key'] == key), None)
        if not found:
            raise ValueError('team_playbook_not_found')
        from assistant_team import digest
        return {**found, 'sha256': digest(found), 'preset_id': preset['id']}

    def context(self, profile):
        with self.core.db() as db:
            preset = self._get(db, profile['preset_id'])
        package = preset['package']
        source = next(p for p in package['profiles'] if p['key'] == profile['preset_key'])
        return {'name': package['name'], 'instructions': package['instructions'],
            'playbooks': [p for p in package['playbooks'] if p['key'] in source['playbook_keys']],
            'starter_notes': [p for p in package['starter_notes'] if p['profile_key'] == source['key']],
            'skill_descriptions': [p for p in package['skills'] if p['key'] in source['skill_keys']],
            'connector_requirements': [p for p in package['connector_requirements'] if p['key'] in source['connector_keys']],
            'reference_only': True, 'tools_or_credentials_granted': False}

    def export(self, name, channel_id=None, preset_id=None, version=None):
        if version is None:
            version = 2 if preset_id else 1
        if (channel_id is None) == (preset_id is None) or type(version) is not int or version not in (1, 2):
            raise ValueError('team_invalid_package')
        if preset_id and version == 1:
            raise ValueError('team_package_format_unsupported')
        if channel_id and version == 1:
            return self.teams._legacy_package_export(channel_id, name)
        from assistant_team import text
        name = text(name, 80)
        with self.core.db() as db:
            if channel_id:
                channel = self.teams._get(db, 'channels', channel_id)
                preset_id = channel.get('preset_id')
            if preset_id:
                record = self._get(db, preset_id)
                package = json.loads(canonical(record['package']))
                ids = dict(record['profile_map'])
                channels = [(c['key'], self.teams._get(db, 'channels', record['channel_map'][c['key']])) for c in package['channels']]
            else:
                package = normalize_package({'schema': 'phone-lab-team-v2', 'name': name, 'profiles': [
                    {'key': 'p' + str(i), **{k: self.teams._get(db, 'profiles', key)[k] for k in ('name', 'role_id', 'instructions')}}
                    for i, key in enumerate(channel['member_ids'])], 'channels': [
                        {'key': 'c0', 'name': channel['name'], 'instructions': channel['instructions'],
                         'members': ['p' + str(i) for i in range(len(channel['member_ids']))]}]}, **self._options())
                ids = {'p' + str(i): key for i, key in enumerate(channel['member_ids'])}
                channels = [('c0', channel)]
            # Include members added to an installed channel, keeping all old
            # portable keys stable. Nothing from the runtime grant fields travels.
            for _, channel in channels:
                for profile_id in channel['member_ids']:
                    if profile_id not in ids.values():
                        key = 'added-' + str(len(ids))
                        while key in ids: key += 'x'
                        profile = self.teams._get(db, 'profiles', profile_id)
                        package['profiles'].append({'key': key, 'name': profile['name'], 'role_id': profile['role_id'],
                            'instructions': profile['instructions'], 'expertise': profile.get('expertise', []),
                            'playbook_keys': [], 'skill_keys': [], 'connector_keys': []})
                        ids[key] = profile_id
            reverse = {value: key for key, value in ids.items()}
            for item in package['profiles']:
                profile = self.teams._get(db, 'profiles', ids[item['key']])
                for field in ('name', 'role_id', 'instructions', 'expertise'):
                    item[field] = profile.get(field, []) if field == 'expertise' else profile[field]
            for key, channel in channels:
                item = next(c for c in package['channels'] if c['key'] == key)
                routing = channel.get('routing', {})
                item.update(name=channel['name'], instructions=channel['instructions'], members=[reverse[k] for k in channel['member_ids']],
                    lead_key=reverse[routing.get('lead_id', channel['member_ids'][0])],
                    routing={'mode': routing.get('mode', 'all'), 'max_rounds': routing.get('max_rounds', 1),
                        'rules': [{'keywords': r['keywords'], 'member_keys': [reverse[k] for k in r['member_ids']]} for r in routing.get('rules', [])]})
                item['responder'] = ({'kind': 'everyone'} if item['routing']['mode'] == 'all' else
                                     {'kind': 'mentions'} if item['routing']['mode'] == 'auto' and routing.get('mentions_only') else
                                     {'kind': 'lead', 'member_key': item['lead_key']})
                item['playbook_key'] = channel.get('playbook_key')
            channel_keys = {channel['id']: key for key, channel in channels}
            mapped_keys = set(record.get('trigger_map', {})) if preset_id else set()
            original_triggers = {item['key']: item for item in package['triggers'] if item['key'] not in mapped_keys}
            runtime_ids = {value: key for key, value in record.get('trigger_map', {}).items()} if preset_id else {}
            for trigger in self.teams.triggers.list()['triggers']:
                if trigger['channel_id'] not in channel_keys:
                    continue
                key = runtime_ids.get(trigger['id'], 'trigger-' + trigger['id'].split('_')[-1])
                item = {'key': key, 'name': trigger['name'], 'channel_key': channel_keys[trigger['channel_id']],
                    'kind': trigger['kind'], 'question': trigger['question'], 'dispatch_mode': trigger['dispatch_mode'],
                    'max_rounds': trigger['max_rounds'], 'enabled': False,
                    'schedule': {} if trigger['kind'] == 'after_discussion' else trigger['schedule']}
                if trigger.get('playbook_key'): item['playbook_key'] = trigger['playbook_key']
                original_triggers[key] = item
            package['triggers'] = list(original_triggers.values())
            if not package.get('chief_key'):
                package['chief_key'] = package['channels'][0]['lead_key']
            package['name'] = name
        return export_package(package, **self._options())
