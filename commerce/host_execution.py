"""Pinned native host attempts subordinate to existing research tasks and runs.

This is an execution journal, not another task queue. A claimed request whose
outcome is unconfirmed is never handed to another worker implicitly.
"""
import hashlib
import json
import re
import secrets
import shutil
import time
import uuid
from agent_runtime.policy import canonical

HOSTS = ('dsh', 'hermes', 'codex')
LEASE_SECONDS = 45


def definitions(schema, string):
    return [('commerce_execution_hosts','读取受控宿主与模型快照；程序或worker存在不代表实际推理成功',schema())]


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def bounded_name(value, limit=160):
    return isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


class HostExecution:
    def __init__(self, service):
        self.service, self.core = service, service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS execution_hosts(id TEXT PRIMARY KEY,route TEXT NOT NULL,seen REAL NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS agent_host_attempts(
                id TEXT PRIMARY KEY,task_id TEXT NOT NULL,run_id TEXT NOT NULL,phase TEXT NOT NULL,
                generation INTEGER NOT NULL,parent_owner TEXT NOT NULL,host_id TEXT NOT NULL,
                request TEXT NOT NULL,status TEXT NOT NULL,worker TEXT,token_sha TEXT,expires REAL,
                result TEXT,receipt TEXT,finish_sha TEXT,created REAL NOT NULL,updated REAL NOT NULL,
                UNIQUE(run_id,phase))''')

    def _policy(self):
        path=self.service.state/'conversation-routing.json'
        if not path.exists():return None
        try:
            value=json.loads(path.read_text())
            if (not isinstance(value,dict) or set(value)!={'mode','enabled','priority'}
                    or value['mode']!='auto' or type(value['enabled']) is not bool
                    or not isinstance(value['priority'],list) or len(value['priority'])!=3
                    or set(value['priority'])!=set(HOSTS)):
                raise ValueError()
            return value
        except (ValueError,TypeError,OSError):raise ValueError('host_routing_invalid_configuration') from None

    @staticmethod
    def _eligible(route):
        return route.get('available') and (route['host_id']=='dsh' or route['provider']=='codex')

    def auto_profile(self):
        try:policy=self._policy()
        except ValueError:
            return {'id':'project-auto','label':'智能选择 · 配置待修复','engine':'builtin',
                    'provider':'host_auto','model':'按任务选择','revision':'invalid',
                    'enabled':True,'selectable':False,'test_status':'invalid_configuration'}
        if not policy or not policy['enabled']:return None
        with self.core.db() as db:available=any(self._eligible(r) for r in self._routes(db))
        return {'id':'project-auto','label':'智能选择','engine':'builtin','provider':'host_auto',
                'model':'按任务选择','revision':digest(policy),'enabled':True,
                'selectable':available,'test_status':'existing_route'}

    @staticmethod
    def native_snapshot(marker, route, reason):
        names={'dsh':'Harness','hermes':'Hermes','codex':'Codex'}
        return {**marker,'provider':'host_native','host_id':route['host_id'],
                'native_provider':route['provider'],'model':route['model'],
                'route_sha256':route['route_sha256'],'routing_reason':reason,
                'label':'智能选择 · '+names[route['host_id']]}

    @staticmethod
    def plan_for_payload(payload):
        if payload.get('execution_hosts'):return payload['execution_hosts']
        route=payload.get('model_route',{})
        if route.get('provider')=='host_native':
            return [{'host_id':route['host_id'],'provider':route['native_provider'],
                     'model':route['model'],'route_sha256':route['route_sha256']}]
        return None

    def guard_conversation(self, db, thread_id):
        latest=db.execute('''SELECT r.id,r.status,r.payload FROM copilot_turns t JOIN agent_runs r ON r.id=t.run_id
                            WHERE t.thread_id=? ORDER BY t.rowid DESC LIMIT 1''',(thread_id,)).fetchone()
        if latest:
            research=self.service.market_research.for_run(latest[0],db)
            # A resumed research job points at its authoritative successor run;
            # the original copilot turn deliberately retains its UNKNOWN receipt.
            current=(db.execute('SELECT id,status,payload FROM agent_runs WHERE id=?',(research['run_id'],)).fetchone()
                     if research else latest)
            cancelled=(research and research['status']=='cancelled') or (current and current[1]=='cancelled')
            unresolved=(current and db.execute("SELECT 1 FROM agent_host_attempts WHERE run_id=? AND status IN ('claimed','unknown') LIMIT 1",(current[0],)).fetchone())
            native=(current and json.loads(current[2]).get('model_route',{}).get('provider')=='host_native')
            if not cancelled and (native or unresolved) and ((research and research['status']=='unknown')
                                  or (current and current[1]=='unknown') or unresolved):
                raise ValueError('agent_provider_outcome_unknown')

    def resolve_auto(self, db, marker, thread_id, parent_id=None):
        policy=self._policy()
        if not policy or not policy['enabled'] or marker.get('profile_revision')!=digest(policy):
            raise ValueError('copilot_model_changed')
        self.guard_conversation(db,thread_id)
        if parent_id:
            parent=db.execute('SELECT payload,status FROM agent_runs WHERE id=?',(parent_id,)).fetchone()
            if parent and parent[1]=='awaiting_input':
                # A clarification continues its original model, including old
                # implicit project-default turns created before auto was enabled.
                return json.loads(parent[0])['model_route']
        routes={r['host_id']:r for r in self._routes(db) if self._eligible(r)}
        for host in policy['priority']:
            if host in routes:return self.native_snapshot(marker,routes[host],'priority_live_capability')
        raise ValueError('host_unavailable_use_workbench')

    def register(self, host_id, provider, model):
        if host_id not in HOSTS or not bounded_name(provider, 100) or not bounded_name(model):
            raise ValueError('host_invalid_route')
        route = {'host_id': host_id, 'provider': provider, 'model': model}
        with self.core.atomic() as db:
            db.execute('INSERT INTO execution_hosts VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET route=excluded.route,seen=excluded.seen',
                       (host_id, canonical(route), time.time()))
        return {**route, 'route_sha256': digest(route)}

    def listing(self):
        with self.core.db() as db:
            hosts = self._routes(db)
        return {'hosts': hosts,
                'unavailable_fallback': 'shared_workbench', 'automatic_model_substitution': False}

    def _routes(self, db):
        hosts = {json.loads(raw)['host_id']: {**json.loads(raw), 'route_sha256': digest(json.loads(raw)),
                    'available': time.time() - seen < 90}
                 for raw, seen in db.execute('SELECT route,seen FROM execution_hosts')}
        try: configured = self.service.models.default_snapshot()
        except ValueError: configured = {}
        if configured.get('provider') == 'codex':
            from agent_runtime.codex_provider import KNOWN_BINARIES
            codex_available = bool(shutil.which('codex') or any(p.is_file() for p in KNOWN_BINARIES))
            try:
                from host_native import hermes_command
                hermes_command(); hermes_available = True
            except ValueError: hermes_available = False
            for host_id, available in [('codex', codex_available), ('hermes', hermes_available)]:
                route = {'host_id': host_id, 'provider': 'codex', 'model': configured['model']}
                hosts.setdefault(host_id, {**route, 'route_sha256': digest(route), 'available': available})
        return [hosts[key] for key in sorted(hosts)]

    @staticmethod
    def validate_plan_request(hosts):
        if not isinstance(hosts, list) or not 1 <= len(hosts) <= 3:
            raise ValueError('host_invalid_plan')
        for item in hosts:
            if not isinstance(item, dict) or set(item) != {'host_id', 'expected_route_sha256'}:
                raise ValueError('host_invalid_plan')
            if item['host_id'] not in HOSTS or not isinstance(item['expected_route_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['expected_route_sha256']):
                raise ValueError('host_invalid_plan')

    def freeze(self, db, hosts):
        self.validate_plan_request(hosts)
        result = []
        for item in hosts:
            route = next((r for r in self._routes(db) if r['host_id'] == item['host_id']), None)
            if not route or not route['available']: raise ValueError('host_unavailable_use_workbench')
            if route['route_sha256'] != item['expected_route_sha256']: raise ValueError('host_route_changed')
            result.append({k: v for k, v in route.items() if k != 'available'})
        return result

    def inherited_plan(self, db, thread_id):
        context=self.service.copilot._thread(db,thread_id)['context']
        for (raw,) in db.execute('SELECT document FROM market_research_jobs ORDER BY rowid DESC LIMIT 100'):
            job = json.loads(raw)
            if job['thread_id'] == thread_id and job['status'] == 'awaiting_input' and job['_context']==context:
                return job.get('_execution_hosts')
        return None

    def guard_model_selection(self, db, thread_id, model_id):
        context=self.service.copilot._thread(db,thread_id)['context']
        for (raw,) in db.execute('SELECT document FROM market_research_jobs ORDER BY rowid DESC LIMIT 100'):
            job=json.loads(raw)
            if (job['thread_id']!=thread_id or job['status']!='awaiting_input'
                    or job['_context']!=context or not job.get('_execution_hosts')):continue
            original=json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?',(job['run_id'],)).fetchone()[0])['model_route']
            if model_id not in ('project-auto',original.get('profile_id')):
                raise ValueError('host_plan_model_conflict')
            return

    @staticmethod
    def same_model(left, right):
        fields=('provider','model','profile_id','profile_revision','host_id','native_provider','route_sha256')
        return all(left.get(k)==right.get(k) for k in fields)

    def _parent(self, db, task_id, run_id, parent_owner=None):
        row = db.execute('SELECT owner,status,expires,payload FROM agent_runs WHERE id=?', (run_id,)).fetchone()
        if (not row or row[1] != 'running' or row[2] is None or row[2] <= time.time()
                or (parent_owner is not None and row[0] != parent_owner)):
            raise ValueError('host_parent_superseded')
        payload=json.loads(row[3])
        if not task_id:
            binding=db.execute('SELECT thread_id,context_sha,revision FROM copilot_turns WHERE run_id=?',(run_id,)).fetchone()
            if not binding or payload.get('model_route',{}).get('provider')!='host_native':
                raise ValueError('host_parent_superseded')
            thread=self.service.copilot._thread(db,binding[0]);context=payload['parameters']['context']
            if thread['context']!=context or (thread['context_sha256'],thread['revision'])!=binding[1:]:
                raise ValueError('host_context_changed')
            return {'run_id':run_id,'_context':context,'_host_attempt':payload.get('_host_attempt')},row[0],payload
        job = self.service.market_research._load(db, task_id)
        if job['run_id'] != run_id or job['status'] not in ('queued','running','cancelling'):
            raise ValueError('host_parent_superseded')
        thread = self.service.copilot._thread(db, job['thread_id'])
        if thread['context'] != job['_context']: raise ValueError('host_context_changed')
        return job, row[0], payload

    def request(self, task_id, run_id, phase, payload, output_schema, instructions):
        allowed=('planning','analyzing') if task_id else ('dialogue_1','dialogue_2','dialogue_3')
        if phase not in allowed: raise ValueError('host_invalid_phase')
        content = {'payload': payload, 'output_schema': output_schema, 'instructions': instructions}
        if len(canonical(content).encode()) > 100000: raise ValueError('host_request_too_large')
        with self.core.atomic() as db:
            job, owner, run = self._parent(db, task_id, run_id, self.service.agent_runtime.owner)
            old = db.execute('SELECT * FROM agent_host_attempts WHERE run_id=? AND phase=?', (run_id, phase)).fetchone()
            if old:
                stored = json.loads(old[7])
                if any(stored[k] != v for k, v in content.items()): raise ValueError('host_request_conflict')
                return self._public(old)
            plan = self.plan_for_payload(run)
            if not plan: raise ValueError('host_plan_required')
            # A committed native receipt can outlive a crash before the domain
            # checkpoint. Reuse the same evidence and frozen route, including
            # after explicit recovery created a successor agent run.
            for prior in db.execute("SELECT * FROM agent_host_attempts WHERE task_id=? AND phase=? AND status='completed' ORDER BY generation DESC", (task_id or '', phase)) if task_id else ():
                if prior[0] in job.get('_rejected_host_attempts',[]):continue
                stored = json.loads(prior[7])
                if (all(stored[k] == v for k, v in content.items())
                        and stored.get('context_sha256') == digest(job['_context'])
                        and stored['route'] in plan):
                    return self._public(prior)
            if db.execute("SELECT 1 FROM agent_host_attempts WHERE run_id=? AND status IN ('pending','claimed','unknown')", (run_id,)).fetchone():
                raise ValueError('host_prior_step_unconfirmed')
            if task_id and job['phase'] != phase: raise ValueError('host_phase_changed')
            key,column=(task_id,'task_id') if task_id else (run_id,'run_id')
            count = db.execute('SELECT count(*) FROM agent_host_attempts WHERE '+column+'=?', (key,)).fetchone()[0]
            # A confirmed pre-admission failure consumes no model step. Explicit
            # recovery retries that pinned host; UNKNOWN still advances only
            # after the human-authorized resume creates a successor run.
            history=db.execute('SELECT phase,status,result FROM agent_host_attempts WHERE '+column+'=?',(key,)).fetchall()
            # Asking for missing human input does not finish the planning step.
            # Its clarification stays on that host; a settled plan advances to
            # analysis, while an explicitly resumed UNKNOWN advances as before.
            submitted=sum(1 for old_phase,status,result in history
                          if status in ('claimed','unknown') or status=='completed' and not (
                              old_phase=='planning' and json.loads(result or '{}').get('questions')))
            route = plan[min(submitted, len(plan) - 1)]
            request = {**content, 'route': route, 'request_id': uuid.uuid4().hex,
                       'context_sha256': digest(job['_context'])}
            ident = uuid.uuid4().hex; now = time.time()
            db.execute('INSERT INTO agent_host_attempts VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,?,?)',
                       (ident, task_id or '', run_id, phase, count + 1, owner, route['host_id'], canonical(request), 'pending', now, now))
            job['_host_attempt'] = {'id': ident, 'generation': count + 1,
                                    'request_sha256': digest(request), 'route_sha256': route['route_sha256']}
            if task_id:self.service.market_research._save(db, job)
            else:
                run['_host_attempt']=job['_host_attempt']
                db.execute('UPDATE agent_runs SET payload=? WHERE id=?',(canonical(run),run_id))
            return self._public(db.execute('SELECT * FROM agent_host_attempts WHERE id=?', (ident,)).fetchone())

    @staticmethod
    def _public(row):
        request = json.loads(row[7])
        return {'attempt_id': row[0], 'task_id': row[1] or None, 'run_id': row[2], 'phase': row[3],
                'generation': row[4], 'host_id': row[6], 'route': request['route'],
                'request_id': request['request_id'], 'request_sha256': digest(request), 'status': row[8],
                'result': json.loads(row[12]) if row[12] else None,
                'receipt': json.loads(row[13]) if row[13] else None}

    def for_task(self, task_id):
        with self.core.db() as db:
            return [self._public(row) for row in db.execute('SELECT * FROM agent_host_attempts WHERE task_id=? ORDER BY generation', (task_id,))]

    def for_run(self, run_id):
        with self.core.db() as db:
            return [self._public(row) for row in db.execute('SELECT * FROM agent_host_attempts WHERE run_id=? ORDER BY generation',(run_id,))]

    def get(self, attempt_id):
        with self.core.db() as db:
            row = db.execute('SELECT * FROM agent_host_attempts WHERE id=?', (attempt_id,)).fetchone()
        if not row: raise ValueError('host_attempt_not_found')
        return self._public(row)

    def claim(self, host_id, worker_id, attempt_id=None):
        if host_id not in HOSTS or not bounded_name(worker_id, 100): raise ValueError('host_invalid_worker')
        with self.core.atomic() as db:
            # Expired claims have unknown outcomes, even if an admission receipt was
            # lost. They are not put back into the pending set.
            db.execute("UPDATE agent_host_attempts SET status='unknown',updated=? WHERE status='claimed' AND expires<=?",
                       (time.time(), time.time()))
            rows = db.execute("SELECT * FROM agent_host_attempts WHERE host_id=? AND status='pending'" +
                              (' AND id=?' if attempt_id else '') + ' ORDER BY created',
                              (host_id, attempt_id) if attempt_id else (host_id,)).fetchall()
            for row in rows:
                try: self._parent(db, row[1], row[2], row[5])
                except ValueError: continue
                token = secrets.token_hex(32); expires = time.time() + LEASE_SECONDS
                db.execute("UPDATE agent_host_attempts SET status='claimed',worker=?,token_sha=?,expires=?,updated=? WHERE id=? AND status='pending'",
                           (worker_id, hashlib.sha256(token.encode()).hexdigest(), expires, time.time(), row[0]))
                leased = self._public(db.execute('SELECT * FROM agent_host_attempts WHERE id=?', (row[0],)).fetchone())
                return {**leased, 'worker_id': worker_id, 'lease_token': token, 'lease_expires': expires,
                        'request': json.loads(row[7])}
        return None

    def _lease(self, db, attempt_id, generation, worker_id, lease_token):
        row = db.execute('SELECT * FROM agent_host_attempts WHERE id=?', (attempt_id,)).fetchone()
        if not row: raise ValueError('host_attempt_not_found')
        if (type(generation) is not int or row[4] != generation or row[9] != worker_id
                or not isinstance(lease_token, str) or len(lease_token) != 64
                or not secrets.compare_digest(row[10] or '', hashlib.sha256(lease_token.encode()).hexdigest())):
            raise ValueError('host_lease_conflict')
        return row

    def heartbeat(self, attempt_id, generation, worker_id, lease_token):
        with self.core.atomic() as db:
            row = self._lease(db, attempt_id, generation, worker_id, lease_token)
            if row[8] != 'claimed' or row[11] <= time.time(): raise ValueError('host_lease_expired')
            self._current(db, row)
            expires = time.time() + LEASE_SECONDS
            db.execute('UPDATE agent_host_attempts SET expires=?,updated=? WHERE id=?', (expires, time.time(), attempt_id))
            return {'lease_expires': expires}

    def admit(self, attempt_id, generation, worker_id, lease_token, session_id):
        if not bounded_name(session_id, 200): raise ValueError('host_invalid_receipt')
        with self.core.atomic() as db:
            row = self._lease(db, attempt_id, generation, worker_id, lease_token)
            if row[8] != 'claimed' or row[11] <= time.time(): raise ValueError('host_lease_expired')
            self._current(db, row)
            acknowledgement = {'session_id': session_id, 'request_id': json.loads(row[7])['request_id'], 'accepted': True}
            if row[13] and json.loads(row[13]) != acknowledgement: raise ValueError('host_admission_conflict')
            db.execute('UPDATE agent_host_attempts SET receipt=?,updated=? WHERE id=?',
                       (canonical(acknowledgement), time.time(), attempt_id))
            return self._public(db.execute('SELECT * FROM agent_host_attempts WHERE id=?', (attempt_id,)).fetchone())

    def _current(self, db, row):
        job, _, _ = self._parent(db, row[1], row[2], row[5])
        request = json.loads(row[7])
        if ((row[1] and job['phase'] != row[3]) or digest(job['_context']) != request['context_sha256']
                or job.get('_host_attempt') != {'id': row[0], 'generation': row[4],
                    'request_sha256': digest(request), 'route_sha256': request['route']['route_sha256']}):
            raise ValueError('host_attempt_superseded')

    def finish(self, attempt_id, generation, worker_id, lease_token, outcome, result=None, receipt=None):
        if outcome not in ('completed', 'failed', 'unknown'): raise ValueError('host_invalid_outcome')
        finish = {'outcome': outcome, 'result': result, 'receipt': receipt}
        if len(canonical(finish).encode()) > 50000: raise ValueError('host_result_too_large')
        with self.core.atomic() as db:
            row = self._lease(db, attempt_id, generation, worker_id, lease_token)
            if row[14]:
                if row[14] != digest(finish): raise ValueError('host_finish_conflict')
                return self._public(row)
            if row[8] != 'claimed' or row[11] <= time.time(): raise ValueError('host_lease_expired')
            self._current(db, row)
            request = json.loads(row[7]); route = request['route']
            if outcome == 'completed':
                required = {'session_id', 'provider', 'model', 'request_id', 'finish_reason', 'tools_used'}
                if (not isinstance(receipt, dict) or set(receipt) != required
                        or not bounded_name(receipt['session_id'], 200)
                        or receipt['provider'] != route['provider'] or receipt['model'] != route['model']
                        or receipt['request_id'] != request['request_id']
                        or receipt['finish_reason'] != 'completed' or receipt['tools_used'] != []):
                    raise ValueError('host_invalid_receipt')
                if row[13] and json.loads(row[13])['session_id'] != receipt['session_id']:
                    raise ValueError('host_invalid_receipt')
                import jsonschema
                try: jsonschema.validate(result, request['output_schema'])
                except jsonschema.ValidationError: raise ValueError('host_invalid_result') from None
            elif result is not None or receipt is not None:
                raise ValueError('host_invalid_outcome')
            db.execute('UPDATE agent_host_attempts SET status=?,result=?,receipt=?,finish_sha=?,expires=0,updated=? WHERE id=?',
                       (outcome, canonical(result) if result is not None else None,
                        canonical(receipt) if receipt is not None else None, digest(finish), time.time(), attempt_id))
            return self._public(db.execute('SELECT * FROM agent_host_attempts WHERE id=?', (attempt_id,)).fetchone())

    def broker(self, operation, arguments):
        """Bearer-only local control plane; never included in the model tool menu."""
        from inspect import signature
        if not isinstance(operation, str): raise ValueError('host_invalid_worker_request')
        method = {'register': self.register, 'claim': self.claim, 'admit': self.admit,
                  'heartbeat': self.heartbeat, 'finish': self.finish}.get(operation)
        if method is None or not isinstance(arguments, dict): raise ValueError('host_invalid_worker_request')
        try: signature(method).bind(**arguments)
        except TypeError: raise ValueError('host_invalid_worker_request') from None
        return method(**arguments)

    def _abandon(self, attempt_id):
        with self.core.atomic() as db:
            row = db.execute('SELECT * FROM agent_host_attempts WHERE id=?', (attempt_id,)).fetchone()
            if row and row[5] == self.service.agent_runtime.owner and row[8] in ('pending', 'claimed'):
                # Pending is known not submitted; claimed may already have reached
                # a provider even if its admission acknowledgement was lost.
                db.execute('UPDATE agent_host_attempts SET status=?,updated=? WHERE id=?',
                           ('failed' if row[8] == 'pending' else 'unknown', time.time(), attempt_id))

    def recover(self, db, run_id):
        """Fence dead-parent children atomically; admission is never replayable."""
        unknown = bool(db.execute("SELECT 1 FROM agent_host_attempts WHERE run_id=? AND status IN ('claimed','unknown')", (run_id,)).fetchone())
        db.execute("UPDATE agent_host_attempts SET status=CASE WHEN status='pending' THEN 'failed' ELSE 'unknown' END,expires=0,updated=? WHERE run_id=? AND status IN ('pending','claimed')",
                   (time.time(), run_id))
        return 'unknown' if unknown else 'queued'

    def recover_dialogues(self, db):
        for run_id,encoded in db.execute("SELECT id,payload FROM agent_runs WHERE status IN ('running','cancel_requested')").fetchall():
            payload=json.loads(encoded)
            if (payload.get('model_route',{}).get('provider')!='host_native'
                    or db.execute('SELECT 1 FROM market_research_runs WHERE run_id=?',(run_id,)).fetchone()):continue
            outcome=self.recover(db,run_id)
            status='unknown' if outcome=='unknown' else 'interrupted'
            error='agent_provider_outcome_unknown' if status=='unknown' else 'agent_interrupted_no_automatic_resubmit'
            db.execute('UPDATE agent_runs SET status=?,expires=0,updated=?,result=? WHERE id=?',
                       (status,time.time(),canonical({'error':error,'automatic_retry':False}),run_id))

    def invoke_run(self, run_id, turn, payload, cancelled):
        from agent_runtime.codex_provider import schema,decode
        from agent_runtime.model_worker import STRUCTURED_SYSTEM
        generated=self.generate({'task_id':None,'run_id':run_id},'dialogue_'+str(turn),payload,
                                schema(payload.get('observations',[])),STRUCTURED_SYSTEM,cancelled)
        return {'decision':decode(generated['data']),'provider':'host_native:'+generated['host_id'],'model':generated['model']}

    def generate(self, job, phase, payload, output_schema, instructions, cancelled):
        attempt = self.request(job['task_id'], job['run_id'], phase, payload, output_schema, instructions)
        if attempt['status'] == 'completed':
            return {'data': attempt['result'], **{k:attempt['route'][k] for k in ('provider','model','host_id')}}
        if attempt['status'] != 'pending': raise ValueError('agent_provider_outcome_unknown')
        end = time.monotonic() + 110
        try:
            if attempt['host_id'] in ('hermes', 'codex'):
                from host_native import invoke
                lease = self.claim(attempt['host_id'], self.service.agent_runtime.owner, attempt['attempt_id'])
                if lease is None: raise ValueError('agent_host_claim_conflict')
                next_heartbeat = time.monotonic() + 10
                def stopped():
                    nonlocal next_heartbeat
                    if cancelled(): return True
                    if time.monotonic() >= next_heartbeat:
                        self.heartbeat(lease['attempt_id'], lease['generation'], lease['worker_id'], lease['lease_token'])
                        next_heartbeat = time.monotonic() + 10
                    return False
                native = invoke(lease, stopped)
                self.finish(lease['attempt_id'], lease['generation'], lease['worker_id'], lease['lease_token'],
                            'completed', native['data'], {**native['receipt'], 'request_id': lease['request_id']})
            while time.monotonic() < end:
                if cancelled():
                    from agent_runtime.model import Cancelled
                    raise Cancelled()
                current = self.get(attempt['attempt_id'])
                if current['status'] == 'completed':
                    return {'data': current['result'], **{k:current['route'][k] for k in ('provider','model','host_id')}}
                if current['status'] in ('failed', 'unknown'):
                    raise ValueError('agent_provider_outcome_unknown' if current['status'] == 'unknown' else 'agent_host_unavailable_use_workbench')
                time.sleep(.1)
            self._abandon(attempt['attempt_id'])
            current = self.get(attempt['attempt_id'])
            if current['status'] == 'completed':
                return {'data': current['result'], **{k:current['route'][k] for k in ('provider','model','host_id')}}
            raise ValueError('agent_provider_outcome_unknown' if current['status'] == 'unknown' else 'agent_host_unavailable_use_workbench')
        except Exception as error:
            self._abandon(attempt['attempt_id'])
            if type(error).__name__ == 'Cancelled':
                from agent_runtime.model import Cancelled
                raise Cancelled() from None
            # Transport exit is not evidence that a claimed provider request
            # failed. Preserve the journal's uncertainty in the parent too.
            if self.get(attempt['attempt_id'])['status']=='unknown':
                raise ValueError('agent_provider_outcome_unknown') from None
            raise
