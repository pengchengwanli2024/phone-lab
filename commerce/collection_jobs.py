"""Durable bounded collection queue. Only the fixed project worker is executable."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid

from collection_state import create, evolve
from collection_registry import REGISTRY
from feed_planner import plan
from evidence_capacity import EvidenceCapacity

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ('queued', 'running', 'cancelling')


def terminate(process):
    if process.poll() is not None:return
    try:os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=2)


def load(db, ident):
    row = db.execute('SELECT document,owner,heartbeat FROM collection_jobs WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError('collection_job_not_found')
    return json.loads(row[0]), row[1], row[2]


def save(db, value, owner=None, heartbeat=0):
    db.execute('UPDATE collection_jobs SET status=?,attempt=?,document=?,owner=?,heartbeat=? WHERE id=?',
               (value['status'], value['attempt'], json.dumps(value, ensure_ascii=False, allow_nan=False),
                owner, heartbeat, value['id']))


def worker_valid(db, ident, attempt, owner):
    value, current_owner, heartbeat = load(db, ident)
    return value, (value['status'] == 'running' and value['attempt'] == attempt
                   and current_owner == owner and heartbeat and time.time() - heartbeat < 8)


class CollectionJobs:
    def __init__(self, core, state, importer=None, command_builder=None):
        self.core, self.state, self.importer = core, Path(state), importer
        self.owner = uuid.uuid4().hex
        self.stop_event = threading.Event()
        self.thread = None
        self.command_builder = command_builder
        self.directory = self.state / 'collection-jobs'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS collection_jobs (id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL, document TEXT NOT NULL, owner TEXT, heartbeat REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS collection_alerts (id TEXT PRIMARY KEY, job_id TEXT, attempt INTEGER, code TEXT, status TEXT, created_at REAL, UNIQUE(job_id,attempt,code))')
        self.capacity=EvidenceCapacity(core,self.state)

    @staticmethod
    def alert(db,value):
        if value['status'] in ('failed','interrupted'):
            db.execute('INSERT OR IGNORE INTO collection_alerts VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,value['id'],value['attempt'],value.get('error') or 'collection_failed','open',time.time()))

    def acknowledge(self,alert_id):
        with self.core.db() as db:
            if not db.execute('SELECT 1 FROM collection_alerts WHERE id=?',(alert_id,)).fetchone():raise ValueError('collection_alert_not_found')
            db.execute("UPDATE collection_alerts SET status='acknowledged' WHERE id=?",(alert_id,))
        return {'status':'acknowledged','alert_id':alert_id}

    @staticmethod
    def due(db,source):
        stamps=[]
        for (document,) in db.execute('SELECT document FROM collection_jobs'):
            old=json.loads(document)
            if old['source']=='all' or source=='all' or old['source']==source:
                stamps.append(old.get('started_at',0)+90 if old.get('started_at') else 0)
        return max([0,*stamps])

    def request(self, source, idempotency_key):
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            return self.enqueue(db,source,idempotency_key,time.time())

    def enqueue(self,db,source,idempotency_key,at,trigger='manual'):
        if source not in ('all', *REGISTRY):
            raise ValueError('invalid_collection_source')
        value = create(source, idempotency_key, at)
        old = db.execute('SELECT document FROM collection_jobs WHERE idem=?', (idempotency_key,)).fetchone()
        if old:
            document = json.loads(old[0])
            if document['source'] != source:
                raise ValueError('idempotency_conflict')
            return document
        active = db.execute("SELECT source FROM collection_jobs WHERE status IN ('queued','running','cancelling')").fetchall()
        if len(active) >= 20:
            raise ValueError('collection_queue_full')
        if any(source == 'all' or other == 'all' or other == source for (other,) in active):
            raise ValueError('collection_source_already_active')
        value.update(id=uuid.uuid4().hex, progress={'processed': 0, 'total': len(REGISTRY) if source == 'all' else 1,
                     'successful': 0, 'current_source': None, 'routes_checked': 0}, sources=[], finished_at=None)
        value['not_before']=self.due(db,source)
        value.update(trigger=trigger,scheduled_at=at if trigger=='schedule' else None)
        db.execute('INSERT INTO collection_jobs VALUES (?,?,?,?,?,?,NULL,0)',
                   (value['id'], idempotency_key, source, 'queued', 1, json.dumps(value)))
        return value

    def schedule_tick(self,enabled,interval,at=None):
        at=time.time() if at is None else at
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Same transaction as manual enqueue: another timer or caller cannot
            # insert an overlapping source between planning and claiming.
            jobs=[json.loads(r[0]) for r in db.execute('SELECT document FROM collection_jobs')]
            due=plan(list(REGISTRY),jobs,at,interval,enabled)
            for source in due:
                self.enqueue(db,source,'schedule:'+source+':'+str(int(at//interval)),at,'schedule')
        return self.schedule_status(interval,at)

    def schedule_status(self,interval,at=None):
        at=time.time() if at is None else at
        with self.core.db() as db:jobs=[json.loads(r[0]) for r in db.execute('SELECT document FROM collection_jobs ORDER BY rowid')]
        sources={}
        for source in REGISTRY:
            relevant=[j for j in jobs if j['source'] in (source,'all')]
            latest=relevant[-1] if relevant else None
            successes=[j['finished_at'] for j in relevant if j['status']=='succeeded' and j.get('finished_at') and (j['source']==source or source in (j.get('result') or {}).get('completed_sources',[]))]
            started=[j['started_at'] for j in relevant if j.get('started_at') is not None]
            sources[source]={'status':latest['status'] if latest else 'not_collected','error':latest.get('error') if latest else None,
                             'job_id':latest['id'] if latest else None,'last_success':max(successes) if successes else None,
                             'last_attempt':max(started) if started else None,'next_due':max(started)+interval if started else at}
        attempts=[s['last_attempt'] for s in sources.values() if s['last_attempt'] is not None]
        successes=[s['last_success'] for s in sources.values()]
        return {'sources':sources,'last_attempt':max(attempts) if attempts else None,
                'last_success':min(successes) if all(s is not None for s in successes) else None,
                'next_attempt':min(s['next_due'] for s in sources.values()),'execution':'durable_serial_queue'}

    def get(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('collection_job_not_found')
        with self.core.db() as db:
            return load(db, job_id)[0]

    def listing(self):
        with self.core.db() as db:
            jobs = [json.loads(row[0]) for row in db.execute('SELECT document FROM collection_jobs ORDER BY rowid DESC LIMIT 50')]
            alerts=[dict(zip(('id','job_id','attempt','code','status','created_at'),row)) for row in db.execute('SELECT * FROM collection_alerts ORDER BY created_at DESC LIMIT 50')]
        return {'jobs': jobs, 'concurrency': 1, 'max_queued': 20,
                'capacity':self.capacity.status(),
                'endurance':self.endurance_status(),
                'alerts':alerts,'cooldown_seconds':90,'private_evidence_limit_bytes':200_000_000,
                'cancellation_scope': 'remaining_work_only_completed_source_snapshots_are_retained'}

    def endurance_status(self):
        try:
            parent=self.state/'crawler-endurance'
            pointer=json.loads((parent/'latest.json').read_text())['directory']
            if not re.fullmatch('[a-f0-9]{32}',pointer):raise ValueError()
            value=json.loads((parent/pointer/'status.json').read_text())
            if value.get('status')=='in_progress' and time.time()-datetime.fromisoformat(value['observed_at']).timestamp()>120:
                value.update(status='stale_observer',formal_acceptance=False)
            if value.get('elapsed_seconds',0)<86400:value['formal_acceptance']=False
            return value
        except (OSError,ValueError,KeyError):return {'status':'not_started_or_unavailable','formal_acceptance':False}

    def cancel(self, job_id):
        self.get(job_id)
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            value, owner, heartbeat = load(db, job_id)
            value = evolve(value, 'cancel', time.time())
            if value['status'] == 'cancelled':
                value['finished_at'] = value['updated_at']
            save(db, value, owner, heartbeat)
        return value

    def retry(self, job_id):
        self.get(job_id)
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            value, _, _ = load(db, job_id)
            if db.execute("SELECT 1 FROM collection_jobs WHERE status IN ('queued','running','cancelling') AND id<>?", (job_id,)).fetchone():
                raise ValueError('collection_worker_busy')
            value = evolve(value, 'retry', time.time())
            value.update(sources=[], finished_at=None,not_before=self.due(db,value['source']))
            value['progress'].update(processed=0, successful=0, current_source=None, routes_checked=0)
            save(db, value)
        return value

    def command(self, value, output):
        if self.command_builder:
            return self.command_builder(value, output)
        executable = Path(os.environ.get('COMMERCE_CRAWLER_PYTHON', str(ROOT / '.local/crawlers/venv/bin/python')))
        if not executable.is_file():
            raise ValueError('collection_runtime_unavailable')
        return [str(executable), str(ROOT / 'crawlers/job_worker.py'), '--database', self.core.path,
                '--job', value['id'], '--attempt', str(value['attempt']), '--owner', self.owner,
                '--output', str(output)]

    def work_once(self):
        with self.core.db() as db:pending=db.execute("SELECT 1 FROM collection_jobs WHERE status='queued' LIMIT 1").fetchone()
        capacity=self.capacity.maintain()['capacity'] if pending else None
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM collection_jobs WHERE status IN ('running','cancelling')").fetchone():
                return False
            row=next(((ident,) for ident,doc in db.execute("SELECT id,document FROM collection_jobs WHERE status='queued' ORDER BY rowid") if json.loads(doc).get('not_before',0)<=time.time()),None)
            if row is None:
                return False
            value, _, _ = load(db, row[0])
            value = evolve(value, 'start', time.time(), attempt=value['attempt'])
            value['started_at']=time.time()
            save(db, value, self.owner, time.time())
        attempt = value['attempt']
        folder = self.directory / value['id'] / str(attempt)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        output = folder / 'result.json'
        result, error, process = None, None, None
        try:
            if capacity and capacity['status']=='blocked':
                raise ValueError('collection_evidence_quota_reached')
            command = self.command(value, output)
            with (folder / 'worker.log').open('w') as log:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           env=os.environ.copy(), start_new_session=True)
                began = time.monotonic(); stopping = None
                while process.poll() is None:
                    with self.core.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        current, owner, _ = load(db, value['id'])
                        same = owner == self.owner and current['attempt'] == attempt
                        interrupted = self.stop_event.is_set() or time.monotonic() - began > 600
                        if same and interrupted and current['status'] in ('running','cancelling'):
                            current = evolve(current, 'interrupt', time.time(), attempt=attempt)
                            current['finished_at'] = current['updated_at']
                            save(db, current)
                            self.alert(db,current)
                        elif same:
                            db.execute('UPDATE collection_jobs SET heartbeat=? WHERE id=?', (time.time(), value['id']))
                        stop = not same or current['status'] != 'running' or interrupted
                    if stop:
                        stopping = stopping or time.monotonic()
                        if time.monotonic() - stopping > 3:
                            terminate(process)
                            break
                    time.sleep(.15)
            if output.exists():
                if output.stat().st_size > 100000:
                    raise ValueError('collection_result_too_large')
                result = json.loads(output.read_text())
            if process.returncode or not result or result.get('status') != 'succeeded':
                error = 'collection_source_check_failed'
        except Exception as failure:
            error = str(failure) if isinstance(failure, ValueError) and str(failure) in ('collection_runtime_unavailable','collection_result_too_large','collection_evidence_quota_reached') else 'collection_worker_failed'
        finally:
            if process and process.poll() is None:
                terminate(process)
        with self.core.db() as db:
            fenced, current_owner, _ = load(db, value['id'])
            may_import = current_owner == self.owner and fenced['attempt'] == attempt and fenced['status'] in ('running','cancelling')
        if may_import and self.importer and result and result.get('completed_sources'):
            try:
                result['imports'] = [self.importer(ident) for ident in result['completed_sources']]
            except Exception:
                error = 'collection_import_failed'
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current, owner, _ = load(db, value['id'])
            if owner == self.owner and current['attempt'] == attempt and current['status'] in ('running','cancelling'):
                current = evolve(current, 'finish_error' if error else 'finish_ok', time.time(), attempt=attempt, error=error)
                current['finished_at'] = current['updated_at']
                current['result'] = result or {'status':'failed'}
                save(db, current)
                self.alert(db,current)
        return True

    def start(self, recover=False):
        if self.thread and self.thread.is_alive():return
        if recover:
            with self.core.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for (ident,) in db.execute("SELECT id FROM collection_jobs WHERE status IN ('running','cancelling')").fetchall():
                    value, _, _ = load(db, ident)
                    value = evolve(value, 'interrupt', time.time(), attempt=value['attempt'])
                    value['finished_at'] = value['updated_at'];save(db, value)
                    self.alert(db,value)
        def run():
            next_capacity_check=0
            while not self.stop_event.is_set():
                try:
                    if time.monotonic()>=next_capacity_check:
                        self.capacity.maintain();next_capacity_check=time.monotonic()+60
                    self.work_once()
                except Exception:
                    # Recover only this runner's interrupted claim. Never clear a
                    # peer's owner, replay a job, or leave an exception invisible.
                    try:
                        with self.core.db() as db:
                            db.execute('BEGIN IMMEDIATE')
                            for (ident,) in db.execute("SELECT id FROM collection_jobs WHERE owner=? AND status IN ('running','cancelling')",(self.owner,)).fetchall():
                                value,_,_=load(db,ident)
                                value=evolve(value,'interrupt',time.time(),attempt=value['attempt'])
                                value['finished_at']=value['updated_at'];save(db,value);self.alert(db,value)
                    except Exception:pass
                self.stop_event.wait(.3)
        self.thread = threading.Thread(target=run, daemon=True, name='commerce-collection-worker')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=8)
