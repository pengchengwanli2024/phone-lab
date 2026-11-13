"""A selected product view over existing artifacts, forms, tasks and local drafts.

No parallel task ledger, scheduler, platform transport or model-owned permissions.
"""
from copy import deepcopy
import json
import math
import re
from operations_analysis import UNIT_FIELDS, RATES, unit_economics
from research import canonical, digest

FORMS = ('plan', 'cost', 'content', 'view')


def definitions(schema, string):
    selected = {'case_id': string}
    guarded = {**selected, 'expected_source_sha256': string,
               'expected_revision': {'type': 'integer', 'minimum': 0}}
    return [
        ('commerce_workspace_list', '读取当前连接下的商品工作项；不创建任务或读取店铺', schema()),
        ('commerce_workspace_get', '读取商品当前工作项及可选研究任务的只读历史产物；不改商品创建归属或标记事实已核实', schema({**selected, 'research_task_id': string}, ['case_id'])),
        ('commerce_workspace_save', '按来源版本与草稿修订保存商品目标、测算输入或内容编辑；不自动执行模型或任务', schema({**guarded, 'form': {'type': 'string', 'enum': list(FORMS)}, 'payload': {'type': 'object'}}, [*guarded, 'form', 'payload'])),
        ('commerce_workspace_calculate', '使用已保存同币种参数测算并交接到原商品工作项；来源变化拒绝，不创建采购或平台动作', schema(guarded, list(guarded))),
        ('commerce_workspace_submit_content', '按当前商品来源版本与已保存修订生成本地待审阅版本；不接受未保存字段，不提交平台', schema(guarded, list(guarded))),
        ('commerce_workspace_currency', '明确当前商品工作项的金额币种；按来源版本校验，不换汇或改价', schema({**selected, 'currency': {'type': 'string', 'pattern': '^[A-Z]{3}$'}, 'expected_source_sha256': string}, ['case_id', 'currency', 'expected_source_sha256'])),
    ]


