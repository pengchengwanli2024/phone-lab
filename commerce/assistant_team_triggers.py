"""Durable local team triggers; ingress uses the existing authenticated tools.

Saved definitions are paused. Enabling freezes source fingerprints, and every
dispatch shares the Copilot lock and SQLite transaction with discussion creation.
Webhook data is hashed as event metadata and never becomes model instructions.
"""
from datetime import datetime, timedelta
import hashlib
from inspect import signature
import json
import math
import re
import time
import unicodedata
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent_runtime.policy import canonical
from copilot import LOCK as COPILOT_LOCK


KINDS = ('manual', 'once', 'interval', 'weekly', 'webhook', 'after_discussion')
READ_ONLY = {'commerce_assistant_team_trigger_list', 'commerce_assistant_team_trigger_get'}
LIMITS = {'triggers': 100, 'events_per_trigger': 2000, 'history': 20,
          'payload_bytes': 8192, 'slot_grace_seconds': 60}
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted', 'partial', 'rejected', 'blocked'}
MODEL_FIELDS = ('provider', 'profile_id', 'profile_revision', 'model', 'engine', 'base_url',
                'json_mode', 'host_id', 'native_provider', 'route_sha256', 'reasoning_effort')


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _private(value):
    # AssistantTeams imports this module while its own constants are initializing.
    from assistant_team import PRIVATE
    return PRIVATE.search(value)


def definitions(schema, string):
    ident = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    revision = {'type': 'integer', 'minimum': 1}
    # Schedule fields are checked by kind; arbitrary condition execution is absent.
    schedule = schema({'at': string, 'start_at': string,
                       'interval_seconds': {'type': 'integer', 'minimum': 60, 'maximum': 604800},
                       'weekday': {'type': 'integer', 'minimum': 0, 'maximum': 6},
                       'time': {'type': 'string', 'pattern': r'^\d{2}:\d{2}$'},
                       'timezone': string, 'discussion_id': ident})
    trigger = schema({'id': ident, 'name': {'type': 'string', 'minLength': 1, 'maxLength': 80},
                      'kind': {'type': 'string', 'enum': list(KINDS)},
                      'channel_id': ident, 'channel_revision': revision,
                      'question': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
                      'dispatch_mode': {'type': 'string', 'enum': ['auto', 'all', 'collaborate']},
                      'max_rounds': {'type': 'integer', 'minimum': 1, 'maximum': 3},
                      'playbook_key': {'type': 'string', 'minLength': 1, 'maxLength': 64},
                      'schedule': schedule},
                     ['name', 'kind', 'channel_id', 'channel_revision', 'question',
                      'dispatch_mode', 'max_rounds', 'schedule'])
    return [
        ('commerce_assistant_team_trigger_save', '保存本地团队触发定义并暂停；不会调用模型',
         schema({'trigger': trigger, 'expected_revision': revision}, ['trigger'])),
        ('commerce_assistant_team_trigger_enable', '明确启停本地触发器；启用冻结当前频道、成员和模型配置',
         schema({'trigger_id': ident, 'expected_revision': revision, 'enabled': {'type': 'boolean'}},
                ['trigger_id', 'expected_revision', 'enabled'])),
        ('commerce_assistant_team_trigger_list', '读取本地团队触发器与最近事件', schema({'channel_id': ident})),
        ('commerce_assistant_team_trigger_get', '读取一个本地团队触发器；不执行或重放', schema({'trigger_id': ident}, ['trigger_id'])),
        ('commerce_assistant_team_trigger_run', '明确执行已启用的本地触发器；按幂等键去重',
         schema({'trigger_id': ident, 'expected_revision': revision, 'idempotency_key': ident},
                ['trigger_id', 'expected_revision', 'idempotency_key'])),
        ('commerce_assistant_team_trigger_event', '通过现有认证入口提交本地webhook事件；数据不作为模型指令',
         schema({'trigger_id': ident, 'expected_revision': revision, 'event_id': ident,
                 'payload': {'type': 'object'}},
                ['trigger_id', 'expected_revision', 'event_id', 'payload'])),
    ]


def _text(value, limit, code):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in '\n\t' for c in value)):
        raise ValueError(code)
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ValueError(code) from None
    return value.strip()


