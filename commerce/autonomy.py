"""Durable bounded local work and public-feed scheduling. No agent shell/tools.

Only explicit operations are executable. Free text and source documents are
data, never executable instructions. A local receipt is not fact verification.
"""
import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone

OPERATIONS = ('report', 'intel_review', 'unit_economics', 'restock_plan')


def stamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat()


class Autonomy:
    def __init__(self, service):
        self.service = service
        self.core = service.core
        self.owner = uuid.uuid4().hex
        self.stop_event = threading.Event()
        self.thread = None
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runtime_settings (id INTEGER PRIMARY KEY, enabled INTEGER, interval INTEGER)')
            db.execute('INSERT OR IGNORE INTO runtime_settings VALUES (1,0,900)')
            db.execute('CREATE TABLE IF NOT EXISTS runtime_leases (id TEXT PRIMARY KEY, owner TEXT, expires REAL, last_attempt REAL, last_success REAL, result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS task_runs (task_id TEXT PRIMARY KEY, operation TEXT, requested REAL, started REAL, finished REAL, owner TEXT, expires REAL, result TEXT, error TEXT, attempt INTEGER)')

    def configure(self, enabled, interval_seconds='900'):
        if interval_seconds not in ('300', '900', '1800', '3600'):
            raise ValueError('invalid_interval_seconds')
        if not isinstance(enabled, bool):
            raise ValueError('invalid_enabled')
        with self.core.db() as db:
            db.execute('UPDATE runtime_settings SET enabled=?,interval=? WHERE id=1', (int(enabled), int(interval_seconds)))
        return self.status()

    def status(self):
        at = time.time()
        with self.core.db() as db:
            enabled, interval = db.execute('SELECT enabled,interval FROM runtime_settings WHERE id=1').fetchone()
            feeds = db.execute("SELECT expires,last_attempt,last_success,result FROM runtime_leases WHERE id='feeds'").fetchone()
            clock = db.execute("SELECT expires FROM runtime_leases WHERE id='clock'").fetchone()
            counts = dict(db.execute('SELECT status,count(*) FROM tasks GROUP BY status'))
            active = db.execute('SELECT count(*) FROM task_runs r JOIN tasks t ON t.id=r.task_id WHERE t.status IN (\'queued\',\'running\')').fetchone()[0]
        scheduled=self.service.collections.schedule_status(interval,at)
        return {'worker': 'running' if clock and clock[0] > at else 'stopped_or_stale',
                'public_collection': {'enabled': bool(enabled), 'interval_seconds': interval,
                    'last_attempt': stamp(scheduled['last_attempt']) if scheduled['last_attempt'] is not None else None,
                    'last_success': stamp(scheduled['last_success']) if scheduled['last_success'] is not None else None,
                    'next_attempt': stamp(max(at,scheduled['next_attempt'])) if enabled else None,
                    'result': scheduled['sources']},
                'tasks': counts, 'requested_local_work': active, 'operations': list(OPERATIONS),
                'marketplace_writes': False, 'model_executor': False, 'model_executor_scope':'scheduled_local_tasks_only',
                'conversational_model_readiness':'checked_on_explicit_request','mobile_gateway': 'not_managed',
                'availability': 'local_user_session_awake_only'}

    def request(self, task_id, operation):
        if operation not in OPERATIONS:
            raise ValueError('unsupported_local_operation')
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            task = self.core.present(row)
            self.validate_operation(task, operation)
            old = db.execute('SELECT operation FROM task_runs WHERE task_id=?', (task_id,)).fetchone()
            if old and old[0] != operation:
                raise ValueError('task_operation_conflict')
            if task['status'] == 'cancelled':
                raise ValueError('task_cancelled')
            # Repeated requests are reads, including failed/interrupted receipts.
            # Retry is explicit so a lost acknowledgement never repeats work.
            if not old:
                if task['status'] != 'queued':
                    raise ValueError('task_not_queued')
                db.execute('INSERT INTO task_runs VALUES (?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,0)', (task_id, operation, time.time()))
        return self.result(task_id)

    @staticmethod
    def validate_operation(task, operation):
        data = task['input']
        if operation == 'report':
            if task['kind'] != 'report' or type(data.get('demo', False)) is not bool:
                raise ValueError('report_task_required')
        elif operation == 'intel_review':
            evidence = data.get('evidence')
            if task['kind'] != 'analysis' or data.get('mode') != 'public_source' or not isinstance(evidence, dict):
                raise ValueError('intel_evidence_required')
            from intel_store import CONTENT_KEYS, canonical, digest
            if evidence.get('source') not in __import__('intelligence').SOURCES or evidence.get('record_sha256') != digest(canonical({key: evidence.get(key) for key in CONTENT_KEYS})):
                raise ValueError('intel_evidence_mismatch')
        elif task['kind'] != 'analysis' or not isinstance(data.get('parameters'), dict):
            raise ValueError('calculation_parameters_required')

    def result(self, task_id):
        task = self.core.invoke('commerce_task_get', {'task_id': task_id})
        with self.core.db() as db:
            row = db.execute('SELECT operation,requested,started,finished,result,error,attempt FROM task_runs WHERE task_id=?', (task_id,)).fetchone()
        return {'task': task, 'execution': None if row is None else dict(operation=row[0], requested_at=stamp(row[1]),
                started_at=stamp(row[2]) if row[2] else None, finished_at=stamp(row[3]) if row[3] else None,
                result=json.loads(row[4]) if row[4] else None, error=row[5], attempt=row[6]),
                'external_operations_executed': False}

    def retry(self, task_id):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or row[0] not in ('failed', 'interrupted'):
                raise ValueError('task_not_retryable')
            db.execute("UPDATE tasks SET status='queued' WHERE id=?", (task_id,))
            db.execute('UPDATE task_runs SET started=NULL,finished=NULL,owner=NULL,expires=NULL,result=NULL,error=NULL,requested=? WHERE task_id=?', (time.time(), task_id))
        return self.result(task_id)

    def lease(self, name, at, interval=0):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT expires,last_attempt FROM runtime_leases WHERE id=?', (name,)).fetchone()
            if row and ((row[0] or 0) > at or (row[1] or 0) + interval > at):
                return False
            db.execute('INSERT INTO runtime_leases VALUES (?,?,?,?,NULL,NULL) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires,last_attempt=excluded.last_attempt', (name, self.owner, at + 120, at))
            return True

    def tick(self, at=None, collect=True):
        at = time.time() if at is None else at
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            clock = db.execute("SELECT owner,expires FROM runtime_leases WHERE id='clock'").fetchone()
            if clock and clock[0] != self.owner and clock[1] > at:
                return
            db.execute("INSERT INTO runtime_leases VALUES ('clock',?,?,?,NULL,NULL) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires,last_attempt=excluded.last_attempt", (self.owner, at + 120, at))
            # A crash is visible, never silently reported as success or replayed.
            db.execute("UPDATE tasks SET status='interrupted' WHERE status='running' AND id IN (SELECT task_id FROM task_runs WHERE expires<?)", (at,))
            db.execute("UPDATE task_runs SET finished=?,error='worker_interrupted' WHERE expires<? AND finished IS NULL AND started IS NOT NULL", (at, at))
            enabled, interval = db.execute('SELECT enabled,interval FROM runtime_settings WHERE id=1').fetchone()
        # Local work is processed first; a slow feed must not starve results.
        for _ in range(8):
            if not self.work(at):
                break
        if collect:
            self.service.collections.schedule_tick(bool(enabled),interval,at)

    def work(self, at):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT t.id,r.operation FROM tasks t JOIN task_runs r ON t.id=r.task_id WHERE t.status='queued' ORDER BY r.requested LIMIT 1").fetchone()
            if not row:
                return False
            task_id, operation = row
            db.execute("UPDATE tasks SET status='running' WHERE id=? AND status='queued'", (task_id,))
            db.execute('UPDATE task_runs SET owner=?,expires=?,started=?,attempt=attempt+1 WHERE task_id=?', (self.owner, at + 120, at, task_id))
        try:
            task = self.core.invoke('commerce_task_get', {'task_id': task_id})
            self.validate_operation(task, operation)
            data = task['input']
            if operation == 'report':
                report_scope = {k: v for k, v in data.get('source_context', {}).items() if k in ('platform', 'store_id', 'market')}
                output = self.service.invoke('commerce_report_create', {**report_scope, 'demo': data.get('demo', False), 'idempotency_key': 'local-report:' + task_id})
            elif operation == 'intel_review':
                e = data['evidence']
                output = {'generator': 'local_evidence_template', 'verification': 'not_independently_verified',
                          'title': e.get('title'), 'source': e['source'], 'url': e.get('url'),
                          'published': e.get('published'), 'evidence_sha256': e['record_sha256'],
                          'store_impact': 'unknown', 'questions': ['销售国家是否与来源区域重叠？', '相关仓库和运输路线有哪些？', '是否有独立来源确认影响？'],
                          'evidence': e, 'recommendation': '先补齐业务关联与独立依据，再决定行动；未执行经营操作。'}
            else:
                output = self.service.invoke('commerce_' + operation, {'input': data['parameters']})
            # JSON validation also bounds errors; never save raw exception text.
            encoded = json.dumps(output, ensure_ascii=False, allow_nan=False)
            if len(encoded) > 100000:
                raise ValueError('result_too_large')
            error, status = None, 'completed'
        except Exception:
            encoded, error, status = None, 'local_operation_failed_check_input', 'failed'
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            updated = db.execute('UPDATE tasks SET status=? WHERE id=? AND status=\'running\' AND EXISTS (SELECT 1 FROM task_runs WHERE task_id=? AND owner=?)', (status, task_id, task_id, self.owner))
            if updated.rowcount:
                db.execute('UPDATE task_runs SET finished=?,expires=0,result=?,error=? WHERE task_id=? AND owner=?', (time.time(), encoded, error, task_id, self.owner))
        return True

    def start(self, recover=False):
        if self.thread and self.thread.is_alive():
            return
        if recover:
            # Caller holds the per-state server lock. Previous server work can
            # no longer be live, so recovery need not wait for its lease.
            with self.core.db() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE tasks SET status='interrupted' WHERE status='running' AND id IN (SELECT task_id FROM task_runs WHERE finished IS NULL)")
                db.execute("UPDATE task_runs SET finished=?,error='worker_interrupted',expires=0 WHERE started IS NOT NULL AND finished IS NULL", (time.time(),))
                db.execute("UPDATE runtime_leases SET expires=0 WHERE id IN ('clock','feeds')")
        def run():
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    pass  # Expiring heartbeat exposes a stuck worker.
                self.stop_event.wait(2)
        self.thread = threading.Thread(target=run, name='commerce-local-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)
        if not self.thread or not self.thread.is_alive():
            with self.core.db() as db:
                db.execute("UPDATE runtime_leases SET expires=0 WHERE id='clock' AND owner=?", (self.owner,))
