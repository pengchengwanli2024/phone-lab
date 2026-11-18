"""Read-only: recurring failures across the operating domains, as improvement candidates.

Counts error codes already recorded by model requests, extension runs, market
research, Ozon reads and operating-loop work in a time window. A code that
repeats becomes a candidate with the kind of fix to try first: a deterministic
check or API before a skill or prompt change, and never a new role first.
Nothing is created, applied, retried or sent to a model here; turning a
candidate into an engineering work order stays an explicit operator step.
"""
import json
import re
import time

READ_ONLY = {'commerce_operating_retrospect_get'}
CODE = re.compile(r'[a-z][a-z0-9_]{2,99}')
TYPE = re.compile(r'[A-Z][A-Za-z0-9]{1,59}')
WINDOW_DAYS = (7, 30)
# Where the first fix belongs; the first matching rule wins, so specific codes come
# before broad words such as "unavailable". Unlisted codes default to a check or test.
FIX = (
    (('no_product_evidence', 'needs_input', 'case_unavailable'), 'inputs', '补充资料或数据来源，不是代码缺陷'),
    (('rate_limit', 'network', 'timeout', 'unavailable'), 'connector', '连接器的退避、限流或重试边界'),
    (('schema', 'invalid_response', 'too_large', 'evidence_reference', 'scope_mismatch'), 'contract', '输入输出契约或确定性校验'),
    (('budget', 'limit', 'exhausted'), 'limits', '额度与上限配置，由人决定是否调整'),
    (('outcome_unknown', 'interrupted', 'receipt'), 'recovery', '结果未知后的核对入口；不自动重发'),
)


def definitions(schema, string):
    return [('commerce_operating_retrospect_get', '只读统计各经营环节重复出现的失败并给出改进候选与优先修复方向；不创建任务、不调用模型、不自动应用',
             schema({'window_days': {'type': 'integer', 'enum': list(WINDOW_DAYS)}}))]


# Which registered engineering recipe may work on one exact failure. The bounded
# executor snapshots at most 64 KB, so a failure is listed only after its logic has
# been split into a module small enough to load together with its tests.
FEATURES = {'store_read:ozon_rate_limited': 'ozon-read-backoff',
            'model_request:agent_provider_outcome_unknown': 'model-attempt-outcome'}


def classify(code):
    for needles, kind, hint in FIX:
        if any(n in code for n in needles):
            return kind, hint
    return 'check', '先补可重跑的检查或回归测试，再判断是否需要改技能'


class OperatingRetrospect:
    def __init__(self, service):
        self.service, self.core = service, service.core

    def invoke(self, name, args):
        if name != 'commerce_operating_retrospect_get':
            raise ValueError('unknown_tool')
        return self.get(**args)

    @staticmethod
    def _code(value):
        if isinstance(value, dict):
            value = value.get('code') or value.get('error')
        return value if isinstance(value, str) and CODE.fullmatch(value) else None

    def _events(self, since):
        """Yield (domain, code, at). Text other than a bounded code is never read out."""
        with self.core.db() as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            def rows(table, sql, args=()):
                return db.execute(sql, args).fetchall() if table in names else []
            for raw, at in rows('agent_runs', "SELECT result,updated FROM agent_runs WHERE status IN ('failed','unknown','interrupted') AND updated>=? AND result IS NOT NULL", (since,)):
                yield 'model_request', self._code(json.loads(raw)), at
            for raw, at in rows('extension_runs', "SELECT document,created FROM extension_runs WHERE status IN ('failed','interrupted','unknown') AND created>=?", (since,)):
                doc = json.loads(raw);code = self._code(doc.get('error'))
                cause = (doc.get('error_cause') or {}).get('type') if isinstance(doc.get('error_cause'), dict) else None
                # A generic code is split by the recorded exception type, when it is a plain name.
                if code == 'extension_execution_failed' and isinstance(cause, str) and TYPE.fullmatch(cause):
                    code = code + ':' + cause
                yield 'extension', code, at
            for (raw,) in rows('market_research_jobs', 'SELECT document FROM market_research_jobs'):
                job = json.loads(raw)
                if job.get('status') in ('failed', 'partial'):
                    yield 'market_research', self._code(job.get('error')) or ('market_research_partial' if job['status'] == 'partial' else None), None
            for error, count in rows('live_http', "SELECT error,count(*) FROM live_http WHERE error IS NOT NULL AND at>=? GROUP BY error", (time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(since)),)):
                for _ in range(min(count, 100000)):
                    yield 'store_read', self._code(error), None
            for raw, status, at in rows('operating_loop_work', "SELECT document,status,created FROM operating_loop_work WHERE status IN ('failed','unknown') AND created>=?", (since,)):
                yield 'operating_loop', self._code(json.loads(raw).get('error')) or 'operating_loop_' + status, at

    def get(self, window_days=7, at=None):
        if window_days not in WINDOW_DAYS:
            raise ValueError('operating_retrospect_invalid_window')
        at = time.time() if at is None else at
        counts, uncoded = {}, {}
        for domain, code, when in self._events(at - window_days * 86400):
            if code is None:
                uncoded[domain] = uncoded.get(domain, 0) + 1
                continue
            entry = counts.setdefault((domain, code), {'count': 0, 'last_at': None})
            entry['count'] += 1
            if when and (entry['last_at'] is None or when > entry['last_at']): entry['last_at'] = when
        candidates = []
        for (domain, code), entry in counts.items():
            if entry['count'] < 2:
                continue  # a single failure is an incident, not a pattern
            kind, hint = classify(code)
            candidates.append({'id': domain + ':' + code, 'domain': domain, 'error': code, 'count': entry['count'],
                               'last_at': entry['last_at'], 'fix_first': kind, 'hint': hint, 'status': 'candidate',
                               'engineering_feature': FEATURES.get(domain + ':' + code)})
        candidates.sort(key=lambda c: (-c['count'], c['id']))
        return {'schema': 'commerce-operating-retrospect-v1', 'window_days': window_days, 'candidates': candidates[:20],
                'single_incidents': sum(1 for e in counts.values() if e['count'] == 1), 'uncoded_failures': uncoded,
                'priority': 'deterministic_check_or_api_before_skill_or_new_role',
                'engineering': {'covered_candidates': sorted(c['id'] for c in candidates if c['engineering_feature']),
                                'automatic_work_orders': False,
                                'uncovered_domains': sorted({c['domain'] for c in candidates if not c['engineering_feature']}),
                                'reason': 'recipe_exists_only_where_logic_fits_the_bounded_snapshot'},
                'automatically_applied': False, 'new_tasks_created': 0, 'model_calls': 0}
