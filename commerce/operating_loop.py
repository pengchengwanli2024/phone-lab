"""Bounded operating loop: turn known next steps into controlled work items.

The loop owns no product facts, scheduler, task ledger or executor. For every
enabled grant it reads the existing operating pipeline, picks stages whose
dependencies are prepared, and creates at most one work item per
(grant, stage, evidence basis). Unchanged evidence never dispatches again, so
an idle loop makes no model calls.

A work item at level "prepare" becomes one bounded read-only model request in
the existing agent runtime (role = stage owner). Its proposals stay under human
review; approval reuses the original agent apply path. No marketplace write,
payment, message or purchase can be issued from this module.
"""
import json
import threading
import time

from research import canonical, digest

READ_ONLY = {'commerce_operating_loop_get'}
LEVELS = ('observe', 'prepare')
ACTIVE = ('pending', 'dispatched')
OPEN = ('waiting_input', 'awaiting_decision', 'failed', 'unknown')
RUN_STATUS = {'queued': 'dispatched', 'running': 'dispatched', 'cancel_requested': 'dispatched',
              'awaiting_input': 'waiting_input', 'completed': 'completed', 'failed': 'failed',
              'cancelled': 'cancelled', 'interrupted': 'unknown', 'unknown': 'unknown'}
LIMITS = {'grants': 50, 'runs_per_day': 12, 'check_interval_seconds': 60, 'failures_before_halt': 3,
          'work_listed': 100}
LOCK = threading.RLock()


def definitions(schema, string):
    ident = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    revision = {'type': 'integer', 'minimum': 0}
    sha = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
    target = schema({'case_id': ident, 'platform': string, 'store_ref': string, 'market': string},
                    ['case_id', 'platform', 'store_ref', 'market'])
    return [
        ('commerce_operating_loop_get', '读取经营回路的授权、各阶段工单与待处理事项；不派发、不调用模型', schema({'grant_id': ident})),
        ('commerce_operating_loop_grant_save', '保存单商品经营回路授权并保持停用；只允许观察或范围内准备，不含任何外部经营动作',
         schema({'target': target, 'goal': {'type': 'string', 'enum': ['launch', 'operate', 'brand']},
                 'stages': {'type': 'array', 'items': ident, 'minItems': 1, 'maxItems': 14},
                 'level': {'type': 'string', 'enum': list(LEVELS)},
                 'max_runs_per_day': {'type': 'integer', 'minimum': 1, 'maximum': LIMITS['runs_per_day']},
                 'expires_at': {'type': 'number'}, 'expected_revision': revision},
                ['target', 'goal', 'stages', 'level', 'max_runs_per_day', 'expected_revision'])),
        ('commerce_operating_loop_grant_enable', '明确启停经营回路授权；停用只阻止后续派发，不撤回已发出的请求',
         schema({'grant_id': ident, 'expected_revision': revision, 'enabled': {'type': 'boolean'}},
                ['grant_id', 'expected_revision', 'enabled'])),
        ('commerce_operating_loop_advance', '按当前证据明确推进一次指定授权；证据未变化不重复派发',
         schema({'grant_id': ident}, ['grant_id'])),
        ('commerce_operating_loop_decide', '按准确结果哈希批准或驳回一项待决建议；批准沿用原审阅提交，不执行店铺操作',
         schema({'work_id': ident, 'decision': {'type': 'string', 'enum': ['approve', 'reject']},
                 'proposal_id': ident, 'expected_result_sha256': sha},
                ['work_id', 'decision', 'expected_result_sha256'])),
        ('commerce_operating_loop_resolve', '核对后关闭一项失败或结果未知的工单；不重发原请求',
         schema({'work_id': ident, 'note': {'type': 'string', 'maxLength': 500}}, ['work_id'])),
    ]


def _text(value, limit):
    if type(value) is not str or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('operating_loop_invalid_text')
    return value.strip()


