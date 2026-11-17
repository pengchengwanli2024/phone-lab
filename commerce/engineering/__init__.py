"""Project-owned engineering runs; models propose edits, the host owns effects."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
import re
from pathlib import Path
import threading
import time
import uuid

from . import workspace
from .workspace import digest
from .features import FeatureMap

ACTIVE = {'running'}
TERMINAL = {'completed', 'awaiting_review', 'failed', 'unknown', 'cancelled', 'interrupted'}
ROLES = {
    'plan': 'Plan a small change from the supplied source and goal. State acceptance criteria. Do not expand scope.',
    'build': 'Implement the goal using only allowed writable paths. Return full UTF-8 file contents. Preserve the trusted acceptance files. No shell, tools, credentials or permission changes.',
    'review': 'Review the goal, original source, candidate edits and actual check receipts. Look for correctness, regressions and scope violations. Tests passing alone are insufficient. Approve only the supplied candidate hash.',
}
READ_ONLY = {'commerce_engineering_' + name for name in ('status', 'get', 'artifact', 'recall', 'retrospect', 'memory_get', 'memory_search', 'feature_list', 'feature_get', 'prepare')}


def text(value, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise ValueError('engineering_invalid_text')
    return value.strip()


def definitions(schema):
    s = {'type': 'string', 'minLength': 1, 'maxLength': 200}
    strings = {'type': 'array', 'items': s, 'minItems': 1, 'maxItems': 24}
    check = schema({'kind': {'type': 'string', 'enum': ['python_unittest', 'python_compile']}, 'paths': strings}, ['kind', 'paths'])
    run = {'run_id': s}
    feature_ref = schema({'id': s, 'recipe_sha256': s, 'source_sha256': s}, ['id', 'recipe_sha256', 'source_sha256'])
    return [
        ('commerce_engineering_status', '读取工程团队、停用状态与验证边界；空闲不调用模型', schema()),
        ('commerce_engineering_configure', '启停明确工单的本机工程调度；不创建工单或扩大业务权限', schema({'enabled': {'type': 'boolean'}}, ['enabled'])),
        ('commerce_engineering_create', '明确创建私有源码快照工单；模型不执行Shell，结果为待审补丁', schema({
            'goal': {'type': 'string', 'minLength': 1, 'maxLength': 2000}, 'files': strings, 'writable_paths': strings,
            'checks': {'type': 'array', 'items': check, 'minItems': 1, 'maxItems': 4}, 'idempotency_key': s,
            'model_id': s, 'kind': {'type': 'string', 'enum': ['bugfix', 'feature']}, 'feature_ref': feature_ref,
            'max_attempts': {'type': 'integer', 'minimum': 1, 'maximum': 2},
            'max_model_calls': {'type': 'integer', 'minimum': 1, 'maximum': 5},
            'max_seconds': {'type': 'integer', 'minimum': 10, 'maximum': 900}}, ['goal', 'files', 'writable_paths', 'checks', 'idempotency_key'])),
        ('commerce_engineering_feature_list', '只读检索功能与源码/验收映射；登记不代表检查通过', schema({'query': {'type': 'string', 'maxLength': 100}})),
        ('commerce_engineering_feature_get', '只读获取功能配方与当前源码哈希；不执行检查', schema({'feature_id': s}, ['feature_id'])),
        ('commerce_engineering_prepare', '按功能生成绑定源码/配方的工单草稿；不入队、不调用模型', schema({
            'feature_id': s, 'goal': {'type': 'string', 'minLength': 1, 'maxLength': 2000}, 'idempotency_key': s,
            'kind': {'type': 'string', 'enum': ['bugfix', 'feature']}}, ['feature_id', 'goal', 'idempotency_key'])),
        *[(f'commerce_engineering_{name}', description, schema(run, ['run_id'])) for name, description in [
            ('get', '读取原工程运行与实际回执，不触发执行'), ('artifact', '读取绑定候选哈希的补丁；不回写日常源码'),
            ('cancel', '取消本工程工单后续模型与验证，保留产物'), ('resume', '明确恢复安全中断检查点；未知模型尝试禁止重发')]],
        ('commerce_engineering_recall', '读取持久工程经历与当前有效经验；不是经营事实或授权', schema()),
        ('commerce_engineering_record_adoption', '明确记录已由操作者采用且实际源码匹配的补丁；本接口不修改源码', schema({**run,
            'candidate_sha256': s, 'confirmed': {'type': 'boolean'}}, ['run_id', 'candidate_sha256', 'confirmed'])),
        ('commerce_engineering_retrospect', '按真实运行错误归类并提出检查优先的改进候选；不调用模型或新建任务', schema()),
        ('commerce_engineering_memory_propose', '保存绑定原工程回执和源码的待确认经验', schema({'content': {'type': 'string', 'minLength': 1, 'maxLength': 2000}, **run, 'idempotency_key': s}, ['content', 'run_id', 'idempotency_key'])),
        ('commerce_engineering_memory_search', '只检索当前有效且明确确认的工程经验', schema({'query': s}, ['query'])),
        ('commerce_engineering_memory_get', '读取工程经验来源、确认/撤回与失效状态', schema({'memory_id': s}, ['memory_id'])),
        ('commerce_engineering_memory_decide', '明确确认或撤回准确哈希的工程经验；不授予任何工具权限', schema({'memory_id': s, 'expected_sha256': s,
            'decision': {'type': 'string', 'enum': ['confirm', 'withdraw']}, 'confirmed': {'type': 'boolean'}}, ['memory_id', 'expected_sha256', 'decision', 'confirmed'])),
    ]


class EngineeringTeam:
    def __init__(self, service, project_root=None):
        self.service, self.core = service, service.core
        self.project = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
        self.features = FeatureMap(self.project)
        self.state = (service.state / 'engineering').resolve()
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.owner = uuid.uuid4().hex
        self._lock = threading.Lock();self._thread = None;self._closed = False
        self._probe = None
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS engineering_settings(id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL,revision INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO engineering_settings VALUES(1,0,1)')
            db.execute('CREATE TABLE IF NOT EXISTS engineering_runs(id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,request_sha TEXT NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL,created REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS engineering_memories(id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,request_sha TEXT NOT NULL,document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS engineering_daily_usage(day TEXT PRIMARY KEY,model_calls INTEGER NOT NULL)')

    def _ownership(self):
        handle = (self.state / 'worker.lock').open('a+')
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close();return None
        return handle

    @staticmethod
    def _day():
        return datetime.now(timezone(timedelta(hours=8))).date().isoformat()

    def invoke(self, name, args):
        allowed = {row[0] for row in definitions(lambda p=None, r=None: {'properties': p or {}, 'required': r or []})}
        if name not in allowed: raise ValueError('unknown_tool')
        return getattr(self, name.removeprefix('commerce_engineering_'))(**args)

    def status(self):
        with self.core.db() as db:
            enabled, revision = db.execute('SELECT enabled,revision FROM engineering_settings WHERE id=1').fetchone()
            states = dict(db.execute('SELECT status,count(*) FROM engineering_runs GROUP BY status'))
            daily = db.execute('SELECT model_calls FROM engineering_daily_usage WHERE day=?', (self._day(),)).fetchone()
        return {'enabled': bool(enabled), 'revision': revision, 'states': states,
                'roles': [{'id': k, 'instructions_sha256': digest(v)} for k, v in ROLES.items()],
                'worker_running': bool(self._thread and self._thread.is_alive()),
                'idle_model_calls': 0, 'source_writeback': False, 'external_execution_allowed': False,
                'business_executor': 'existing_assistant_team_and_extension_runtime',
                'memory_scope': 'project_engineering_only', 'review': 'model_review_plus_fixed_runtime_checks',
                'daily_model_calls': daily[0] if daily else 0, 'daily_model_call_limit': 30, 'budget_timezone': 'Asia/Shanghai',
                'token_usage': None, 'cost': None, 'sandbox': self._probe or {'available': None, 'status': 'not_probed'}}

    def configure(self, enabled):
        if type(enabled) is not bool: raise ValueError('engineering_invalid_enabled')
        with self.core.db() as db:
            db.execute('UPDATE engineering_settings SET enabled=?,revision=revision+1 WHERE id=1', (int(enabled),))
        return self.status()

    def feature_list(self, query=''):
        return self.features.listing(query)

    def feature_get(self, feature_id):
        return self.features.get(feature_id)

    def prepare(self, feature_id, goal, idempotency_key, kind='bugfix'):
        goal = text(goal);key = text(idempotency_key, 200)
        if kind not in ('bugfix', 'feature'): raise ValueError('engineering_invalid_kind')
        feature = self.feature_get(feature_id)
        order = {k: feature[k] for k in ('files', 'writable_paths', 'checks')}
        order.update(goal=goal, idempotency_key=key, kind=kind,
            feature_ref={k: feature[k] for k in ('id', 'recipe_sha256', 'source_sha256')})
        return {'feature': feature, 'work_order': order, 'queued': False, 'model_calls': 0, 'grants_execution': False}

    def _load(self, db, ident):
        text(ident, 200)
        row = db.execute('SELECT document FROM engineering_runs WHERE id=?', (ident,)).fetchone()
        if not row: raise ValueError('engineering_run_not_found')
        return json.loads(row[0])

    def _save(self, db, doc):
        previous = self._load(db, doc['id'])
        task = db.execute('SELECT status FROM tasks WHERE id=?', (doc['task_id'],)).fetchone()
        if previous['status'] == 'cancelled' or task and task[0] == 'cancelled':
            doc['cancel_requested'] = True
            if doc['status'] != 'unknown': doc['status'] = 'cancelled'
        doc['updated_at'] = time.time()
        db.execute('UPDATE engineering_runs SET status=?,document=? WHERE id=?', (doc['status'], json.dumps(doc, ensure_ascii=False, allow_nan=False), doc['id']))
        status = {'awaiting_review': 'blocked', 'unknown': 'unknown', 'interrupted': 'interrupted'}.get(doc['status'], doc['status'])
        db.execute('UPDATE tasks SET status=? WHERE id=?', (status, doc['task_id']))

    def _route(self, db, model_id):
        route = self.service.models.snapshot(db, model_id=model_id)
        if route.get('provider') not in ('compatible', 'codex'): raise ValueError('engineering_model_route_unsupported')
        return route

    def create(self, goal, files, writable_paths, checks, idempotency_key, model_id='project-default', kind='bugfix', max_attempts=2, max_model_calls=5, max_seconds=300, feature_ref=None):
        goal = text(goal);key = text(idempotency_key, 200);text(model_id, 200)
        if (type(files) is not list or type(writable_paths) is not list
                or any(not isinstance(p, str) for p in files + writable_paths)): raise ValueError('engineering_invalid_scope')
        if kind not in ('bugfix', 'feature'): raise ValueError('engineering_invalid_kind')
        for value, maximum in ((max_attempts, 2), (max_model_calls, 5), (max_seconds, 900)):
            if type(value) is not int or not 1 <= value <= maximum: raise ValueError('engineering_invalid_budget')
        if max_seconds < 10: raise ValueError('engineering_invalid_budget')
        workspace.validate_checks(checks, files, writable_paths)
        request = dict(goal=goal, files=files, writable_paths=writable_paths, checks=checks, model_id=model_id,
            kind=kind, max_attempts=max_attempts, max_model_calls=max_model_calls, max_seconds=max_seconds)
        if feature_ref is not None: request['feature_ref'] = feature_ref
        request_sha = digest(request)
        with self.core.atomic() as db:
            old = db.execute('SELECT id,request_sha FROM engineering_runs WHERE idem=?', (key,)).fetchone()
            if old:
                if old[1] != request_sha: raise ValueError('engineering_idempotency_conflict')
                return self.get(old[0])
            route = self._route(db, model_id)
            if db.execute("SELECT count(*) FROM engineering_runs WHERE status IN ('queued','running')").fetchone()[0] >= 20:
                raise ValueError('engineering_queue_full')
            contents, manifest = workspace.capture(self.project, files, writable_paths)
            feature = self.features.bind(feature_ref, request, manifest) if feature_ref is not None else None
            ident = 'eng_' + uuid.uuid4().hex
            task = self.core.invoke('commerce_task_create', {'idempotency_key': 'engineering:' + key, 'kind': 'analysis',
                'input': {'title': goal[:120], 'engineering_run_id': ident, 'source': 'engineering_team'}})
            doc = {'id': ident, 'task_id': task['id'], 'status': 'queued', 'request': request,
                'source_contents': contents, 'source_manifest': manifest, 'source_sha256': digest(manifest),
                'model_route': route, 'model_route_sha256': digest(route), 'owner': None,
                'role_contracts': {stage: digest(instructions) for stage, instructions in ROLES.items()},
                'created_at': time.time(), 'updated_at': time.time(), 'started_at': None,
                'usage': {'model_calls': 0, 'seconds': 0.0}, 'attempt': 0, 'inflight': None,
                'events': [], 'verification': {'baseline': [], 'candidate': []}, 'error': None,
                'plan': None, 'pending_edits': None, 'review': None, 'candidate_sha256': None,
                'stage_outputs': {}, 'settled_attempt': 0}
            if feature is not None: doc['feature'] = feature
            db.execute('INSERT INTO engineering_runs VALUES(?,?,?,?,?,?)', (ident, key, request_sha, 'queued', json.dumps(doc, ensure_ascii=False), doc['created_at']))
        return self.get(ident)

    def get(self, run_id):
        with self.core.db() as db: doc = self._load(db, run_id)
        public = {k: v for k, v in doc.items() if k not in ('source_contents', 'model_route', 'owner', 'pending_edits', 'stage_outputs')}
        return {**public, 'source_current': workspace.current(self.project, doc['source_manifest']),
                'model': self.service.models.public_snapshot(doc['model_route']),
                'patch_adopted': doc.get('patch_adopted', False), 'candidate_current': bool(doc.get('candidate_manifest')) and workspace.current(self.project, doc['candidate_manifest']),
                'token_usage': None, 'cost': None,
                'review_independence': 'separate_call_same_route_not_independent_certification'}

    def for_task(self, task_id):
        with self.core.db() as db:
            row = db.execute("SELECT id FROM engineering_runs WHERE json_extract(document,'$.task_id')=?", (task_id,)).fetchone()
        return self.get(row[0]) if row else None

    def artifact(self, run_id):
        run = self.get(run_id)
        if not run.get('patch_sha256'): raise ValueError('engineering_artifact_unavailable')
        p = self.state / run_id / ('patch-' + str(run['attempt']) + '.diff')
        if p.is_symlink() or not p.is_file() or digest(p.read_bytes()) != run['patch_sha256']:
            raise ValueError('engineering_artifact_changed')
        return {'run_id': run_id, 'candidate_sha256': run['candidate_sha256'], 'patch_sha256': run['patch_sha256'],
                'patch': p.read_text(), 'source_current': run['source_current'], 'adopted': run['patch_adopted']}

    def record_adoption(self, run_id, candidate_sha256, confirmed):
        if confirmed is not True: raise ValueError('engineering_explicit_confirmation_required')
        with self.core.atomic() as db:
            doc = self._load(db, run_id)
            if doc['candidate_sha256'] != candidate_sha256 or doc['status'] not in ('awaiting_review', 'completed'):
                raise ValueError('engineering_candidate_not_reviewable')
            if not doc.get('candidate_manifest') or not workspace.current(self.project, doc['candidate_manifest']):
                raise ValueError('engineering_candidate_not_applied')
            doc.update(status='completed', patch_adopted=True, adopted_at=time.time());self._save(db, doc)
        return self.get(run_id)

    def cancel(self, run_id):
        with self.core.atomic() as db:
            doc = self._load(db, run_id)
            if doc['status'] not in TERMINAL:
                doc['status'] = 'cancelled';self._save(db, doc)
        return self.get(run_id)

    def _cancelled(self, doc):
        if self._closed: return True
        with self.core.db() as db:
            current = self._load(db, doc['id'])
            enabled = db.execute('SELECT enabled FROM engineering_settings WHERE id=1').fetchone()[0]
            task = db.execute('SELECT status FROM tasks WHERE id=?', (doc['task_id'],)).fetchone()
        return (not enabled or current['status'] == 'cancelled' or not task or task[0] == 'cancelled'
                or doc['usage']['seconds'] + time.time() - doc['started_at'] >= doc['request']['max_seconds'])

    def _call(self, doc, stage, payload):
        if self._cancelled(doc): raise ValueError('engineering_cancelled_or_timed_out')
        if doc.get('role_contracts', {}).get(stage) != digest(ROLES[stage]): raise ValueError('engineering_role_contract_changed_or_unrecorded')
        checkpoint = stage + ':' + str(doc['attempt'])
        if checkpoint in doc.get('stage_outputs', {}): return doc['stage_outputs'][checkpoint]
        if self._cancelled(doc): raise ValueError('engineering_cancelled_or_timed_out')
        if doc['usage']['model_calls'] >= doc['request']['max_model_calls']: raise ValueError('engineering_model_budget_exhausted')
        with self.core.atomic() as db:
            route = self._route(db, doc['request']['model_id'])
            if digest(route) != doc['model_route_sha256']: raise ValueError('engineering_model_changed')
            day = self._day()
            daily = db.execute('SELECT model_calls FROM engineering_daily_usage WHERE day=?', (day,)).fetchone()
            if daily and daily[0] >= 30: raise ValueError('engineering_daily_model_budget_exhausted')
            db.execute('INSERT INTO engineering_daily_usage VALUES(?,1) ON CONFLICT(day) DO UPDATE SET model_calls=model_calls+1', (day,))
            doc['usage']['model_calls'] += 1
            doc['inflight'] = {'kind': 'model', 'stage': stage, 'attempt': doc['attempt']}
            self._save(db, doc)
        runtime_route = self.service.models.runtime_route(route)
        result = self._model(stage, payload, runtime_route, lambda: self._cancelled(doc))
        if self._cancelled(doc): raise ValueError('engineering_cancelled_or_timed_out')
        from .model import ModelReply
        receipt = None
        if isinstance(result, ModelReply): result, receipt = result.value, result.receipt
        doc['inflight'] = None
        doc.setdefault('stage_outputs', {})[checkpoint] = result
        doc['events'].append({'kind': 'model_receipt', 'stage': stage, 'attempt': doc['attempt'], 'response_sha256': digest(result),
                              'provider_receipt': receipt, 'verification': 'provider_response' if receipt else 'injected_test_response'})
        with self.core.db() as db: self._save(db, doc)
        return result

    @staticmethod
    def _model(stage, payload, route, cancelled):
        from .model import generate
        return generate(stage, payload, route, cancelled, ROLES[stage])

    def _checkpoint(self, doc):
        with self.core.db() as db: self._save(db, doc)

    def _process(self, doc):
        if self._cancelled(doc): raise ValueError('engineering_cancelled_or_timed_out')
        if not workspace.current(self.project, doc['source_manifest']): raise ValueError('engineering_source_changed')
        if 'feature_ref' in doc['request']: self.features.bind(doc['request']['feature_ref'], doc['request'], doc['source_manifest'])
        if self._probe is None: self._probe = workspace.sandbox_probe()
        if not self._probe['available']: raise ValueError('engineering_sandbox_unavailable')
        root = self.state / doc['id'];root.mkdir(exist_ok=True, mode=0o700)
        readonly = [p for p in doc['source_manifest'] if p not in doc['request']['writable_paths']]
        recalled = self.recall()
        memory = {'episodes': recalled['episodes'], 'lessons': [{k: m[k] for k in ('id', 'content', 'candidate_sha256')} for m in recalled['lessons']]}
        context = {'goal': doc['request']['goal'], 'source': doc['source_contents'],
            'writable_paths': doc['request']['writable_paths'], 'checks': doc['request']['checks'],
            'memory': memory, 'source_sha256': doc['source_sha256']}
        if doc.get('feature'): context['feature'] = doc['feature']
        def receipts(rows):
            return [{**r, 'output': r.get('output', '')[-2000:]} for r in rows]
        def started(pid, receipt):
            doc['inflight'].update(watchdog_pid=pid, verification_receipt=str(receipt.relative_to(self.state)));self._checkpoint(doc)
        if not doc['verification']['baseline']:
            baseline = root / ('baseline-' + uuid.uuid4().hex[:8]);baseline.mkdir()
            for name, content in doc['source_contents'].items():
                if content is not None:
                    p = baseline / name;p.parent.mkdir(parents=True, exist_ok=True);p.write_text(content)
            doc['inflight'] = {'kind': 'verification', 'stage': 'baseline'};self._checkpoint(doc)
            doc['verification']['baseline'] = workspace.checks(baseline, doc['request']['checks'], lambda: self._cancelled(doc), readonly, on_start=started)
            doc['inflight'] = None;self._checkpoint(doc)
            if doc['request']['kind'] == 'bugfix' and all(r['status'] == 'passed' for r in doc['verification']['baseline']):
                raise ValueError('engineering_bug_not_reproduced')
        context['baseline'] = receipts(doc['verification']['baseline'])
        if doc['plan'] is None:
            doc['plan'] = self._call(doc, 'plan', context)
            if type(doc['plan']) is not dict or set(doc['plan']) != {'summary', 'acceptance'} or type(doc['plan']['acceptance']) is not list:
                raise ValueError('engineering_invalid_plan')
            text(doc['plan']['summary']);self._checkpoint(doc)
            if not 1 <= len(doc['plan']['acceptance']) <= 8: raise ValueError('engineering_invalid_plan')
            for item in doc['plan']['acceptance']: text(item, 400)
        context['plan'] = doc['plan']
        cached = doc.get('stage_outputs', {}).get('build:' + str(doc['attempt']))
        if doc['pending_edits'] is None and cached and doc.get('settled_attempt', 0) < doc['attempt']:
            doc['pending_edits'] = cached['edits']
        while doc['attempt'] < doc['request']['max_attempts'] or doc['pending_edits'] is not None:
            if doc['pending_edits'] is None:
                doc['attempt'] += 1
                reply = self._call(doc, 'build', {**context, 'previous_checks': receipts(doc['verification']['candidate']), 'previous_review': doc['review']})
                if type(reply) is not dict or set(reply) != {'summary', 'edits'}: raise ValueError('engineering_invalid_builder_response')
                text(reply['summary']);doc['pending_edits'] = reply['edits'];self._checkpoint(doc)
            work = root / ('attempt-' + str(doc['attempt']) + '-' + uuid.uuid4().hex[:8])
            candidate, patch = workspace.materialize(work, doc['source_contents'], doc['pending_edits'], doc['request']['writable_paths'])
            doc['candidate_sha256'] = digest(candidate);doc['candidate_manifest'] = candidate
            doc['patch_sha256'] = digest(patch.encode())
            (root / ('patch-' + str(doc['attempt']) + '.diff')).write_text(patch)
            doc['inflight'] = {'kind': 'verification', 'stage': 'candidate'};self._checkpoint(doc)
            doc['verification']['candidate'] = workspace.checks(work, doc['request']['checks'], lambda: self._cancelled(doc), readonly, on_start=started)
            doc['inflight'] = None;self._checkpoint(doc)
            if not workspace.current(work, candidate): raise ValueError('engineering_candidate_changed_during_checks')
            if all(r['status'] == 'passed' for r in doc['verification']['candidate']):
                review = self._call(doc, 'review', {**context, 'edits': doc['pending_edits'],
                    'verification': {k: receipts(v) for k, v in doc['verification'].items()}, 'candidate_sha256': doc['candidate_sha256']})
                if (type(review) is not dict or set(review) != {'decision', 'reason'}
                        or review['decision'] not in ('approve', 'changes_requested', 'blocked')):
                    raise ValueError('engineering_invalid_review')
                text(review['reason']);doc['review'] = {**review, 'candidate_sha256': doc['candidate_sha256']}
                if review['decision'] == 'approve':
                    if not workspace.current(self.project, doc['source_manifest']): raise ValueError('engineering_source_changed')
                    doc['status'] = 'awaiting_review';self._checkpoint(doc);return
                if review['decision'] == 'blocked': raise ValueError('engineering_review_blocked')
            doc['pending_edits'] = None;doc['settled_attempt'] = doc['attempt'];self._checkpoint(doc)
        raise ValueError('engineering_attempts_exhausted')

    def run_once(self):
        if self._closed or not self._lock.acquire(blocking=False): return False
        doc = None;started = time.monotonic();ownership = None
        try:
            ownership = self._ownership()
            if ownership is None: return False
            with self.core.atomic() as db:
                if not db.execute('SELECT enabled FROM engineering_settings WHERE id=1').fetchone()[0]: return False
                if db.execute("SELECT 1 FROM engineering_runs WHERE status='running'").fetchone(): return False
                for raw, in db.execute("SELECT document FROM engineering_runs WHERE json_extract(document,'$.inflight.kind')='verification'"):
                    previous = json.loads(raw)
                    if (previous.get('inflight') or {}).get('kind') == 'verification' and not self._verification_settled(previous): return False
                row = db.execute("SELECT id FROM engineering_runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if not row: return False
                doc = self._load(db, row[0]);doc.update(status='running', owner=self.owner, started_at=time.time())
                self._save(db, doc)
            try: self._process(doc)
            except Exception as error:
                message = str(error) if isinstance(error, ValueError) and str(error).startswith('engineering_') else 'engineering_execution_failed'
                if isinstance(error, ValueError) and re.fullmatch(r'[a-z][a-z0-9_]{0,100}', str(error)):
                    doc['failure_code'] = str(error)
                if (doc.get('inflight') or {}).get('kind') == 'model' or message in ('engineering_checker_outcome_unknown', 'engineering_watchdog_stop_unknown'):
                    status = 'unknown'
                else: status = 'failed'
                if status != 'unknown' and (self._closed or self.get(doc['id'])['status'] == 'cancelled' or 'cancelled' in message): status = 'cancelled'
                doc.update(status=status, error=message)
            finally:
                doc['usage']['seconds'] += round(time.monotonic() - started, 3)
                doc['started_at'] = None
                self._checkpoint(doc)
            return True
        finally:
            if ownership is not None: ownership.close()
            self._lock.release()

    def tick(self, at=None):
        if self._closed or self._thread and self._thread.is_alive(): return
        with self.core.db() as db:
            enabled = db.execute('SELECT enabled FROM engineering_settings WHERE id=1').fetchone()[0]
            pending = db.execute("SELECT 1 FROM engineering_runs WHERE status='queued'").fetchone()
        if enabled and pending:
            self._thread = threading.Thread(target=self.run_once, name='commerce-engineering', daemon=True);self._thread.start()

    def recover(self):
        ownership = self._ownership()
        if ownership is None: return {'recovered': 0, 'active_owner': True, 'automatically_replayed': 0}
        try:
            with self.core.atomic() as db:
                ids = [r[0] for r in db.execute("SELECT id FROM engineering_runs WHERE status='running'")]
                for ident in ids:
                    doc = self._load(db, ident)
                    if doc.get('started_at'):
                        doc['usage']['seconds'] += max(0, time.time() - doc['started_at'])
                        doc['started_at'] = None
                    inflight = doc.get('inflight') or {}
                    doc['status'] = 'unknown' if inflight.get('kind') == 'model' or not self._verification_settled(doc) else 'interrupted'
                    doc['error'] = 'engineering_interrupted_no_automatic_replay';self._save(db, doc)
        finally: ownership.close()
        return {'recovered': len(ids), 'automatically_replayed': 0}

    def resume(self, run_id):
        with self.core.atomic() as db:
            doc = self._load(db, run_id)
            inflight = doc.get('inflight') or {}
            safe = doc['status'] == 'interrupted' or (doc['status'] == 'unknown' and inflight.get('kind') == 'verification' and inflight.get('watchdog_pid'))
            if not safe or inflight.get('kind') == 'model' or not self._verification_settled(doc):
                raise ValueError('engineering_cannot_resume_unknown_or_terminal')
            if not workspace.current(self.project, doc['source_manifest']): raise ValueError('engineering_source_changed')
            if doc['usage']['seconds'] >= doc['request']['max_seconds']: raise ValueError('engineering_time_budget_exhausted')
            doc.update(status='queued', inflight=None, error=None);self._save(db, doc)
        return self.get(run_id)

    @staticmethod
    def _owner_alive(pid):
        if type(pid) is not int or pid <= 1: return False
        try: os.kill(pid, 0);return True
        except ProcessLookupError: return False
        except PermissionError: return True

    def _verification_settled(self, doc):
        inflight = doc.get('inflight') or {}
        if inflight.get('kind') != 'verification': return True
        name = inflight.get('verification_receipt')
        # No watcher has been armed: this is a safe pre-launch checkpoint.
        if not name: return not inflight.get('watchdog_pid')
        p = self.state / name
        if p.is_symlink() or not p.resolve().is_relative_to(self.state): return False
        try: receipt = json.loads(p.read_text())
        except (OSError, ValueError): return False
        if receipt.get('state') == 'finished': return True
        pid = receipt.get('checker_pid')
        return type(pid) is int and not self._owner_alive(pid) and not self._owner_alive(receipt.get('watchdog_pid'))

    def stop(self):
        self._closed = True
        if self._thread: self._thread.join(timeout=3)

    def recall(self):
        with self.core.db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM engineering_runs WHERE status NOT IN ('queued','running') ORDER BY created DESC LIMIT 5")]
        episodes = []
        for ident in ids:
            run = self.get(ident)
            episodes.append({k: run[k] for k in ('status', 'source_sha256', 'candidate_sha256', 'error', 'source_current')})
            episodes[-1].update(run_id=ident, goal=run['request']['goal'], kind='observed_run_not_instruction')
        return {'episodes': episodes, 'lessons': self.memory_search('')['items'], 'scope': 'project_engineering', 'grants_execution': False}

    def memory_propose(self, content, run_id, idempotency_key):
        content = text(content);key = text(idempotency_key, 200);run = self.get(run_id)
        if run['status'] not in TERMINAL: raise ValueError('engineering_memory_evidence_not_settled')
        body = {'content': content, 'run_id': run_id};sha = digest(body)
        with self.core.atomic() as db:
            old = db.execute('SELECT id,request_sha FROM engineering_memories WHERE idem=?', (key,)).fetchone()
            if old:
                if old[1] != sha: raise ValueError('engineering_memory_idempotency_conflict')
                return self.memory_get(old[0])
            ident = 'engmem_' + uuid.uuid4().hex
            doc = {**body, 'id': ident, 'status': 'proposed', 'revision': 1,
                'source_manifest': run['candidate_manifest'] if run['patch_adopted'] else run['source_manifest'],
                'candidate_sha256': run['candidate_sha256'], 'created_at': time.time()}
            db.execute('INSERT INTO engineering_memories VALUES(?,?,?,?)', (ident, key, sha, json.dumps(doc, ensure_ascii=False)))
        return self.memory_get(ident)

    def memory_get(self, memory_id):
        text(memory_id, 200)
        with self.core.db() as db: row = db.execute('SELECT document FROM engineering_memories WHERE id=?', (memory_id,)).fetchone()
        if not row: raise ValueError('engineering_memory_not_found')
        doc = json.loads(row[0]);effective = doc['status']
        if effective != 'withdrawn' and not workspace.current(self.project, doc['source_manifest']): effective = 'stale'
        return {**doc, 'sha256': digest(doc), 'effective_status': effective, 'grants_execution': False,
                'verification': 'operator_confirmed_experience_not_independent_fact'}

    def memory_decide(self, memory_id, expected_sha256, decision, confirmed):
        if confirmed is not True or decision not in ('confirm', 'withdraw'): raise ValueError('engineering_explicit_confirmation_required')
        with self.core.atomic() as db:
            current = self.memory_get(memory_id)
            if current['sha256'] != expected_sha256: raise ValueError('engineering_memory_changed')
            if decision == 'confirm' and current['effective_status'] != 'proposed': raise ValueError('engineering_memory_not_confirmable')
            doc = json.loads(db.execute('SELECT document FROM engineering_memories WHERE id=?', (memory_id,)).fetchone()[0])
            doc['status'] = 'confirmed' if decision == 'confirm' else 'withdrawn';doc['revision'] += 1
            db.execute('UPDATE engineering_memories SET document=? WHERE id=?', (json.dumps(doc, ensure_ascii=False), memory_id))
        return self.memory_get(memory_id)

    def memory_search(self, query):
        if not isinstance(query, str) or len(query) > 200: raise ValueError('engineering_invalid_query')
        with self.core.db() as db: ids = [r[0] for r in db.execute('SELECT id FROM engineering_memories ORDER BY rowid DESC LIMIT 500')]
        items = [self.memory_get(i) for i in ids]
        selected = [m for m in items if m['effective_status'] == 'confirmed' and query.casefold() in m['content'].casefold()]
        return {'items': selected[:8], 'truncated': len(ids) >= 500 or len(selected) > 8, 'scope': 'project_engineering_only'}

    def retrospect(self):
        with self.core.db() as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT document FROM engineering_runs ORDER BY created DESC LIMIT 100')]
        failures = Counter(r['error'] for r in rows if r.get('error'))
        return {'run_count': len(rows), 'failure_counts': dict(failures),
                'suggestions': [{'evidence_error': error, 'count': count,
                    'priority': 'deterministic_check_or_api_before_skill_or_new_role', 'status': 'candidate'} for error, count in failures.most_common(5)],
                'automatically_applied': False, 'new_tasks_created': 0, 'model_calls': 0}