class ProductWorkspace:
    def __init__(self, service):
        self.service = service
        self.core = service.core
        self.org = service.organization

    @staticmethod
    def label(case):
        return case['scope'].get('label') or case['scope'].get('sku') or '未命名商品'

    def listing(self):
        return {'items': [{'id': c['id'], 'name': self.label(c), 'platform': c['scope'].get('platform'),
                           'market': c['scope'].get('market'), 'candidate': c['scope'].get('origin') == 'research_candidate_not_inventory',
                           'synthetic': c['scope'].get('synthetic') is True} for c in self.org.cases()],
                'external_execution_allowed': False}

    def facts(self, case):
        # An explicit subject identity is required. Similar titles and SKU strings
        # never join imported facts from another object or connection.
        mode = case['scope'].get('synthetic') is True
        return [s for s in self.service.business.listing(mode)['sources']
                if s['kind'] == 'facts' and s['scope']['subject_ref'] == case['id']
                and s['scope']['platform'] == case['scope'].get('platform')]

    def sources(self, case_id):
        case = self.org.case(case_id)
        artifacts = {kind: self.org.artifact(case_id, kind) for kind in ('research', 'supply', 'economics', 'images')}
        facts = self.facts(case)
        source = {'case': case, 'artifacts': {k: {'id': v['id'], 'sha256': v['sha256'], 'intact': v['intact']}
                                            if v else None for k, v in artifacts.items()},
                  'facts': [{k: s[k] for k in ('id', 'version', 'sha256')} for s in facts]}
        return case, artifacts, facts, digest(canonical(source))

    @staticmethod
    def form_scope(case_id, form):
        if form not in FORMS:
            raise ValueError('workspace_invalid_form')
        return {'module': 'product_workspace', 'form': form, 'case_id': case_id}

    def checkpoint(self, case_id, form, source):
        saved = self.service.form_drafts.get(self.form_scope(case_id, form))
        envelope = saved['payload'] or {}
        return {**saved, 'payload': envelope.get('data'),
                'source_sha256': envelope.get('source_sha256'),
                'stale': bool(envelope and envelope.get('source_sha256') != source)}

    def get(self, case_id, research_task_id=None):
        case, artifacts, facts, source = self.sources(case_id)
        board = self.org.board(case_id)
        forms = {f: self.checkpoint(case_id, f, source) for f in FORMS}
        saved = forms['cost']
        inputs = (saved['payload'] or {}).get('input', {}) if saved['payload'] else (artifacts['economics'] or {}).get('payload', {})
        calculation = unit_economics(inputs) if not saved['stale'] and (not artifacts['economics'] or artifacts['economics']['intact']) else unit_economics({})
        calculation['stale'] = saved['stale']
        tasks = []
        with self.core.db() as db:
            for row in db.execute('SELECT * FROM tasks ORDER BY rowid DESC'):
                payload = json.loads(row[2]); scope = payload.get('input', {})
                if scope.get('organization_case') == case_id:
                    tasks.append(self.core.present(row))
                if len(tasks) >= 100:
                    break
        sources = [self.service.business.source(s['id']) for s in facts]
        content = []
        for d in self.service.business.listing(case['scope'].get('synthetic') is True)['drafts']:
            if d['kind'] == 'listing' and d['scope']['subject_ref'] == case_id and d['scope']['platform'] == case['scope'].get('platform'):
                content.append(self.service.business.get(d['id']))
        from research_workspace import views
        study = views(self.core, case, (artifacts['research'] or {}).get('id'), research_task_id)
        return {'schema': 'commerce-product-workspace-v1', 'case': case, 'name': self.label(case),
                'source_sha256': source, 'artifacts': artifacts, 'forms': forms,
                'stages': board['stages'], 'calculation': calculation, 'tasks': tasks,
                'content_sources': sources, 'content_drafts': content,
                'read_scope': 'selected_case_only', 'facts_independently_verified': False,
                'external_execution_allowed': False, **study}

    def validate_form(self, case_id, form, payload):
        if not isinstance(payload, dict):
            raise ValueError('workspace_invalid_form')
        if form == 'view':
            if set(payload) != {'tab'} or payload['tab'] not in ('overview', 'research', 'cost', 'content', 'review', 'tasks'):
                raise ValueError('workspace_invalid_view')
        elif form == 'plan':
            if set(payload) != {'goal', 'steps'} or not isinstance(payload['goal'], str) or len(payload['goal']) > 2000 or not isinstance(payload['steps'], list) or len(payload['steps']) > 12:
                raise ValueError('workspace_invalid_plan')
            tasks = {t['id'] for t in self.get(case_id)['tasks']}
            for step in payload['steps']:
                if not isinstance(step, dict) or set(step) - {'title', 'task_id'} or not isinstance(step.get('title'), str) or not 1 <= len(step['title']) <= 160:
                    raise ValueError('workspace_invalid_plan')
                if step.get('task_id') and step['task_id'] not in tasks:
                    raise ValueError('workspace_task_outside_scope')
        elif form == 'cost':
            if set(payload) != {'input'} or not isinstance(payload['input'], dict) or set(payload['input']) - set(UNIT_FIELDS):
                raise ValueError('workspace_invalid_cost')
            for k, value in payload['input'].items():
                if k == 'currency':
                    if not isinstance(value, str) or not re.fullmatch('[A-Z]{3}', value):
                        raise ValueError('invalid_currency')
                elif type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= (1 if k in RATES else 10**12) or (k == 'price' and value <= 0):
                    raise ValueError('invalid_' + k)
        elif form == 'content':
            if set(payload) - {'source_id', 'fields', 'draft_id'} or not isinstance(payload.get('fields', {}), dict):
                raise ValueError('workspace_invalid_content')
            if set(payload.get('fields', {})) - {'sku', 'title', 'description', 'category_id', 'price', 'currency', 'quantity', 'image_refs'}:
                raise ValueError('workspace_invalid_content')
            source_id = payload.get('source_id')
            if source_id and source_id not in {s['id'] for s in self.facts(self.org.case(case_id))}:
                raise ValueError('workspace_source_outside_scope')
            if payload.get('draft_id'):
                draft = self.service.business.get(payload['draft_id'])
                if draft['draft']['scope']['subject_ref'] != case_id or draft['draft']['kind'] != 'listing':
                    raise ValueError('workspace_draft_outside_scope')

    def guard(self, case_id, expected_source_sha256):
        case, artifacts, facts, source = self.sources(case_id)
        if source != expected_source_sha256:
            raise ValueError('workspace_source_changed')
        if any(a and not a['intact'] for a in artifacts.values()):
            raise ValueError('workspace_artifact_changed')
        return case

    def save(self, case_id, form, payload, expected_revision, expected_source_sha256, *, _reuse=False):
        self.form_scope(case_id, form)
        with self.core.atomic(reuse=_reuse):
            self.guard(case_id, expected_source_sha256)
            self.validate_form(case_id, form, payload)
            result = self.service.form_drafts.save(self.form_scope(case_id, form),
                      {'source_sha256': expected_source_sha256, 'data': deepcopy(payload)}, expected_revision)
            self.org.case(case_id)  # Reject a connection revoked during the write.
        return {**result, 'payload': payload, 'source_sha256': expected_source_sha256}

    def calculate(self, case_id, expected_revision, expected_source_sha256, *, _reuse=False):
        with self.core.atomic(reuse=_reuse):
            case = self.guard(case_id, expected_source_sha256)
            saved = self.checkpoint(case_id, 'cost', expected_source_sha256)
            if saved['revision'] != expected_revision:
                raise ValueError('form_draft_conflict')
            if not saved['payload'] or saved['stale']:
                raise ValueError('workspace_cost_checkpoint_required')
            inputs = saved['payload']['input']
            if not case['currency'] or inputs.get('currency') != case['currency']:
                raise ValueError('workspace_currency_required')
            result = unit_economics(inputs)
            if result['status'] != 'CALCULATED':
                return result
            context = self.org.exchange.context(case_id)
            result = self.org.exchange.produce(context, 'commerce_unit_economics', {'input': inputs})
            if result['artifact_handoff']['status'] != 'saved':
                raise ValueError('workspace_handoff_held')
            current = self.sources(case_id)[3]
            self.service.form_drafts.save(self.form_scope(case_id, 'cost'), {'source_sha256': current, 'data': saved['payload']}, expected_revision)
            self.org.case(case_id)
            return result

    def currency(self, case_id, currency, expected_source_sha256):
        with self.core.atomic():
            self.guard(case_id, expected_source_sha256)
            return self.org.set_currency(case_id, currency)

    def submit_content(self, case_id, expected_revision, expected_source_sha256):
        with self.core.atomic():
            case = self.guard(case_id, expected_source_sha256)
            saved = self.checkpoint(case_id, 'content', expected_source_sha256)
            if saved['revision'] != expected_revision:
                raise ValueError('form_draft_conflict')
            if not saved['payload'] or saved['stale']:
                raise ValueError('workspace_content_checkpoint_required')
            payload = saved['payload']
            self.validate_form(case_id, 'content', payload)
            source_id = payload.get('source_id')
            if source_id not in {s['id'] for s in self.facts(case)}:
                raise ValueError('workspace_source_outside_scope')
            # A retry must select the same parent as the saved editing revision,
            # not the version that the first submission just created.
            parents = [d for d in self.get(case_id)['content_drafts'] if d['created_at'] < saved['saved_at']]
            key = 'workspace-content:' + digest(canonical([case_id, expected_source_sha256, expected_revision]))
            result = self.service.business.draft('listing', [source_id],
                {'fields': payload['fields'], 'citations': {k: {'source_id': source_id, 'key': k} for k in payload['fields']}},
                key, parents[0]['id'] if parents else None)
            self.org.case(case_id)
            return result

    def invoke(self, name, args):
        return {'list': self.listing, 'get': self.get, 'save': self.save, 'calculate': self.calculate, 'currency': self.currency, 'submit_content': self.submit_content}[name.removeprefix('commerce_workspace_')](**args)
