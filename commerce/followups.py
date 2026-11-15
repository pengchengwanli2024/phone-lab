"""One-shot durable checks of existing local records. No model, network or execution."""
from datetime import datetime, timezone
import hashlib
from itertools import chain
import math
import re
import sqlite3
import time
import uuid

from agent_runtime.policy import canonical
from attention import item, object_json, text
from intelligence import SOURCES
from followup_groups import ReceiptGroups

KINDS = ('attention', 'task_result', 'public_source')
STATES = ('scheduled', 'checked', 'cancelled', 'acknowledged')
COLUMNS = 'id,idem,request,kind,ref,demo,revision,state,due,created,updated,target,receipt'


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def due_time(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('invalid_followup_time')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        at = parsed.timestamp()
        if not math.isfinite(at) or at <= time.time():
            raise ValueError()
        return at
    except (ValueError, OverflowError):
        raise ValueError('invalid_followup_time') from None


def definitions(schema, string):
    ident = {'followup_id': string}
    revision = {**ident, 'expected_revision': {'type': 'integer', 'minimum': 1}}
    return [
        ('commerce_followup_targets', '读取可预约的本机事项、任务与固定公开来源；不检查远端或触发模型', schema({'demo': {'type': 'boolean'}})),
        ('commerce_followup_create', '显式预约一次只读复查；绑定已展示版本，不执行原任务', schema({'target': {'type': 'object'}, 'due_at': string, 'idempotency_key': string}, ['target', 'due_at', 'idempotency_key'])),
        ('commerce_followup_list', '分页读取本机复查预约与检查回执', schema({'demo': {'type': 'boolean'}, 'state': {'type': 'string', 'enum': ['all', *STATES]}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'cursor': string})),
        ('commerce_followup_get', '读取同一复查及当前可用的原工作入口，不恢复或执行原任务', schema(ident, ['followup_id'])),
        ('commerce_followup_reschedule', '按当前修订改期尚未检查的预约；不会更换目标或执行原任务', schema({**revision, 'due_at': string}, [*revision, 'due_at'])),
        ('commerce_followup_cancel', '取消本次复查预约，不取消或修改原任务', schema(revision, list(revision))),
        ('commerce_followup_ack', '标记已查看复查回执；可按已展示的合并组哈希确认，不表示原业务已处理', schema({**revision,'group_sha256':string}, list(revision))),
    ]


class Followups:
    def __init__(self, service):
        self.service, self.core = service, service.core
        self.groups = ReceiptGroups()
        with self.core.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS followups(
                id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,request TEXT NOT NULL,
                kind TEXT NOT NULL,ref TEXT NOT NULL,demo INTEGER NOT NULL,revision INTEGER NOT NULL,
                state TEXT NOT NULL,due REAL NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
                target TEXT NOT NULL,receipt TEXT)''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS followups_pending_target ON followups(kind,ref) WHERE state='scheduled'")
            db.execute('CREATE INDEX IF NOT EXISTS followups_due ON followups(state,due)')
            db.execute('''CREATE TABLE IF NOT EXISTS followup_checks(
                followup_id TEXT NOT NULL,revision INTEGER NOT NULL,checked_at REAL NOT NULL,
                receipt TEXT NOT NULL,PRIMARY KEY(followup_id,revision))''')

    def invoke(self, name, args):
        methods = {'targets': self.targets, 'create': self.create, 'list': self.listing, 'get': self.get,
                   'reschedule': self.reschedule, 'cancel': self.cancel, 'ack': self.ack}
        return methods[name.removeprefix('commerce_followup_')](**args)

    @staticmethod
    def _load(db, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'followup_[a-f0-9]{32}', ident):
            raise ValueError('invalid_followup_id')
        row = db.execute('SELECT ' + COLUMNS + ' FROM followups WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('followup_not_found')
        return dict(zip(COLUMNS.split(','), row))

    @staticmethod
    def _thread(db, ident):
        row = db.execute('SELECT revision,context_sha FROM copilot_threads WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('followup_source_unavailable')
        return {'thread_id': ident, 'thread_revision': row[0], 'context_sha256': row[1]}

    def _capture(self, db, kind, ref, *, attention_item=None):
        if kind not in KINDS or not isinstance(ref, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,160}', ref):
            raise ValueError('invalid_followup_target')
        action, binding, example = None, {}, False
        if kind == 'attention':
            value = attention_item if attention_item is not None else self.service.attention.get(ref)['item']
            if value['source'] == 'followup':
                raise ValueError('invalid_followup_target')
            label, example, action = value['title'], value['demo'], value['action']
            if value.get('thread_id'):
                binding = self._thread(db, value['thread_id'])
            baseline = {'item_id': value['id']}
        elif kind == 'task_result':
            row = db.execute('SELECT payload,status FROM tasks WHERE id=?', (ref,)).fetchone()
            if not row:
                raise ValueError('followup_source_unavailable')
            payload = object_json(row[0]); data = payload.get('input', {})
            if not isinstance(data, dict):
                raise ValueError('followup_source_unavailable')
            label, example = data.get('title') or '共享任务', data.get('demo') is True
            binding = {'task_id': ref, 'payload_sha256': sha(payload)}
            action = {'type': 'tasks', 'id': ref}
            research = db.execute('SELECT document FROM market_research_jobs WHERE task_id=?', (ref,)).fetchone()
            if research:
                job = object_json(research[0]); scope = job['_context']
                if not isinstance(scope, dict):raise ValueError('followup_source_unavailable')
                current = self._thread(db, job['thread_id'])
                origin = db.execute('''SELECT t.revision,t.context_sha FROM copilot_turns t
                    JOIN market_research_runs m ON m.run_id=t.run_id WHERE m.task_id=? ORDER BY t.rowid DESC LIMIT 1''', (ref,)).fetchone()
                if not origin or tuple(origin) != (current['thread_revision'], current['context_sha256']):
                    raise ValueError('followup_source_changed')
                binding.update(current); example = scope.get('demo') is True
                action = {'type': 'research', 'id': ref}
            elif 'demo' not in data and data.get('organization_case'):
                case = db.execute('SELECT scope FROM org_cases WHERE id=?', (data['organization_case'],)).fetchone()
                if not case:
                    raise ValueError('followup_source_unavailable')
                example = object_json(case[0]).get('synthetic') is True
            if research:
                receipt_available = isinstance(job.get('report'), dict) and bool(job['report'])
            else:
                execution = db.execute('SELECT finished,result FROM task_runs WHERE task_id=?', (ref,)).fetchone()
                receipt_available = bool(execution and execution[0] is not None and execution[1] and object_json(execution[1]))
            baseline = {'status': row[1], 'receipt_available': receipt_available}
        else:
            if ref not in SOURCES:
                raise ValueError('invalid_followup_target')
            label = SOURCES[ref]['name']
            binding = {'source_id': ref, 'url_sha256': sha(SOURCES[ref]['url'])}
            row = db.execute('SELECT state FROM intel_sources WHERE id=?', (ref,)).fetchone()
            state = object_json(row[0]) if row else {}
            success, digest = state.get('last_success'), state.get('payload_sha256')
            if success is not None and (type(success) not in (int, float) or not math.isfinite(success)):
                raise ValueError('followup_source_unavailable')
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
                raise ValueError('followup_source_unavailable')
            baseline = {'last_success': success, 'payload_sha256': digest}
        target = {'kind': kind, 'ref': ref, 'label': text(label, 120), 'demo': example,
                  'binding': binding, 'baseline': baseline, 'action': action}
        target['version_sha256'] = sha(target)
        return target

    def targets(self, demo=False):
        if type(demo) is not bool:
            raise ValueError('invalid_demo')
        result, errors, task_count, truncated = [], set(), 0, False
        with self.core.db() as db:
            if not db.in_transaction:db.execute('BEGIN')
            attention, issues = self.service.attention._collect(demo)
            errors.update(issues)
            refs = chain(
                (('attention', value['id'], value) for value in attention),
                (('public_source', key, None) for key in SOURCES if not demo),
                (('task_result', row[0], None) for row in db.execute("SELECT id FROM tasks WHERE status NOT IN ('completed','cancelled') ORDER BY rowid DESC")),
            )
            for kind, ref, snapshot in refs:
                try:
                    target = self._capture(db, kind, ref, attention_item=snapshot)
                    if target['demo'] != demo:continue
                    if kind == 'task_result':
                        if task_count == 100:
                            truncated = True
                            break
                        task_count += 1
                    result.append({'label': target['label'], 'target': {k: target[k] for k in ('kind', 'ref', 'version_sha256')}})
                except (ValueError, TypeError, KeyError, sqlite3.Error) as error:
                    if str(error) not in ('attention_item_changed', 'followup_source_changed'):errors.add(kind)
        return {'targets': result, 'complete': not errors and not truncated, 'source_errors': sorted(errors), 'truncated': truncated}

    def create(self, target, due_at, idempotency_key):
        if not isinstance(target, dict) or set(target) != {'kind', 'ref', 'version_sha256'}:
            raise ValueError('invalid_followup_target')
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 160:
            raise ValueError('invalid_idempotency_key')
        request = canonical({'target': target, 'due_at': due_at})
        with self.core.atomic() as db:
            old = db.execute('SELECT id,request FROM followups WHERE idem=?', (idempotency_key,)).fetchone()
            if old:
                if old[1] != request:raise ValueError('idempotency_conflict')
                ident = old[0]
            else:
                at = due_time(due_at)
                frozen = self._capture(db, target['kind'], target['ref'])
                if frozen['version_sha256'] != target['version_sha256']:raise ValueError('followup_source_changed')
                if db.execute("SELECT 1 FROM followups WHERE state='scheduled' AND kind=? AND ref=?", (target['kind'], target['ref'])).fetchone():
                    raise ValueError('followup_already_scheduled')
                if db.execute("SELECT count(*) FROM followups WHERE state='scheduled'").fetchone()[0] >= 100:
                    raise ValueError('followup_queue_full')
                ident = 'followup_' + uuid.uuid4().hex
                db.execute('INSERT INTO followups VALUES (?,?,?,?,?,?,1,?,?,?,?,?,NULL)',
                    (ident, idempotency_key, request, target['kind'], target['ref'], int(frozen['demo']), 'scheduled', at, time.time(), time.time(), canonical(frozen)))
        return self.get(ident)

    def _scope_current(self, db, target):
        binding = target['binding']
        if not isinstance(binding, dict):raise ValueError('followup_source_unavailable')
        if binding.get('thread_id') and self._thread(db, binding['thread_id']) != {k:binding[k] for k in ('thread_id','thread_revision','context_sha256')}:
            return False
        if binding.get('task_id'):
            row = db.execute('SELECT payload FROM tasks WHERE id=?', (binding['task_id'],)).fetchone()
            if not row or sha(object_json(row[0])) != binding['payload_sha256']:return False
        if binding.get('source_id'):
            source=SOURCES.get(binding['source_id'])
            if not source or sha(source['url'])!=binding.get('url_sha256'):return False
        return True

    def _public(self, db, row, groups=None):
        target = object_json(row['target']); receipt = object_json(row['receipt']) if row['receipt'] else None
        try:current = self._scope_current(db, target)
        except (ValueError, KeyError, TypeError):current = False
        action = target['action'] if current and (not receipt or receipt['condition'] not in ('unavailable','scope_changed')) else None
        group=None
        if row['state']=='checked':
            groups=self.groups.collect(db,row['kind'],row['ref'],row['demo']) if groups is None else groups
            group=self.groups.public(groups[self.groups.key(row)])
        return {'id': row['id'], 'kind': row['kind'], 'ref': row['ref'], 'label': target['label'], 'demo': bool(row['demo']),
                'revision': row['revision'], 'state': row['state'], 'due_at': iso(row['due']),
                'receipt': receipt, 'receipt_group':group, 'scope_current': current, 'current_action': action}

    def get(self, followup_id):
        with self.core.db() as db:
            if not db.in_transaction:db.execute('BEGIN')
            return self._public(db, self._load(db, followup_id))

    def listing(self, demo=False, state='all', limit=30, cursor=None):
        if type(demo) is not bool or state not in ('all', *STATES) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('invalid_followup_query')
        if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch('followup_[a-f0-9]{32}', cursor)):
            raise ValueError('invalid_followup_cursor')
        with self.core.db() as db:
            if not db.in_transaction:db.execute('BEGIN')
            sql = 'SELECT ' + COLUMNS + ' FROM followups WHERE demo=?'; args = [int(demo)]
            if state != 'all':sql += ' AND state=?'; args.append(state)
            if cursor:sql += ' AND id>?'; args.append(cursor)
            rows = db.execute(sql + ' ORDER BY id LIMIT ?', [*args, limit+1]).fetchall()
            groups=self.groups.collect(db,demo=int(demo))
            items = [self._public(db, dict(zip(COLUMNS.split(','), row)),groups) for row in rows[:limit]]
        more = len(rows) > limit
        return {'items': items, 'has_more': more, 'next_cursor': items[-1]['id'] if more else None}

    @staticmethod
    def _revision(row, expected):
        if type(expected) is not int or expected != row['revision']:
            raise ValueError('followup_revision_conflict')

    def _mutate(self, ident, expected, state, due=None):
        with self.core.atomic() as db:
            row = self._load(db, ident); self._revision(row, expected)
            if row['state'] != ('checked' if state == 'acknowledged' else 'scheduled'):
                raise ValueError('followup_state_conflict')
            db.execute('UPDATE followups SET state=?,due=?,revision=revision+1,updated=? WHERE id=?',
                       (state, due if due is not None else row['due'], time.time(), ident))
        return self.get(ident)

    def reschedule(self, followup_id, expected_revision, due_at):
        return self._mutate(followup_id, expected_revision, 'scheduled', due_time(due_at))

    def cancel(self, followup_id, expected_revision):
        return self._mutate(followup_id, expected_revision, 'cancelled')

    def ack(self, followup_id, expected_revision, group_sha256=None):
        if group_sha256 is None:return self._mutate(followup_id, expected_revision, 'acknowledged')
        if not isinstance(group_sha256,str) or not re.fullmatch('[a-f0-9]{64}',group_sha256):raise ValueError('followup_group_changed')
        with self.core.atomic() as db:
            row=self._load(db,followup_id);self._revision(row,expected_revision)
            if row['state']!='checked':raise ValueError('followup_state_conflict')
            group=self.groups.collect(db,row['kind'],row['ref'],row['demo'])[self.groups.key(row)]
            if self.groups.public(group)['sha256']!=group_sha256:raise ValueError('followup_group_changed')
            db.executemany("UPDATE followups SET state='acknowledged',revision=revision+1,updated=? WHERE id=?",[(time.time(),member['id'])for member in group])
        return self.get(followup_id)

    def _evaluate(self, db, frozen):
        if not self._scope_current(db, frozen):return 'scope_changed', {}, None
        try:current = self._capture(db, frozen['kind'], frozen['ref'])
        except ValueError as error:
            if str(error) == 'attention_item_changed':return 'changed', {}, frozen['action']
            raise
        if current['binding'] != frozen['binding']:return 'scope_changed', {}, None
        observed = current['baseline']
        if frozen['kind'] == 'task_result':
            state = observed['status']
            condition = 'outcome_unknown' if state == 'unknown' else ('ready' if observed['receipt_available'] else 'needs_attention') if state in ('completed','succeeded','success','partial') else 'needs_attention' if state in ('failed','interrupted','cancelled') else 'unchanged'
        elif frozen['kind'] == 'public_source':
            success, previous = observed['last_success'], frozen['baseline']['last_success']
            if success is not None and (observed['payload_sha256'] is None or previous is not None and success < previous):
                condition = 'needs_attention'
            else:condition = 'ready' if success is not None and observed != frozen['baseline'] else 'unchanged'
        else:condition = 'unchanged'
        return condition, observed, current['action']

    def tick(self, at=None, limit=8):
        at = time.time() if at is None else at
        count = 0
        with self.core.atomic() as db:
            rows = db.execute('SELECT ' + COLUMNS + " FROM followups WHERE state='scheduled' AND due<=? ORDER BY due,id LIMIT ?", (at, limit)).fetchall()
            for raw in rows:
                row = dict(zip(COLUMNS.split(','), raw))
                try:condition, observed, action = self._evaluate(db, object_json(row['target']))
                except (ValueError, KeyError, TypeError, sqlite3.Error):condition, observed, action = 'unavailable', {}, None
                receipt = {'checked_at': iso(at), 'condition': condition, 'observed': observed, 'action': action,
                           'business_verified': False, 'original_work_executed': False}
                encoded = canonical(receipt)
                db.execute('INSERT INTO followup_checks VALUES (?,?,?,?)', (row['id'], row['revision'], at, encoded))
                db.execute("UPDATE followups SET state='checked',receipt=?,revision=revision+1,updated=? WHERE id=?", (encoded, at, row['id']))
                count += 1
        return count

    def attention_items(self, db, demo):
        result = []
        for members in self.groups.collect(db,demo=None if demo is None else int(demo)).values():
            row=members[-1];group=self.groups.public(members);target = object_json(row['target']); receipt = object_json(row['receipt'])
            condition = receipt['condition']
            detail = {'ready':'原任务已有结果或来源已有新成功快照，请核对原工作。','unchanged':'本次检查未发现预期变化，可查看回执后重新预约。',
                'changed':'原事项已有变化或已处理，请核对当前记录。','scope_changed':'原工作范围已变化，旧入口已停用。',
                'outcome_unknown':'原任务结果仍未确认，本次检查没有重发执行。','needs_attention':'原记录或回执需要人工核对，本次检查没有重试。',
                'unavailable':'本机来源未能读取，请核对原记录。'}[condition]
            if group['count']>1:detail='已合并'+str(group['count'])+'次复查，以下为最新结果。'+detail
            result.append(item('followup', row['id'], 'receipt', [row['revision'],group['sha256']], 'unknown' if condition in ('outcome_unknown','unavailable') else 'input',
                '复查：' + target['label'], detail, {'type':'followup','id':row['id']}, status='checked', demo=bool(row['demo']),followup_count=group['count']))
        return result
