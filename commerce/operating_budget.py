"""Local cumulative CNY accounting. No payment, permission or dispatch adapter."""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import hashlib
import json
import re
import time
import uuid

KINDS = ('purchase', 'payment', 'refund', 'advertising', 'repricing')
EVENTS = ('intent', 'unknown', 'paid', 'release', 'refund')
MAX_MINOR = 10 ** 14
ENFORCEMENT = {
    'scope': 'local_budget_preparation_and_accounting_only',
    'external_execution_authorized': False,
    'external_operations_executed': False,
    'all_external_executors_gated': False,
    'operator_identity': 'local_management_declaration_not_human_authentication',
    'financial_evidence': 'caller_record_not_independently_verified',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text(value, code, maximum=160):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > maximum:
        raise ValueError(code)
    return value


def integer(value, code, minimum=0):
    if type(value) is not int or not minimum <= value <= 2 ** 31 - 1:
        raise ValueError(code)
    return value


def money(value):
    """CNY units, exact to two decimals; deliberately reject binary floats."""
    if type(value) not in (str, int, Decimal):
        raise ValueError('invalid_money')
    raw = str(value)
    if len(raw) > 18 or not re.fullmatch(r'(0|[1-9][0-9]*)(\.[0-9]{1,2})?', raw):
        raise ValueError('invalid_money')
    whole, _, fraction = raw.partition('.')
    minor = int(whole) * 100 + int(fraction.ljust(2, '0'))
    if minor > MAX_MINOR:
        raise ValueError('invalid_money')
    return minor


def mode_value(mode):
    if type(mode) is not str or mode not in ('live', 'synthetic'):
        raise ValueError('invalid_budget_mode')
    return mode


def binding_value(binding):
    fields = {'task_id', 'action_id', 'task_input_sha256', 'action_input_sha256'}
    if type(binding) is not dict or set(binding) != fields:
        raise ValueError('invalid_budget_binding')
    for key in fields:
        text(binding[key], 'invalid_budget_binding')
    for key in ('task_input_sha256', 'action_input_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', binding[key]):
            raise ValueError('invalid_budget_binding')
    return dict(binding)


def conversion_value(source_currency, conversion, amount):
    if type(source_currency) is not str or not re.fullmatch('[A-Z]{3}', source_currency):
        raise ValueError('invalid_source_currency')
    if source_currency == 'CNY':
        if conversion is not None:
            raise ValueError('unexpected_conversion')
        return None
    fields = {'original_amount', 'rate_cny_upper', 'observed_at', 'evidence_ref'}
    if type(conversion) is not dict or set(conversion) != fields:
        raise ValueError('conversion_required')
    original_minor = money(conversion['original_amount'])
    rate = conversion['rate_cny_upper']
    if type(rate) is not str or len(rate) > 24 or not re.fullmatch(r'(0|[1-9][0-9]*)(\.[0-9]{1,10})?', rate):
        raise ValueError('invalid_conversion')
    try:
        observed = datetime.fromisoformat(conversion['observed_at'])
        if observed.utcoffset() is None or Decimal(rate) <= 0 or original_minor <= 0:
            raise ValueError('invalid_conversion')
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError('invalid_conversion') from None
    text(conversion['evidence_ref'], 'invalid_conversion', 500)
    with localcontext() as ctx:
        ctx.prec = 60
        upper = int((Decimal(original_minor) * Decimal(rate)).to_integral_value(rounding=ROUND_CEILING))
    if amount < upper:
        raise ValueError('conversion_upper_bound')
    return dict(conversion)


def definitions(schema, string):
    """Proposed tools for the owning service; policy save is local management only."""
    mode = {'type': 'string', 'enum': ['live', 'synthetic']}
    revision = {'type': 'integer', 'minimum': 0}
    binding = {'type': 'object', 'properties': {k: string for k in
               ('task_id', 'action_id', 'task_input_sha256', 'action_input_sha256')},
               'required': ['task_id', 'action_id', 'task_input_sha256', 'action_input_sha256'], 'additionalProperties': False}
    warning = '仅本机预算准备/占用记录；不付款、不授权经营，外部执行器尚未全部接预算闸门。'
    return [
        ('commerce_operating_budget_policy_get', '只读版本化共享累计预算。' + warning,
         schema({'mode': mode}, ['mode'])),
        ('commerce_operating_budget_reserve', '按原任务/动作和输入版本占用共享累计预算。' + warning,
         schema({'mode': mode, 'binding': binding, 'amount_cny': string, 'expected_policy_revision': revision,
                 'idempotency_key': string, 'source_currency': string, 'conversion': {'type': 'object'}},
                ['mode', 'binding', 'amount_cny', 'expected_policy_revision', 'idempotency_key'])),
        ('commerce_operating_budget_transition', '记录派发意图/未知/实付/未派发释放/退款；UNKNOWN不重发、不释放。' + warning,
         schema({'mode': mode, 'reservation_id': string, 'binding': binding, 'event': {'type': 'string', 'enum': list(EVENTS)},
                 'expected_revision': revision, 'idempotency_key': string, 'expected_policy_revision': revision,
                 'amount_cny': string, 'evidence': {'type': 'object'}, 'paid_receipt_id': string},
                ['mode', 'reservation_id', 'binding', 'event', 'expected_revision', 'idempotency_key'])),
        ('commerce_operating_budget_ledger', '只读本机预算台账及原事件分页。' + warning,
         schema({'mode': mode, 'task_id': string, 'offset': {'type': 'integer', 'minimum': 0},
                 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['mode'])),
    ]


class OperatingBudget:
    def __init__(self, core):
        self.core = core
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operating_budget_policies(mode TEXT PRIMARY KEY, document TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS operating_budget_records(
                id TEXT PRIMARY KEY,mode TEXT NOT NULL,task_id TEXT NOT NULL,action_id TEXT NOT NULL,document TEXT NOT NULL,
                UNIQUE(mode,task_id,action_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS operating_budget_receipts(
                mode TEXT NOT NULL,key TEXT NOT NULL,request_sha TEXT NOT NULL,receipt TEXT NOT NULL,record_id TEXT,
                PRIMARY KEY(mode,key))''')
            db.execute('CREATE INDEX IF NOT EXISTS operating_budget_receipts_record ON operating_budget_receipts(record_id)')
            db.execute('''CREATE TABLE IF NOT EXISTS operating_budget_external_records(
                mode TEXT NOT NULL,kind TEXT NOT NULL,source TEXT NOT NULL,external_id TEXT NOT NULL,record_id TEXT NOT NULL,
                PRIMARY KEY(mode,kind,source,external_id))''')

    def invoke(self, name, args):
        methods = {'commerce_operating_budget_' + method: getattr(self, method)
                   for method in ('policy_get', 'reserve', 'transition', 'ledger')}
        if name not in methods:
            raise ValueError('unknown_budget_tool')
        if type(args) is not dict:
            raise ValueError('invalid_arguments')
        return methods[name](**args)

    @staticmethod
    def _policy(db, mode):
        row = db.execute('SELECT document FROM operating_budget_policies WHERE mode=?', (mode,)).fetchone()
        return json.loads(row[0]) if row else {'mode': mode, 'configured': False, 'revision': 0,
            'cap_minor': None, 'task_ids': [], 'halted': False, 'currency': 'CNY',
            'period': 'cumulative_no_automatic_reset', 'refunds_restore_capacity': False}

    def _summary(self, db, mode):
        policy = self._policy(db, mode)
        records = [json.loads(r[0]) for r in db.execute('SELECT document FROM operating_budget_records WHERE mode=?', (mode,))]
        held = sum(r['reserved_minor'] for r in records if r['status'] in ('RESERVED', 'INTENT', 'UNKNOWN'))
        paid = sum(r['paid_minor'] for r in records)
        refunded = sum(r['refunded_minor'] for r in records)
        exposure = held + paid
        cap = policy['cap_minor']
        return {'policy': policy, 'usage': {'held_minor': held, 'gross_paid_minor': paid, 'refunded_minor': refunded,
            'net_paid_minor': paid - refunded, 'exposure_minor': exposure,
            'available_minor': max(0, cap - exposure) if cap is not None and not policy['halted'] else 0,
            'over_cap_minor': max(0, exposure - cap) if cap is not None else 0,
            'over_reservation_minor': sum(max(0, r['paid_minor'] - r['reserved_minor']) for r in records)},
            'enforcement': dict(ENFORCEMENT)}

    @staticmethod
    def _replay(db, mode, key, request):
        text(key, 'invalid_idempotency_key')
        row = db.execute('SELECT request_sha,receipt FROM operating_budget_receipts WHERE mode=? AND key=?', (mode, key)).fetchone()
        if row:
            if row[0] != digest(request):
                raise ValueError('idempotency_conflict')
            return json.loads(row[1])
        return None

    @staticmethod
    def _receipt(db, mode, key, request, value, operation, record_id=None, receipt_id=None):
        result = dict(value, receipt_id=receipt_id or uuid.uuid4().hex, operation=operation, recorded_at=time.time())
        db.execute('INSERT INTO operating_budget_receipts VALUES(?,?,?,?,?)',
                   (mode, key, digest(request), canonical(result), record_id))
        return result

    def policy_get(self, mode):
        mode_value(mode)
        with self.core.db() as db:
            if not db.in_transaction:
                db.execute('BEGIN')
            return self._summary(db, mode)

    def policy_save(self, mode, cap_cny, task_ids, expected_revision, idempotency_key, operator_confirmation):
        """Trusted local management seam. Caller must keep this out of agent dispatch."""
        mode_value(mode); cap = money(cap_cny); integer(expected_revision, 'invalid_policy_revision')
        if type(task_ids) is not list or not task_ids or len(task_ids) > 1000:
            raise ValueError('invalid_policy_tasks')
        for task_id in task_ids:
            text(task_id, 'invalid_policy_tasks')
        if len(set(task_ids)) != len(task_ids):
            raise ValueError('invalid_policy_tasks')
        candidate = {'mode': mode, 'cap_minor': cap, 'task_ids': sorted(task_ids)}
        request = dict(operation='policy_save', candidate=candidate, expected_revision=expected_revision, operator_confirmation=operator_confirmation)
        # Copy/check before the transaction; no caller-owned mutable documents survive.
        try:
            request = json.loads(canonical(request))
        except (TypeError, ValueError):
            raise ValueError('local_operator_confirmation_required') from None
        confirmation = request['operator_confirmation']
        with self.core.atomic() as db:
            replay = self._replay(db, mode, idempotency_key, request)
            if replay:
                return replay
            policy = self._policy(db, mode)
            if policy['revision'] != expected_revision:
                raise ValueError('policy_version_conflict')
            if (type(confirmation) is not dict or set(confirmation) != {'kind', 'name', 'confirmed', 'expected_revision', 'policy_sha256'}
                    or confirmation.get('kind') != 'local_operator' or confirmation.get('confirmed') is not True
                    or type(confirmation.get('expected_revision')) is not int or confirmation['expected_revision'] != expected_revision
                    or confirmation.get('policy_sha256') != digest(candidate)):
                raise ValueError('local_operator_confirmation_required')
            text(confirmation['name'], 'local_operator_confirmation_required')
            for task_id in candidate['task_ids']:
                row = db.execute('SELECT payload FROM tasks WHERE id=?', (task_id,)).fetchone()
                if not row:
                    raise ValueError('task_not_found')
                data = json.loads(row[0]).get('input', {})
                self._task_mode(data, mode)
            policy.update(candidate, configured=True, revision=expected_revision + 1,
                          operator_declaration=confirmation, updated_at=time.time())
            db.execute('INSERT INTO operating_budget_policies VALUES(?,?) ON CONFLICT(mode) DO UPDATE SET document=excluded.document', (mode, canonical(policy)))
            return self._receipt(db, mode, idempotency_key, request, self._summary(db, mode), 'policy_save')

    @staticmethod
    def _task_mode(data, mode):
        if type(data) is not dict or type(data.get('demo')) is not bool:
            raise ValueError('task_mode_required')
        if data['demo'] != (mode == 'synthetic'):
            raise ValueError('task_mode_mismatch')

    def _task_action(self, db, mode, binding):
        row = db.execute('SELECT payload,status FROM tasks WHERE id=?', (binding['task_id'],)).fetchone()
        if not row:
            raise ValueError('task_not_found')
        data = json.loads(row[0]).get('input', {})
        self._task_mode(data, mode)
        if row[1] == 'cancelled':
            raise ValueError('task_cancelled')
        if digest(data) != binding['task_input_sha256']:
            raise ValueError('task_input_changed')
        actions = data.get('budget_actions')
        if type(actions) is not list or not actions or len(actions) > 100:
            raise ValueError('action_not_found')
        ids = []
        for action in actions:
            if (type(action) is not dict or set(action) != {'id', 'kind', 'role', 'input'}
                    or type(action.get('input')) is not dict or action.get('kind') not in KINDS):
                raise ValueError('invalid_task_actions')
            ids.append(text(action['id'], 'invalid_task_actions'))
            text(action['role'], 'invalid_task_actions')
        if len(set(ids)) != len(ids):
            raise ValueError('invalid_task_actions')
        matched = [a for a in actions if a['id'] == binding['action_id']]
        if not matched:
            raise ValueError('action_not_found')
        action = matched[0]
        if digest(action['input']) != binding['action_input_sha256']:
            raise ValueError('action_input_changed')
        return action

    def _gate(self, db, mode, binding, expected_revision):
        state = self._summary(db, mode); policy = state['policy']
        if not policy['configured']:
            raise ValueError('policy_unconfigured')
        if policy['revision'] != expected_revision:
            raise ValueError('policy_version_conflict')
        action = self._task_action(db, mode, binding)
        if binding['task_id'] not in policy['task_ids']:
            raise ValueError('task_out_of_scope')
        if policy['halted']:
            raise ValueError('budget_halted')
        return state, action

    def reserve(self, mode, binding, amount_cny, expected_policy_revision, idempotency_key, source_currency='CNY', conversion=None):
        mode_value(mode); binding = binding_value(binding); amount = money(amount_cny)
        integer(expected_policy_revision, 'invalid_policy_revision')
        conversion = conversion_value(source_currency, conversion, amount)
        request = dict(operation='reserve', binding=binding, amount_minor=amount, expected_policy_revision=expected_policy_revision,
                       source_currency=source_currency, conversion=conversion)
        with self.core.atomic() as db:
            replay = self._replay(db, mode, idempotency_key, request)
            if replay:
                return replay
            state, action = self._gate(db, mode, binding, expected_policy_revision)
            if db.execute('SELECT 1 FROM operating_budget_records WHERE mode=? AND task_id=? AND action_id=?',
                          (mode, binding['task_id'], binding['action_id'])).fetchone():
                raise ValueError('action_already_bound')
            if state['usage']['exposure_minor'] + amount > state['policy']['cap_minor']:
                raise ValueError('budget_cap_exceeded')
            ident = uuid.uuid4().hex
            record = dict(id=ident, mode=mode, binding=binding, kind=action['kind'], role=action['role'], revision=1, status='RESERVED',
                          reserved_minor=amount, paid_minor=0, refunded_minor=0, paid_receipt_id=None,
                          source_currency=source_currency, conversion=conversion, policy_revision=expected_policy_revision,
                          stable_external_key='budget:' + ident, created_at=time.time())
            db.execute('INSERT INTO operating_budget_records VALUES(?,?,?,?,?)', (ident, mode, binding['task_id'], binding['action_id'], canonical(record)))
            return self._receipt(db, mode, idempotency_key, request, dict(self._summary(db, mode), record=record), 'reserve', ident)

    @staticmethod
    def _external(db, mode, event, ident, evidence):
        if type(evidence) is not dict or set(evidence) != {'source', 'external_id', 'record_sha256'}:
            raise ValueError('financial_evidence_required')
        text(evidence['source'], 'financial_evidence_required')
        text(evidence['external_id'], 'financial_evidence_required')
        if type(evidence['record_sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', evidence['record_sha256']):
            raise ValueError('financial_evidence_required')
        if db.execute('SELECT 1 FROM operating_budget_external_records WHERE mode=? AND kind=? AND source=? AND external_id=?',
                      (mode, event, evidence['source'], evidence['external_id'])).fetchone():
            raise ValueError('duplicate_external_record')
        db.execute('INSERT INTO operating_budget_external_records VALUES(?,?,?,?,?)',
                   (mode, event, evidence['source'], evidence['external_id'], ident))

    def transition(self, mode, reservation_id, binding, event, expected_revision, idempotency_key,
                   expected_policy_revision=None, amount_cny=None, evidence=None, paid_receipt_id=None):
        mode_value(mode); text(reservation_id, 'invalid_reservation_id'); binding = binding_value(binding)
        integer(expected_revision, 'invalid_record_revision', 1)
        if event not in EVENTS or type(event) is not str:
            raise ValueError('invalid_budget_event')
        if expected_policy_revision is not None:
            integer(expected_policy_revision, 'invalid_policy_revision')
        amount = money(amount_cny) if amount_cny is not None else None
        if (event in ('paid', 'refund')) != (amount is not None) or amount == 0:
            raise ValueError('invalid_event_amount')
        if event != 'refund' and paid_receipt_id is not None:
            raise ValueError('unexpected_paid_receipt')
        request = dict(operation=event, reservation_id=reservation_id, binding=binding, expected_revision=expected_revision,
                       expected_policy_revision=expected_policy_revision, amount_minor=amount, evidence=evidence, paid_receipt_id=paid_receipt_id)
        try:
            request = json.loads(canonical(request))
        except (TypeError, ValueError):
            raise ValueError('invalid_event_evidence') from None
        evidence = request['evidence']
        with self.core.atomic() as db:
            replay = self._replay(db, mode, idempotency_key, request)
            if replay:
                return replay
            row = db.execute('SELECT document FROM operating_budget_records WHERE id=? AND mode=?', (reservation_id, mode)).fetchone()
            if not row:
                raise ValueError('record_not_found')
            record = json.loads(row[0])
            if record['binding'] != binding:
                raise ValueError('binding_mismatch')
            if record['revision'] != expected_revision:
                raise ValueError('record_version_conflict')
            allowed = {'intent': ('RESERVED',), 'unknown': ('INTENT',), 'paid': ('INTENT', 'UNKNOWN'),
                       'release': ('RESERVED',), 'refund': ('PAID',)}
            if record['status'] not in allowed[event]:
                raise ValueError('invalid_transition')
            receipt_id = uuid.uuid4().hex
            if event == 'intent':
                integer(expected_policy_revision, 'invalid_policy_revision')
                state, _ = self._gate(db, mode, binding, expected_policy_revision)
                if state['usage']['exposure_minor'] > state['policy']['cap_minor']:
                    raise ValueError('budget_cap_exceeded')
                record['status'] = 'INTENT'
                record['intent_policy_revision'] = expected_policy_revision
            elif event in ('unknown', 'release'):
                if type(evidence) is not dict or set(evidence) != {'reason'}:
                    raise ValueError('event_reason_required')
                text(evidence['reason'], 'event_reason_required', 1000)
                record['status'] = 'UNKNOWN' if event == 'unknown' else 'RELEASED'
            else:
                if event == 'refund':
                    if paid_receipt_id != record['paid_receipt_id']:
                        raise ValueError('paid_receipt_mismatch')
                    if record['refunded_minor'] + amount > record['paid_minor']:
                        raise ValueError('refund_exceeds_paid')
                self._external(db, mode, event, reservation_id, evidence)
                if event == 'paid':
                    record.update(status='PAID', paid_minor=amount, paid_receipt_id=receipt_id)
                    if amount > record['reserved_minor']:
                        policy = self._policy(db, mode)
                        policy.update(halted=True, halt_reason='actual_exceeds_reservation', halt_receipt_id=receipt_id)
                        db.execute('UPDATE operating_budget_policies SET document=? WHERE mode=?', (canonical(policy), mode))
                else:
                    record['refunded_minor'] += amount
            record.update(revision=expected_revision + 1, updated_at=time.time())
            db.execute('UPDATE operating_budget_records SET document=? WHERE id=?', (canonical(record), reservation_id))
            value = dict(self._summary(db, mode), record=record, evidence=evidence)
            return self._receipt(db, mode, idempotency_key, request, value, event, reservation_id, receipt_id)

    def ledger(self, mode, task_id=None, offset=0, limit=50):
        mode_value(mode); integer(offset, 'invalid_ledger_page'); integer(limit, 'invalid_ledger_page', 1)
        if limit > 100:
            raise ValueError('invalid_ledger_page')
        if task_id is not None:
            text(task_id, 'invalid_task_id')
        where = 'mode=?' + (' AND task_id=?' if task_id is not None else '')
        params = (mode, task_id) if task_id is not None else (mode,)
        with self.core.db() as db:
            if not db.in_transaction:
                db.execute('BEGIN')
            total = db.execute('SELECT count(*) FROM operating_budget_records WHERE ' + where, params).fetchone()[0]
            records = [json.loads(row[0]) for row in db.execute('SELECT document FROM operating_budget_records WHERE ' + where + ' ORDER BY rowid LIMIT ? OFFSET ?', (*params, limit, offset))]
            ids = [r['id'] for r in records]
            events = [json.loads(row[0]) for row in db.execute('SELECT receipt FROM operating_budget_receipts WHERE mode=? AND record_id IN (' + ','.join('?' for _ in ids) + ') ORDER BY rowid', (mode, *ids))] if ids else []
            return dict(self._summary(db, mode), records=records, events=events, total=total, offset=offset, limit=limit,
                        next_offset=offset + len(records) if offset + len(records) < total else None)
