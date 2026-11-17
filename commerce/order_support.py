"""Exact order snapshots linked to existing immutable local support drafts."""
from copy import deepcopy
import json
import re

from business_workflows.store import digest, encoded, text
from commerce_core import PLATFORMS


class OrderSupport:
    def __init__(self, service):
        self.service, self.core, self.business = service, service.core, service.business
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS order_support_drafts(draft_id TEXT PRIMARY KEY,context TEXT NOT NULL)')

    @staticmethod
    def _scope(demo, platform, store_id, market):
        if type(demo) is not bool or platform not in (*PLATFORMS, 'local'):
            raise ValueError('order_support_scope_mismatch')
        for value in (store_id, market):
            if type(value) is not str or not value.strip() or value == 'all' or len(value) > 160 or any(ord(c) < 32 for c in value):
                raise ValueError('order_support_scope_mismatch')
        if not re.fullmatch('[A-Z]{2}', market):
            raise ValueError('order_support_scope_mismatch')
        return {'demo': demo, 'platform': platform, 'store_id': store_id, 'market': market}

    def _current(self, demo, platform, store_id, market, order_id, import_batch_id=None, expected_source_sha256=None):
        scope = self._scope(demo, platform, store_id, market)
        text(order_id, 300)
        filters = {**scope}
        batch = None
        if import_batch_id is not None:
            text(import_batch_id)
            batch = self.service.order_imports.get(import_batch_id)
            expected_scope = {'platform': platform, 'store_ref': store_id, 'market': market}
            if batch['synthetic'] != demo or batch['scope'] != expected_scope:
                raise ValueError('order_support_scope_mismatch')
            filters['import_batch_id'] = import_batch_id
        # CSV references use their reviewed private scope, independent of the fixed platform-store filter enum.
        response = self.service.order_imports.orders(import_batch_id, filters) if import_batch_id else self.service.invoke('commerce_orders_list', filters)
        matches = [r for r in response['orders'] if r['id'] == order_id]
        if len(matches) != 1:
            raise ValueError('order_support_source_unavailable')
        row = matches[0]
        if any(row.get(k) != scope[k] for k in ('platform', 'store_id', 'market')):
            raise ValueError('order_support_scope_mismatch')
        if response.get('scope_confirmed') is False:
            raise ValueError('order_support_scope_unconfirmed')
        if row.get('stale') or response.get('stale'):
            raise ValueError('order_support_source_stale')
        if bool(row.get('batch_id')) != bool(import_batch_id) or row.get('batch_id') != import_batch_id:
            raise ValueError('order_support_scope_mismatch')
        fingerprint = row.get('source_sha256') or (digest(row) if demo else None)
        if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', fingerprint):
            raise ValueError('order_support_source_unavailable')
        if expected_source_sha256 is not None and expected_source_sha256 != fingerprint:
            raise ValueError('order_support_source_changed')
        order_ref = row.get('order_id', row['id'])
        text(order_ref)
        body = {'schema': 'commerce-order-support-context-v1', 'scope': scope,
                'order': {'id': row['id'], 'order_id': order_ref, 'line_id': row.get('line_id'),
                          'source_sha256': fingerprint, 'record_sha256': digest(row),
                          'import_batch_id': import_batch_id, 'batch_sha256': batch['sha256'] if batch else None},
                'source': {'data_source': response.get('data_source', row.get('data_source', 'unknown')),
                           'observed_at': row.get('observed_at', response.get('observed_at'))}}
        return {**body, 'context_sha256': digest(body)}

    def _check(self, context):
        if type(context) is not dict or set(context) != {'schema', 'scope', 'order', 'source', 'context_sha256'}:
            raise ValueError('order_support_invalid_context')
        body = {k: v for k, v in context.items() if k != 'context_sha256'}
        if context['schema'] != 'commerce-order-support-context-v1' or context['context_sha256'] != digest(body):
            raise ValueError('order_support_invalid_context')
        scope, order = context['scope'], context['order']
        if type(scope) is not dict or set(scope) != {'demo', 'platform', 'store_id', 'market'} or type(order) is not dict or set(order) != {'id', 'order_id', 'line_id', 'source_sha256', 'record_sha256', 'import_batch_id', 'batch_sha256'}:
            raise ValueError('order_support_invalid_context')
        current = self._current(**scope, order_id=order['id'], import_batch_id=order['import_batch_id'])
        if current != context:
            raise ValueError('order_support_source_changed')
        return current

    @staticmethod
    def _eligible(source, context):
        doc = source.get('document', source)
        scope, order = context['scope'], context['order']
        return doc['kind'] in ('conversation', 'facts') and doc['synthetic'] == scope['demo'] and doc['scope'] == {
            'platform': scope['platform'], 'store_ref': scope['store_id'], 'subject_ref': order['order_id']}

    def prepare(self, demo, platform, store_id, market, order_id, expected_source_sha256=None, import_batch_id=None):
        context = self._current(demo, platform, store_id, market, order_id, import_batch_id, expected_source_sha256)
        candidates = [s for s in self.business.listing(demo)['sources'] if self._eligible(s, context)]
        return {'context': context, 'sources': candidates, 'external_execution_allowed': False,
                'notice': '仅接续本机草稿。请选择已导入的同订单会话与事实；事实须明确包含 order_ref 和 market。'}

    def _selected(self, refs, context):
        if type(refs) is not list or not 2 <= len(refs) <= 20:
            raise ValueError('order_support_sources_required')
        ids, sources = set(), []
        for ref in refs:
            if type(ref) is not dict or set(ref) != {'id', 'version', 'sha256'} or type(ref['id']) is not str or ref['id'] in ids or type(ref['version']) is not int or ref['version'] < 1 or type(ref['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', ref['sha256']):
                raise ValueError('order_support_invalid_sources')
            ids.add(ref['id']);source = self.business.source(ref['id'])
            if any(source[k] != ref[k] for k in ('id', 'version', 'sha256')):
                raise ValueError('order_support_source_changed')
            if not source['fresh']:
                raise ValueError('order_support_source_stale')
            if not self._eligible(source, context):
                raise ValueError('order_support_scope_mismatch')
            sources.append(source)
        if not any(s['document']['kind'] == 'conversation' for s in sources):
            raise ValueError('order_support_conversation_required')
        facts = [s for s in sources if s['document']['kind'] == 'facts']
        if not facts:
            raise ValueError('order_support_facts_required')
        for source in facts:
            values = {r['key']: r['value'] for r in source['document']['records']}
            if values.get('order_ref') != context['order']['order_id']:
                raise ValueError('order_support_order_mismatch')
            if values.get('market') != context['scope']['market']:
                raise ValueError('order_support_market_mismatch')
        return sources

    def draft(self, context, source_refs, content, idempotency_key, parent_id=None, expected_parent_sha256=None):
        text(idempotency_key)
        if (parent_id is None) != (expected_parent_sha256 is None):
            raise ValueError('order_support_parent_changed')
        payload = {'action': 'order_support_draft', 'context': context, 'source_refs': source_refs,
                   'content': content, 'parent_id': parent_id, 'expected_parent_sha256': expected_parent_sha256}
        with self.core.atomic() as db:
            def make():
                self._check(context)
                sources = self._selected(source_refs, context)
                if type(content) is not dict or type(content.get('fields')) is not dict or content['fields'].get('conversation_ref') != context['order']['order_id']:
                    raise ValueError('order_support_order_mismatch')
                if parent_id is not None:
                    parent = self.business.get(parent_id)
                    link = self._link(parent_id)
                    if not link or link != context or parent['draft']['draft_sha256'] != expected_parent_sha256:
                        raise ValueError('order_support_parent_changed')
                result = self.business.draft('support', [s['id'] for s in sources], content,
                                             'order-support-inner-' + digest(idempotency_key), parent_id)
                db.execute('INSERT INTO order_support_drafts VALUES (?,?)', (result['id'], encoded(context)))
                return {'draft_id': result['id']}
            result = self.business._once(db, 'order-support-' + digest(idempotency_key), payload, make)
        return self.decorate(self.business.get(result['draft_id']))

    def _link(self, draft_id):
        with self.core.db() as db:
            row = db.execute('SELECT context FROM order_support_drafts WHERE draft_id=?', (draft_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def decorate(self, result):
        context = self._link(result['id'])
        if context is None:
            return result
        shown = deepcopy(result)
        try:
            self._check(context)
            status, reason = 'current', None
        except ValueError as exc:
            status, reason = 'stale', str(exc)
        shown['order_context'] = {'context': context, 'status': status, 'reason': reason}
        shown['preflight']['order_context_status'] = status
        if status != 'current':
            shown['status'] = 'stale'
            shown['preflight'].update(status='stale', ready_for_local_review=False)
        return shown

    def decorate_listing(self, board):
        shown = deepcopy(board)
        checked = {}
        for summary in shown['drafts']:
            context = self._link(summary['id'])
            if context is None:
                continue
            key = context['context_sha256']
            if key not in checked:
                try:
                    self._check(context)
                    checked[key] = ('current', None)
                except ValueError as exc:
                    checked[key] = ('stale', str(exc))
            status, reason = checked[key]
            summary.update(order_context_status=status, order_context_reason=reason)
            if status != 'current':
                summary['status'] = 'stale'
        return shown

    def legacy_draft(self, **args):
        if args.get('parent_id') and self._link(args['parent_id']) is not None:
            raise ValueError('order_support_bound_draft_required')
        return self.business.draft(**args)

    def review(self, **args):
        with self.core.atomic() as _:
            context = self._link(args['draft_id'])
            if context is not None and args.get('decision') == 'reviewed':
                self._check(context)
            return self.business.review(**args, _reuse=True)

    def export(self, draft_id):
        result = self.business.export(draft_id)
        if self._link(draft_id) is None:
            return result
        artifact = json.loads(result['content'])
        artifact['draft'] = self.decorate(artifact['draft'])
        return {**result, 'content': json.dumps(artifact, ensure_ascii=False, indent=2), 'sha256': digest(artifact)}

    def invoke(self, name, args):
        return {'prepare': self.prepare, 'draft': self.draft}[name.removeprefix('commerce_order_support_')](**args)


def definitions(schema):
    string = {'type': 'string', 'minLength': 1, 'maxLength': 300}
    sha = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
    return [
        ('commerce_order_support_prepare', '从准确订单及来源快照准备本机客服接续，返回同订单已导入资料；不创建会话或发送消息。', schema({
            'demo': {'type': 'boolean'}, 'platform': {'type': 'string', 'enum': [*PLATFORMS, 'local']},
            'store_id': string, 'market': {'type': 'string', 'pattern': '^[A-Z]{2}$'}, 'order_id': string,
            'expected_source_sha256': sha, 'import_batch_id': string}, ['demo', 'platform', 'store_id', 'market', 'order_id'])),
        ('commerce_order_support_draft', '复核准确订单、范围、引用版本及市场事实后保存本机客服草稿；不向买家或平台发送。', schema({
            'context': {'type': 'object'}, 'source_refs': {'type': 'array', 'minItems': 2, 'maxItems': 20, 'items': {
                'type': 'object', 'properties': {'id': string, 'version': {'type': 'integer', 'minimum': 1}, 'sha256': sha},
                'required': ['id', 'version', 'sha256'], 'additionalProperties': False}},
            'content': {'type': 'object'}, 'idempotency_key': string, 'parent_id': string, 'expected_parent_sha256': sha},
            ['context', 'source_refs', 'content', 'idempotency_key'])),
    ]
