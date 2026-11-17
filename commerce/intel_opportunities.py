"""Read-only, source-bound news hypotheses for the existing extension runner.

No scheduler, queue, model call, network request or business action lives here.
The original extension task owns persistence and uncertain model outcomes.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time

from intelligence import SOURCES

READ_ONLY = {'commerce_intel_opportunity_packet', 'commerce_intel_opportunity_validate'}
UNKNOWN_TERMS = {'status': 'unknown', 'terms': None}
PACKET_SCHEMA = 'commerce-intel-opportunity-packet-v1'


def definitions(schema, string):
    return [
        ('commerce_intel_opportunity_packet', '只读本机资讯积累，生成最多20条来源绑定的新闻机会输入；不抓取，不代表平台热搜',
         schema({'limit': {'type': 'integer', 'enum': [8, 20]}}, ['limit'])),
        ('commerce_intel_opportunity_validate', '校验同一新鲜资讯包的低置信机会假设及原记录版本；不授权采购、投放或其它业务执行',
         schema({'packet': {'type': 'object'}, 'analysis': {'type': 'object'}}, ['packet', 'analysis'])),
    ]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def epoch(value):
    if type(value) in (float, int) and math.isfinite(value):
        return value
    if isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if result.tzinfo is not None:
                return result.timestamp()
        except (ValueError, OverflowError):
            pass
    raise ValueError('intel_opportunity_invalid_time')


def text(value, limit):
    if type(value) is not str or not value.strip() or len(value) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('intel_opportunity_invalid_analysis')
    return value


def fields(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('intel_opportunity_invalid_analysis')


class IntelOpportunities:
    def __init__(self, service):
        self.service = service

    def invoke(self, name, args):
        if name == 'commerce_intel_opportunity_packet':
            return self.packet(**args)
        if name == 'commerce_intel_opportunity_validate':
            return self.validate(**args)
        raise ValueError('intel_opportunity_unknown_tool')

    def _states(self, at):
        result = {}
        for row in self.service.intelligence.sources()['sources']:
            last = row.get('last_success')
            fresh = type(last) in (int, float) and math.isfinite(last) and 0 <= at - last <= 21600
            result[row['id']] = {'source': row['id'], 'cache_status': row.get('status', 'not_collected'),
                                 'last_success': last, 'fresh': bool(fresh),
                                 'availability': 'fresh_cache' if fresh else 'stale_or_missing'}
        return result

    @staticmethod
    def _project(row, at):
        if (row.get('source') not in SOURCES or not isinstance(row.get('id'), str)
                or not re.fullmatch(r'[a-f0-9]{24}', row['id'])
                or not isinstance(row.get('record_sha256'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', row['record_sha256'])):
            raise ValueError('intel_opportunity_invalid_source')
        published, collected = epoch(row.get('published')), epoch(row.get('collected_at'))
        if not 0 <= at - published <= 86400 or not 0 <= at - collected <= 21600:
            raise ValueError('intel_opportunity_source_expired')
        from intelligence import safe_url
        url = safe_url(row.get('url'))
        if not url or len(url) > 600:
            raise ValueError('intel_opportunity_invalid_source')
        return {'id': row['id'], 'source': row['source'], 'title': text(row.get('title'), 10000)[:180],
                'url': url, 'published': published, 'collected_at': row['collected_at'],
                'record_sha256': row['record_sha256'], 'verification': 'publisher_report_not_independently_verified'}

    def packet(self, limit):
        if type(limit) is not int or limit not in (8, 20):
            raise ValueError('intel_opportunity_invalid_limit')
        at = time.time();states = self._states(at);groups = {};total = 0
        for source in SOURCES:
            state = states.get(source, {})
            if not state.get('fresh') or state.get('cache_status') != 'ok':
                continue
            view = self.service.intelligence.search(source=source, scope='archive', hours='24',
                limit='20', include_map=False, include_panels=False)
            total += view['total'];rows = []
            for row in view['items']:
                try:rows.append(self._project(row, at))
                except (ValueError, TypeError):continue
            groups[source] = rows
        selected = []
        while len(selected) < limit and any(groups.values()):
            for source in sorted(groups):
                if groups[source] and len(selected) < limit:
                    selected.append(groups[source].pop(0))
        packet = {'schema': PACKET_SCHEMA, 'scope': 'news_derived_opportunity_hypotheses',
                  'not_platform_hot_terms': True, 'generated_at': stamp(at), 'expires_at': stamp(at + 3600),
                  'limit': limit, 'items': selected, 'source_states': list(states.values()),
                  'coverage': {'status': 'bounded_public_news_sample' if selected else 'needs_fresh_sources',
                               'selected': len(selected), 'max_items': limit, 'window_hours': 24,
                               'selection': 'source_balanced_latest_publications', 'truncated': total > len(selected),
                               'archive_search': True},
                  'platform_hot_terms': dict(UNKNOWN_TERMS), 'external_execution_allowed': False}
        packet['packet_sha256'] = digest(packet)
        if len(canonical(packet).encode()) > 16000:
            raise ValueError('intel_opportunity_packet_too_large_use_limit_8')
        return packet

    def validate(self, packet, analysis):
        try:
            if type(packet) is not dict or len(canonical(packet).encode()) > 16000:
                raise ValueError()
            fields(packet, ('schema', 'scope', 'not_platform_hot_terms', 'generated_at', 'expires_at',
                            'limit', 'items', 'source_states', 'coverage', 'platform_hot_terms',
                            'external_execution_allowed', 'packet_sha256'))
            body = {k: v for k, v in packet.items() if k != 'packet_sha256'}
            if (packet.get('schema') != PACKET_SCHEMA or packet.get('packet_sha256') != digest(body)
                    or packet.get('scope') != 'news_derived_opportunity_hypotheses'
                    or packet.get('not_platform_hot_terms') is not True
                    or packet.get('external_execution_allowed') is not False
                    or packet.get('platform_hot_terms') != UNKNOWN_TERMS
                    or type(packet.get('limit')) is not int or packet['limit'] not in (8, 20)
                    or type(packet.get('items')) is not list or len(packet['items']) > packet['limit']):
                raise ValueError()
            coverage = packet['coverage']
            fields(coverage, ('status', 'selected', 'max_items', 'window_hours', 'selection', 'truncated', 'archive_search'))
            if (coverage['status'] != ('bounded_public_news_sample' if packet['items'] else 'needs_fresh_sources')
                    or type(coverage['selected']) is not int or coverage['selected'] != len(packet['items'])
                    or type(coverage['max_items']) is not int or coverage['max_items'] != packet['limit']
                    or type(coverage['window_hours']) is not int or coverage['window_hours'] != 24
                    or coverage['selection'] != 'source_balanced_latest_publications'
                    or type(coverage['truncated']) is not bool or coverage['archive_search'] is not True):
                raise ValueError()
            at = time.time();created = epoch(packet['generated_at']);expires = epoch(packet['expires_at'])
            if not created <= at <= expires or not 0 < expires - created <= 3600:
                raise ValueError()
            states = self._states(at);known = {}
            for item in packet['items']:
                original = self.service.intelligence.store.item(item['id'])
                state = states.get(original['source'], {})
                if item != self._project(original, at) or not state.get('fresh') or state.get('cache_status') != 'ok' or item['id'] in known:
                    raise ValueError()
                known[item['id']] = item
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError('intel_opportunity_packet_changed_or_expired') from None
        fields(analysis, ('summary', 'opportunities', 'platform_hot_terms'))
        text(analysis['summary'], 1200)
        if analysis['platform_hot_terms'] != UNKNOWN_TERMS:
            raise ValueError('intel_opportunity_platform_hot_terms_unknown')
        rows = analysis['opportunities']
        if type(rows) is not list or len(rows) > 3 or not known and rows:
            raise ValueError('intel_opportunity_invalid_analysis')
        for row in rows:
            fields(row, ('hypothesis', 'evidence_ids', 'confidence', 'status', 'next_checks'))
            text(row['hypothesis'], 500)
            if row['confidence'] != 'low' or row['status'] != 'needs_evidence':
                raise ValueError('intel_opportunity_invalid_analysis')
            refs = row['evidence_ids'];checks = row['next_checks']
            if (type(refs) is not list or not 1 <= len(refs) <= 4
                    or any(type(ref) is not str or ref not in known for ref in refs) or len(set(refs)) != len(refs)
                    or type(checks) is not list or not 1 <= len(checks) <= 4):
                raise ValueError('intel_opportunity_invalid_analysis')
            for check in checks:text(check, 200)
        return {'schema': 'commerce-intel-opportunity-result-v1', 'packet_sha256': packet['packet_sha256'],
                'scope': 'news_derived_opportunity_hypotheses', 'not_platform_hot_terms': True,
                'summary': analysis['summary'], 'opportunities': json.loads(canonical(rows)),
                'evidence': packet['items'], 'coverage': packet['coverage'],
                'platform_hot_terms': dict(UNKNOWN_TERMS), 'verification': 'news_derived_hypotheses_needs_evidence',
                'external_execution_allowed': False, 'business_actions_executed': False}