class OperatingLoop:
    def __init__(self, service):
        self.service, self.core = service, service.core
        self._checked = {}
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operating_loop_grants (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS operating_loop_work (id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, '
                       'stage_id TEXT NOT NULL, basis_sha256 TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, '
                       'document TEXT NOT NULL, UNIQUE(grant_id, stage_id, basis_sha256))')

    def invoke(self, name, args):
        methods = {'get': self.get, 'grant_save': self.grant_save, 'grant_enable': self.grant_enable,
                   'advance': self.advance, 'decide': self.decide, 'resolve': self.resolve}
        action = name.removeprefix('commerce_operating_loop_')
        if not name.startswith('commerce_operating_loop_') or action not in methods:
            raise ValueError('unknown_tool')
        return methods[action](**args)

    # ---- grants -------------------------------------------------------
    def _grant(self, db, grant_id):
        row = db.execute('SELECT document FROM operating_loop_grants WHERE id=?', (grant_id,)).fetchone()
        if not row:
            raise ValueError('operating_loop_grant_not_found')
        return json.loads(row[0])

    @staticmethod
    def _store_grant(db, grant):
        db.execute('INSERT INTO operating_loop_grants VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                   (grant['id'], canonical(grant)))

    def grant_save(self, target, goal, stages, level, max_runs_per_day, expected_revision, expires_at=None):
        from operating_pipeline import GOALS, STAGES
        if goal not in GOALS or level not in LEVELS:
            raise ValueError('operating_loop_invalid_grant')
        if type(max_runs_per_day) is not int or not 1 <= max_runs_per_day <= LIMITS['runs_per_day']:
            raise ValueError('operating_loop_invalid_grant')
        known = [row[0] for row in STAGES]
        if (not isinstance(stages, list) or not stages or len(set(stages)) != len(stages)
                or any(type(s) is not str or s not in known for s in stages)):
            raise ValueError('operating_loop_invalid_stages')
        if expires_at is not None and (type(expires_at) not in (int, float) or not time.time() < expires_at < 4102444800):
            raise ValueError('operating_loop_invalid_expiry')
        if not isinstance(target, dict) or set(target) != {'case_id', 'platform', 'store_ref', 'market'}:
            raise ValueError('operating_loop_invalid_target')
        # The original listing scope validates platform, store and an existing case.
        scope, _ = self.service.listings.scope(**target)
        if not scope['store_ref'] or not scope['market']:
            raise ValueError('operating_loop_invalid_target')
        ident = 'loopgrant_' + digest(canonical({'target': scope, 'goal': goal}))[:24]
        with LOCK, self.core.atomic() as db:
            row = db.execute('SELECT document FROM operating_loop_grants WHERE id=?', (ident,)).fetchone()
            old = json.loads(row[0]) if row else None
            if (old['revision'] if old else 0) != expected_revision:
                raise ValueError('operating_loop_revision_conflict')
            if not old and db.execute('SELECT count(*) FROM operating_loop_grants').fetchone()[0] >= LIMITS['grants']:
                raise ValueError('operating_loop_grant_limit')
            now = time.time()
            # Any change to scope of automation returns the grant to disabled.
            grant = {'id': ident, 'target': scope, 'goal': goal, 'stages': [s for s in known if s in stages],
                     'level': level, 'max_runs_per_day': max_runs_per_day, 'expires_at': expires_at,
                     'enabled': False, 'halted_reason': None, 'revision': expected_revision + 1,
                     'created': old['created'] if old else now, 'updated': now}
            self._store_grant(db, grant)
        return self._present_grant(grant)

    def grant_enable(self, grant_id, expected_revision, enabled):
        if type(enabled) is not bool:
            raise ValueError('operating_loop_invalid_grant')
        with LOCK, self.core.atomic() as db:
            grant = self._grant(db, grant_id)
            if grant['revision'] != expected_revision:
                raise ValueError('operating_loop_revision_conflict')
            if enabled and grant['expires_at'] is not None and grant['expires_at'] <= time.time():
                raise ValueError('operating_loop_grant_expired')
            grant.update(enabled=enabled, revision=grant['revision'] + 1, updated=time.time())
            if enabled:
                grant['halted_reason'] = None
                grant['enabled_at'] = time.time()
            self._store_grant(db, grant)
        self._checked.pop(grant_id, None)
        return self._present_grant(grant)

    @staticmethod
    def _present_grant(grant):
        return {**grant, 'active': bool(grant['enabled'] and (grant['expires_at'] is None or grant['expires_at'] > time.time())),
                'external_execution_allowed': False}

    # ---- work items ---------------------------------------------------
    @staticmethod
    def _work(db, work_id):
        row = db.execute('SELECT document,status FROM operating_loop_work WHERE id=?', (work_id,)).fetchone()
        if not row:
            raise ValueError('operating_loop_work_not_found')
        return {**json.loads(row[0]), 'status': row[1]}

    @staticmethod
    def _store_work(db, work):
        document = {k: v for k, v in work.items() if k != 'status'}
        db.execute('UPDATE operating_loop_work SET status=?,document=? WHERE id=?',
                   (work['status'], canonical(document), work['id']))

    @staticmethod
    def _basis(snapshot, stage, executable=False):
        basis = {'source': snapshot['product_source_sha256'], 'stage': stage['id'],
                 'status': stage['acceptance_status'], 'missing': stage['missing'], 'evidence': stage['evidence']}
        # Recording a gap and asking the stage owner are different work on the same evidence.
        # Gap-only keeps its original key so existing records still match.
        if executable:
            basis['executor'] = 'agent_runtime'
        return digest(canonical(basis))

    @staticmethod
    def _question(stage):
        lines = ['经营回路派工：请核对本商品“' + stage['name'] + '”阶段的当前证据与缺项，说明还缺什么、由谁补、如何复验。',
                 '只读取所选工作项；不执行采购、付款、发布、广告或客户消息。']
        lines.extend('缺项：' + item[:200] for item in stage['missing'][:6])
        return '\n'.join(lines)[:1900]

    def _reconcile(self, grant_id):
        """Project the original run status onto dispatched work; never resubmits."""
        with self.core.db() as db:
            rows = [self._work(db, r[0]) for r in db.execute(
                "SELECT id FROM operating_loop_work WHERE grant_id=? AND status='dispatched'", (grant_id,))]
        for work in rows:
            try:
                run = self.service.agent_runtime.get(work['run_id'])
            except ValueError:
                run = {'status': 'unknown', 'result': None, 'result_sha256': None}
            status = RUN_STATUS.get(run['status'])
            result = run.get('result') or {}
            if run['status'] == 'awaiting_review':
                status = 'awaiting_decision' if result.get('proposals') else 'completed'
            if status is None:
                status = 'unknown'
            if status == 'dispatched':
                continue
            with LOCK, self.core.atomic() as db:
                current = self._work(db, work['id'])
                if current['status'] != 'dispatched':
                    continue
                current.update(status=status, updated=time.time(), result_sha256=run.get('result_sha256'),
                               questions=list(result.get('questions') or [])[:3],
                               proposals=[{'id': p['id'], 'operation': p['operation'], 'reason': p['reason']}
                                          for p in result.get('proposals') or []],
                               error=result.get('error') if status in ('failed', 'unknown', 'cancelled') else None)
                self._store_work(db, current)

    def _halt_if_failing(self, grant_id):
        with LOCK, self.core.atomic() as db:
            grant = self._grant(db, grant_id)
            # Failures from before the operator re-enabled the grant were already answered.
            recent = [r[0] for r in db.execute(
                'SELECT status FROM operating_loop_work WHERE grant_id=? AND created>=? ORDER BY created DESC LIMIT ?',
                (grant_id, grant.get('enabled_at') or 0, LIMITS['failures_before_halt']))]
            if (grant['enabled'] and len(recent) == LIMITS['failures_before_halt']
                    and all(s in ('failed', 'unknown') for s in recent)):
                grant.update(enabled=False, halted_reason='consecutive_failures', revision=grant['revision'] + 1,
                             updated=time.time())
                self._store_grant(db, grant)
                return True
        return False

    def _advance(self, grant_id, at):
        self._reconcile(grant_id)
        if self._halt_if_failing(grant_id):
            return {'dispatched': None, 'reason': 'halted_consecutive_failures'}
        with self.core.db() as db:
            grant = self._grant(db, grant_id)
            counts = dict(db.execute('SELECT status,count(*) FROM operating_loop_work WHERE grant_id=? GROUP BY status', (grant_id,)))
            today = db.execute("SELECT count(*) FROM operating_loop_work WHERE grant_id=? AND created>? "
                               "AND json_extract(document,'$.run_id') IS NOT NULL", (grant_id, at - 86400)).fetchone()[0]
            pending = [r[0] for r in db.execute("SELECT id FROM operating_loop_work WHERE grant_id=? AND status='pending'", (grant_id,))]
        if not grant['enabled']:
            return {'dispatched': None, 'reason': 'grant_disabled'}
        if grant['expires_at'] is not None and grant['expires_at'] <= at:
            return {'dispatched': None, 'reason': 'grant_expired'}
        for work_id in pending:  # crash between insert and dispatch: same key, same run
            return {'dispatched': self._dispatch(work_id), 'reason': 'resumed_pending'}
        if counts.get('dispatched') or counts.get('unknown'):
            # One executor at a time; an unknown result is checked before more work.
            return {'dispatched': None, 'reason': 'unknown_requires_check' if counts.get('unknown') else 'work_in_flight'}
        snapshot = self.service.operating_pipeline.get(**grant['target'], goal=grant['goal'])
        if grant['level'] == 'prepare':
            local = self._local_calculation(grant, snapshot, at)
            if local:
                return local
        eligible = [s for s in snapshot['stages'] if s['id'] in grant['stages'] and s['required_for_goal']
                    and s['acceptance_status'] != 'prepared' and not s['blocked_by']]
        self._supersede(grant_id, {s['id']: self._basis(snapshot, s) for s in eligible
                                   if not (grant['level'] == 'prepare' and s['original_gates'])}, at)
        with self.core.db() as db:
            undecided = {r[0] for r in db.execute(
                "SELECT stage_id FROM operating_loop_work WHERE grant_id=? AND status='awaiting_decision'", (grant_id,))}
        held = None
        for stage in eligible:
            if stage['id'] in undecided:
                # A proposal for this stage is still with the operator. Asking the model
                # again on newer evidence would stack decisions; wait for the answer first.
                # Other stages are independent and continue.
                held = held or 'awaiting_your_decision'
                continue
            executable = grant['level'] == 'prepare' and bool(stage['original_gates'])
            basis = self._basis(snapshot, stage, executable)
            if executable and today >= grant['max_runs_per_day']:
                # The limit only stops model requests; gaps without an executor are still recorded.
                with self.core.db() as db:
                    seen = db.execute('SELECT 1 FROM operating_loop_work WHERE grant_id=? AND stage_id=? AND basis_sha256=?',
                                      (grant_id, stage['id'], basis)).fetchone()
                if not seen:
                    held = held or 'daily_limit'
                continue
            work_id = 'loopwork_' + digest(canonical([grant_id, stage['id'], basis]))[:24]
            work = {'id': work_id, 'grant_id': grant_id, 'grant_revision': grant['revision'], 'target': grant['target'],
                    'stage_id': stage['id'], 'stage_name': stage['name'], 'owner': stage['owner'],
                    'gate': stage['original_gates'][0] if stage['original_gates'] else None,
                    'basis_sha256': basis, 'missing': stage['missing'][:12], 'acceptance_status': stage['acceptance_status'],
                    'question': self._question(stage), 'created': at, 'updated': at, 'run_id': None,
                    'executor': 'agent_runtime' if executable else None}
            with LOCK, self.core.atomic() as db:
                if not self._grant(db, grant_id)['enabled']:
                    return {'dispatched': None, 'reason': 'grant_disabled'}
                inserted = db.execute('INSERT OR IGNORE INTO operating_loop_work VALUES (?,?,?,?,?,?,?)',
                    (work_id, grant_id, stage['id'], basis, 'pending' if executable else 'waiting_input', at,
                     canonical(work))).rowcount
            if not inserted:
                continue  # same evidence was already handled; never repeat it
            return {'dispatched': self._dispatch(work_id) if executable else self._public(dict(work, status='waiting_input')),
                    'reason': 'dispatched' if executable else 'recorded_gap_without_executor'}
        return {'dispatched': None, 'reason': held or ('no_new_evidence' if eligible else 'nothing_eligible')}

    def _local_calculation(self, grant, snapshot, at):
        """Keep the saved cost inputs and their calculation in step, without a model.

        Only the action the pipeline itself offers is used: the operator already
        saved these inputs, and the original calculator re-checks source, revision
        and currency. It runs even while an upstream stage is open, because it
        does not mark the stage as accepted.
        """
        for stage in snapshot['stages']:
            if stage['id'] not in grant['stages'] or stage['acceptance_status'] != 'needs_calculation':
                continue
            action = next((a for a in stage['next_actions'] if a['tool'] == 'commerce_workspace_calculate'
                           and a['callable'] and a['effect'] == 'local_prepare'), None)
            if not action or action['arguments'].get('case_id') != grant['target']['case_id']:
                continue
            basis = digest(canonical({'calculate': action['arguments'], 'stage': stage['id']}))
            work_id = 'loopwork_' + digest(canonical([grant['id'], stage['id'], basis]))[:24]
            work = {'id': work_id, 'grant_id': grant['id'], 'grant_revision': grant['revision'], 'target': grant['target'],
                    'stage_id': stage['id'], 'stage_name': stage['name'], 'owner': stage['owner'], 'gate': None,
                    'basis_sha256': basis, 'missing': [], 'acceptance_status': stage['acceptance_status'],
                    'question': '', 'created': at, 'updated': at, 'run_id': None, 'executor': 'local_calculator',
                    'local_arguments': action['arguments']}
            with LOCK, self.core.atomic() as db:
                if not self._grant(db, grant['id'])['enabled']:
                    return {'dispatched': None, 'reason': 'grant_disabled'}
                inserted = db.execute('INSERT OR IGNORE INTO operating_loop_work VALUES (?,?,?,?,?,?,?)',
                    (work_id, grant['id'], stage['id'], basis, 'pending', at, canonical(work))).rowcount
            if not inserted:
                continue  # these exact inputs were already attempted; never repeat
            result = self._dispatch(work_id)
            return {'dispatched': result, 'reason': 'calculated_locally' if result['status'] == 'completed' else 'local_calculation_not_completed'}
        return None

    def _calculate(self, work):
        try:
            result = self.service.product_workspace.calculate(**work['local_arguments'])
        except ValueError as error:
            return {'status': 'failed', 'error': str(error)[:120]}
        if result.get('status') != 'CALCULATED':
            return {'status': 'waiting_input', 'missing': ['成本参数缺项：' + str(item)[:80] for item in result.get('missing') or []][:12]}
        return {'status': 'completed'}

    def _supersede(self, grant_id, current, at):
        """Close gap records that no longer describe the product.

        Only 'waiting_input' items are touched: they carry no decision and no
        request. An item is superseded when its stage is no longer open, or is
        open on different evidence. History stays readable.
        """
        with LOCK, self.core.atomic() as db:
            rows = [self._work(db, r[0]) for r in db.execute(
                "SELECT id FROM operating_loop_work WHERE grant_id=? AND status='waiting_input'", (grant_id,))]
            for work in rows:
                if current.get(work['stage_id']) == work['basis_sha256']:
                    continue
                work.update(status='superseded', updated=at)
                self._store_work(db, work)

    def _dispatch(self, work_id):
        with self.core.db() as db:
            work = self._work(db, work_id)
        if work.get('executor') == 'local_calculator':
            update = self._calculate(work)
            with LOCK, self.core.atomic() as db:
                current = self._work(db, work_id)
                if current['status'] == 'pending':
                    current.update(update, updated=time.time())
                    self._store_work(db, current)
                return self._public(current)
        try:
            run = self.service.agent_runtime.create(question=work['question'], role=work['owner'], topic='organization_case',
                parameters={'case_id': work['target']['case_id'], 'stage_id': work['gate']},
                idempotency_key='operating-loop:' + work_id)
            update = {'status': 'dispatched', 'run_id': run['id']}
        except ValueError as error:
            update = {'status': 'failed', 'error': str(error)[:120]}
        with LOCK, self.core.atomic() as db:
            current = self._work(db, work_id)
            if current['status'] == 'pending':
                current.update(update, updated=time.time())
                self._store_work(db, current)
            return self._public(current)

    @staticmethod
    def _public(work):
        keys = ('id', 'grant_id', 'target', 'stage_id', 'stage_name', 'owner', 'status', 'missing', 'acceptance_status',
                'basis_sha256', 'run_id', 'executor', 'created', 'updated', 'result_sha256', 'questions', 'proposals',
                'error', 'decision', 'resolution')
        return {k: work.get(k) for k in keys}

    # ---- public operations -------------------------------------------
    def advance(self, grant_id):
        with self.core.db() as db:
            self._grant(db, grant_id)
        outcome = self._advance(grant_id, time.time())
        return {**outcome, 'external_execution_allowed': False, 'view': self.get(grant_id)}

    def tick(self, at=None):
        """Background entry: each enabled grant is examined at most once a minute."""
        at = time.time() if at is None else at
        with self.core.db() as db:
            grants = [json.loads(r[0]) for r in db.execute('SELECT document FROM operating_loop_grants')]
        for grant in grants:
            if not grant['enabled'] or at - self._checked.get(grant['id'], 0) < LIMITS['check_interval_seconds']:
                continue
            self._checked[grant['id']] = at
            try:
                self._advance(grant['id'], at)
            except ValueError:
                continue  # one unreadable target never blocks other grants

    def decide(self, work_id, decision, expected_result_sha256, proposal_id=None):
        if decision not in ('approve', 'reject'):
            raise ValueError('operating_loop_invalid_decision')
        with self.core.db() as db:
            work = self._work(db, work_id)
        self._reconcile(work['grant_id'])
        with self.core.db() as db:
            work = self._work(db, work_id)
        if work.get('decision'):
            if work['decision']['decision'] != decision or work['decision'].get('proposal_id') != proposal_id:
                raise ValueError('operating_loop_already_decided')
            return {'work': self._public(work), 'reused': True, 'external_operations_executed': False}
        if work['status'] != 'awaiting_decision':
            raise ValueError('operating_loop_not_awaiting_decision')
        if work.get('result_sha256') != expected_result_sha256:
            raise ValueError('operating_loop_result_changed')
        record = {'decision': decision, 'proposal_id': proposal_id, 'at': time.time(), 'task_id': None}
        if decision == 'approve':
            if proposal_id not in [p['id'] for p in work.get('proposals') or []]:
                raise ValueError('operating_loop_proposal_not_found')
            # The original review path re-checks case binding and evidence.
            applied = self.service.agent_runtime.apply(work['run_id'], proposal_id, expected_result_sha256)
            record['task_id'] = applied['task']['id']
        with LOCK, self.core.atomic() as db:
            current = self._work(db, work_id)
            if not current.get('decision'):
                current.update(status='completed' if decision == 'approve' else 'rejected', decision=record, updated=time.time())
                self._store_work(db, current)
        return {'work': self._public(current), 'reused': False, 'external_operations_executed': False}

    def resolve(self, work_id, note=''):
        note = _text(note, 500)
        with LOCK, self.core.atomic() as db:
            work = self._work(db, work_id)
            if work.get('resolution'):
                return {'work': self._public(work), 'reused': True, 'resubmitted': False}
            if work['status'] not in ('failed', 'unknown'):
                raise ValueError('operating_loop_not_resolvable')
            work.update(status='resolved', resolution={'previous_status': work['status'], 'note': note, 'at': time.time()},
                        updated=time.time())
            self._store_work(db, work)
        return {'work': self._public(work), 'reused': False, 'resubmitted': False}

    def get(self, grant_id=None):
        with self.core.db() as db:
            grants = [json.loads(r[0]) for r in db.execute('SELECT document FROM operating_loop_grants ORDER BY id')]
            if grant_id is not None:
                grants = [self._grant(db, grant_id)]
            rows = db.execute('SELECT id FROM operating_loop_work' + (' WHERE grant_id=?' if grant_id else '') +
                              ' ORDER BY created DESC,id LIMIT ?', ((grant_id,) if grant_id else ()) + (LIMITS['work_listed'] + 1,)).fetchall()
            work = [self._public(self._work(db, r[0])) for r in rows[:LIMITS['work_listed']]]
        from operating_pipeline import STAGES
        presented = []
        for grant in grants:
            view = self._present_grant(grant)
            try:
                case = self.service.organization.case(grant['target']['case_id']);scope = case['scope']
                view.update(case_label=self.service.product_workspace.label(case), case_available=True, synthetic=scope.get('synthetic') is True)
            except ValueError:
                # e.g. the case belongs to another store connection; never guess a name.
                view.update(case_label=None, case_available=False, synthetic=False)
            presented.append(view)
        return {'schema': 'commerce-operating-loop-v1', 'grants': presented,
                'stage_catalog': [{'id': row[0], 'name': row[1], 'owner': row[2], 'executable': bool(row[3]),
                                   'depends_on': list(row[4])} for row in STAGES],
                'work': work, 'work_truncated': len(rows) > LIMITS['work_listed'],
                'needs_attention': [w for w in work if w['status'] in OPEN],
                'levels': {'observe': '只记录缺项与负责人，不调用模型', 'prepare': '按阶段负责人发起一次有界只读模型分析，建议待人工决定；已保存的成本参数变化时用确定性计算器重算'},
                'limits': LIMITS, 'external_execution_allowed': False,
                'semantics': 'work_completion_is_not_business_completion'}
