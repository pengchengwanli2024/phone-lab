"""Local mobile command contracts; transport authentication belongs to the SDK.

No listener, scheduler, external sender, financial approval or second executor.
Only the trusted SDK owner adapter can consume a target-bound button nonce.
Do not expose FeishuSDKAdapter or its methods as HTTP/MCP tools.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import secrets
import time
import uuid

from operations_analysis import unit_economics

INTENTS = ('new_task', 'research_request', 'feature_suggestion', 'status', 'budget_query', 'pause_request')
COMMAND_SCHEMA = 'commerce-mobile-command-v1'
UNIMPLEMENTED = ['external_payment', 'procurement', 'advertising', 'listing_submission',
                 'customer_message_send', 'warehouse_execution', 'remote_runtime_pause',
                 'notification_send', 'phone_delivery_confirmation']
PREFIXES = {'新任务': 'new_task', '研究请求': 'research_request', '功能建议': 'feature_suggestion',
            '状态': 'status', '预算查询': 'budget_query', '暂停请求': 'pause_request'}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def bounded(value, maximum=160):
    return isinstance(value, str) and 0 < len(value) <= maximum and bool(value.strip()) and not any(ord(c) < 32 for c in value)


def definitions(schema, string):
    """Optional root integration: these tools never accept a decision or identity."""
    return [
        ('commerce_mobile_command', '记录真实范围的本机手机指挥意图或查询；创建待办不代表执行，暂停仅为请求',
         schema({'command': {'type': 'object'}, 'idempotency_key': string}, ['command', 'idempotency_key'])),
        ('commerce_mobile_receipt_get', '读取本地指挥收件回执，不证明手机实收',
         schema({'receipt_id': string}, ['receipt_id'])),
        ('commerce_mobile_decision_get', '读取准确本地决策与原任务接续结果；不接受批准',
         schema({'decision_id': string}, ['decision_id'])),
        ('commerce_mobile_project', '只读投影原领域待审对象；不授予外部执行权限',
         schema({'kind': {'type': 'string', 'enum': ['attention', 'followup', 'order_support', 'listing']},
                 'reference': {'type': ['string', 'object']}}, ['kind', 'reference'])),
    ]


class MobileControl:
    def __init__(self, service, *, budget_reader=None):
        self.service, self.core, self.budget_reader = service, service.core, budget_reader
        # Other domains may own decision cards; each returns None for a nonce that is not theirs.
        self.deciders = []
        with self.core.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS mobile_inbox(
                id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
                task_id TEXT, receipt TEXT NOT NULL, created REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS mobile_sdk_messages(
                message_key TEXT PRIMARY KEY, owner_sha256 TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS mobile_decisions(
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, target TEXT NOT NULL,
                owner_sha256 TEXT NOT NULL, policy_sha256 TEXT NOT NULL, expires REAL NOT NULL,
                state TEXT NOT NULL, reason TEXT, continuation_task_id TEXT, created REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS mobile_nonces(
                token_sha256 TEXT PRIMARY KEY, decision_id TEXT NOT NULL, choice TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS mobile_sdk_events(
                event_key TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
                state TEXT NOT NULL, receipt TEXT, created REAL NOT NULL)''')

    def invoke(self, name, args):
        methods = {'commerce_mobile_command': lambda **a: self.receive(**a),
                   'commerce_mobile_receipt_get': self.receipt_get,
                   'commerce_mobile_decision_get': self.decision_get,
                   'commerce_mobile_project': self.project}
        if name not in methods:
            raise ValueError('unknown_mobile_tool')
        return methods[name](**args)

    def receive(self, command, idempotency_key):
        if (type(command) is not dict or set(command) != {'schema', 'intent', 'text'}
                or command['schema'] != COMMAND_SCHEMA or command['intent'] not in INTENTS
                or type(command['text']) is not str or len(command['text']) > 6000
                or not bounded(idempotency_key)):
            raise ValueError('invalid_mobile_command')
        request = canonical(command)
        with self.core.atomic(reuse=True) as db:
            row = db.execute('SELECT request,receipt FROM mobile_inbox WHERE idem=?', (idempotency_key,)).fetchone()
            if row:
                if row[0] != request: raise ValueError('idempotency_conflict')
                return json.loads(row[1])
            ident, task_id, result = 'mobile_receipt_' + uuid.uuid4().hex, None, None
            intent = command['intent']
            if intent == 'status':
                result = {'task_counts': dict(db.execute('SELECT status,count(*) FROM tasks GROUP BY status')),
                          'scope': 'local_core_tasks', 'live_external_state': 'not_checked'}
            elif intent == 'budget_query':
                # Root owns the shared budget ledger. This module never invents or changes it.
                value = self.budget_reader() if self.budget_reader else None
                fields = ('schema', 'status', 'currency', 'total_limit', 'remaining', 'period', 'source_sha256')
                result = {k: value[k] for k in fields if k in value} if isinstance(value, dict) else {
                    'status': 'unknown', 'remaining': None, 'reason': 'shared_budget_reader_not_integrated'}
            else:
                task = self.service.invoke('commerce_task_create', {
                    'idempotency_key': 'mobile-command:' + sha(idempotency_key), 'kind': 'analysis',
                    'input': {'demo': False, 'title': PREFIXES_TITLE[intent], 'mobile_receipt_id': ident,
                              'mobile_intent': intent, 'request_text': command['text'],
                              'execution': 'not_requested', 'instruction_trust': 'business_data_only'}})
                task_id = task['id']
            receipt = {'schema': 'commerce-mobile-receipt-v1', 'receipt_id': ident, 'intent': intent,
                       'task_id': task_id, 'status': 'queried' if result is not None else 'recorded_not_executed',
                       'result': result, 'external_operations_executed': False,
                       'delivery_status': 'not_sent', 'recorded_at': iso(time.time()),
                       'unimplemented_external_actions': UNIMPLEMENTED}
            db.execute('INSERT INTO mobile_inbox VALUES (?,?,?,?,?,?)',
                       (ident, idempotency_key, request, task_id, canonical(receipt), time.time()))
        return receipt

    def receipt_get(self, receipt_id):
        with self.core.db() as db:
            row = db.execute('SELECT receipt FROM mobile_inbox WHERE id=?', (receipt_id,)).fetchone()
        if not row: raise ValueError('mobile_receipt_not_found')
        return json.loads(row[0])

    def _local_target(self, db, task_id, parameters):
        owned = db.execute('SELECT task_id FROM mobile_inbox WHERE task_id=?', (task_id,)).fetchone()
        if not owned: raise ValueError('mobile_operation_not_supported')
        task = self.core.invoke('commerce_task_get', {'task_id': task_id})
        if task['status'] != 'queued' or db.execute('SELECT 1 FROM task_runs WHERE task_id=?', (task_id,)).fetchone():
            raise ValueError('mobile_source_not_resumable')
        calculated = unit_economics(parameters)
        if calculated['status'] != 'CALCULATED': raise ValueError('mobile_calculation_incomplete')
        target = {'kind': 'local_task', 'task_id': task_id, 'task_sha256': sha(task),
                  'operation': 'unit_economics', 'parameters': parameters}
        target['version_sha256'] = sha(target)
        return target

    def _prepare_local(self, task_id, parameters, owner, policy, ttl_seconds):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError('invalid_mobile_expiry')
        # Copy inputs before validating/storing, so caller mutations cannot retarget a card.
        parameters = json.loads(canonical(parameters))
        with self.core.atomic() as db:
            target = self._local_target(db, task_id, parameters)
            old = db.execute('''SELECT 1 FROM mobile_decisions WHERE task_id=? AND
                (continuation_task_id IS NOT NULL OR (state='pending' AND expires>?))''', (task_id, time.time())).fetchone()
            if old: raise ValueError('mobile_decision_already_exists')
            ident, expires = 'mobile_decision_' + uuid.uuid4().hex, time.time() + ttl_seconds
            db.execute('INSERT INTO mobile_decisions VALUES (?,?,?,?,?,?,?,NULL,NULL,?)',
                       (ident, task_id, canonical(target), sha(owner), sha(policy), expires, 'pending', time.time()))
            nonces = []
            for choice in ('approve', 'reject'):
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO mobile_nonces VALUES (?,?,?)', (sha(token), ident, choice))
                nonces.append(token)
        candidate = {'schema': 'commerce-mobile-candidate-v1', 'target': {k: v for k, v in target.items() if k != 'parameters'},
                     'status': 'pending', 'amount': 0, 'currency': 'CNY', 'actionable': True,
                     'input_amount': parameters['price'], 'input_currency': parameters['currency'],
                     'reason': '继续原待办的明确本地成本计算；金额为零表示不发生资金交易。',
                     'expires_at': iso(expires), 'external_execution_allowed': False}
        description = ('原任务 ' + task_id + '\n版本 ' + target['version_sha256'] +
                       '\n动作：本地成本计算；交易金额 0 CNY' + '\n输入售价 ' + str(parameters['price']) +
                       ' ' + parameters['currency'] + '\n' + candidate['reason'] + '\n有效期 ' + candidate['expires_at'])
        card = {'config': {'wide_screen_mode': True},
                'header': {'title': {'tag': 'plain_text', 'content': '本地任务接续确认'}},
                'elements': [{'tag': 'div', 'text': {'tag': 'plain_text', 'content': description}},
                             {'tag': 'action', 'actions': [
                                 {'tag': 'button', 'text': {'tag': 'plain_text', 'content': label},
                                  'type': style, 'value': {'nonce': token}}
                                 for label, style, token in zip(('确认本地计算', '拒绝'), ('primary', 'default'), nonces)]}]}
        return {'schema': 'commerce-mobile-card-v1', 'decision_id': ident, 'candidate': candidate,
                'card': card, 'delivery_status': 'not_sent', 'external_operations_executed': False}

    @staticmethod
    def _decision_row(db, decision_id):
        columns = 'id,task_id,target,owner_sha256,policy_sha256,expires,state,reason,continuation_task_id'
        row = db.execute('SELECT ' + columns + ' FROM mobile_decisions WHERE id=?', (decision_id,)).fetchone()
        if not row: raise ValueError('mobile_decision_not_found')
        return dict(zip(columns.split(','), row))

    def _decide(self, nonce, owner, policy):
        if not isinstance(nonce, str) or not re.fullmatch('[A-Za-z0-9_-]{43}', nonce):
            raise ValueError('mobile_nonce_invalid')
        dispatch = None
        with self.core.atomic() as db:
            token = db.execute('SELECT decision_id,choice FROM mobile_nonces WHERE token_sha256=?', (sha(nonce),)).fetchone()
        if not token:
            for decider in self.deciders:
                receipt = decider(nonce, owner, policy)
                if receipt is not None: return receipt
            raise ValueError('mobile_nonce_invalid')
        with self.core.atomic() as db:
            ident, choice = token
            row = self._decision_row(db, ident)
            if row['owner_sha256'] != sha(owner): raise ValueError('mobile_owner_mismatch')
            if row['state'] == 'pending':
                reason = None
                if row['policy_sha256'] != sha(policy): reason = 'identity_policy_changed'
                elif row['expires'] <= time.time(): reason = 'decision_expired'
                else:
                    target = json.loads(row['target'])
                    try: current = self._local_target(db, row['task_id'], target['parameters'])
                    except ValueError: current = None
                    if current != target: reason = 'source_changed_or_not_resumable'
                if reason:
                    db.execute("UPDATE mobile_decisions SET state='blocked',reason=? WHERE id=?", (reason, ident))
                elif choice == 'reject':
                    db.execute("UPDATE mobile_decisions SET state='rejected' WHERE id=?", (ident,))
                else:
                    # Original domain creates its own immutable continuation. No parallel task engine.
                    child = self.service.invoke('commerce_task_continue', {'task_id': row['task_id'],
                        'operation': 'unit_economics', 'input': {'parameters': target['parameters']},
                        'idempotency_key': 'mobile-continuation:' + ident})
                    db.execute("UPDATE mobile_decisions SET state='dispatching',continuation_task_id=? WHERE id=?", (child['id'], ident))
                    dispatch = child['id']
        if dispatch:
            # The existing request API owns its transaction. Commit intent first; never replay a
            # dispatching intent after a crash. decision_get only reads the original task receipt.
            try:
                self.service.invoke('commerce_task_execute', {'task_id': dispatch, 'operation': 'unit_economics'})
            except Exception:
                pass  # Missing receipt becomes UNKNOWN; raw transport errors can contain secrets.
        return self.decision_get(ident)

    def decision_get(self, decision_id):
        with self.core.db() as db:
            row = self._decision_row(db, decision_id)
            child = row['continuation_task_id']
            status, reason, result, result_sha = row['state'], row['reason'], None, None
            if child:
                try:
                    execution = self.service.invoke('commerce_task_result', {'task_id': child})
                except ValueError:
                    execution = None
                if execution is None:
                    status, reason = 'unknown', 'continuation_receipt_unavailable'
                else:
                    task, run = execution['task'], execution['execution']
                    target = json.loads(row['target'])
                    if (task.get('input', {}).get('predecessor_task_id') != row['task_id']
                            or task['input'].get('parameters') != target['parameters']
                            or (run and run['operation'] != 'unit_economics')):
                        status, reason = 'unknown', 'continuation_binding_changed'
                    elif not run:
                        status, reason = 'unknown', 'dispatch_receipt_missing_no_automatic_retry'
                    else:
                        status = {'queued': 'approved_queued', 'running': 'running', 'completed': 'completed',
                                  'failed': 'failed', 'interrupted': 'interrupted', 'cancelled': 'cancelled'}.get(task['status'], 'unknown')
                        output = run.get('result')
                        if status == 'completed' and (not run.get('finished_at') or not isinstance(output, dict) or output.get('status') != 'CALCULATED'):
                            status, reason = 'unknown', 'completed_result_missing_or_unconfirmed'
                        if isinstance(output, dict) and status == 'completed':
                            fields = ('model', 'status', 'currency', 'price', 'contribution', 'total_cost', 'contribution_rate', 'cost_breakdown')
                            result, result_sha = {k: output[k] for k in fields if k in output}, sha(output)
                        if status in ('failed', 'interrupted'): reason = 'original_local_task_' + status
            elif status == 'pending' and row['expires'] <= time.time():
                status, reason = 'expired', 'decision_expired'
        return {'schema': 'commerce-mobile-decision-receipt-v1', 'decision_id': row['id'],
                'original_task_id': row['task_id'], 'continuation_task_id': child, 'status': status,
                'reason': reason, 'result': result, 'result_sha256': result_sha,
                'external_operations_executed': False, 'delivery_status': 'not_sent',
                'unimplemented_external_actions': UNIMPLEMENTED}

    def project(self, kind, reference):
        """Read original domain objects, omit text/customer payloads, expose no buttons."""
        amount, currency, expires = None, None, None
        if kind in ('attention', 'followup', 'order_support') and not bounded(reference):
            raise ValueError('invalid_mobile_reference')
        if kind == 'attention':
            value = self.service.attention.get(reference)
            current = value['item']
            status = current['status']
            version = sha(current)
            target = {'kind': kind, 'ref': current['id'], 'source': current['source']}
        elif kind == 'followup':
            current = self.service.followups.get(reference)
            status, version = current['state'], sha(current)
            target = {'kind': kind, 'ref': current['id'], 'revision': current['revision']}
        elif kind == 'order_support':
            current = self.service.order_support.decorate(self.service.business.get(reference))
            if 'order_context' not in current: raise ValueError('mobile_domain_object_not_bound')
            status, version = current['status'], sha(current)
            target = {'kind': kind, 'ref': current['id'], 'context_sha256': current['order_context']['context']['context_sha256']}
        elif kind == 'listing':
            required = {'case_id', 'platform', 'store_ref', 'market'}
            if not isinstance(reference, dict) or set(reference) != required or any(not bounded(v) for v in reference.values()):
                raise ValueError('invalid_mobile_reference')
            current = self.service.listings.get(**reference)
            status = 'stale' if current['stale'] else 'local_preparation'
            version = current['preview_sha256']
            # Do not infer a transaction amount or currency from an unsubmitted price draft.
            target = {'kind': kind, 'target_sha256': sha(reference), 'revision': current['revision']}
        else:
            raise ValueError('mobile_operation_not_supported')
        return {'schema': 'commerce-mobile-candidate-v1', 'target': target, 'version_sha256': version,
                'status': status, 'amount': amount, 'currency': currency, 'expires_at': expires,
                'actionable': False, 'reason': 'original_domain_review_required_mobile_action_not_implemented',
                'external_execution_allowed': False}


PREFIXES_TITLE = {'new_task': '手机新任务', 'research_request': '手机研究请求',
                  'feature_suggestion': '手机功能建议', 'pause_request': '手机暂停请求（尚未执行）'}


class FeishuSDKAdapter:
    """Internal adapter for authenticated SDK long-connection callbacks ONLY.

    policy_reader reads private, locally administered app/tenant/owner/revision.
    Neither this constructor nor handle_sdk_event is a remote approval API.
    Dictionaries here are trusted SDK output, never ordinary caller assertions.
    """
    def __init__(self, mobile, policy_reader, *, app_id):
        self.mobile, self.policy_reader, self.app_id = mobile, policy_reader, app_id

    def _policy(self):
        policy = self.policy_reader()
        fields = {'app_id', 'tenant_key', 'owner_allowlist', 'revision'}
        if (not isinstance(policy, dict) or set(policy) != fields
                or not bounded(policy['app_id']) or not bounded(policy['tenant_key'])
                or not isinstance(policy['owner_allowlist'], list) or not policy['owner_allowlist']
                or any(not bounded(owner) for owner in policy['owner_allowlist'])
                or type(policy['revision']) is not int or policy['revision'] < 1):
            raise ValueError('mobile_identity_unconfigured')
        if policy['app_id'] != self.app_id: raise ValueError('mobile_sdk_app_mismatch')
        return json.loads(canonical(policy))

    def prepare_local(self, task_id, parameters, *, owner_open_id=None, ttl_seconds=900):
        policy = self._policy()
        if owner_open_id is None:
            if len(policy['owner_allowlist']) != 1: raise ValueError('mobile_owner_required')
            owner_open_id = policy['owner_allowlist'][0]
        if owner_open_id not in policy['owner_allowlist']: raise ValueError('mobile_owner_not_allowed')
        owner = [policy['app_id'], policy['tenant_key'], owner_open_id]
        return self.mobile._prepare_local(task_id, parameters, owner, policy, ttl_seconds)

    @staticmethod
    def _command(text):
        if not isinstance(text, str) or len(text) > 6050: raise ValueError('invalid_mobile_command')
        parts = text.strip().removeprefix('/').split(maxsplit=1)
        if not parts or parts[0] not in PREFIXES: raise ValueError('mobile_explicit_intent_required')
        return {'schema': COMMAND_SCHEMA, 'intent': PREFIXES[parts[0]], 'text': parts[1] if len(parts) > 1 else ''}

    def _receive_message(self, command, message_key, owner):
        with self.mobile.core.atomic() as db:
            old = db.execute('SELECT owner_sha256 FROM mobile_sdk_messages WHERE message_key=?', (message_key,)).fetchone()
            if old and old[0] != sha(owner): raise ValueError('mobile_message_conflict')
            if not old:
                db.execute('INSERT INTO mobile_sdk_messages VALUES (?,?)', (message_key, sha(owner)))
            return self.mobile.receive(command, message_key)

    def handle_sdk_event(self, envelope):
        policy = self._policy()
        try:
            if type(envelope) is not dict or envelope['schema'] != '2.0': raise ValueError()
            header, event = envelope['header'], envelope['event']
            kind, event_id = header['event_type'], header['event_id']
            if (header['app_id'] != self.app_id or header['tenant_key'] != policy['tenant_key']
                    or not bounded(event_id) or kind not in ('im.message.receive_v1', 'card.action.trigger')):
                raise ValueError()
            at = float(header['create_time'])
            if at >= 1e14: at /= 1e6
            elif at >= 1e11: at /= 1e3
            if not math.isfinite(at) or not -60 <= time.time() - at <= 300: raise ValueError()
            if kind == 'im.message.receive_v1':
                sender, message = event['sender'], event['message']
                owner_id = sender['sender_id']['open_id']
                if (sender['sender_type'] != 'user' or sender['tenant_key'] != policy['tenant_key']
                        or message['message_type'] != 'text' or message['chat_type'] != 'p2p'
                        or not bounded(message['message_id'])): raise ValueError()
                content = json.loads(message['content'])
                command = self._command(content['text'])
                message_key = 'feishu-message:' + sha([self.app_id, policy['tenant_key'], message['message_id']])
            else:
                operator = event['operator']; owner_id = operator['open_id']
                if operator['tenant_key'] != policy['tenant_key']: raise ValueError()
                if set(event['action']['value']) != {'nonce'}: raise ValueError()
                nonce = event['action']['value']['nonce']
            if owner_id not in policy['owner_allowlist']: raise ValueError()
            owner = [self.app_id, policy['tenant_key'], owner_id]
            event_key = sha([self.app_id, policy['tenant_key'], event_id])
            fingerprint = sha(envelope)
        except (ValueError, KeyError, TypeError, OverflowError):
            raise ValueError('mobile_sdk_identity_or_event_invalid') from None
        with self.mobile.core.atomic() as db:
            old = db.execute('SELECT request_sha256,state,receipt FROM mobile_sdk_events WHERE event_key=?', (event_key,)).fetchone()
            if old:
                if old[0] != fingerprint: raise ValueError('mobile_event_conflict')
                if old[1] == 'failed': raise ValueError(json.loads(old[2])['reason'])
                return json.loads(old[2]) if old[2] else {'status': 'unknown', 'reason': 'event_processing_no_automatic_retry',
                                                        'external_operations_executed': False}
            db.execute('INSERT INTO mobile_sdk_events VALUES (?,?,?,NULL,?)', (event_key, fingerprint, 'processing', time.time()))
        try:
            result = self._receive_message(command, message_key, owner) if kind == 'im.message.receive_v1' else self.mobile._decide(nonce, owner, policy)
        except ValueError as exc:
            # These are local contract codes, not provider payloads or exception text from I/O.
            code = str(exc)
            if not re.fullmatch('[a-z_]{1,100}', code): code = 'mobile_local_contract_failed'
            with self.mobile.core.db() as db:
                db.execute("UPDATE mobile_sdk_events SET state='failed',receipt=? WHERE event_key=?", (canonical({'reason': code}), event_key))
            raise ValueError(code) from None
        with self.mobile.core.db() as db:
            db.execute("UPDATE mobile_sdk_events SET state='completed',receipt=? WHERE event_key=?", (canonical(result), event_key))
        return result
