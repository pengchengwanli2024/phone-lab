"""Scope-bound operating guidance over original product artifacts and workflows.

This is a next-step resolver, not another scheduler or business authorization.
"""
from datetime import datetime, timezone
import json

from research import canonical, digest
from video_eligibility import automatic_video_policy

READ_ONLY = {'commerce_operating_pipeline_get', 'commerce_operating_pipeline_template'}
GOALS = {'launch', 'operate', 'brand'}
STAGES = (
    ('research', '市场研究与选品', 'scout', ('S1',), ()),
    ('sourcing', '多货源比较与实物事实', 'sourcer', ('S3',), ('research',)),
    ('economics', '落地成本、贡献与现金', 'economist', ('S2',), ('sourcing',)),
    ('localization', '卖点、关键词与本地化', 'localizer', ('S5',), ('research',)),
    ('images', '主图、细节、多视角与场景图', 'creative', ('S4',), ('sourcing',)),
    ('ugc', 'UGC或有标识的UGC风格视频', 'creative', (), ('sourcing',)),
    ('policy', '情报政策、资质与目标规则', 'gatekeeper', (), ('research',)),
    ('listing', '目标店铺上架与结果回读', 'conductor', (), ('economics', 'localization', 'images', 'policy')),
    ('growth', '搜索与广告实验优化', 'grower', ('S7',), ('listing',)),
    ('service', '客服、售后与日常运营', 'voice', ('S9',), ('listing',)),
    ('procurement', '采购、库存与发货', 'fulfiller', ('S8',), ('sourcing', 'economics')),
    ('logistics', '物流异常、丢包与索赔', 'fulfiller', (), ('procurement',)),
    ('settlement', '结算、退款与经营复盘', 'controller', ('S10',), ('listing',)),
    ('brand', '热销验证、品牌与独立站', 'conductor', (), ('growth', 'settlement')),
)
REQUIRED = {
    'launch': {'research', 'sourcing', 'economics', 'localization', 'images', 'policy', 'listing'},
    'operate': {'growth', 'service', 'procurement', 'logistics', 'settlement'},
    'brand': {'research', 'economics', 'settlement', 'brand'},
}
PENDING_SUBMISSIONS = {'checking', 'submitting', 'accepted', 'interrupted_before_dispatch'}


def execution_status(release):
    submission = release.get('submission_status')
    reading = release.get('read_status')
    observation = release.get('observation_status')
    if submission == 'unknown' or reading in ('unknown', 'interrupted') or observation in ('unknown', 'interrupted'):
        return 'unknown'
    if submission in PENDING_SUBMISSIONS: return submission
    if reading == 'running': return 'reading'
    if reading == 'failed': return 'read_failed'
    if submission in ('queued', 'running', 'failed', 'cancelled', 'failed_before_dispatch'): return submission
    return None


def definitions(schema, string):
    target = {'case_id': string, 'platform': string, 'store_ref': string, 'market': string,
              'goal': {'type': 'string', 'enum': sorted(GOALS)}}
    sha = {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}
    return [
        ('commerce_operating_pipeline_get', '读取同商品、目标与经营目标的真实缺项和下一步；不执行采集、模型或经营动作',
         schema({**target, 'expected_snapshot_sha256': sha}, ['case_id', 'platform', 'store_ref', 'market'])),
        ('commerce_operating_pipeline_template', '生成复用原持久工作流的只读经营复查配方；不会保存、启用或运行',
         schema({**target, 'expected_snapshot_sha256': sha}, ['case_id', 'platform', 'store_ref', 'market', 'expected_snapshot_sha256'])),
    ]


