"""Bounded portable team data. Parsing never installs, fetches, grants or executes.

v2 stores profiles, room membership/routing/lead, shared instructions,
playbooks, starter notes, inert skill text, unconfigured connector checklists
and paused triggers. Foreign schedules without local semantics remain deferred.
The caller owns persistence, role selection and any later explicit activation.
"""
from datetime import datetime
import hashlib
import json
import re
import unicodedata
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from assistant_team_routing import keywords as routing_keywords

MAX_BYTES = 65536
SCHEMA = 'phone-lab-team-v2'
LIMITS = {'profiles': 24, 'channels': 20, 'members': 4, 'playbooks': 40,
          'starter_notes': 64, 'skills': 60, 'connector_requirements': 30, 'triggers': 50}
LIST_FIELDS = set(LIMITS) - {'members'}
PRIVATE = re.compile(
    r'sk-[A-Za-z0-9_-]{12,}|(?:ghp_|github_pat_)[A-Za-z0-9_]{12,}|'
    r'(?:api[_ -]?key|password|secret|token)\s*["\x27]?\s*[:=]\s*["\x27]?[^\s"\x27,}]+|'
    r'authorization\s*:\s*(?:bearer|basic)\b|\bbearer\s+[A-Za-z0-9_./+=-]{8,}|'
    r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|\bxox[baprs]-[A-Za-z0-9-]{12,}|\bAKIA[A-Z0-9]{16}\b|'
    r'[?&](?:key|api[_-]?key|access[_-]?token|token|auth|signature|password)=[^\s&"\x27]+|'
    r'/(?:Users|home)/[^\s]+|[A-Za-z]:\\Users\\|'
    r'https?://[^\s/]+:[^\s/@]+@', re.I)
MODES = {'all', 'auto', 'collaborate'}
HEADINGS = ('Activation', 'Mission', 'Outcomes', 'Connections', 'Team', 'Chief of Staff', 'Completion rule')
FORBIDDEN_KEYS = {'credential', 'credentials', 'secret', 'secrets', 'password', 'apikey', 'accesstoken',
                  'authorization', 'model', 'models', 'modelid', 'modelids', 'history', 'conversations',
                  'context', 'accountid', 'storeid', 'tenantid', 'customerid', 'toolgrants', 'grants',
                  'permissions', 'approval', 'computer', 'cwd', 'env', 'command', 'script', 'args', 'tools'}
BASE_WARNINGS = [
    'Imported profiles remain disabled without model bindings or execution grants.',
    'Skills and connector requirements are inert; external services remain unconfigured.',
    'All imported triggers remain paused; importing starts no work.',
]


def _fail(code='team_invalid_package'):
    raise ValueError(code)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _text(value, limit=8000, *, empty=False):
    if not isinstance(value, str):
        _fail()
    value = unicodedata.normalize('NFC', value.replace('\r\n', '\n'))
    if len(value) > limit or (not empty and not value.strip()) or any(
            unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} and c not in '\n\t' for c in value):
        _fail('team_invalid_text')
    if PRIVATE.search(unquote(unquote(value))):
        _fail('team_package_private_data')
    return value


def _key(value):
    value = _text(value, 64)
    if not re.fullmatch(r'[\w][\w.-]{0,63}', value):
        _fail()
    return value


def _fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        _fail('team_package_unsupported_field')
    return value


