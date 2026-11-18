"""Phone decision cards for operating-loop proposals.

A card binds one work item, one proposal, the exact result hash, the owner, the
private identity policy revision and an expiry. Buttons carry only a random
nonce. Approval calls the loop's own decide(), which reuses the original review
path and re-checks evidence; nothing here creates tasks or executes anything
itself. This module is reached only through the authenticated SDK adapter in
mobile_control; it is not an MCP tool. Building a card does not send it.
"""
import re
import secrets
import time
import uuid

from mobile_control import canonical, sha, iso

OWNERS = {'observer': '观察与复盘', 'scout': '市场调研', 'economist': '经济测算', 'sourcer': '供应链资料', 'creative': '创意与交付',
          'localizer': '语言与字段', 'gatekeeper': '规则与合规核查', 'grower': '增长方案', 'fulfiller': '库存与履约观察',
          'voice': '客户之声', 'controller': '财务控制', 'conductor': '编排协调'}


class LoopMobileDecisions:
    def __init__(self, service):
        self.service, self.core, self.loop = service, service.core, service.operating_loop
        with self.core.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS loop_mobile_decisions(
                id TEXT PRIMARY KEY, work_id TEXT NOT NULL, proposal_id TEXT NOT NULL, result_sha256 TEXT NOT NULL,
                owner_sha256 TEXT NOT NULL, policy_sha256 TEXT NOT NULL, expires REAL NOT NULL,
                state TEXT NOT NULL, reason TEXT, created REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS loop_mobile_nonces(
                token_sha256 TEXT PRIMARY KEY, decision_id TEXT NOT NULL, choice TEXT NOT NULL)''')

    def _current(self, work_id):
        return next((w for w in self.loop.get()['work'] if w['id'] == work_id), None)

    def prepare(self, work_id, proposal_id, owner, policy, ttl_seconds=900):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError('invalid_mobile_expiry')
        work = self._current(work_id)
        if not work or work['status'] != 'awaiting_decision' or not work.get('result_sha256'):
            raise ValueError('loop_mobile_not_awaiting_decision')
        proposal = next((p for p in work.get('proposals') or [] if p['id'] == proposal_id), None)
        if not proposal:
            raise ValueError('loop_mobile_proposal_not_found')
        grant = next((g for g in self.loop.get(work['grant_id'])['grants']), None)
        label = (grant or {}).get('case_label') or '商品待核对'
        with self.core.atomic() as db:
            if db.execute("SELECT 1 FROM loop_mobile_decisions WHERE work_id=? AND (state IN ('deciding','approved','rejected') "
                          "OR (state='pending' AND expires>?))", (work_id, time.time())).fetchone():
                raise ValueError('loop_mobile_decision_already_exists')
            ident, expires = 'loop_mobile_' + uuid.uuid4().hex, time.time() + ttl_seconds
            db.execute('INSERT INTO loop_mobile_decisions VALUES (?,?,?,?,?,?,?,?,NULL,?)',
                       (ident, work_id, proposal_id, work['result_sha256'], sha(owner), sha(policy), expires, 'pending', time.time()))
            nonces = []
            for choice in ('approve', 'reject'):
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO loop_mobile_nonces VALUES (?,?,?)', (sha(token), ident, choice))
                nonces.append(token)
        description = '\n'.join([
            '商品：' + label, '阶段：' + work['stage_name'], '负责岗位：' + OWNERS.get(work['owner'], work['owner']),
            '建议：' + proposal['reason'][:300],
            '批准后：登记一条原岗位交接任务；交易金额 0 CNY，不执行店铺、付款或消息操作。',
            '结果版本 ' + work['result_sha256'][:16], '有效期 ' + iso(expires)])
        card = {'config': {'wide_screen_mode': True},
                'header': {'title': {'tag': 'plain_text', 'content': '经营回路建议待决定'}},
                'elements': [{'tag': 'div', 'text': {'tag': 'plain_text', 'content': description}},
                             {'tag': 'action', 'actions': [
                                 {'tag': 'button', 'text': {'tag': 'plain_text', 'content': text}, 'type': style, 'value': {'nonce': token}}
                                 for text, style, token in zip(('批准交接', '驳回'), ('primary', 'default'), nonces)]}]}
        return {'schema': 'commerce-loop-mobile-card-v1', 'decision_id': ident, 'work_id': work_id, 'proposal_id': proposal_id,
                'result_sha256': work['result_sha256'], 'amount': 0, 'currency': 'CNY', 'expires_at': iso(expires),
                'card': card, 'delivery_status': 'not_sent', 'external_operations_executed': False}

    @staticmethod
    def _row(db, ident):
        columns = 'id,work_id,proposal_id,result_sha256,owner_sha256,policy_sha256,expires,state,reason'
        row = db.execute('SELECT ' + columns + ' FROM loop_mobile_decisions WHERE id=?', (ident,)).fetchone()
        if not row: raise ValueError('loop_mobile_decision_not_found')
        return dict(zip(columns.split(','), row))

    def decide(self, nonce, owner, policy):
        """Return None when the nonce is not one of ours, so the caller can reject it."""
        if not isinstance(nonce, str) or not re.fullmatch('[A-Za-z0-9_-]{43}', nonce):
            return None
        claimed = None
        with self.core.atomic() as db:
            token = db.execute('SELECT decision_id,choice FROM loop_mobile_nonces WHERE token_sha256=?', (sha(nonce),)).fetchone()
            if not token:
                return None
            ident, choice = token
            row = self._row(db, ident)
            if row['owner_sha256'] != sha(owner): raise ValueError('mobile_owner_mismatch')
            if row['state'] == 'pending':
                reason = None
                if row['policy_sha256'] != sha(policy): reason = 'identity_policy_changed'
                elif row['expires'] <= time.time(): reason = 'decision_expired'
                if reason:
                    db.execute("UPDATE loop_mobile_decisions SET state='blocked',reason=? WHERE id=?", (reason, ident))
                else:
                    # Claim before the loop call, which owns its own transactions. A crash
                    # here leaves 'deciding'; the receipt then reads the work item itself.
                    db.execute("UPDATE loop_mobile_decisions SET state='deciding' WHERE id=?", (ident,))
                    claimed = (row, choice)
        if claimed:
            row, choice = claimed
            try:
                self.loop.decide(row['work_id'], choice, row['result_sha256'], row['proposal_id'] if choice == 'approve' else None)
                state, reason = ('approved' if choice == 'approve' else 'rejected'), None
            except ValueError as error:
                code = str(error)
                state, reason = 'blocked', code if re.fullmatch('[a-z_]{1,100}', code) else 'loop_decision_refused'
            with self.core.db() as db:
                db.execute("UPDATE loop_mobile_decisions SET state=?,reason=? WHERE id=? AND state='deciding'", (state, reason, ident))
        return self.receipt(ident)

    def receipt(self, decision_id):
        with self.core.db() as db:
            row = self._row(db, decision_id)
        work = self._current(row['work_id'])
        recorded = (work or {}).get('decision')
        status, reason, task_id = row['state'], row['reason'], None
        if status == 'pending' and row['expires'] <= time.time():
            status, reason = 'expired', 'decision_expired'
        elif status in ('deciding', 'approved', 'rejected'):
            # The work item is the record of what happened; this row is only the card.
            if not recorded:
                status, reason = 'unknown', 'loop_decision_receipt_missing_no_automatic_retry'
            else:
                status = 'approved' if recorded['decision'] == 'approve' else 'rejected'
                task_id = recorded.get('task_id')
        return {'schema': 'commerce-loop-mobile-receipt-v1', 'decision_id': row['id'], 'work_id': row['work_id'],
                'status': status, 'reason': reason, 'handoff_task_id': task_id,
                'work_status': (work or {}).get('status'), 'delivery_status': 'not_sent',
                'external_operations_executed': False}