class OperatingPipeline:
    def __init__(self, service):
        self.service = service

    def invoke(self, name, args):
        return {'commerce_operating_pipeline_get': self.get, 'commerce_operating_pipeline_template': self.template}[name](**args)

    @staticmethod
    def _checks(gates, ids):
        checks = [c for ident in ids for c in gates[ident]['checks'] if not c['id'].startswith('upstream:')]
        states = {c['state'] for c in checks}
        status = ('failed' if 'FAIL' in states else 'needs_evidence' if 'HOLD' in states else
                  'blocked' if 'BLOCKED' in states else 'prepared' if states == {'PASS'} else 'needs_evidence')
        evidence = [e for c in checks for e in c['evidence']]
        gaps = [c['detail'] for c in checks if c['state'] != 'PASS']
        return status, evidence, gaps

    @staticmethod
    def _action(tool, arguments, missing_inputs=(), effect='read'):
        return {'tool': tool, 'arguments': arguments, 'missing_inputs': list(missing_inputs),
                'callable': tool is not None and not missing_inputs, 'effect': effect,
                'grants_execution': False}

    def _unresolved(self, target, listing):
        releases = self.service.listing_releases
        with self.service.core.db() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM org_artifacts WHERE case_id=? AND kind=? ORDER BY created DESC,id DESC LIMIT 201',
                (target['case_id'], releases.kind(target)))]
        items = []
        for ident in ids[:200]:
            request = releases.request(ident)
            if request['data']['target'] != target: raise ValueError('operating_release_scope_changed')
            public = releases.public(request, listing)
            submission = public.get('system_submission')
            ref = {'request_id': ident, 'request_sha256': public['sha256'], 'event_sha256': public['event_sha256'],
                'current': public['current'], 'read_status': public['read']['status'],
                'submission_status': submission['state']['status'] if submission else None,
                'observation_status': public['observation']['status'] if public['observation'] else None}
            status = execution_status(ref)
            if status in {'unknown', 'reading', *PENDING_SUBMISSIONS}:
                items.append({**ref, 'status': status})
        return items, len(ids) <= 200

    def _video_policy(self, view, target, source_matches):
        """Describe the real sales adapter gap without promoting reported counts.

        Current performance reports have a free-form source reference and no
        verified store/SKU/sale-state contract. The Ozon analytics snapshot is
        store-wide; the product-linked snapshot contains fulfillment records.
        Neither is an authoritative product-sale trigger for automatic spend.
        Explicit human media requests continue through the original media API.
        """
        observations = {'status': 'no_bound_media_project', 'positive_reported_order_records': 0,
            'reported_record_ids': [], 'reported_orders_verification': 'self_reported_not_verified_product_sales',
            'fulfillment': None, 'reported_history_truncated': False}
        policy = automatic_video_policy(observations)
        if not source_matches:
            observations['status'] = 'target_mismatch'
            return policy
        # The existing linked fulfillment adapter only establishes this store.
        if (target['platform'], target['store_ref'], target['market']) != ('ozon', 'ozon-live', 'RU'):
            observations['status'] = 'store_scope_unverified'
            return policy
        artifact = view['artifacts']['images']
        project_id = artifact['payload'].get('project_id') if artifact else None
        if not project_id: return policy
        try:
            with self.service.core.atomic(reuse=True):
                project = self.service.media.project(project_id)
                binding = project['brief'].get('product_binding') or {}
                if binding.get('case_id') != target['case_id']:
                    observations['status'] = 'binding_mismatch'
                    return policy
                if binding.get('source_sha256') != view['source_sha256']:
                    observations['status'] = 'binding_stale'
                    return policy
                if project['brief'].get('synthetic') or view['case']['scope'].get('synthetic'):
                    observations['status'] = 'synthetic_only'
                    return policy
                with self.service.core.db() as db:
                    rows = db.execute('SELECT document FROM creative_performance WHERE project=? ORDER BY rowid DESC LIMIT 101', (project_id,)).fetchall()
                records = [json.loads(row[0]) for row in rows[:100]]
                if any(digest(canonical(record['payload'])) != record['input_sha256'] for record in records):
                    raise ValueError('creative_performance_integrity')
                positive = [record['id'] for record in records if type(record['payload'].get('orders')) is int and record['payload']['orders'] > 0]
                observations.update(status='unverified_observations_only', positive_reported_order_records=len(positive),
                    reported_record_ids=positive, reported_history_truncated=len(rows) > 100,
                    fulfillment=self.service.media.sales_context(project),
                    performance_sha256=digest(canonical(records)))
        except (ValueError, OSError, KeyError, TypeError):
            observations['status'] = 'media_evidence_unavailable'
        return policy

    def get(self, case_id, platform, store_ref, market, goal='launch', expected_snapshot_sha256=None):
        if goal not in GOALS: raise ValueError('operating_invalid_goal')
        target, _ = self.service.listings.scope(case_id, platform, store_ref, market)
        if not target['store_ref'] or not target['market']: raise ValueError('operating_explicit_target_required')
        # Existing domain methods share this read snapshot. No new record is written.
        with self.service.core.atomic(reuse=True):
            view = self.service.product_workspace.get(case_id)
            listing = self.service.listings.get(**target)
            release = self.service.listing_releases.summary(target, listing)
            unresolved, history_complete = self._unresolved(target, listing)
        gates = {s['id']: s for s in view['stages']}
        source_matches = all(view['case']['scope'].get(k) == target[k] for k in ('platform', 'market'))
        stages = []
        for ident, label, owner, ids, dependencies in STAGES:
            acceptance, evidence, gaps = self._checks(gates, ids)
            stages.append({'id': ident, 'name': label, 'owner': owner, 'depends_on': list(dependencies),
                'required_for_goal': ident in REQUIRED[goal], 'capability_status': 'partial',
                'acceptance_status': acceptance, 'evidence': evidence, 'missing': gaps,
                'verification': 'local_contract_checks_only', 'original_gates': list(ids), 'next_actions': [], 'limitations': []})
        by_id = {s['id']: s for s in stages}
        by_id['ugc']['automation_policy'] = self._video_policy(view, target, source_matches)
        def action(ident, tool, args, missing=(), effect='read'):
            by_id[ident]['next_actions'].append(self._action(tool, args, missing, effect))
        def need(ident, *items): by_id[ident]['missing'].extend(items)
        action('research', 'commerce_organization_brief', {'case_id': case_id, 'stage_id': 'S1'})
        action('sourcing', 'commerce_workspace_quotes', {'case_id': case_id})
        action('sourcing', 'commerce_workspace_quote_compare', {'case_id': case_id}, ('quantity',))
        quotes = view['supply_quotes']['items']
        if len([q for q in quotes if q['status'] == 'READY_FOR_SELECTION']) < 2:
            by_id['sourcing']['acceptance_status'] = 'needs_evidence'
            need('sourcing', '至少两份完整有效报价供比较；报价完整不证明供应商或实物已经核验')
        cost = view['forms']['cost']
        economics = view['artifacts']['economics']
        if cost['payload'] and (cost['stale'] or not economics or cost['payload'].get('input') != economics['payload']):
            by_id['economics']['acceptance_status'] = 'needs_calculation'
        if (source_matches and cost['payload'] and not cost['stale'] and gates['S3']['status'] == 'PASS'
                and view['calculation']['status'] == 'CALCULATED'
                and cost['payload'].get('input', {}).get('currency') == view['case']['currency']):
            action('economics', 'commerce_workspace_calculate', {'case_id': case_id,
                'expected_revision': cost['revision'], 'expected_source_sha256': view['source_sha256']}, effect='local_prepare')
        else:
            action('economics', 'commerce_workspace_get', {'case_id': case_id})
            need('economics', '核对原币成本、费用、退款/损耗假设及现金占用；未知费用不记零')
        action('localization', 'commerce_workspace_get', {'case_id': case_id})
        action('images', 'commerce_workspace_delivery_get', {'case_id': case_id})
        if by_id['images']['acceptance_status'] == 'prepared' and view['delivery_review']['status'] != 'local_review_recorded':
            by_id['images']['acceptance_status'] = 'awaiting_review'
        by_id['images']['limitations'].append('文件/本地审阅检查不独立证明商品身份、各视角真实性、素材权利或平台合规')
        # A local montage or generated presenter is not a verified customer testimonial.
        need('ugc', '需绑定同商品制作项目、真实素材/授权、视频审阅；区分真实UGC与AI制作的UGC风格广告')
        image_artifact = view['artifacts']['images']
        project_id = image_artifact['payload'].get('project_id') if image_artifact else None
        if project_id:
            try:
                project = self.service.media.project(project_id)
                binding = project['brief'].get('product_binding') or {}
                if binding.get('case_id') == case_id:
                    action('ugc', 'commerce_media_overview', {'project_id': project_id})
                else: need('ugc', '关联素材项目归属已变化，须重新核对同商品绑定')
            except (ValueError, OSError):
                need('ugc', '关联素材项目不可读取或归属已变化，须重新核对；不影响其它阶段缺口的读取')
        if not by_id['ugc']['next_actions']:
            action('ugc', None, {}, ('product_bound_media_project', 'licensed_materials'))
        ready_checks = {r['id']: r['status'] for r in listing['checks']}
        by_id['policy']['acceptance_status'] = 'prepared' if all(ready_checks.get(k) == 'prepared' for k in ('rules', 'professional_gate', 'platform_schema')) else 'needs_evidence'
        by_id['policy']['missing'] = [r['label'] for r in listing['checks']
            if r['id'] in ('rules', 'professional_gate', 'platform_schema') and r['status'] != 'prepared']
        by_id['policy']['limitations'].append('热点和政策须保留来源、适用地区、类目、生效时间与复核日期；研究完整不代表合法可售')
        action('policy', 'commerce_listing_get', target)
        by_id['listing']['acceptance_status'] = 'needs_evidence' if listing['missing'] else 'awaiting_approval'
        by_id['listing']['missing'] = list(listing['missing'])
        action('listing', 'commerce_listing_get', target)
        if release:
            by_id['listing']['source_current'] = release['current']
            action('listing', 'commerce_listing_submission_get', {'request_id': release['request_id']})
            actual = execution_status(release)
            if actual: by_id['listing']['acceptance_status'] = actual
            elif not release['current']: by_id['listing']['acceptance_status'] = 'stale'
        if unresolved:
            uncertain = next((r for r in unresolved if r['status'] == 'unknown'), unresolved[0])
            by_id['listing']['acceptance_status'] = uncertain['status']
            by_id['listing']['next_actions'].insert(0, self._action('commerce_listing_release_get', {**target, 'request_id': uncertain['request_id']}))
            need('listing', '同目标历史申请仍有未决结果；先核对原申请，不能用新草稿覆盖或重发')
        if not history_complete:
            by_id['listing']['acceptance_status'] = 'unknown'
            need('listing', '目标申请历史超过200条，本轮未完整核查；不得推断没有更早未决申请')
        for ident, missing in {
            'growth': ('广告账户、预算和止损策略、真实消耗/转化、归因窗口与实验版本',),
            'service': ('平台客户会话/订单、发送适配与人员接管；草稿不等于已回复',),
            'procurement': ('供应商采购确认、库存预留、付款边界和仓库发货回执',),
            'logistics': ('运单、承运商事件、服务时限、丢包判定与索赔期限；装箱估算不等于物流跟踪',),
            'settlement': ('订单/费用/退款/物流/广告/结算逐笔关联与差异核对',),
            'brand': ('持续净贡献、退货与质量反馈、商标/素材权利、品牌预算及站点授权',),
        }.items():
            need(ident, *missing);action(ident, None, {}, missing)
        by_id['logistics']['capability_status'] = 'missing'
        if by_id['procurement']['acceptance_status'] == 'prepared':
            by_id['procurement']['acceptance_status'] = 'needs_fulfillment_evidence'
        for ident in ('logistics', 'brand'): by_id[ident]['acceptance_status'] = 'needs_evidence'
        by_id['ugc']['acceptance_status'] = 'deferred'
        by_id['ugc']['missing'].insert(0, by_id['ugc']['automation_policy']['reason'])
        if not source_matches:
            for ident in ('research', 'sourcing', 'economics', 'localization', 'images', 'policy', 'growth', 'service', 'procurement', 'settlement'):
                by_id[ident]['acceptance_status'] = 'needs_target_evidence'
                by_id[ident]['inapplicable_evidence'] = by_id[ident]['evidence'];by_id[ident]['evidence'] = []
                need(ident, '原工作项证据的市场/平台不匹配本次目标，不能沿用原门禁通过结论')
        for stage in stages:
            stage['blocked_by'] = [ident for ident in stage['depends_on'] if by_id[ident]['acceptance_status'] != 'prepared']
        next_stage = next((s for s in stages if s['required_for_goal'] and s['acceptance_status'] != 'prepared'), None)
        next_action = {**next_stage['next_actions'][0], 'stage_id': next_stage['id']} if next_stage else None
        basis = {'target': target, 'goal': goal, 'source_sha256': view['source_sha256'], 'stages': stages,
            'forms': {k: {'revision': v['revision'], 'stale': v['stale']} for k, v in view['forms'].items()},
            'listing_preview_sha256': listing['preview_sha256'], 'release': release,
            'unresolved_releases': unresolved, 'release_history_complete': history_complete}
        sha = digest(canonical(basis))
        if expected_snapshot_sha256 is not None and expected_snapshot_sha256 != sha: raise ValueError('operating_snapshot_changed')
        return {'schema': 'commerce-operating-pipeline-v1', 'target': target, 'goal': goal, 'snapshot_sha256': sha,
            'listing_preview_sha256': listing['preview_sha256'], 'listing_revision': listing['revision'],
            'product_source_sha256': view['source_sha256'], 'source_target_matches': source_matches,
            'observed_at': datetime.now(timezone.utc).isoformat(), 'synthetic': view['case']['scope'].get('synthetic') is True,
            'stages': stages, 'next_action': next_action, 'release': release,
            'unresolved_releases': unresolved[:20], 'unresolved_release_count': len(unresolved),
            'unresolved_releases_truncated': len(unresolved) > 20, 'release_history_complete': history_complete,
            'status': 'needs_attention' if next_stage else 'ready_for_local_review',
            'business_outcome_verified': False, 'external_execution_allowed': False,
            'execution_semantics': 'diagnostic_completion_is_not_business_completion', 'model_calls': 0}

    def template(self, case_id, platform, store_ref, market, expected_snapshot_sha256, goal='launch'):
        snapshot = self.get(case_id, platform, store_ref, market, goal, expected_snapshot_sha256)
        scope = {'case_id': case_id, 'platform': platform, 'store_id': store_ref, 'market': market}
        limits = {'max_steps': 1, 'max_model_calls': 0, 'max_seconds': 60, 'max_output_bytes': 64000}
        args = {key: {'$ref': 'scope.' + source} for key, source in
                [('case_id', 'case_id'), ('platform', 'platform'), ('store_ref', 'store_id'), ('market', 'market')]}
        args['goal'] = goal
        definition = {'kind': 'workflow', 'name': '单商品经营复查 · ' + goal,
            'description': '只读取精确经营范围的当前证据与缺项，不执行经营动作。', 'limits': limits,
            'spec': {'steps': [{'id': 'inspect', 'uses': {'builtin': 'commerce_operating_pipeline_get'}, 'input': args}],
                     'output': {'$ref': 'steps.inspect'}}}
        return {'definition': definition, 'run_arguments': {'input': {}, 'scope': scope, 'budget': limits},
            'prepared_snapshot_sha256': snapshot['snapshot_sha256'], 'execution_started': False,
            'next_steps': ['commerce_extension_save', 'commerce_extension_test', 'commerce_extension_enable', 'commerce_extension_run'],
            'scheduling': 'Existing interval schedules create a new original run per slot; do not reuse an old idempotency key for a fresh observation.',
            'external_execution_allowed': False}