def _list(value, maximum, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _fail('team_package_limit')
    return value


def _strings(value, maximum=20, limit=100, *, keys=False):
    result = [(_key(x) if keys else _text(x, limit)) for x in _list(value, maximum)]
    if len({x.casefold() for x in result}) != len(result):
        _fail('team_package_duplicate')
    return result


def _unique(items):
    keys = [x['key'].casefold() for x in items]
    if len(set(keys)) != len(keys):
        _fail('team_package_duplicate')


def _walk(value, depth=0, budget=None):
    """Bound decoded structures before copying or interpreting any field."""
    if budget is None:
        budget = [4096]
    budget[0] -= 1
    if depth > 16 or budget[0] < 0:
        _fail('team_package_limit')
    if isinstance(value, dict):
        for k, v in value.items():
            _text(k, 200)
            if k.casefold().replace('_', '').replace('-', '') in FORBIDDEN_KEYS:
                _fail('team_package_unsupported_field')
            _walk(v, depth + 1, budget)
    elif isinstance(value, list):
        for item in value:
            _walk(item, depth + 1, budget)
    elif isinstance(value, str):
        _text(value, MAX_BYTES, empty=True)
    elif value is not None and type(value) not in {int, bool}:
        _fail()


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        key = unicodedata.normalize('NFC', key)
        if key in out:
            _fail('team_package_duplicate')
        out[key] = value
    return out


def _yaml(raw):
    try:
        import yaml
    except ImportError:
        _fail('team_yaml_unavailable')
    try:
        depth = 0
        for count, token in enumerate(yaml.scan(raw), 1):
            name = type(token).__name__
            if name in {'AnchorToken', 'AliasToken', 'TagToken'}:
                _fail('team_unsafe_yaml')
            if name in {'BlockMappingStartToken', 'BlockSequenceStartToken', 'FlowMappingStartToken', 'FlowSequenceStartToken'}:
                depth += 1
            elif name in {'BlockEndToken', 'FlowMappingEndToken', 'FlowSequenceEndToken'}:
                depth -= 1
            if depth > 16 or count > 10000:
                _fail('team_package_limit')
        node = yaml.compose(raw, Loader=yaml.SafeLoader)
        budget = [4096]

        def construct(item, level=0):
            budget[0] -= 1
            if level > 16 or budget[0] < 0:
                _fail('team_package_limit')
            if isinstance(item, yaml.ScalarNode):
                text = item.value
                if item.tag.endswith(':null') and text.lower() in {'null', '~', ''}:
                    return None
                if item.tag.endswith(':bool') and text.lower() in {'true', 'false'}:
                    return text.lower() == 'true'
                if item.tag.endswith(':int') and re.fullmatch(r'-?(?:0|[1-9][0-9]*)', text):
                    return int(text)
                return text
            if isinstance(item, yaml.SequenceNode):
                return [construct(child, level + 1) for child in item.value]
            if isinstance(item, yaml.MappingNode):
                pairs = []
                for key, child in item.value:
                    if not isinstance(key, yaml.ScalarNode) or key.tag != 'tag:yaml.org,2002:str':
                        _fail('team_unsafe_yaml')
                    pairs.append((key.value, construct(child, level + 1)))
                return _pairs(pairs)
            _fail('team_unsafe_yaml')
        return construct(node)
    except (yaml.YAMLError, RecursionError, OverflowError):
        _fail('team_invalid_yaml')


def _schedule(kind, value):
    if kind in {'manual', 'webhook', 'after_discussion'}:
        return dict(_fields(value, ()))
    if kind == 'weekly':
        _fields(value, {'weekday', 'time', 'timezone'}, {'weekday', 'time', 'timezone'})
        if type(value['weekday']) is not int or not 0 <= value['weekday'] <= 6:
            _fail()
        at = _text(value['time'], 5)
        zone = _text(value['timezone'], 80)
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', at):
            _fail()
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            _fail('team_invalid_timezone')
        return {'weekday': value['weekday'], 'time': at, 'timezone': zone}
    if kind not in {'once', 'interval'}:
        _fail()
    allowed = {'at'} if kind == 'once' else {'start_at', 'interval_seconds'}
    _fields(value, allowed, allowed)
    field = 'at' if kind == 'once' else 'start_at'
    at = _text(value[field], 40)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', at):
        _fail('team_invalid_schedule')
    try:
        parsed = datetime.fromisoformat(at.replace('Z', '+00:00'))
        if parsed.utcoffset() is None or not 2000 <= parsed.year <= 2100 or not 0 <= parsed.timestamp() <= 4102444800:
            _fail()
    except (ValueError, OverflowError):
        _fail('team_invalid_schedule')
    result = {field: at}
    if kind == 'interval':
        seconds = value['interval_seconds']
        if type(seconds) is not int or not 60 <= seconds <= 604800:
            _fail('team_invalid_schedule')
        result['interval_seconds'] = seconds
    return result


def _normalise(value, role_ids, default_role_id, warnings):
    _walk(value)
    schema = value.get('schema') if isinstance(value, dict) else None
    if schema == 'phone-lab-team-v1':
        _fields(value, {'schema', 'name', 'profiles', 'channels'}, {'schema', 'name', 'profiles', 'channels'})
        for profile in _list(value['profiles'], 8, 1):
            _fields(profile, {'key', 'name', 'role_id', 'instructions'}, {'key', 'name', 'role_id', 'instructions'})
        channels = []
        for i, channel in enumerate(_list(value['channels'], 8, 1)):
            _fields(channel, {'name', 'instructions', 'members'}, {'name', 'instructions', 'members'})
            channels.append({**channel, 'key': 'c' + str(i)})
        value = {**value, 'schema': SCHEMA, 'channels': channels}
    if value.get('schema') != SCHEMA:
        _fail('team_package_version_unsupported')
    _fields(value, {'schema', 'name', 'instructions', 'chief_key', *LIST_FIELDS}, {'schema', 'name', 'profiles', 'channels'})
    out = {'schema': SCHEMA, 'name': _text(value['name'], 80),
           'instructions': _text(value.get('instructions', ''), 8000, empty=True),
           'chief_key': _key(value['chief_key']) if value.get('chief_key') is not None else None}
    profiles = []
    for p in _list(value['profiles'], LIMITS['profiles'], 1):
        _fields(p, {'key', 'name', 'role_id', 'instructions', 'expertise', 'playbook_keys', 'skill_keys', 'connector_keys'}, {'key', 'name', 'role_id', 'instructions'})
        role = _text(p['role_id'], 160)
        if role_ids is not None and role not in role_ids:
            _fail('team_invalid_role')
        profiles.append({'key': _key(p['key']), 'name': _text(p['name'], 80), 'role_id': role,
                         'instructions': _text(p['instructions'], 8000, empty=True),
                         'expertise': routing_keywords(p.get('expertise', [])),
                         **{field: _strings(p.get(field, []), 60, keys=True) for field in ('playbook_keys', 'skill_keys', 'connector_keys')}})
    _unique(profiles)
    out['profiles'] = profiles
    profile_keys = {p['key'] for p in profiles}
    if out['chief_key'] is not None and out['chief_key'] not in profile_keys:
        _fail('team_package_invalid_reference')
    channels = []
    for c in _list(value['channels'], LIMITS['channels'], 1):
        _fields(c, {'key', 'name', 'instructions', 'members', 'lead_key', 'routing', 'responder', 'playbook_key'}, {'key', 'name', 'instructions', 'members'})
        members = _strings(c['members'], LIMITS['members'], keys=True)
        if not members or set(members) - profile_keys:
            _fail('team_package_invalid_reference')
        lead = _key(c['lead_key']) if c.get('lead_key') is not None else None
        if lead is not None and lead not in members:
            _fail('team_package_invalid_reference')
        routing = c.get('routing', {})
        _fields(routing, {'mode', 'rules', 'max_rounds'})
        mode, rounds = routing.get('mode', 'all'), routing.get('max_rounds', 1)
        if mode not in MODES or type(rounds) is not int or not 1 <= rounds <= 3:
            _fail()
        rules = []
        for rule in _list(routing.get('rules', []), 12):
            _fields(rule, {'keywords', 'member_keys'}, {'keywords', 'member_keys'})
            words, targets = routing_keywords(rule['keywords']), _strings(rule['member_keys'], 4, keys=True)
            if not words or not targets or set(targets) - set(members):
                _fail('team_package_invalid_reference')
            rules.append({'keywords': words, 'member_keys': targets})
        responder = c.get('responder', {'kind': 'everyone'})
        _fields(responder, {'kind', 'member_key'}, {'kind'})
        if responder['kind'] not in {'everyone', 'mentions', 'lead'}:
            _fail()
        if responder['kind'] == 'lead':
            if lead is None or responder.get('member_key', lead) != lead:
                _fail('team_package_invalid_reference')
            responder = {'kind': 'lead', 'member_key': lead}
        elif 'member_key' in responder:
            _fail()
        channels.append({'key': _key(c['key']), 'name': _text(c['name'], 80),
                         'instructions': _text(c['instructions'], 8000, empty=True), 'members': members,
                         'lead_key': lead, 'routing': {'mode': mode, 'rules': rules, 'max_rounds': rounds}, 'responder': responder,
                         'playbook_key': _key(c['playbook_key']) if c.get('playbook_key') is not None else None})
    _unique(channels); out['channels'] = channels
    for field in ('playbooks', 'skills', 'connector_requirements'):
        out[field] = []
        for item in _list(value.get(field, []), LIMITS[field]):
            if field == 'playbooks':
                _fields(item, {'key', 'name', 'instructions', 'triggers'}, {'key', 'name', 'instructions'})
                result = {'key': _key(item['key']), 'name': _text(item['name'], 100),
                          'instructions': _text(item['instructions'], 8000), 'triggers': _strings(item.get('triggers', []), 30)}
            elif field == 'skills':
                _fields(item, {'key', 'name', 'description', 'instructions'}, {'key', 'name', 'description', 'instructions'})
                result = {'key': _key(item['key']), 'name': _text(item['name'], 100),
                          'description': _text(item['description'], 1024, empty=True), 'instructions': _text(item['instructions'], 8000, empty=True)}
            else:
                _fields(item, {'key', 'label', 'reason', 'optional', 'status'}, {'key', 'label', 'reason'})
                if type(item.get('optional', False)) is not bool or item.get('status', 'unconfigured') != 'unconfigured':
                    _fail('team_package_unsupported_field')
                result = {'key': _key(item['key']), 'label': _text(item['label'], 100),
                          'reason': _text(item['reason'], 1000, empty=True), 'optional': item.get('optional', False), 'status': 'unconfigured'}
            out[field].append(result)
        _unique(out[field])
    for profile in profiles:
        for reference, target in (('playbook_keys', 'playbooks'), ('skill_keys', 'skills'), ('connector_keys', 'connector_requirements')):
            if set(profile[reference]) - {x['key'] for x in out[target]}:
                _fail('team_package_invalid_reference')
    for channel in channels:
        if channel['playbook_key'] is not None and channel['playbook_key'] not in {x['key'] for x in out['playbooks']}:
            _fail('team_package_invalid_reference')
    out['starter_notes'] = []
    note_keys = set()
    for item in _list(value.get('starter_notes', []), LIMITS['starter_notes']):
        _fields(item, {'profile_key', 'name', 'content'}, {'profile_key', 'name', 'content'})
        who, name = _key(item['profile_key']), _text(item['name'], 100)
        if who not in profile_keys or (who, name.casefold()) in note_keys:
            _fail('team_package_invalid_reference')
        if '\\' in name or '..' in name or name.startswith('/') or ('/' in name and not re.fullmatch(r'memory/[\w .-]+\.md', name)) or re.search(r'\d{4}-\d{2}-\d{2}\.md$', name):
            _fail('team_package_private_data')
        note_keys.add((who, name.casefold()))
        out['starter_notes'].append({'profile_key': who, 'name': name, 'content': _text(item['content'], 8000, empty=True)})
    out['triggers'] = []
    for item in _list(value.get('triggers', []), LIMITS['triggers']):
        _fields(item, {'key', 'name', 'channel_key', 'kind', 'question', 'dispatch_mode', 'max_rounds', 'playbook_key', 'schedule', 'enabled', 'source_spec', 'reason'}, {'key', 'name', 'channel_key', 'kind', 'question'})
        kind = item['kind']; channel = item['channel_key']
        if kind == 'after_discussion':
            if channel not in {c['key'] for c in channels}:
                _fail('team_package_invalid_reference')
            _fields(item.get('schedule', {}), ())
            if 'source_spec' in item or 'reason' in item:
                _fail('team_package_unsupported_field')
            item = {k: v for k, v in item.items() if k != 'schedule'}
            item.update(kind='deferred', reason='requires_discussion_binding',
                        source_spec={'kind': 'after_discussion', 'schedule': {}})
            kind = 'deferred'
        if (kind != 'deferred' or channel is not None) and channel not in {c['key'] for c in channels}:
            _fail('team_package_invalid_reference')
        mode, rounds = item.get('dispatch_mode', 'auto'), item.get('max_rounds', 1)
        if mode not in MODES or type(rounds) is not int or not 1 <= rounds <= 3 or type(item.get('enabled', False)) is not bool:
            _fail()
        result = {'key': _key(item['key']), 'name': _text(item['name'], 80), 'channel_key': channel, 'kind': kind,
                  'question': _text(item['question'], 2000), 'dispatch_mode': mode, 'max_rounds': rounds, 'enabled': False}
        if item.get('enabled'):
            warnings.append('An enabled trigger was imported paused; enable it only after reviewing local configuration.')
        if 'playbook_key' in item:
            if item['playbook_key'] not in {p['key'] for p in out['playbooks']}:
                _fail('team_package_invalid_reference')
            result['playbook_key'] = item['playbook_key']
        if kind == 'deferred':
            if 'schedule' in item:
                _fail('team_package_unsupported_field')
            result['source_spec'] = _deferred_spec(item.get('source_spec', {}))
            spec = result['source_spec']
            if spec.get('agent') is not None and spec['agent'] not in profile_keys:
                _fail('team_package_invalid_reference')
            if spec.get('room') is not None and spec['room'] not in {c['key'] for c in channels}:
                _fail('team_package_invalid_reference')
            if item.get('source_spec', {}).get('enabledAfterInstall'):
                warnings.append('An enabled foreign routine was imported paused.')
            result['reason'] = _text(item.get('reason', 'unsupported_upstream_schedule'), 300)
            warnings.append('Deferred trigger remains unconfigured: ' + result['reason'])
        else:
            if 'source_spec' in item or 'reason' in item:
                _fail('team_package_unsupported_field')
            result['schedule'] = _schedule(kind, item.get('schedule', {}))
        out['triggers'].append(result)
    _unique(out['triggers'])
    return out


def _deferred_spec(value):
    if isinstance(value, dict) and 'kind' in value:
        _fields(value, {'kind', 'schedule'}, {'kind', 'schedule'})
        if value['kind'] != 'after_discussion':
            _fail('team_package_unsupported_field')
        _fields(value['schedule'], ())
        return {'kind': 'after_discussion', 'schedule': {}}
    _fields(value, {'key', 'name', 'agent', 'room', 'prompt', 'runOn', 'schedule', 'durationMinutes', 'timeoutMinutes',
                    'overlap', 'continuity', 'runOnStartup', 'enabledAfterInstall', 'trigger'})
    schedule = value.get('schedule', {})
    _fields(schedule, {'type', 'expression', 'timeZone', 'at', 'time', 'weekdays', 'everyMinutes', 'anchorAt', 'window', 'endsAt'})
    if 'window' in schedule:
        _fields(schedule['window'], {'start', 'end'}, {'start', 'end'})
        for text in schedule['window'].values():
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', _text(text, 5)):
                _fail('team_invalid_schedule')
    for field in ('type', 'expression', 'timeZone', 'time'):
        if field in schedule:
            _text(schedule[field], 300)
    for field in ('at', 'everyMinutes', 'anchorAt', 'endsAt'):
        if field in schedule and (type(schedule[field]) is not int or not 0 <= schedule[field] <= 8640000000000000):
            _fail('team_invalid_schedule')
    if 'weekdays' in schedule:
        days = _list(schedule['weekdays'], 7, 1)
        if any(type(day) is not int or not 0 <= day <= 6 for day in days) or len(set(days)) != len(days):
            _fail('team_invalid_schedule')
    if 'trigger' in value:
        _fields(value['trigger'], {'type', 'event', 'description'})
        for text in value['trigger'].values():
            _text(text, 1000)
    for field in ('key', 'name', 'agent', 'room', 'prompt', 'runOn', 'overlap'):
        if field in value:
            _text(value[field], 8000)
    for field in ('continuity', 'runOnStartup', 'enabledAfterInstall'):
        if field in value and type(value[field]) is not bool:
            _fail()
    for field in ('durationMinutes', 'timeoutMinutes'):
        if field in value and (type(value[field]) is not int or not 1 <= value[field] <= 1440):
            _fail()
    if value.get('runOn', 'maus') not in {'maus', 'cloud'} or value.get('overlap', 'skip') not in {'skip', 'queue'}:
        _fail('team_package_unsupported_field')
    result = json.loads(_canonical(value))
    if 'enabledAfterInstall' in result:
        result['enabledAfterInstall'] = False
    return result


def _upstream(metadata, body, default_role_id, role_ids, warnings):
    """Map the official BotMRR blueprint into local data, never its privileges."""
    _walk(metadata)
    listing = {'id', 'release', 'tagline', 'summary', 'category', 'author', 'license', 'featured',
               'tags', 'outcomes', 'setupMinutes', 'examples', 'proof'}
    _fields(metadata, {'botmrr', 'name', 'agents', 'chiefOfStaff', 'team', 'rooms', 'routines', 'playbooks',
                       'skills', 'requirements', 'connections', *listing}, {'botmrr', 'name', 'agents'})
    if type(metadata['botmrr']) is not int or metadata['botmrr'] != 1:
        _fail('team_package_version_unsupported')
    for heading in HEADINGS:
        if not re.search(r'^##[ \t]+' + re.escape(heading) + r'[ \t]*$', body, re.M):
            _fail('team_package_missing_section')
    if 'author' in metadata:
        author = _fields(metadata['author'], {'name', 'url'}, {'name'})
        for value in author.values():
            _text(value, 500)
    for field in ('id', 'release', 'tagline', 'summary', 'category', 'license'):
        if field in metadata:
            _text(metadata[field], 2000)
    for field in ('tags', 'outcomes'):
        if field in metadata:
            _strings(metadata[field], 30, 240)
    if 'featured' in metadata and type(metadata['featured']) is not bool:
        _fail()
    if 'setupMinutes' in metadata and (type(metadata['setupMinutes']) is not int or not 1 <= metadata['setupMinutes'] <= 240):
        _fail()
    if 'proof' in metadata:
        proof = _fields(metadata['proof'], {'amount', 'period', 'source', 'credibility'})
        if 'source' in proof:
            _fields(proof['source'], {'url', 'author', 'date', 'quote'})
            for value in proof['source'].values():
                _text(value, 2000)
        for field in ('amount', 'period', 'credibility'):
            if field in proof:
                _text(proof[field], 300)
        warnings.append('Public proof claims are unverified listing metadata and confer no authority.')
    for example in _list(metadata.get('examples', []), 12):
        _fields(example, {'title', 'input', 'output'}, {'title', 'input', 'output'})
        for text in example.values():
            _text(text, 8000)
    omitted = sorted(listing & set(metadata))
    if omitted:
        warnings.append('Listing metadata omitted from local configuration: ' + ', '.join(omitted) + '.')
    if default_role_id is None and role_ids is not None and len(role_ids) == 1:
        default_role_id = next(iter(role_ids))
    if not default_role_id or (role_ids is not None and default_role_id not in role_ids):
        _fail('team_package_role_mapping_required')
    warnings.append('Foreign role titles use the selected local role; no external permissions are imported.')
    team = _fields(metadata.get('team', {}), {'name', 'brief', 'leader'})
    chief = metadata.get('chiefOfStaff', team.get('leader'))
    if metadata.get('chiefOfStaff') and team.get('leader') and metadata['chiefOfStaff'] != team['leader']:
        _fail('team_package_invalid_reference')
    profiles, notes = [], []
    for agent in _list(metadata['agents'], LIMITS['profiles'], 1):
        _fields(agent, {'key', 'name', 'title', 'description', 'soul', 'appearance', 'playbooks', 'skills', 'connections', 'seed'}, {'key', 'name'})
        key = _key(agent['key'])
        if 'appearance' in agent:
            appearance = _fields(agent['appearance'], {'color', 'mascotExpression', 'mascotBody', 'avatar'})
            for field in ('color', 'mascotExpression', 'mascotBody'):
                if field in appearance:
                    _text(appearance[field], 80)
            if 'avatar' in appearance:
                avatar = _fields(appearance['avatar'], {'mime', 'data', 'crop'}, {'mime', 'data', 'crop'})
                for text in avatar.values():
                    _text(text, MAX_BYTES)
            warnings.append('Foreign appearance metadata is not applied to local profiles.')
        instructions = '\n\n'.join(_text(agent[field], 8000) for field in ('title', 'description', 'soul') if agent.get(field))
        title = _text(agent['title'], 200) if agent.get('title') else None
        if title and (len(title) > 40 or any(ord(c) < 32 for c in title)):
            warnings.append('Foreign title retained completely in instructions; derived expertise is limited to 40 characters on one line.')
            title = ' '.join(title.split())[:40]
        profiles.append({'key': key, 'name': agent['name'], 'role_id': default_role_id, 'instructions': instructions,
                         'expertise': [title] if title else [],
                         'playbook_keys': agent.get('playbooks', []), 'skill_keys': agent.get('skills', []),
                         'connector_keys': agent.get('connections', [])})
        if 'seed' in agent:
            seed = _fields(agent['seed'], {'memory'}, {'memory'})
            if not isinstance(seed['memory'], dict):
                _fail()
            for name, content in seed['memory'].items():
                notes.append({'profile_key': key, 'name': name, 'content': content})
    profile_keys = {p['key'] for p in profiles}
    if chief is not None and chief not in profile_keys:
        _fail('team_package_invalid_reference')
    rooms = _list(metadata.get('rooms', []), LIMITS['channels'])
    if not rooms:
        warnings.append('No foreign room was supplied; explicit local review rooms were created for the imported members.')
        rooms = [{'key': 'room-' + str(i // 4 + 1), 'name': metadata['name'] + ' ' + str(i // 4 + 1),
                  'members': [p['key'] for p in profiles[i:i + 4]], 'bulletin': '',
                  'defaultResponder': {'kind': 'everyone'}} for i in range(0, len(profiles), 4)]
    channels = []
    for room in rooms:
        _fields(room, {'key', 'name', 'members', 'bulletin', 'defaultResponder'}, {'key', 'name', 'members'})
        responder = _fields(room.get('defaultResponder', {'kind': 'everyone'}), {'kind', 'agent'}, {'kind'})
        kind = responder['kind']
        if kind not in {'everyone', 'mentions', 'agent', 'auto'}:
            _fail()
        lead = responder.get('agent') if kind in {'agent', 'auto'} else (chief if chief in room['members'] else None)
        if kind == 'agent' and not lead:
            _fail('team_package_invalid_reference')
        if kind in {'everyone', 'mentions'} and 'agent' in responder:
            _fail('team_package_unsupported_field')
        if kind == 'auto' and lead is None:
            lead = chief if chief in room['members'] else None
        local_responder = {'kind': 'lead', 'member_key': lead} if kind in {'agent', 'auto'} and lead else {'kind': 'mentions' if kind == 'mentions' else 'everyone'}
        channels.append({'key': room['key'], 'name': room['name'], 'instructions': room.get('bulletin', ''),
                         'members': room['members'], 'lead_key': lead, 'responder': local_responder,
                         'routing': {'mode': 'all' if kind == 'everyone' else 'auto', 'rules': [], 'max_rounds': 1}})
    playbooks = []
    for item in _list(metadata.get('playbooks', []), LIMITS['playbooks']):
        _fields(item, {'key', 'name', 'summary', 'triggers', 'instructions'}, {'key', 'name', 'instructions'})
        instructions = '\n\n'.join(_text(item[field], 8000) for field in ('summary', 'instructions') if item.get(field))
        playbooks.append({'key': item['key'], 'name': item['name'], 'instructions': instructions, 'triggers': item.get('triggers', [])})
    skills = []
    if 'skills' in metadata:
        section = _fields(metadata['skills'], {'version', 'entries'}, {'version', 'entries'})
        if type(section['version']) is not int or section['version'] != 1:
            _fail('team_package_version_unsupported')
        for item in _list(section['entries'], LIMITS['skills']):
            _fields(item, {'name', 'description', 'source', 'license', 'compatibility', 'instructions'}, {'name', 'description', 'instructions'})
            if 'source' in item:
                source = _text(item['source'], 2000, empty=True)
                if re.match(r'^(?:[a-z]:[\\/]|[\\/]|file:)', source, re.I):
                    _fail('team_package_private_data')
            for field in ('license', 'compatibility'):
                if field in item:
                    _text(item[field], 200, empty=True)
            if {'source', 'license', 'compatibility'} & set(item):
                warnings.append('Skill source/license/compatibility labels are retained only within inert instructions when supplied.')
            skill_text = item['instructions']
            labels = ['%s: %s' % (field, item[field]) for field in ('source', 'license', 'compatibility') if item.get(field)]
            if labels:
                skill_text += '\n\n' + '\n'.join(labels)
            skills.append({'key': item['name'], 'name': item['name'], 'description': item['description'], 'instructions': skill_text})
    requirements = _fields(metadata.get('requirements', {}), {'apps', 'capabilities', 'platforms'})
    connectors = []
    for app in _list(requirements.get('apps', []), LIMITS['connector_requirements']):
        _fields(app, {'slug', 'label', 'reason', 'optional'}, {'slug', 'label', 'reason'})
        connectors.append({'key': app['slug'], 'label': app['label'], 'reason': app['reason'], 'optional': app.get('optional', False), 'status': 'unconfigured'})
    for field in ('capabilities', 'platforms'):
        if requirements.get(field):
            labels = _strings(requirements[field], 30)
            warnings.append('Foreign ' + field + ' are requirements only, unconfigured: ' + ', '.join(labels) + '.')
    for connection in _list(metadata.get('connections', []), LIMITS['connector_requirements']):
        _fields(connection, {'key', 'label', 'reason', 'mcp'}, {'key', 'label', 'reason'})
        reason = connection['reason']
        if 'mcp' in connection:
            spec = _fields(connection['mcp'], {'transport', 'url', 'valueNames'}, {'transport', 'url', 'valueNames'})
            if spec['transport'] not in {'http', 'sse'}:
                _fail('team_package_unsupported_field')
            _text(spec['url'], 2000)
            headers = _strings(spec['valueNames'], 32, 128)
            reason += '\nRequired value names: ' + ', '.join(headers)
            warnings.append('Remote connector addresses are omitted; configure each connector through the local connection flow.')
        connectors.append({'key': connection['key'], 'label': connection['label'], 'reason': reason, 'optional': False, 'status': 'unconfigured'})
    triggers = []
    for routine in _list(metadata.get('routines', []), LIMITS['triggers']):
        spec = _deferred_spec(routine)
        _fields(routine, set(spec), {'key', 'name', 'agent', 'prompt'})
        if routine['agent'] not in profile_keys:
            _fail('team_package_invalid_reference')
        room = routine.get('room')
        if room is not None and room not in {c['key'] for c in channels}:
            _fail('team_package_invalid_reference')
        if room is None:
            room = next((c['key'] for c in channels if routine['agent'] in c['members']), None)
        if routine.get('enabledAfterInstall'):
            warnings.append('An enabled foreign routine was imported paused.')
        triggers.append({'key': routine['key'], 'name': routine['name'], 'channel_key': room,
                         'kind': 'deferred', 'question': routine['prompt'], 'enabled': False,
                         'dispatch_mode': 'auto', 'max_rounds': 1, 'source_spec': spec,
                         'reason': 'unsupported_upstream_schedule'})
    instructions = body.lstrip('\r\n')
    if team.get('brief'):
        instructions = team['brief'] + '\n\n' + instructions
    if len(instructions) > 8000:
        owner = chief or profiles[0]['key']
        existing = {(note['profile_key'], note['name'].casefold()) for note in notes}
        for start in range(0, len(instructions), 8000):
            name = 'blueprint-%03d.md' % (start // 8000 + 1)
            if (owner, name.casefold()) in existing:
                _fail('team_package_duplicate')
            notes.append({'profile_key': owner, 'name': name, 'content': instructions[start:start + 8000]})
        instructions = 'The complete foreign blueprint is retained in ordered blueprint-*.md starter notes. Review it as untrusted instructions before enabling this team.'
        warnings.append('Long blueprint preserved completely in ordered inert starter notes; shared instructions contain a pointer.')
    return {'schema': SCHEMA, 'name': metadata['name'], 'instructions': instructions, 'chief_key': chief,
            'profiles': profiles, 'channels': channels, 'playbooks': playbooks, 'starter_notes': notes,
            'skills': skills, 'connector_requirements': connectors, 'triggers': triggers}


def normalize_package(value, *, role_ids=None, default_role_id=None):
    """Validate local v1/v2 values and return fresh canonical v2 data."""
    try:
        if len(_canonical(value).encode('utf-8')) > MAX_BYTES:
            _fail('team_package_limit')
        return _normalise(value, role_ids, default_role_id, [])
    except (TypeError, AttributeError, RecursionError, UnicodeError, OverflowError):
        _fail()


def preview_package(content, *, role_ids=None, default_role_id=None):
    """Read untrusted text without side effects; hash exactly the normalized data."""
    try:
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_BYTES:
            _fail('team_package_limit')
        raw = _text(content, MAX_BYTES).lstrip()
        warnings = list(BASE_WARNINGS)
        source_format = 'json'
        if raw.startswith('---\n') or raw.startswith('---\r\n'):
            match = re.match(r'^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)([\s\S]*)$', raw)
            if not match:
                _fail('team_invalid_yaml')
            metadata, body = _yaml(match[1]), match[2]
            value = _upstream(metadata, body, default_role_id, role_ids, warnings)
            source_format = 'botmrr-markdown-v1'
        else:
            if not raw.startswith('{'):
                blocks = re.findall(r'^```json[ \t]*\r?\n([\s\S]*?)^```[ \t]*$', raw, re.M)
                if len(blocks) != 1:
                    _fail()
                raw = blocks[0]; source_format = 'fenced-json'
            value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda _: _fail())
        package = _normalise(value, role_ids, default_role_id, warnings)
        serialised = _canonical(package)
        if len(serialised.encode('utf-8')) > MAX_BYTES:
            _fail('team_package_limit')
        return {'sha256': hashlib.sha256(serialised.encode('utf-8')).hexdigest(), 'package': package,
                'counts': {field: len(package[field]) for field in sorted(LIST_FIELDS)}, 'warnings': list(dict.fromkeys(warnings)),
                'source_format': source_format, 'execution_started': False}
    except (json.JSONDecodeError, TypeError, AttributeError, RecursionError, UnicodeError, OverflowError):
        _fail()


def export_package(value, *, format='markdown', role_ids=None, default_role_id=None):
    """Render only allowlisted portable fields; runtime state must be projected by caller."""
    if format not in {'json', 'markdown'}:
        _fail('team_package_format_unsupported')
    package = normalize_package(value, role_ids=role_ids, default_role_id=default_role_id)
    content = json.dumps(package, ensure_ascii=False, indent=2)
    if format == 'markdown':
        content = '# ' + package['name'].replace('\n', ' ') + '\n\n```json\n' + content + '\n```\n'
    result = preview_package(content, role_ids=role_ids, default_role_id=default_role_id)
    return {**result, 'content': content}
