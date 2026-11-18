"""Stateless decision checks over caller-provided commerce evidence.

Third capability batch studied from Personal Agent OS (commerce_selection.py,
commerce_demand.py, commerce_competitors.py, commerce_fulfillment.py and the
experiment part of commerce_actions.py). Independent standard-library
implementation: nothing is stored, fetched, scheduled or written to a store.
Every result is a reviewable draft computed only from the given input.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re

from operations_analysis import number

READ_ONLY = frozenset({'commerce_selection_scorecard', 'commerce_demand_trend_assess',
                       'commerce_competitor_changes', 'commerce_shipment_reconcile',
                       'commerce_experiment_evaluate'})
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MONTH = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')
STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}Z)?$')
SOURCE_KINDS = ('MANUAL_QUOTE', 'THIRD_PARTY_ESTIMATE', 'FIRST_PARTY_ACTUAL', 'SIMULATION')
LEVELS = {'high': 1, 'medium': 3, 'low': 5}
CORE_METRICS = ('review_dependency', 'net_margin_pct', 'promo_intensity', 'estimated_acos_pct')
Z_95 = Decimal('1.96')


def _base(model):
    return {'model': model, 'data_source': 'caller_input', 'review_required': True,
            'marketplace_writes': False, 'external_execution_allowed': False}


def _object(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('decision_invalid_input')


def _text(value, field, limit=128):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or CONTROL.search(value):
        raise ValueError('decision_invalid_' + field)
    return value


def _enum(value, choices, field):
    if not isinstance(value, str) or value not in choices:
        raise ValueError('decision_invalid_' + field)
    return value


def _flag(row, field):
    value = row.get(field, False)
    if type(value) is not bool:
        raise ValueError('decision_invalid_' + field)
    return value


def _rows(value, field, maximum, minimum=1):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ValueError('decision_invalid_' + field)
    return value


def _number(value, field, minimum=0, maximum=10 ** 9, integer=False):
    try:
        return number(value, field, minimum=minimum, maximum=maximum, integer=integer)
    except ValueError:
        raise ValueError('decision_invalid_' + field) from None


def _optional(row, field, **limits):
    return None if row.get(field) is None else _number(row[field], field, **limits)


def _day(value, field):
    if not isinstance(value, str) or not DAY.match(value):
        raise ValueError('decision_invalid_' + field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError('decision_invalid_' + field) from None


def _month(value, field):
    if not isinstance(value, str) or not MONTH.match(value):
        raise ValueError('decision_invalid_' + field)
    return int(value[:4]) * 12 + int(value[5:]) - 1


def _month_text(index):
    return f'{index // 12:04}-{index % 12 + 1:02}'


def _plain(value, places='0.01'):
    return None if value is None else format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), 'f')


def _mean(values):
    return sum(values, Decimal(0)) / len(values)


# --- selection scorecard -------------------------------------------------

def _score(row):
    missing = [name for name in CORE_METRICS if row[name] is None]
    if row['source_kind'] == 'SIMULATION':
        return {'status': 'HOLD', 'scores': None, 'needs_evidence': ['non_simulated_source', *missing],
                'reason': '模拟数据不作为选品证据'}
    if missing:
        return {'status': 'HOLD', 'scores': None, 'needs_evidence': missing,
                'reason': '四项核心指标不完整，不补造数据'}
    margin, acos = row['net_margin_pct'], row['estimated_acos_pct']
    scores = {'review_dependency': LEVELS[row['review_dependency']],
              'net_margin_pct': 1 if margin < 15 else 3 if margin < 25 else 5,
              'promo_intensity': LEVELS[row['promo_intensity']],
              'estimated_acos_pct': 1 if acos > 50 else 3 if acos > 30 else 5}
    after_ads = margin - acos
    result = {'scores': scores, 'profit_after_ads_pct': _plain(after_ads), 'needs_evidence': []}
    if row['differentiation'] == 'none':
        return {**result, 'status': 'REJECT', 'reason': '与头部同款且无买家可感知差异'}
    if after_ads < 0:
        return {**result, 'status': 'REJECT', 'reason': '净毛利减预估广告后为负'}
    if after_ads < 5:
        return {**result, 'status': 'HOLD', 'reason': '广告后盈余不足5个百分点缓冲'}
    if row['differentiation'] == 'unknown':
        return {**result, 'status': 'HOLD', 'needs_evidence': ['differentiation'],
                'reason': '尚未说明买家可感知差异'}
    return {**result, 'status': 'READY', 'reason': '所填数据通过四项核心指标与毛利底线；不是盈利承诺'}


def selection_scorecard(data):
    _object(data, ('candidates',))
    seen, matrix = set(), []
    for raw in _rows(data['candidates'], 'candidates', 100):
        _object(raw, ('sku', 'source', 'source_kind'), ('title', *CORE_METRICS, 'differentiation'))
        sku = _text(raw['sku'], 'sku')
        if sku in seen:
            raise ValueError('decision_duplicate_sku')
        seen.add(sku)
        row = {'source_kind': _enum(raw['source_kind'], SOURCE_KINDS, 'source_kind'),
               'differentiation': _enum(raw.get('differentiation', 'unknown'),
                                        ('buyer_visible', 'none', 'unknown'), 'differentiation'),
               'net_margin_pct': _optional(raw, 'net_margin_pct', minimum=-1000, maximum=100),
               'estimated_acos_pct': _optional(raw, 'estimated_acos_pct', maximum=1000)}
        for field in ('review_dependency', 'promo_intensity'):
            row[field] = None if raw.get(field) is None else _enum(raw[field], tuple(LEVELS), field)
        entry = {'sku': sku, 'source': _text(raw['source'], 'source', 256), 'source_kind': row['source_kind'],
                 'estimated': row['source_kind'] != 'FIRST_PARTY_ACTUAL', **_score(row)}
        if 'title' in raw:
            entry['title'] = _text(raw['title'], 'title', 256)
        matrix.append(entry)
    counts = {status: sum(1 for row in matrix if row['status'] == status) for status in ('READY', 'HOLD', 'REJECT')}
    return {**_base('four_metric_scorecard_v1'), 'candidate_count': len(matrix), 'status_counts': counts,
            'matrix': matrix,
            'thresholds': {'margin_score_pct': [15, 25], 'acos_score_pct': [30, 50], 'after_ads_buffer_pct': 5},
            'assumptions': ['Rows keep input order; the matrix is not a ranking.',
                            'READY means the supplied figures pass fixed gates, not that the product will be profitable.',
                            'Figures not marked FIRST_PARTY_ACTUAL are estimates and need their source reviewed.']}


# --- demand trend --------------------------------------------------------

def _series(items, country, end, months):
    buckets = defaultdict(list)
    for item in items:
        if end - months < item['month'] <= end:
            buckets[item['month']].append(item)
    conflicts = sorted(n for n, rows in buckets.items() if len({row['value'] for row in rows}) > 1)
    points = {n: rows[0]['value'] for n, rows in buckets.items() if n not in conflicts}
    values = [(n, v) for n, v in sorted(points.items()) if v is not None]
    coverage = Decimal(len(values)) / months
    first, reasons = items[0], []
    if first['country_code'] != country:
        reasons.append('REGION_MISMATCH')
    if coverage < Decimal('0.7'):
        reasons.append('COVERAGE_BELOW_70_PERCENT')
    if conflicts:
        reasons.append('CONFLICTING_MONTHS')
    if any(row['source_revoked'] for row in items):
        reasons.append('SOURCE_UNAVAILABLE')
    if any(row['source_kind'] == 'SIMULATION' for row in items):
        reasons.append('SIMULATION_EXCLUDED')
    third = months // 3
    early = [v for n, v in values if n <= end - months + third]
    late = [v for n, v in values if n > end - third]
    if not early or not late:
        reasons.append('WINDOW_EDGE_MISSING')
    direction, change = 'UNKNOWN', None
    if not reasons:
        before, after = _mean(early), _mean(late)
        if before > 0:
            change = (after - before) / before
            direction = 'UP' if change >= Decimal('0.2') else 'DOWN' if change <= Decimal('-0.2') else 'FLAT'
        elif after > 0:
            direction = 'UP'
        else:
            reasons.append('ZERO_BASELINE')
    seasonal = False
    if not reasons and months >= 24 and coverage >= Decimal('0.9'):
        peaks = []
        for start in range(end - months + 1, end + 1, 12):
            block = [points.get(n) for n in range(start, start + 12)]
            if any(v is None for v in block) or _mean(block) <= 0:
                continue
            top = max(block)
            if top >= Decimal('1.5') * _mean(block) and block.count(top) == 1:
                peaks.append((start + block.index(top)) % 12)
        seasonal = len(peaks) >= 2 and len(set(peaks)) == 1
    return {'source_id': first['source_id'], 'source_type': first['source_type'],
            'independent_group': first['independent_group'], 'country_code': first['country_code'],
            'metric': first['metric'], 'unit': first['unit'], 'series_version': first['series_version'],
            'direction': direction, 'coverage': float(coverage.quantize(Decimal('0.0001'))),
            'change_pct': _plain(None if change is None else change * 100), 'seasonal': seasonal,
            'reasons': reasons, 'conflicting_months': [_month_text(n) for n in conflicts],
            'evidence_ids': sorted(row['id'] for row in items),
            'points': [{'month': _month_text(n), 'value': None if points.get(n) is None else _plain(points[n], '0.0001')}
                       for n in range(end - months + 1, end + 1)]}


def demand_trend(data):
    _object(data, ('country_code', 'query', 'as_of_month', 'records'), ('months',))
    country = _text(data['country_code'], 'country_code', 2)
    query = _text(data['query'], 'query', 200)
    end = _month(data['as_of_month'], 'as_of_month')
    months = data.get('months', 12)
    if type(months) is not int or months not in (12, 24, 36):
        raise ValueError('decision_invalid_months')
    fields = ('id', 'source_id', 'source_type', 'independent_group', 'country_code', 'metric', 'unit',
              'series_version', 'period', 'value', 'source_kind')
    groups, ids = defaultdict(list), set()
    for raw in _rows(data['records'], 'records', 2000):
        _object(raw, fields, ('source_revoked',))
        row = {key: _text(raw[key], key) for key in fields[:8]}
        if row['id'] in ids:
            raise ValueError('decision_duplicate_record_id')
        ids.add(row['id'])
        row.update(month=_month(raw['period'], 'period'), value=_optional(raw, 'value'),
                   source_kind=_enum(raw['source_kind'], SOURCE_KINDS, 'source_kind'),
                   source_revoked=_flag(raw, 'source_revoked'))
        groups[tuple(row[key] for key in ('source_id', 'metric', 'unit', 'series_version', 'country_code'))].append(row)
    cards = [_series(items, country, end, months) for _, items in sorted(groups.items())]
    good = [card for card in cards if card['direction'] != 'UNKNOWN']
    pairs = [(a, b) for i, a in enumerate(good) for b in good[i + 1:]
             if a['source_id'] != b['source_id'] and a['source_type'] != b['source_type']
             and a['independent_group'] != b['independent_group']]
    classification = consistency = 'INSUFFICIENT_EVIDENCE'
    if pairs and {'UP', 'DOWN'} <= {card['direction'] for card in good}:
        consistency = 'DIVERGENT'
    elif pairs:
        if any(a['seasonal'] and b['seasonal'] for a, b in pairs):
            classification = 'SEASONAL'
        elif any(a['direction'] == b['direction'] == 'UP' for a, b in pairs):
            classification = 'EMERGING'
        elif any(a['direction'] == b['direction'] == 'DOWN' for a, b in pairs):
            classification = 'DECLINING'
        else:
            classification = 'SUSTAINED'
        consistency = 'CORROBORATED'
    return {**_base('calendar_trend_corroboration_v1'), 'classification': classification,
            'consistency': consistency, 'country_code': country, 'query': query, 'months': months,
            'as_of_month': data['as_of_month'], 'cards': cards,
            'thresholds': {'coverage': 0.7, 'relative_change': 0.2, 'seasonal_min_months': 24,
                           'seasonal_peak_ratio': 1.5},
            'assumptions': ['Descriptive only: no causal, profit or sales-volume conclusion.',
                            'Series with different source, metric, unit, version or country are never merged.',
                            'A classification needs two usable series that differ in source, source type and declared independent group; independence is declared by the caller and needs review.']}


# --- competitor snapshot changes ------------------------------------------

COMPETITOR_FIELDS = ('price', 'rating', 'review_count', 'rank')


def competitor_changes(data):
    _object(data, ('snapshots',))
    required = ('id', 'platform', 'country_code', 'external_id', 'observed_at', 'source_id', 'series_version')
    groups, ids = defaultdict(list), set()
    for raw in _rows(data['snapshots'], 'snapshots', 2000):
        _object(raw, required, (*COMPETITOR_FIELDS, 'currency', 'source_revoked'))
        row = {key: _text(raw[key], key) for key in required}
        if row['id'] in ids or not STAMP.match(row['observed_at']):
            raise ValueError('decision_invalid_snapshot')
        _day(row['observed_at'][:10], 'observed_at')
        ids.add(row['id'])
        for field in COMPETITOR_FIELDS:
            row[field] = _optional(raw, field)
        row['currency'] = None if raw.get('currency') is None else _text(raw['currency'], 'currency', 3)
        if row['price'] is not None and row['currency'] is None:
            raise ValueError('decision_price_requires_currency')
        row['source_revoked'] = _flag(raw, 'source_revoked')
        groups[(row['platform'], row['country_code'], row['external_id'])].append(row)
    products = []
    for (platform, country, external), rows in sorted(groups.items()):
        rows.sort(key=lambda row: (row['observed_at'], row['id']))
        current, previous = rows[-1], rows[-2] if len(rows) > 1 else None
        changes, gaps = {}, set()
        for field in COMPETITOR_FIELDS:
            reason = None
            if current['source_revoked'] or (previous and previous['source_revoked']):
                reason = 'SOURCE_UNAVAILABLE'
            elif previous is None:
                reason = 'NO_BASELINE'
            elif previous['observed_at'] == current['observed_at']:
                reason = 'AMBIGUOUS_ORDER'
            elif (previous['source_id'], previous['series_version']) != (current['source_id'], current['series_version']):
                reason = 'COMPARABILITY_BREAK'
            elif current[field] is None or previous[field] is None:
                reason = 'VALUE_MISSING'
            elif field == 'price' and previous['currency'] != current['currency']:
                reason = 'CURRENCY_MISMATCH'
            if reason:
                gaps.add(reason)
                changes[field] = {'previous': None, 'current': None, 'absolute': None, 'percent': None, 'reason': reason}
                continue
            old, new = previous[field], current[field]
            changes[field] = {'previous': _plain(old), 'current': _plain(new), 'absolute': _plain(new - old),
                              'percent': _plain((new - old) / old * 100) if old else None, 'reason': None}
        products.append({'platform': platform, 'country_code': country, 'external_id': external,
                         'current_evidence_id': current['id'], 'previous_evidence_id': previous['id'] if previous else None,
                         'observed_at': current['observed_at'], 'currency': current['currency'],
                         'snapshot_count': len(rows), 'changes': changes, 'gaps': sorted(gaps),
                         'evidence_ids': [row['id'] for row in rows]})
    return {**_base('adjacent_snapshot_changes_v1'), 'product_count': len(products), 'products': products,
            'assumptions': ['Only the two latest snapshots of one platform/country/product identity are compared.',
                            'A change is reported only for the same source and series version; prices only in one currency. No conversion.',
                            'Snapshots are caller-provided observations and are not verified against the platform.']}


# --- shipment reconciliation ----------------------------------------------

EVENT_TYPES = ('RECEIVED', 'LOST_FOUND', 'TRANSFER', 'ADJUSTMENT')


def shipment_reconcile(data):
    _object(data, ('as_of', 'shipment', 'events'),
            ('claims', 'in_transit_window_days', 'claim_window_days', 'proposed_claim_quantity'))
    as_of = _day(data['as_of'], 'as_of')
    shipment = data['shipment']
    _object(shipment, ('shipment_ref', 'sku', 'expected_quantity', 'shipped_date'))
    expected = int(_number(shipment['expected_quantity'], 'expected_quantity', minimum=1, maximum=10 ** 6, integer=True))
    shipped = _day(shipment['shipped_date'], 'shipped_date')
    if shipped > as_of:
        raise ValueError('decision_invalid_shipped_date')
    windows = {}
    for field, default in (('in_transit_window_days', 14), ('claim_window_days', 90)):
        windows[field] = int(_number(data.get(field, default), field, minimum=1, maximum=365, integer=True))
    totals, seen, repeated = dict.fromkeys(EVENT_TYPES, 0), set(), 0
    for raw in _rows(data['events'], 'events', 500, minimum=0):
        _object(raw, ('event_type', 'quantity', 'event_date', 'source'))
        kind = _enum(raw['event_type'], EVENT_TYPES, 'event_type')
        quantity = int(_number(raw['quantity'], 'quantity', minimum=1, maximum=10 ** 6, integer=True))
        when = _day(raw['event_date'], 'event_date')
        if not shipped <= when <= as_of:
            raise ValueError('decision_invalid_event_date')
        key = (kind, quantity, when, _text(raw['source'], 'source', 256))
        repeated += key in seen
        seen.add(key)
        totals[kind] += quantity
    claimed, refs = 0, set()
    for raw in _rows(data.get('claims', []), 'claims', 50, minimum=0):
        _object(raw, ('claim_ref', 'claimed_quantity', 'state'))
        ref = _text(raw['claim_ref'], 'claim_ref')
        if ref in refs:
            raise ValueError('decision_duplicate_claim_ref')
        refs.add(ref)
        quantity = int(_number(raw['claimed_quantity'], 'claimed_quantity', minimum=1, maximum=10 ** 6, integer=True))
        if _enum(raw['state'], ('OPEN', 'RESOLVED', 'REJECTED'), 'claim_state') != 'REJECTED':
            claimed += quantity
    received = totals['RECEIVED'] + totals['LOST_FOUND']
    gap = expected - received - totals['TRANSFER'] - totals['ADJUSTMENT']
    pending, age = max(0, gap - claimed), (as_of - shipped).days
    warnings = []
    if repeated:
        warnings.append('IDENTICAL_EVENT_ROWS')
    if claimed > max(gap, 0):
        warnings.append('CLAIMS_EXCEED_VARIANCE')
    if gap < 0:
        state = 'OVER_RECEIVED'
    elif pending == 0:
        state = 'BALANCED'
    elif age <= windows['in_transit_window_days']:
        state = 'IN_TRANSIT'
    else:
        state = 'CONFIRMED_VARIANCE'
    result = {**_base('shipment_variance_v1'), 'shipment_ref': _text(shipment['shipment_ref'], 'shipment_ref'),
              'sku': _text(shipment['sku'], 'sku'), 'as_of': data['as_of'], 'age_days': age,
              'expected_quantity': expected, 'received_quantity': received,
              'transfers_excluded': totals['TRANSFER'], 'adjustments_excluded': totals['ADJUSTMENT'],
              'already_claimed': claimed, 'state': state, 'pending_variance': pending,
              'over_received': max(0, -gap), 'warnings': warnings, **windows,
              'claim_window_days_remaining': max(0, windows['claim_window_days'] - age),
              'assumptions': ['Both windows are caller assumptions with defaults of 14 and 90 days, not platform policy.',
                              'Transfers, adjustments and non-rejected claims are excluded before a variance is confirmed.',
                              'Identical event rows are all counted and flagged; duplicates must be removed by the operator.',
                              'No claim is created or submitted.']}
    if 'proposed_claim_quantity' in data:
        proposed = int(_number(data['proposed_claim_quantity'], 'proposed_claim_quantity', minimum=1,
                               maximum=10 ** 6, integer=True))
        verdict = ('BLOCKED_IN_TRANSIT' if state == 'IN_TRANSIT' else
                   'BLOCKED_NO_VARIANCE' if pending == 0 else
                   'BLOCKED_WINDOW_ELAPSED' if age > windows['claim_window_days'] else
                   'BLOCKED_EXCESS' if proposed > pending else 'WITHIN_VARIANCE')
        result['proposed_claim'] = {'quantity': proposed, 'verdict': verdict}
    return result


# --- single-variable experiment --------------------------------------------

def _arm(value, field):
    _object(value, ('trials', 'successes'))
    trials = int(_number(value['trials'], field + '_trials', minimum=0, maximum=10 ** 9, integer=True))
    successes = int(_number(value['successes'], field + '_successes', minimum=0, maximum=10 ** 9, integer=True))
    if successes > trials:
        raise ValueError('decision_invalid_' + field + '_successes')
    return trials, successes


def experiment_evaluate(data):
    _object(data, ('primary_metric', 'changed_variables', 'higher_is_better', 'baseline', 'variant'),
            ('min_sample_per_arm', 'external_interference', 'budget_cap', 'budget_spent'))
    metric = _text(data['primary_metric'], 'primary_metric', 64)
    variables = [_text(v, 'changed_variables') for v in _rows(data['changed_variables'], 'changed_variables', 10)]
    if len(set(variables)) != len(variables) or type(data['higher_is_better']) is not bool:
        raise ValueError('decision_invalid_input')
    minimum = int(_number(data.get('min_sample_per_arm', 100), 'min_sample_per_arm', minimum=30,
                          maximum=10 ** 9, integer=True))
    interference = [_text(v, 'external_interference', 200)
                    for v in _rows(data.get('external_interference', []), 'external_interference', 10, minimum=0)]
    if ('budget_cap' in data) != ('budget_spent' in data):
        raise ValueError('decision_invalid_budget')
    (n1, s1), (n2, s2) = _arm(data['baseline'], 'baseline'), _arm(data['variant'], 'variant')
    flags = []
    if interference:
        flags.append('EXTERNAL_INTERFERENCE')
    if 'budget_cap' in data and _number(data['budget_spent'], 'budget_spent') > _number(data['budget_cap'], 'budget_cap'):
        flags.append('BUDGET_CAP_EXCEEDED')
    rates = [None if not n else Decimal(s) / n for n, s in ((n1, s1), (n2, s2))]
    z = None
    if len(variables) != 1:
        outcome, reason = 'CONFOUNDED', '同时改动多个变量，差异无法归因'
    elif min(n1, n2) < minimum:
        outcome, reason = 'INCONCLUSIVE', f'每组样本需不少于{minimum}，不宣布胜出'
    else:
        pooled = Decimal(s1 + s2) / (n1 + n2)
        variance = pooled * (1 - pooled) * (Decimal(1) / n1 + Decimal(1) / n2)
        if variance == 0:
            outcome, reason = 'INCONCLUSIVE', '两组结果没有可比较的波动'
        else:
            z = (rates[1] - rates[0]) / variance.sqrt()
            if abs(z) < Z_95:
                outcome, reason = 'NO_DETECTED_DIFFERENCE', '差异未达到双侧95%阈值'
            elif (z > 0) == data['higher_is_better']:
                outcome, reason = 'VARIANT_FAVORED', '变体在该指标上达到双侧95%阈值'
            else:
                outcome, reason = 'BASELINE_FAVORED', '基线在该指标上达到双侧95%阈值'
    return {**_base('two_proportion_single_variable_v1'), 'primary_metric': metric, 'changed_variables': variables,
            'outcome': outcome, 'reason': reason, 'flags': flags, 'external_interference': interference,
            'decision_ready': outcome in ('VARIANT_FAVORED', 'BASELINE_FAVORED') and not flags,
            'baseline': {'trials': n1, 'successes': s1, 'rate': _plain(rates[0], '0.000001')},
            'variant': {'trials': n2, 'successes': s2, 'rate': _plain(rates[1], '0.000001')},
            'z_score': _plain(z, '0.0001'), 'threshold_z': '1.96', 'min_sample_per_arm': minimum,
            'assumptions': ['Pooled two-proportion z-test on caller-supplied counts; each trial is assumed independent.',
                            'One fixed-horizon look; repeated peeking, novelty effects and seasonality are not corrected.',
                            'Any flag means the result needs a rerun or human review before it is used.',
                            'No advertising or listing change is made.']}


HANDLERS = {'commerce_selection_scorecard': selection_scorecard, 'commerce_demand_trend_assess': demand_trend,
            'commerce_competitor_changes': competitor_changes, 'commerce_shipment_reconcile': shipment_reconcile,
            'commerce_experiment_evaluate': experiment_evaluate}


def invoke(name, args):
    return HANDLERS[name](args['input'])


def definitions(schema):
    body = schema({'input': {'type': 'object'}}, ['input'])
    return [
        ('commerce_selection_scorecard', '按调用者提供的四项核心指标给最多100个候选打分并列出对比矩阵；缺项或差异未说明返回HOLD。只读草稿，不是排名或盈利承诺', body),
        ('commerce_demand_trend_assess', '按调用者提供的多来源月度序列判断需求方向、覆盖率、冲突月份与季节性；需两个独立来源互证才分类。只读描述，不推算销量', body),
        ('commerce_competitor_changes', '比较同一竞品最近两次快照的价格、评分、评论数与排名变化；来源、口径或币种不一致时标明不可比。只读，不换汇、不访问平台', body),
        ('commerce_shipment_reconcile', '按调用者提供的货件、收货事件与已有索赔核对差异，区分在途与确认差异并检查拟索赔数量。只读，不创建或提交索赔', body),
        ('commerce_experiment_evaluate', '评估单变量对照实验的两组计数；多变量、样本不足或差异未达阈值时不宣布胜出，并标记外部干扰与超预算。只读，不改广告或商品', body)]
