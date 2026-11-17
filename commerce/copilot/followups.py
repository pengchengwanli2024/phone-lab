"""Explicit, durable conversation follow-ups; never retry a prior model request."""
import json
import re
import time
import uuid
from agent_runtime.policy import canonical
from .page_context import PAGE_CONTEXT_SCHEMA, validate_page_context, read_page

ACTIVE = ('queued', 'running', 'cancel_requested')
REPLYABLE = ('completed', 'awaiting_input', 'awaiting_review')
WAITING = ('queued', 'held', 'waiting')
MAX_QUEUE = 8
MAX_STEER = 4


def definitions(schema, string):
    thread = {'thread_id': string}
    binding = {**thread, 'context_sha256': string}
    revision = {'type': 'integer', 'minimum': 0}
    return [
        ('commerce_copilot_followup_list', '读取本会话排队消息与补充接收回执，不发送模型', schema(thread, ['thread_id'])),
        ('commerce_copilot_followup_add', '明确排队下一轮问题或补充当前分析；不重发旧请求', schema({
            **binding, 'after_run_id': string, 'message': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
            'idempotency_key': string, 'mode': {'type': 'string', 'enum': ['queue', 'steer']},
            'expected_model_sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
            'capability_ids': {'type':'array','maxItems':6,'uniqueItems':True,'items':string},
            'expected_capability_sha256': {'type':'string','pattern':'^[a-f0-9]{64}$'},
            'page_context': PAGE_CONTEXT_SCHEMA,
            'material_ids': {'type': 'array', 'maxItems': 4, 'uniqueItems': True, 'items': string}},
            ['thread_id', 'context_sha256', 'after_run_id', 'message', 'idempotency_key'])),
        ('commerce_copilot_followup_change', '按队列版本编辑、排序、撤回或显式转入下一轮', schema({
            **thread, 'item_id': string, 'expected_revision': revision,
            'operation': {'type': 'string', 'enum': ['edit', 'move_up', 'move_down', 'cancel', 'queue']},
            'message': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
            ['thread_id', 'item_id', 'expected_revision', 'operation'])),
        ('commerce_copilot_followup_resume', '明确继续已暂停的后续队列；不会重发失败或未知的原问题',
         schema({**binding, 'expected_revision': revision}, ['thread_id', 'context_sha256', 'expected_revision'])),
    ]


class CopilotFollowups:
    def __init__(self, copilot):
        from . import LOCK
        self.chat, self.core, self.service, self.lock = copilot, copilot.core, copilot.service, LOCK
        with self.core.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS copilot_followups(
                id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,idem TEXT NOT NULL,request TEXT NOT NULL,
                mode TEXT NOT NULL,message TEXT NOT NULL,context_sha TEXT NOT NULL,context_revision INTEGER NOT NULL,
                model_sha TEXT NOT NULL,page_context TEXT,material_ids TEXT NOT NULL,anchor_run TEXT NOT NULL,
                status TEXT NOT NULL,position INTEGER NOT NULL,run_id TEXT,reason TEXT,created REAL NOT NULL,updated REAL NOT NULL,
                UNIQUE(thread_id,idem))''')
            db.execute('CREATE INDEX IF NOT EXISTS copilot_followup_order ON copilot_followups(thread_id,position)')
            if 'capability_selection' not in [r[1] for r in db.execute('PRAGMA table_info(copilot_followups)')]:
                db.execute('ALTER TABLE copilot_followups ADD COLUMN capability_selection TEXT')
            db.execute('CREATE TABLE IF NOT EXISTS copilot_followup_queues(thread_id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0,resume_run_id TEXT)')
            if 'resume_run_id' not in [r[1] for r in db.execute('PRAGMA table_info(copilot_followup_queues)')]:
                db.execute('ALTER TABLE copilot_followup_queues ADD COLUMN resume_run_id TEXT')

    def invoke(self, name, args):
        from inspect import signature
        fn = {'list': self.snapshot, 'add': self.add, 'change': self.change, 'resume': self.resume}.get(name.removeprefix('commerce_copilot_followup_'))
        if not fn: raise ValueError('unknown_tool')
        try: signature(fn).bind(**args)
        except TypeError: raise ValueError('copilot_invalid_arguments') from None
        return fn(**args)

    def _revision(self, db, thread_id):
        row = db.execute('SELECT revision FROM copilot_followup_queues WHERE thread_id=?', (thread_id,)).fetchone()
        return row[0] if row else 0

    def _bump(self, db, thread_id):
        db.execute('''INSERT INTO copilot_followup_queues(thread_id,revision) VALUES (?,1)
            ON CONFLICT(thread_id) DO UPDATE SET revision=revision+1''', (thread_id,))

    def _expected(self, db, thread_id, expected_revision):
        if type(expected_revision) is not int or expected_revision != self._revision(db, thread_id):
            raise ValueError('copilot_followup_changed')

    def _latest(self, db, thread_id):
        return db.execute('''SELECT r.id,r.status,r.payload FROM copilot_turns t
            JOIN agent_runs r ON r.id=t.run_id WHERE t.thread_id=? ORDER BY t.rowid DESC LIMIT 1''', (thread_id,)).fetchone()

    def _can_steer(self, db, thread_id):
        latest = self._latest(db, thread_id)
        return bool(latest and latest[1] in ('queued', 'running')
            and not self.service.market_research.active_for_thread(db, thread_id)
            and not json.loads(latest[2]).get('execution_hosts')
            and json.loads(latest[2]).get('model_route',{}).get('provider') != 'host_native')

    def snapshot(self, thread_id, _db=None):
        from contextlib import nullcontext
        with (nullcontext(_db) if _db is not None else self.core.db()) as db:
            self.chat._thread(db, thread_id)
            rows = db.execute('''SELECT id,mode,message,status,reason,position,run_id,anchor_run,created,updated
                FROM copilot_followups WHERE thread_id=? ORDER BY position,created''', (thread_id,)).fetchall()
            current = [r for r in rows if r[3] in WAITING or r[3] == 'not_received']
            recent = [r for r in rows if r not in current][-16:]
            visible = sorted(current + recent, key=lambda r: (r[5], r[8]))
            items = [dict(zip(('id', 'mode', 'message', 'status', 'reason', 'position', 'run_id', 'after_run_id', 'created', 'updated'), r)) for r in visible]
            return {'revision': self._revision(db, thread_id), 'items': items,
                'paused': any(r[3] == 'held' for r in current), 'can_steer': self._can_steer(db, thread_id),
                'max_queue': MAX_QUEUE, 'max_steer': MAX_STEER}

    @staticmethod
    def _message(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError('copilot_invalid_message')
        return value.strip()

    def add(self, thread_id, message, context_sha256, after_run_id, idempotency_key,
            mode='queue', expected_model_sha256=None, page_context=None, material_ids=None,
            capability_ids=None, expected_capability_sha256=None):
        message = self._message(message); self.chat.key(idempotency_key)
        if mode not in ('queue', 'steer'): raise ValueError('copilot_invalid_arguments')
        material_ids = [] if material_ids is None else material_ids
        if not isinstance(material_ids, list) or len(material_ids) > 4 or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{32}', v) for v in material_ids) or len(set(material_ids)) != len(material_ids):
            raise ValueError('copilot_material_invalid')
        request = canonical(dict(message=message, context_sha256=context_sha256, after_run_id=after_run_id,
            mode=mode, expected_model_sha256=expected_model_sha256, page_context=page_context, material_ids=material_ids,
            capability_ids=capability_ids, expected_capability_sha256=expected_capability_sha256))
        with self.lock, self.core.atomic(reuse=True) as db:
            thread = self.chat._thread(db, thread_id)
            old = db.execute('SELECT request FROM copilot_followups WHERE thread_id=? AND idem=?', (thread_id, idempotency_key)).fetchone()
            if old:
                if old[0] != request: raise ValueError('idempotency_conflict')
                return self.snapshot(thread_id, _db=db)
            if thread['context_sha256'] != context_sha256: raise ValueError('copilot_context_changed')
            latest = self._latest(db, thread_id)
            if not latest or latest[0] != after_run_id: raise ValueError('copilot_followup_anchor_changed')
            page = validate_page_context(page_context, thread['context']) if page_context is not None else None
            selected = self.service.models.selection(db, thread_id)
            model_sha = selected['sha256']
            if expected_model_sha256 is not None and expected_model_sha256 != model_sha:
                raise ValueError('copilot_model_changed')
            if material_ids: self.chat.materials.resolve_for_send(db, thread, material_ids)
            capability_selection=self.chat.capabilities.freeze(thread['context'],capability_ids,expected_capability_sha256)
            if mode == 'steer':
                if not self._can_steer(db, thread_id): raise ValueError('copilot_steer_unavailable')
                if material_ids: raise ValueError('copilot_steer_material_requires_queue')
                original=json.loads(latest[2]).get('capability_selection')
                if capability_selection and capability_selection!=original:raise ValueError('copilot_steer_capability_requires_queue')
                count = db.execute("SELECT count(*) FROM copilot_followups WHERE anchor_run=? AND mode='steer' AND status!='cancelled'", (after_run_id,)).fetchone()[0]
                if count >= MAX_STEER: raise ValueError('copilot_followup_queue_full')
                status, reason = 'waiting', None
            else:
                count = db.execute("SELECT count(*) FROM copilot_followups WHERE thread_id=? AND mode='queue' AND status IN ('queued','held')", (thread_id,)).fetchone()[0]
                total = db.execute("SELECT count(*) FROM copilot_followups WHERE status IN ('queued','held','waiting')").fetchone()[0]
                if count >= MAX_QUEUE or total >= 128: raise ValueError('copilot_followup_queue_full')
                status = 'queued' if latest[1] in ACTIVE + REPLYABLE else 'held'
                reason = None if status == 'queued' else 'previous_run_' + latest[1]
            position = db.execute('SELECT COALESCE(max(position),0)+1 FROM copilot_followups WHERE thread_id=?', (thread_id,)).fetchone()[0]
            at = time.time()
            db.execute('''INSERT INTO copilot_followups(id,thread_id,idem,request,mode,message,context_sha,context_revision,
                model_sha,page_context,material_ids,anchor_run,status,position,run_id,reason,created,updated,capability_selection)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (uuid.uuid4().hex, thread_id, idempotency_key, request, mode, message, context_sha256, thread['revision'], model_sha,
                 canonical(page) if page is not None else None, canonical(material_ids), after_run_id, status, position, None, reason, at, at,
                 canonical(capability_selection) if capability_selection else None))
            self._bump(db, thread_id)
            return self.snapshot(thread_id, _db=db)

    def change(self, thread_id, item_id, expected_revision, operation, message=None):
        with self.lock, self.core.atomic(reuse=True) as db:
            self.chat._thread(db, thread_id); self._expected(db, thread_id, expected_revision)
            row = db.execute('SELECT mode,status,position FROM copilot_followups WHERE id=? AND thread_id=?', (item_id, thread_id)).fetchone()
            if not row: raise ValueError('copilot_followup_not_found')
            if operation not in ('edit', 'move_up', 'move_down', 'cancel', 'queue'):
                raise ValueError('copilot_invalid_arguments')
            if row[1] not in WAITING + ('not_received',): raise ValueError('copilot_followup_already_sent')
            if message is not None and operation != 'edit': raise ValueError('copilot_invalid_arguments')
            if operation == 'edit':
                if row[0] != 'queue': raise ValueError('copilot_followup_already_sent')
                db.execute('UPDATE copilot_followups SET message=?,updated=? WHERE id=?', (self._message(message), time.time(), item_id))
            elif operation == 'cancel':
                db.execute("UPDATE copilot_followups SET status='cancelled',reason=NULL,updated=? WHERE id=?", (time.time(), item_id))
            elif operation == 'queue':
                if row[0] != 'steer' or row[1] != 'not_received': raise ValueError('copilot_followup_already_sent')
                count = db.execute("SELECT count(*) FROM copilot_followups WHERE thread_id=? AND mode='queue' AND status IN ('queued','held')", (thread_id,)).fetchone()[0]
                if count >= MAX_QUEUE: raise ValueError('copilot_followup_queue_full')
                db.execute("UPDATE copilot_followups SET mode='queue',status='queued',reason=NULL,updated=? WHERE id=?", (time.time(), item_id))
            else:
                if row[0] != 'queue': raise ValueError('copilot_invalid_arguments')
                order = db.execute("SELECT id,position FROM copilot_followups WHERE thread_id=? AND mode='queue' AND status IN ('queued','held') ORDER BY position", (thread_id,)).fetchall()
                at = next(i for i, r in enumerate(order) if r[0] == item_id)
                to = max(0, min(len(order) - 1, at + (-1 if operation == 'move_up' else 1)))
                if to != at:
                    db.execute('UPDATE copilot_followups SET position=? WHERE id=?', (order[to][1], item_id))
                    db.execute('UPDATE copilot_followups SET position=? WHERE id=?', (row[2], order[to][0]))
            self._bump(db, thread_id)
            return self.snapshot(thread_id, _db=db)

    def resume(self, thread_id, expected_revision, context_sha256):
        with self.lock, self.core.atomic(reuse=True) as db:
            thread = self.chat._thread(db, thread_id); self._expected(db, thread_id, expected_revision)
            if thread['context_sha256'] != context_sha256: raise ValueError('copilot_context_changed')
            # Unknown native execution must first use the original recovery path.
            self.service.host_execution.guard_conversation(db, thread_id)
            selected = self.service.models.selection(db, thread_id)['sha256']
            rows = db.execute("SELECT id,context_sha,context_revision,model_sha,reason FROM copilot_followups WHERE thread_id=? AND status='held'", (thread_id,)).fetchall()
            for row in rows:
                if (row[1], row[2], row[3]) != (thread['context_sha256'], thread['revision'], selected): raise ValueError('copilot_followup_binding_changed')
                if not str(row[4]).startswith('previous_run_'): raise ValueError('copilot_followup_binding_changed')
            db.execute("UPDATE copilot_followups SET status='queued',reason=NULL,updated=? WHERE thread_id=? AND status='held'", (time.time(), thread_id))
            self._bump(db, thread_id)
            latest = self._latest(db, thread_id)
            if latest and latest[1] in ACTIVE: raise ValueError('copilot_active_run')
            db.execute('UPDATE copilot_followup_queues SET resume_run_id=? WHERE thread_id=?', (latest[0] if latest else None, thread_id))
            return self.snapshot(thread_id, _db=db)

    def dispatch_one(self):
        with self.lock, self.core.atomic(reuse=True) as db:
            rows = db.execute("SELECT id,thread_id FROM copilot_followups WHERE mode='queue' AND status IN ('queued','held') ORDER BY created,position LIMIT 128").fetchall()
            seen = set()
            for _, thread_id in rows:
                if thread_id in seen: continue
                seen.add(thread_id)
                row = db.execute("SELECT id,message,context_sha,context_revision,model_sha,page_context,material_ids,status,capability_selection FROM copilot_followups WHERE thread_id=? AND mode='queue' AND status IN ('queued','held') ORDER BY position LIMIT 1", (thread_id,)).fetchone()
                if row[7] == 'held': continue
                thread = self.chat._thread(db, thread_id); latest = self._latest(db, thread_id)
                if not latest or latest[1] in ACTIVE or self.service.market_research.active_for_thread(db, thread_id): continue
                reason = None
                resumed = db.execute('SELECT resume_run_id FROM copilot_followup_queues WHERE thread_id=?', (thread_id,)).fetchone()
                if latest[1] not in REPLYABLE and (not resumed or resumed[0] != latest[0]): reason = 'previous_run_' + latest[1]
                elif (thread['context_sha256'], thread['revision']) != (row[2], row[3]): reason = 'context_changed'
                elif self.service.models.selection(db, thread_id)['sha256'] != row[4]: reason = 'model_changed'
                if reason:
                    self._hold(db, thread_id, reason); continue
                page = json.loads(row[5]) if row[5] is not None else None
                if page and page.get('source_refs'):
                    data = read_page(self.service, thread['context'], page)
                    if data.get('display_changed') or data.get('source_status') in ('unavailable', 'too_large'):
                        self._hold(db, thread_id, 'page_source_changed'); continue
                db.execute('SAVEPOINT copilot_followup_dispatch')
                try:
                    selection=json.loads(row[8]) if row[8] else None
                    selected_args={'capability_ids':selection['capability_ids'],'expected_capability_sha256':selection['selection_sha256']} if selection else {}
                    sent = self.chat.send(thread_id, row[1], row[2], 'followup:' + row[0],
                        expected_model_sha256=row[4], page_context=page, material_ids=json.loads(row[6]),**selected_args)
                except ValueError as error:
                    db.execute('ROLLBACK TO copilot_followup_dispatch')
                    db.execute('RELEASE copilot_followup_dispatch')
                    code = str(error)
                    if code in ('copilot_active_run', 'agent_queue_full'): continue
                    self._hold(db, thread_id, code if re.fullmatch('[a-z_]{1,80}', code) else 'dispatch_not_confirmed'); continue
                db.execute('RELEASE copilot_followup_dispatch')
                db.execute("UPDATE copilot_followups SET status='sent',run_id=?,reason=NULL,updated=? WHERE id=?", (sent['latest_run']['id'], time.time(), row[0]))
                self._bump(db, thread_id)
                db.execute('UPDATE copilot_followup_queues SET resume_run_id=NULL WHERE thread_id=?', (thread_id,))
                return True
        return False

    def _hold(self, db, thread_id, reason):
        changed = db.execute("UPDATE copilot_followups SET status='held',reason=?,updated=? WHERE thread_id=? AND mode='queue' AND status='queued'", (reason, time.time(), thread_id))
        if changed.rowcount: self._bump(db, thread_id)

    def before_model(self, run_id, payload, turn):
        with self.lock, self.core.atomic(reuse=True) as db:
            row = db.execute('''SELECT t.thread_id,t.context_sha,t.revision,c.context_sha,c.revision
                FROM copilot_turns t JOIN copilot_threads c ON c.id=t.thread_id WHERE t.run_id=?''', (run_id,)).fetchone()
            if not row: return []
            if row[1:3] != row[3:5]: raise ValueError('agent_workspace_reply_scope_changed')
            changed = db.execute("UPDATE copilot_followups SET status='included',reason=?,updated=? WHERE anchor_run=? AND mode='steer' AND status='waiting'", ('model_step_' + str(turn), time.time(), run_id))
            if changed.rowcount: self._bump(db, row[0])
            messages = db.execute("SELECT id,message,created FROM copilot_followups WHERE anchor_run=? AND mode='steer' AND status='included' ORDER BY position", (run_id,)).fetchall()
            return [{'id': r[0], 'message': r[1], 'received_at': r[2], 'scope_sha256': row[1]} for r in messages]

    def has_pending_steer(self, run_id):
        with self.core.db() as db:
            return bool(db.execute("SELECT 1 FROM copilot_followups WHERE anchor_run=? AND mode='steer' AND status='waiting' LIMIT 1", (run_id,)).fetchone())

    def settle_run(self, db, run_id, status):
        row = db.execute('SELECT thread_id FROM copilot_turns WHERE run_id=?', (run_id,)).fetchone()
        if not row: return
        changed = db.execute("UPDATE copilot_followups SET status='not_received',reason='run_finished_before_next_step',updated=? WHERE anchor_run=? AND mode='steer' AND status='waiting'", (time.time(), run_id))
        if changed.rowcount: self._bump(db, row[0])
        if status not in REPLYABLE: self._hold(db, row[0], 'previous_run_' + status)