def _clock(value):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 4102444800:
        raise ValueError('team_trigger_invalid_time')
    return float(value)


def _timestamp(value):
    if (not isinstance(value, str) or len(value) > 40 or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', value)):
        raise ValueError('team_trigger_invalid_schedule')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or not 2000 <= result.year <= 2100:
            raise ValueError()
        return _clock(result.timestamp())
    except (ValueError, OverflowError):
        raise ValueError('team_trigger_invalid_schedule') from None


def _schedule(kind, value):
    fields = {'manual': set(), 'webhook': set(), 'once': {'at'},
              'interval': {'start_at', 'interval_seconds'},
              'weekly': {'weekday', 'time', 'timezone'}, 'after_discussion': {'discussion_id'}}
    if not isinstance(value, dict) or set(value) != fields[kind]:
        raise ValueError('team_trigger_invalid_schedule')
    result = dict(value)
    if kind == 'once':
        _timestamp(value['at'])
    elif kind == 'interval':
        _timestamp(value['start_at'])
        if type(value['interval_seconds']) is not int or not 60 <= value['interval_seconds'] <= 604800:
            raise ValueError('team_trigger_invalid_schedule')
    elif kind == 'weekly':
        if (type(value['weekday']) is not int or not 0 <= value['weekday'] <= 6
                or not isinstance(value['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value['time'])
                or not isinstance(value['timezone'], str) or len(value['timezone']) > 80):
            raise ValueError('team_trigger_invalid_schedule')
        try:
            ZoneInfo(value['timezone'])
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('team_trigger_invalid_schedule') from None
    elif kind == 'after_discussion':
        if not isinstance(value['discussion_id'], str) or not re.fullmatch(r'discussion_[A-Za-z0-9_]{1,80}', value['discussion_id']):
            raise ValueError('team_trigger_invalid_schedule')
    return result


def _payload(value):
    if type(value) not in (dict, str):
        raise ValueError('team_trigger_invalid_payload')
    count = 0

    def check(item, depth=0):
        nonlocal count
        count += 1
        if count > 128 or depth > 4:
            raise ValueError()
        if type(item) is dict:
            for key, child in item.items():
                if (not isinstance(key, str) or not key or len(key) > 80
                        or re.search(r'password|secret|token|api.?key|authorization|credential', key, re.I)):
                    raise ValueError()
                check(child, depth + 1)
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)
        elif type(item) is str:
            if len(item) > LIMITS['payload_bytes'] or any(ord(c) < 32 and c not in '\n\t' for c in item):
                raise ValueError()
        elif item is not None and type(item) not in (bool, int, float):
            raise ValueError()
    try:
        check(value)
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > LIMITS['payload_bytes'] or _private(encoded):
            raise ValueError()
        return digest(value)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError('team_trigger_invalid_payload') from None


def _weekly_at(schedule, day):
    """Choose fold 0 once; a nonexistent wall time has no occurrence that week."""
    hour, minute = map(int, schedule['time'].split(':'))
    zone = ZoneInfo(schedule['timezone'])
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
    epoch = local.timestamp()
    round_trip = datetime.fromtimestamp(epoch, zone)
    return epoch if round_trip.replace(tzinfo=None) == local.replace(tzinfo=None) else None


class TeamTriggers:
    def __init__(self, teams):
        self.teams = teams
        self.service = teams.service
        self.core = teams.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS assistant_team_triggers(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,enabled INTEGER NOT NULL,document TEXT NOT NULL,updated REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS assistant_team_trigger_events(id TEXT PRIMARY KEY,trigger_id TEXT NOT NULL,event_key TEXT NOT NULL,request_sha256 TEXT NOT NULL,document TEXT NOT NULL,created REAL NOT NULL,UNIQUE(trigger_id,event_key))')

    def invoke(self, name, args):
        prefix = 'commerce_assistant_team_trigger_'
        allowed = {'save', 'enable', 'list', 'get', 'run', 'event'}
        method_name = name.removeprefix(prefix) if isinstance(name, str) and name.startswith(prefix) else ''
        if method_name not in allowed:
            raise ValueError('unknown_tool')
        method = getattr(self, method_name)
        try:
            if not isinstance(args, dict):
                raise TypeError()
            signature(method).bind(**args)
        except (TypeError, ValueError):
            raise ValueError('team_trigger_invalid_arguments') from None
        return method(**args)

    @staticmethod
    def _get(db, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'trigger_[a-f0-9]{16}', ident):
            raise ValueError('team_trigger_not_found')
        row = db.execute('SELECT document FROM assistant_team_triggers WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('team_trigger_not_found')
        return json.loads(row[0])

    @staticmethod
    def _revision(doc, revision):
        if type(revision) is not int or revision != doc['revision']:
            raise ValueError('team_trigger_revision_changed')

    @staticmethod
    def _store(db, doc):
        db.execute('INSERT INTO assistant_team_triggers VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled,document=excluded.document,updated=excluded.updated',
                   (doc['id'], doc['revision'], int(doc['enabled']), canonical(doc), time.time()))

    def _present(self, db, doc):
        history = [json.loads(row[0]) for row in db.execute(
            'SELECT document FROM assistant_team_trigger_events WHERE trigger_id=? ORDER BY created DESC,rowid DESC LIMIT ?',
            (doc['id'], LIMITS['history']))]
        return {**doc, 'history': history, 'next_at': self._next_at(doc, max(time.time(), doc.get('last_checked_at') or 0))}

    def get(self, trigger_id):
        with self.core.db() as db:
            return self._present(db, self._get(db, trigger_id))

    def list(self, channel_id=None):
        with self.core.db() as db:
            if channel_id is not None:
                try:
                    self.teams._get(db, 'channels', channel_id)
                except ValueError:
                    raise ValueError('team_trigger_channel_not_found') from None
            docs = [json.loads(row[0]) for row in db.execute('SELECT document FROM assistant_team_triggers ORDER BY updated DESC')]
            return {'triggers': [self._present(db, doc) for doc in docs if channel_id is None or doc['channel_id'] == channel_id]}

    def save(self, trigger, expected_revision=None):
        required = {'name', 'kind', 'channel_id', 'channel_revision', 'question', 'dispatch_mode', 'max_rounds', 'schedule'}
        if not isinstance(trigger, dict) or required - set(trigger) or set(trigger) - required - {'id', 'playbook_key'}:
            raise ValueError('team_trigger_invalid_definition')
        data = dict(trigger)
        ident = data.pop('id', None)
        data['name'] = _text(data['name'], 80, 'team_trigger_invalid_name')
        data['question'] = _text(data['question'], 2000, 'team_trigger_invalid_question')
        if data['kind'] not in KINDS:
            raise ValueError('team_trigger_invalid_kind')
        if (data['dispatch_mode'] not in ('auto', 'all', 'collaborate') or type(data['max_rounds']) is not int
                or not 1 <= data['max_rounds'] <= 3 or type(data['channel_revision']) is not int or data['channel_revision'] < 1):
            raise ValueError('team_trigger_invalid_definition')
        playbook = data.get('playbook_key')
        if playbook is not None:
            if not isinstance(playbook, str):
                raise ValueError('team_trigger_invalid_playbook')
            playbook = unicodedata.normalize('NFC', playbook)
            if not re.fullmatch(r'[\w][\w.-]{0,63}', playbook):
                raise ValueError('team_trigger_invalid_playbook')
        data['playbook_key'] = playbook
        data['schedule'] = _schedule(data['kind'], data['schedule'])
        with COPILOT_LOCK, self.core.atomic(reuse=True) as db:
            old = self._get(db, ident) if ident is not None else None
            if old:
                self._revision(old, expected_revision)
            elif expected_revision is not None:
                raise ValueError('team_trigger_revision_changed')
            elif db.execute('SELECT count(*) FROM assistant_team_triggers').fetchone()[0] >= LIMITS['triggers']:
                raise ValueError('team_trigger_limit_reached')
            try:
                channel = self.teams._get(db, 'channels', data['channel_id'])
            except ValueError:
                raise ValueError('team_trigger_channel_not_found') from None
            if channel['revision'] != data['channel_revision']:
                raise ValueError('team_trigger_source_changed')
            if data['kind'] == 'after_discussion':
                try:
                    self.teams.discussion_get(data['schedule']['discussion_id'])
                except ValueError:
                    raise ValueError('team_trigger_source_not_found') from None
            doc = {**data, 'id': ident or 'trigger_' + uuid.uuid4().hex[:16],
                   'revision': old['revision'] + 1 if old else 1, 'enabled': False,
                   'created': old['created'] if old else time.time(), 'activated_at': None,
                   'pins': None, 'last_slot': None, 'last_checked_at': None,
                   'last_discussion_id': old.get('last_discussion_id') if old else None, 'error': None}
            self._store(db, doc)
            return self._present(db, doc)

    def _pins(self, db, doc, previous=None):
        try:
            channel = self.teams._get(db, 'channels', doc['channel_id'])
            profiles = [self.teams._get(db, 'profiles', ident) for ident in channel['member_ids']]
        except ValueError:
            raise ValueError('team_trigger_source_changed') from None
        channel_pin = {key: channel[key] for key in ('id', 'revision', 'sha256')}
        profile_pins = [{key: profile[key] for key in ('id', 'revision', 'sha256')} for profile in profiles]
        if channel['revision'] != doc['channel_revision'] or previous and (
                previous['channel'] != channel_pin or previous['profiles'] != profile_pins):
            raise ValueError('team_trigger_source_changed')
        if any(not profile['enabled'] for profile in profiles):
            raise ValueError('team_trigger_profile_disabled')
        playbook_pin = None
        playbook_reader = getattr(self.teams, 'playbook_for_channel', None)
        playbook_key = doc['playbook_key'] or channel.get('playbook_key')
        try:
            playbook = playbook_reader(channel, playbook_key) if callable(playbook_reader) else None
            if playbook_key and playbook is None:
                raise ValueError('team_playbook_not_found')
        except ValueError:
            raise ValueError('team_trigger_source_changed' if previous else 'team_trigger_playbook_not_found') from None
        if playbook:
            playbook_pin = {key: playbook.get(key) for key in ('key', 'sha256', 'preset_id')}
        if previous and previous.get('playbook') != playbook_pin:
            raise ValueError('team_trigger_source_changed')
        models = []
        for index, profile in enumerate(profiles):
            try:
                route = self.teams._route(profile)
                model_id = route['selected_model_id']
                if previous and model_id != previous['models'][index]['model_id']:
                    raise ValueError('team_trigger_model_unavailable')
                snapshot = self.service.models.snapshot(db, model_id=model_id)
            except ValueError:
                raise ValueError('team_trigger_model_unavailable') from None
            stable = {key: snapshot[key] for key in MODEL_FIELDS if key in snapshot}
            pin = {'profile_id': profile['id'], 'model_id': model_id, 'configuration_sha256': digest(stable),
                   'snapshot': {key: stable[key] for key in ('provider', 'profile_id', 'profile_revision', 'model', 'engine') if key in stable}}
            if previous and previous['models'][index] != pin:
                raise ValueError('team_trigger_source_changed')
            models.append(pin)
        return {'channel': channel_pin, 'profiles': profile_pins, 'models': models, 'playbook': playbook_pin}

    def enable(self, trigger_id, expected_revision, enabled):
        if type(enabled) is not bool:
            raise ValueError('team_trigger_invalid_enabled')
        with COPILOT_LOCK, self.core.atomic(reuse=True) as db:
            doc = self._get(db, trigger_id)
            self._revision(doc, expected_revision)
            if enabled:
                if db.execute('SELECT count(*) FROM assistant_team_trigger_events WHERE trigger_id=?', (trigger_id,)).fetchone()[0] >= LIMITS['events_per_trigger']:
                    raise ValueError('team_trigger_event_limit')
                doc['pins'] = self._pins(db, doc)
                doc['activated_at'] = time.time()
                doc['last_checked_at'] = None
                doc['error'] = None
            doc['enabled'] = enabled
            doc['revision'] += 1
            self._store(db, doc)
            return self._present(db, doc)

    @staticmethod
    def _key(value):
        value = _text(value, 160, 'team_trigger_invalid_event_id')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value) or _private(value):
            raise ValueError('team_trigger_invalid_event_id')
        return digest(value)

    def run(self, trigger_id, expected_revision, idempotency_key):
        return self._deliver(trigger_id, expected_revision, 'manual:' + self._key(idempotency_key), 'manual')

    def event(self, trigger_id, expected_revision, event_id, payload):
        return self._deliver(trigger_id, expected_revision, 'webhook:' + self._key(event_id),
                             'webhook', payload_sha256=_payload(payload), required_kind='webhook')

    def _busy(self, db, channel_id):
        from assistant_team import ACTIVE
        ids = [row[0] for row in db.execute(
            "SELECT id FROM assistant_team_discussions WHERE json_extract(document,'$.channel_id')=?", (channel_id,))]
        for ident in ids:
            status = self.teams.discussion_get(ident)['status']
            if status in ACTIVE | {'unknown', 'awaiting_approval', 'awaiting_input', 'awaiting_review'}:
                return True
        return False

    def _deliver(self, trigger_id, expected_revision, key, kind, *, payload_sha256=None,
                 required_kind=None, at=None, slot=None, forced_error=None):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('team_trigger_revision_changed')
        with COPILOT_LOCK, self.core.atomic(reuse=True) as db:
            doc = self._get(db, trigger_id)
            request_sha = digest({'revision': expected_revision, 'kind': kind, 'payload_sha256': payload_sha256})
            old = db.execute('SELECT request_sha256,document FROM assistant_team_trigger_events WHERE trigger_id=? AND event_key=?', (trigger_id, key)).fetchone()
            if old:
                if old[0] != request_sha:
                    raise ValueError('team_trigger_event_conflict')
                return json.loads(old[1])
            self._revision(doc, expected_revision)
            if not doc['enabled']:
                raise ValueError('team_trigger_disabled')
            if required_kind and doc['kind'] != required_kind:
                raise ValueError('team_trigger_invalid_kind')
            event_count = db.execute('SELECT count(*) FROM assistant_team_trigger_events WHERE trigger_id=?', (trigger_id,)).fetchone()[0]
            if event_count >= LIMITS['events_per_trigger']:
                raise ValueError('team_trigger_event_limit')
            now = time.time() if at is None else at
            event = {'id': 'trigger_event_' + uuid.uuid4().hex[:16], 'trigger_id': trigger_id,
                     'trigger_revision': doc['revision'], 'event_id': key, 'kind': kind,
                     'created': now, 'status': 'claiming', 'discussion_id': None,
                     'error': None, 'payload_sha256': payload_sha256}
            db.execute('INSERT INTO assistant_team_trigger_events VALUES(?,?,?,?,?,?)',
                       (event['id'], trigger_id, key, request_sha, canonical(event), now))
            if slot is not None:
                doc['last_slot'] = slot
                doc['last_checked_at'] = now
            try:
                self._pins(db, doc, doc['pins'])
                if forced_error:
                    raise ValueError(forced_error)
                if self._busy(db, doc['channel_id']):
                    raise ValueError('team_trigger_channel_busy')
            except ValueError as error:
                code = str(error) if str(error).startswith('team_trigger_') else 'team_trigger_not_ready'
                event.update(status='skipped' if code in ('team_trigger_channel_busy', 'team_trigger_slot_missed') else 'blocked', error=code)
                if code == 'team_trigger_source_changed':
                    doc.update(enabled=False, revision=doc['revision'] + 1)
            else:
                # A rejected nested discussion must not commit partially queued runs.
                db.execute('SAVEPOINT assistant_team_trigger_dispatch')
                try:
                    discussion = self.teams.discussion_start(
                        doc['channel_id'], doc['channel_revision'], doc['question'],
                        'team-trigger:' + digest({'trigger': trigger_id, 'event': key}),
                        mode=doc['dispatch_mode'], max_rounds=doc['max_rounds'], playbook_key=doc['playbook_key'])
                except Exception as error:
                    db.execute('ROLLBACK TO assistant_team_trigger_dispatch')
                    event.update(status='failed' if isinstance(error, ValueError) else 'unknown',
                                 error='team_trigger_dispatch_rejected' if isinstance(error, ValueError) else 'team_trigger_dispatch_unknown')
                else:
                    event.update(status='dispatched', discussion_id=discussion['id'], discussion=discussion)
                    doc['last_discussion_id'] = discussion['id']
                finally:
                    db.execute('RELEASE assistant_team_trigger_dispatch')
            doc['error'] = event['error']
            if event_count + 1 >= LIMITS['events_per_trigger']:
                doc.update(enabled=False, error='team_trigger_event_limit', revision=doc['revision'] + 1)
            db.execute('UPDATE assistant_team_trigger_events SET document=? WHERE id=?', (canonical(event), event['id']))
            self._store(db, doc)
            return event

    @staticmethod
    def _next_at(doc, at):
        if not doc['enabled'] or doc['kind'] in ('manual', 'webhook', 'after_discussion'):
            return None
        schedule = doc['schedule']
        floor = max(at, doc['activated_at'])
        if doc['kind'] == 'once':
            candidate = _timestamp(schedule['at'])
            return candidate if candidate >= floor and str(candidate) != doc['last_slot'] else None
        if doc['kind'] == 'interval':
            start, period = _timestamp(schedule['start_at']), schedule['interval_seconds']
            index = max(0, math.ceil((floor - start) / period))
            candidate = start + index * period
            return candidate + period if str(candidate) == doc['last_slot'] else candidate
        local_day = datetime.fromtimestamp(floor, ZoneInfo(schedule['timezone'])).date()
        for offset in range(15):
            day = local_day + timedelta(days=offset)
            if day.weekday() != schedule['weekday']:
                continue
            candidate = _weekly_at(schedule, day)
            if candidate is not None and candidate >= floor and str(candidate) != doc['last_slot']:
                return candidate
        return None

    @staticmethod
    def _due(doc, at):
        schedule = doc['schedule']
        if doc['kind'] == 'once':
            due = _timestamp(schedule['at'])
        elif doc['kind'] == 'interval':
            start, period = _timestamp(schedule['start_at']), schedule['interval_seconds']
            if at < start:
                return None
            due = start + math.floor((at - start) / period) * period
        elif doc['kind'] == 'weekly':
            day = datetime.fromtimestamp(at, ZoneInfo(schedule['timezone'])).date()
            day -= timedelta(days=(day.weekday() - schedule['weekday']) % 7)
            due = _weekly_at(schedule, day)
            if due is None:
                return None
            if due > at:
                due = _weekly_at(schedule, day - timedelta(days=7))
            if due is None:
                return None
        else:
            return None
        return due if doc['activated_at'] <= due <= at else None

    def tick(self, at=None):
        at = _clock(time.time() if at is None else at)
        events = []
        with self.core.db() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM assistant_team_triggers WHERE enabled=1')]
        for ident in ids:
            # Compute and claim under the same lock as manual runs and source edits.
            with COPILOT_LOCK, self.core.atomic(reuse=True) as db:
                doc = self._get(db, ident)
                if not doc['enabled'] or at < doc['activated_at'] or at < (doc.get('last_checked_at') or 0):
                    continue
                kind, forced_error = doc['kind'], None
                if kind in ('manual', 'webhook'):
                    continue
                if kind == 'after_discussion':
                    source = self.teams.discussion_get(doc['schedule']['discussion_id'])
                    status = source['status']
                    if status not in TERMINAL | {'unknown'}:
                        continue
                    slot = source['id']
                    if status == 'unknown':
                        forced_error = 'team_trigger_source_unknown'
                else:
                    due = self._due(doc, at)
                    if due is None:
                        continue
                    slot = str(due)
                    if at - due >= LIMITS['slot_grace_seconds']:
                        forced_error = 'team_trigger_slot_missed'
                key = 'schedule:' + slot
                if db.execute('SELECT 1 FROM assistant_team_trigger_events WHERE trigger_id=? AND event_key=?', (ident, key)).fetchone():
                    continue
                event = self._deliver(ident, doc['revision'], key, kind, at=at, slot=slot, forced_error=forced_error)
                events.append(event)
        return {'events': events}

    def recover(self):
        """Never replay ambiguous claims. Scheduling only considers the latest slot."""
        recovered = 0
        with COPILOT_LOCK, self.core.atomic(reuse=True) as db:
            rows = db.execute("SELECT id,document FROM assistant_team_trigger_events WHERE json_extract(document,'$.status')='claiming'").fetchall()
            for ident, raw in rows:
                event = json.loads(raw)
                event.update(status='unknown', error='team_trigger_recovered_unknown')
                db.execute('UPDATE assistant_team_trigger_events SET document=? WHERE id=?', (canonical(event), ident))
                recovered += 1
        return {'recovered': recovered, 'unknown': recovered}
