"""Evidence-bound listing lineage: facts -> claims -> listing fields.

Pure, offline and read-only. The caller supplies every fact, keyword, claim,
field and restricted term; nothing is collected, generated, saved or published.
An audit result is a local draft check, never a compliance or platform approval.
"""
import csv
import hashlib
import io
import json
import re

SCHEMA = 'commerce-listing-lineage-v1'
READ_ONLY = {'commerce_listing_lineage_audit', 'commerce_listing_lineage_impact', 'commerce_listing_lineage_export',
             'commerce_listing_lineage_facts_draft'}
LIMITS = {'facts': 200, 'keywords': 500, 'claims': 300, 'fields': 100, 'restricted_terms': 500}
PREFIX = {'facts': 'F', 'keywords': 'K', 'claims': 'C'}
FIELD_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,39}')
VERSION = re.compile(r'v[0-9]{1,4}(\.[0-9]{1,4}){0,2}')
NOTES = ['本结果仅核对调用者提供的资料之间的引用关系；不证明事实真实、证明文件有效或平台合规。',
         '竞品评论洞察只能作为卖点来源线索，不能替代本品证据。',
         '受限词表完全由调用者提供；未内置任何平台违禁词库。']


def _fail(code):
    raise ValueError('lineage_' + code)


def _object(value, required, optional=()):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        _fail('invalid_document')


def _text(value, limit, code='invalid_text'):
    if type(value) is not str or not value.strip() or len(value) > limit:
        _fail(code)
    return value.strip()


def _ident(value, prefix):
    if type(value) is not str or not re.fullmatch(prefix + r'-[0-9]{1,6}', value):
        _fail('invalid_id')
    return value


def _refs(value, prefix, limit=40):
    if type(value) is not list or len(value) > limit:
        _fail('invalid_reference')
    out = []
    for item in value:
        ident = _ident(item, prefix) if prefix else item
        if not prefix and (type(item) is not str or not FIELD_ID.fullmatch(item)):
            _fail('invalid_id')
        if ident in out:
            _fail('duplicate_reference')
        out.append(ident)
    return out


def _strings(value, limit, size):
    if type(value) is not list or len(value) > limit:
        _fail('invalid_list')
    return [_text(item, size) for item in value]


def _rows(document, key, parse, minimum=0):
    rows = document.get(key, [])
    if type(rows) is not list or not minimum <= len(rows) <= LIMITS[key]:
        _fail('invalid_' + key)
    seen, out = set(), []
    for row in rows:
        item = parse(row)
        key = (item.get('channel'), item['id'])
        if key in seen:
            _fail('duplicate_id')
        seen.add(key)
        out.append(item)
    return out


def _fact(row):
    _object(row, ('id', 'dimension', 'statement'), ('proof',))
    return {'id': _ident(row['id'], 'F'), 'dimension': _text(row['dimension'], 80),
            'statement': _text(row['statement'], 1000), 'proof': _strings(row.get('proof', []), 10, 300)}


def _keyword(row):
    _object(row, ('id', 'term'), ('source',))
    return {'id': _ident(row['id'], 'K'), 'term': _text(row['term'], 200),
            'source': _text(row['source'], 200) if 'source' in row else None}


def _claim(row):
    _object(row, ('id', 'statement'), ('fact_ids', 'keyword_ids', 'insight_refs'))
    return {'id': _ident(row['id'], 'C'), 'statement': _text(row['statement'], 1000),
            'fact_ids': _refs(row.get('fact_ids', []), 'F'), 'keyword_ids': _refs(row.get('keyword_ids', []), 'K'),
            'insight_refs': _strings(row.get('insight_refs', []), 20, 300)}


def _field(row):
    _object(row, ('id', 'channel', 'text'), ('claim_ids', 'keyword_ids', 'version', 'max_chars'))
    if type(row['id']) is not str or not FIELD_ID.fullmatch(row['id']):
        _fail('invalid_id')
    version = row.get('version', 'v1')
    if type(version) is not str or not VERSION.fullmatch(version):
        _fail('invalid_version')
    limit = row.get('max_chars')
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 20000):
        _fail('invalid_max_chars')
    return {'id': row['id'], 'channel': _text(row['channel'], 80), 'text': _text(row['text'], 20000),
            'claim_ids': _refs(row.get('claim_ids', []), 'C'), 'keyword_ids': _refs(row.get('keyword_ids', []), 'K'),
            'version': version, 'max_chars': limit}


def _term(row):
    _object(row, ('term',), ('reason',))
    return {'id': _text(row['term'], 120).casefold(), 'term': _text(row['term'], 120),
            'reason': _text(row['reason'], 300) if 'reason' in row else None}


def normalize(document):
    _object(document, ('facts', 'claims', 'fields'), ('schema', 'keywords', 'restricted_terms'))
    if document.get('schema', SCHEMA) != SCHEMA:
        _fail('unsupported_schema')
    return {'schema': SCHEMA, 'facts': _rows(document, 'facts', _fact), 'keywords': _rows(document, 'keywords', _keyword),
            'claims': _rows(document, 'claims', _claim), 'fields': _rows(document, 'fields', _field),
            'restricted_terms': [{'term': t['term'], 'reason': t['reason']} for t in _rows(document, 'restricted_terms', _term)]}


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _fold(value):
    return ' '.join(value.casefold().split())


def _restricted(text, terms):
    folded = _fold(text)
    return [t['term'] for t in terms if _fold(t['term']) in folded]


def audit(document):
    doc = normalize(document)
    facts = {f['id']: f for f in doc['facts']}
    keywords = {k['id']: k for k in doc['keywords']}
    claims, by_claim = [], {}
    for claim in doc['claims']:
        reasons = []
        missing = [i for i in claim['fact_ids'] if i not in facts]
        unproven = [i for i in claim['fact_ids'] if i in facts and not facts[i]['proof']]
        if not claim['fact_ids']:
            reasons.append({'code': 'no_fact_cited'})
        if missing:
            reasons.append({'code': 'fact_not_found', 'ids': missing})
        if unproven:
            reasons.append({'code': 'fact_without_proof', 'ids': unproven})
        unknown = [i for i in claim['keyword_ids'] if i not in keywords]
        if unknown:
            reasons.append({'code': 'keyword_not_found', 'ids': unknown})
        hits = _restricted(claim['statement'], doc['restricted_terms'])
        if hits:
            reasons.append({'code': 'restricted_term', 'terms': hits})
        if not claim['fact_ids'] or missing:
            status = 'rejected_no_evidence'
        elif hits:
            status = 'rejected_restricted_term'
        elif unproven:
            status = 'needs_proof'
        elif unknown:
            status = 'needs_fix'
        else:
            status = 'passed'
        row = {'id': claim['id'], 'audit_status': status, 'reasons': reasons, 'used_in': []}
        claims.append(row)
        by_claim[claim['id']] = row
    source = {c['id']: c for c in doc['claims']}
    fields, used_keywords = [], set()
    for field in doc['fields']:
        blocking, warnings = [], []
        missing = [i for i in field['claim_ids'] if i not in by_claim]
        failed = [i for i in field['claim_ids'] if i in by_claim and by_claim[i]['audit_status'] != 'passed']
        if missing:
            blocking.append({'code': 'claim_not_found', 'ids': missing})
        if failed:
            blocking.append({'code': 'claim_not_passed', 'ids': failed})
        hits = _restricted(field['text'], doc['restricted_terms'])
        if hits:
            blocking.append({'code': 'restricted_term', 'terms': hits})
        if field['max_chars'] is not None and len(field['text']) > field['max_chars']:
            blocking.append({'code': 'over_length', 'length': len(field['text']), 'max_chars': field['max_chars']})
        unknown = [i for i in field['keyword_ids'] if i not in keywords]
        if unknown:
            blocking.append({'code': 'keyword_not_found', 'ids': unknown})
        folded = _fold(field['text'])
        absent = [i for i in field['keyword_ids'] if i in keywords and _fold(keywords[i]['term']) not in folded]
        if absent:
            warnings.append({'code': 'keyword_not_in_text', 'ids': absent})
        if not field['claim_ids']:
            warnings.append({'code': 'no_claim_bound'})
        used_keywords.update(i for i in field['keyword_ids'] if i in keywords and i not in absent)
        for ident in field['claim_ids']:
            if ident in by_claim:
                by_claim[ident]['used_in'].append({'channel': field['channel'], 'field_id': field['id']})
        fields.append({'id': field['id'], 'channel': field['channel'], 'version': field['version'],
                       'length': len(field['text']),
                       'status': 'blocked' if blocking else 'warning' if warnings else 'ready',
                       'blocking': blocking, 'warnings': warnings})
    cited = {i for c in doc['claims'] for i in c['fact_ids']}
    coverage = {'facts_without_proof': [f['id'] for f in doc['facts'] if not f['proof']],
                'facts_unused': [f['id'] for f in doc['facts'] if f['id'] not in cited],
                'claims_unused': [c['id'] for c in claims if not c['used_in']],
                'keywords_unplaced': [k['id'] for k in doc['keywords'] if k['id'] not in used_keywords],
                'claims_from_insight_only': [c['id'] for c in doc['claims'] if c['insight_refs'] and not c['fact_ids']]}
    counts = {'facts': len(doc['facts']), 'keywords': len(doc['keywords']), 'claims': len(claims), 'fields': len(fields),
              'claims_passed': sum(c['audit_status'] == 'passed' for c in claims),
              'fields_ready': sum(f['status'] == 'ready' for f in fields),
              'fields_blocked': sum(f['status'] == 'blocked' for f in fields)}
    clean = bool(fields) and not counts['fields_blocked'] and all(
        by_claim[i]['audit_status'] == 'passed' for f in doc['fields'] for i in f['claim_ids'] if i in by_claim)
    return {'schema': SCHEMA, 'status': 'PASS' if clean else 'HOLD', 'document_sha256': _digest(doc),
            'counts': counts, 'claims': claims, 'fields': fields, 'coverage': coverage,
            'restricted_terms_supplied': len(doc['restricted_terms']), 'data_source': 'caller_input',
            'review_required': True, 'external_execution_allowed': False, 'notes': NOTES}


def impact(document, changed):
    doc = normalize(document)
    _object(changed, (), ('fact_ids', 'keyword_ids', 'claim_ids'))
    wanted = {'fact_ids': _refs(changed.get('fact_ids', []), 'F', 100),
              'keyword_ids': _refs(changed.get('keyword_ids', []), 'K', 100),
              'claim_ids': _refs(changed.get('claim_ids', []), 'C', 100)}
    if not any(wanted.values()):
        _fail('empty_change')
    known = {'fact_ids': {f['id'] for f in doc['facts']}, 'keyword_ids': {k['id'] for k in doc['keywords']},
             'claim_ids': {c['id'] for c in doc['claims']}}
    unknown = sorted(i for key, ids in wanted.items() for i in ids if i not in known[key])
    affected = {}
    for claim in doc['claims']:
        via = [i for i in claim['fact_ids'] if i in wanted['fact_ids']] + [i for i in claim['keyword_ids'] if i in wanted['keyword_ids']]
        if claim['id'] in wanted['claim_ids']:
            via.insert(0, claim['id'])
        if via:
            affected[claim['id']] = via
    fields = []
    for field in doc['fields']:
        claims = [{'claim_id': i, 'via': affected[i]} for i in field['claim_ids'] if i in affected]
        direct = [i for i in field['keyword_ids'] if i in wanted['keyword_ids']]
        if claims or direct:
            fields.append({'channel': field['channel'], 'field_id': field['id'], 'version': field['version'],
                           'claims': claims, 'keyword_ids': direct})
    return {'schema': SCHEMA, 'document_sha256': _digest(doc), 'changed': wanted, 'unknown_ids': unknown,
            'affected_claims': [{'claim_id': k, 'via': v} for k, v in affected.items()],
            'affected_fields': fields, 'unaffected_field_count': len(doc['fields']) - len(fields),
            'data_source': 'caller_input', 'review_required': True, 'external_execution_allowed': False,
            'notes': ['仅按文档内登记的引用定位；未登记引用的文案、图片或其它渠道内容不会出现在结果中。']}


def _cell(value):
    text = ', '.join(value) if type(value) is list else '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


def _csv(header, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(header)
    writer.writerows([[_cell(v) for v in row] for row in rows])
    return out.getvalue()


def export(document):
    doc, result = normalize(document), audit(document)
    status = {c['id']: c for c in result['claims']}
    checked = {(f['channel'], f['id']): f for f in result['fields']}
    codes = lambda rows: [r['code'] for r in rows]
    tables = {
        'Product_Facts': _csv(['Fact_ID', '属性维度', '客观事实描述', '证明文件'],
                              [[f['id'], f['dimension'], f['statement'], f['proof']] for f in doc['facts']]),
        'Keywords': _csv(['Keyword_ID', '关键词', '来源'], [[k['id'], k['term'], k['source']] for k in doc['keywords']]),
        'Claims_Pool': _csv(['Claim_ID', '卖点主张', '关联关键词ID', '关联证据ID', '洞察来源', '审核状态', '审核原因', '引用字段'],
                            [[c['id'], c['statement'], c['keyword_ids'], c['fact_ids'], c['insight_refs'],
                              status[c['id']]['audit_status'], codes(status[c['id']]['reasons']),
                              [u['channel'] + ':' + u['field_id'] for u in status[c['id']]['used_in']]] for c in doc['claims']]),
        'Listing_Output': _csv(['Field_ID', '渠道', '文案内容', '引用的Claim_IDs', '埋入的Keyword_IDs', '版本号', '检查状态', '检查问题'],
                               [[f['id'], f['channel'], f['text'], f['claim_ids'], f['keyword_ids'], f['version'],
                                 checked[(f['channel'], f['id'])]['status'],
                                 codes(checked[(f['channel'], f['id'])]['blocking'] + checked[(f['channel'], f['id'])]['warnings'])]
                                for f in doc['fields']])}
    return {'schema': SCHEMA, 'status': result['status'], 'document_sha256': result['document_sha256'],
            'format': 'csv', 'tables': tables, 'link_columns': {
                'Claims_Pool.关联关键词ID': 'Keywords.Keyword_ID', 'Claims_Pool.关联证据ID': 'Product_Facts.Fact_ID',
                'Listing_Output.引用的Claim_IDs': 'Claims_Pool.Claim_ID', 'Listing_Output.埋入的Keyword_IDs': 'Keywords.Keyword_ID'},
            'data_source': 'caller_input', 'review_required': True, 'external_execution_allowed': False,
            'notes': ['仅返回CSV文本；不写入飞书或任何外部表格。导入后需在多维表格中手动把关联列改为双向关联。',
                      '表内含业务资料，属于私有内容。']}


def template():
    return {'schema': SCHEMA, 'synthetic': True, 'document': {
        'schema': SCHEMA,
        'facts': [{'id': 'F-001', 'dimension': '材质', 'statement': '合成示例：100% 聚酯纤维，克重 180g', 'proof': ['合成示例-质检报告编号']},
                  {'id': 'F-002', 'dimension': '护理', 'statement': '合成示例：可机洗', 'proof': []}],
        'keywords': [{'id': 'K-004', 'term': 'wrinkle free', 'source': '合成示例词库'}],
        'claims': [{'id': 'C-012', 'statement': 'Wrinkle free drape', 'fact_ids': ['F-001'], 'keyword_ids': ['K-004'],
                    'insight_refs': ['合成示例-竞品评论主题']},
                   {'id': 'C-015', 'statement': 'Machine washable', 'fact_ids': ['F-002']}],
        'fields': [{'id': 'Bullet_2', 'channel': 'Amazon US', 'text': 'Wrinkle free drape for travel.',
                    'claim_ids': ['C-012'], 'keyword_ids': ['K-004'], 'version': 'v1.2', 'max_chars': 500}],
        'restricted_terms': [{'term': 'antibacterial', 'reason': '合成示例：无检测支撑'}]}}


FACT_FIELDS = (('model', '型号'), ('variant', '规格/变体'))
OWN_PRODUCT_KINDS = ('document',)


def _short(value, limit):
    text = ' '.join(str(value).split())
    return (text[:limit - 1] + '…', True) if len(text) > limit else (text, False)


def _keyword_candidates(store_terms):
    if store_terms is None:
        return [], {'status': 'not_requested'}
    if type(store_terms) is not dict:
        _fail('invalid_store_terms')
    status = {'status': store_terms.get('availability') or 'unavailable',
              'source': store_terms.get('source'), 'offer_id': store_terms.get('offer_id'),
              'platform_sku': store_terms.get('platform_sku'), 'sku': store_terms.get('platform_sku'),
              'period': store_terms.get('period'), 'snapshot_sha256': store_terms.get('snapshot_sha256'),
              'not_global_hot_terms': True, 'empty_is_not_zero_demand': True,
              'scope_note': store_terms.get('scope_note')
                            or '当前店铺该 SKU 的平台搜索词快照，不是全平台热搜或独立市场需求'}
    items = store_terms.get('items') or []
    if type(items) is not list:
        _fail('invalid_store_terms')
    rows, seen = [], set()
    for item in items:
        if type(item) is not dict:
            continue
        term = ' '.join(str(item.get('query') or '').split())
        if not term or len(term) > 200 or term.casefold() in seen or len(rows) >= LIMITS['keywords']:
            continue
        seen.add(term.casefold())
        rows.append({'keyword': {'id': 'K-' + str(len(rows) + 1).zfill(3), 'term': term,
                                 'source': '本店商品真实搜索词快照 ' + str((store_terms.get('period') or {}).get('date_from', '?'))
                                           + '~' + str((store_terms.get('period') or {}).get('date_to', '?'))},
                     'origin': {'kind': 'store_search_terms', 'snapshot_sha256': store_terms.get('snapshot_sha256'),
                                'platform_sku': store_terms.get('platform_sku'),
                                'offer_id': store_terms.get('offer_id'), 'query_index': item.get('query_index'),
                                'unique_search_users': item.get('unique_search_users'),
                                'not_global_hot_terms': True}})
    return rows, status


def facts_draft(dossier, catalog=None, supplier_source_ids=(), store_terms=None):
    """Turn an evidence dossier into unproven fact candidates; never fills proof.

    Only records that describe this product become facts. A supplier record describes
    some candidate goods item whose identity is not established by the dossier, so it is
    returned separately and becomes a fact only when the caller names its source id.
    """
    if type(dossier) is not dict or type(dossier.get('sources')) is not list or type(dossier.get('case_id')) is not str:
        _fail('invalid_dossier')
    if type(supplier_source_ids) not in (list, tuple) or len(supplier_source_ids) > 50:
        _fail('invalid_supplier_source')
    confirmed = list(supplier_source_ids)
    if len(set(confirmed)) != len(confirmed) or any(type(i) is not str for i in confirmed):
        _fail('invalid_supplier_source')
    by_id = {s.get('id'): s for s in dossier['sources'] if type(s) is dict}
    for ident in confirmed:
        source = by_id.get(ident)
        if source is None or source.get('kind') != 'supplier' or source.get('archived') \
                or source.get('review_state') == 'conflict' or not any(
                    type(source.get(key)) is str and source[key].strip() for key, _ in FACT_FIELDS):
            _fail('invalid_supplier_source')
    candidates, excluded, insights, supply = [], [], [], []

    def add(dimension, statement, origin):
        text, truncated = _short(statement, 1000)
        if not text:
            return
        ident = 'F-' + str(len(candidates) + 1).zfill(3)
        candidates.append({'fact': {'id': ident, 'dimension': dimension, 'statement': text, 'proof': []},
                           'origin': origin, 'truncated': truncated})

    for source in dossier['sources']:
        if type(source) is not dict:
            continue
        ref = {'kind': 'evidence_source', 'id': source.get('id'), 'revision': source.get('revision'),
               'sha256': source.get('sha256'), 'label': _short(source.get('label', ''), 160)[0],
               'url': source.get('url') or None, 'review_state': source.get('review_state'),
               'independently_verified': source.get('independently_verified') is True}
        kind = source.get('kind')
        if kind == 'competitor':
            insights.append(ref['label'])
            excluded.append({**ref, 'reason': 'competitor_not_product_evidence'})
            continue
        if kind == 'supplier':
            fields = {key: source[key] for key, _ in FACT_FIELDS
                      if type(source.get(key)) is str and source[key].strip()}
            if source.get('archived'):
                excluded.append({**ref, 'reason': 'archived_source'})
            elif source.get('review_state') == 'conflict':
                excluded.append({**ref, 'reason': 'source_in_conflict'})
            elif not fields:
                excluded.append({**ref, 'reason': 'no_attribute_fields'})
            elif source.get('id') in confirmed:
                for key, dimension in FACT_FIELDS:
                    if key in fields:
                        add(dimension, fields[key], {**ref, 'field': key, 'identity_confirmed_by_caller': True})
            else:
                supply.append({'origin': ref, 'fields': fields,
                               'reason': 'supplier_item_identity_unconfirmed'})
            continue
        if source.get('archived'):
            excluded.append({**ref, 'reason': 'archived_source'})
            continue
        if kind not in OWN_PRODUCT_KINDS:
            excluded.append({**ref, 'reason': 'not_product_attribute_source'})
            continue
        if source.get('review_state') == 'conflict':
            excluded.append({**ref, 'reason': 'source_in_conflict'})
            continue
        before = len(candidates)
        for key, dimension in FACT_FIELDS:
            if type(source.get(key)) is str and source[key].strip():
                add(dimension, source[key], {**ref, 'field': key})
        if len(candidates) == before:
            excluded.append({**ref, 'reason': 'no_attribute_fields'})
    for field in (catalog or {}).get('fields') or []:
        if type(field) is not dict:
            continue
        ref = {'kind': 'catalog_field', 'key': field.get('key'), 'locator': field.get('locator'),
               'url': field.get('source_url'), 'reviewed': field.get('reviewed') is True}
        if field.get('kind') != 'source_statement':
            excluded.append({**ref, 'reason': 'inference_not_fact'})
            continue
        if type(field.get('original')) is str and field['original'].strip():
            add('来源原文:' + str(field.get('key') or 'field')[:60], field['original'], ref)
    keywords, keyword_status = _keyword_candidates(store_terms)
    return {'schema': SCHEMA, 'case_id': dossier['case_id'], 'dossier_sha256': dossier.get('dossier_sha256'),
            'catalog_source_sha256': (catalog or {}).get('source_sha256'),
            'facts': [c['fact'] for c in candidates], 'candidates': candidates, 'excluded': excluded,
            'supply_candidates': supply, 'supplier_source_ids_confirmed': confirmed,
            'keywords': [c['keyword'] for c in keywords], 'keyword_candidates': keywords,
            'keyword_source': keyword_status,
            'insight_candidates': insights, 'status': 'HOLD', 'review_required': True,
            'data_source': 'existing_local_records', 'external_execution_allowed': False,
            'notes': ['全部为待人工确认的事实候选：proof 一律为空，引用它们的声明审核结果为 needs_proof。核对实物、水洗标或检测报告后再补 proof。',
                      '只采用描述本品自身的已登记记录。货源记录描述的是某个候选货品，档案本身不能确认它与本品同款，因此单独列在 supply_candidates；人工确认同款后，用 supplier_source_ids 显式点名才会进入事实。',
                      '冲突来源、竞品与市场资料已排除；竞品标签只可作为声明的 insight_refs 线索。',
                      '关键词候选只来自当前店铺该 SKU 的真实搜索词快照，不是全平台热搜，也不代表需求高低；空结果不等于零需求。',
                      'Fact/Keyword ID 按本次读取顺序生成，资料变化后编号可能不同；写入正式文档后请固定已确认的 ID。']}


def _store_terms(service, args, dossier, catalog):
    """Read this store item's real search-term snapshot through the existing reader.

    The catalog identifies the item by offer id, while the analytics snapshot identifies it
    by platform product id, so the platform id is resolved from the snapshot's own product
    rows. An ambiguous or missing match generates no keywords instead of guessing.
    """
    offer_id = str((catalog or {}).get('sku') or (dossier.get('case') or {}).get('scope', {}).get('sku') or '').strip()
    product_id = str((catalog or {}).get('product_id') or (dossier.get('case') or {}).get('scope', {}).get('product_id') or '').strip()
    base = {'source': None, 'offer_id': offer_id or None, 'platform_sku': None, 'period': None,
            'snapshot_sha256': None, 'items': []}
    if not offer_id and not product_id:
        return {**base, 'availability': 'no_store_sku',
                'scope_note': '该商品没有店铺 SKU，无法读取本店搜索词'}
    reader = getattr(service, 'ozon_search_terms', None)
    if reader is None:
        return {**base, 'availability': 'reader_unavailable'}
    result = reader.invoke('commerce_ozon_search_terms_search', {'query': offer_id or product_id, 'limit': 100})
    products = [row for row in result.get('products') or [] if type(row) is dict]
    same_offer = [row for row in products if offer_id and str(row.get('offer_id') or '').casefold() == offer_id.casefold()]
    same_id = [row for row in products if product_id and str(row.get('sku')) == product_id]
    candidates = sorted({str(row.get('sku')) for row in (same_offer or same_id) if row.get('sku') is not None})
    common = {'source': result.get('source'), 'period': result.get('period'),
              'snapshot_sha256': result.get('snapshot_sha256'),
              'availability': result.get('availability')}
    if len(candidates) != 1:
        return {**base, **common, 'platform_sku': None,
                'availability': 'ambiguous_store_sku' if candidates else (result.get('availability') or 'no_store_sku'),
                'scope_note': '本店搜索词快照里没有唯一对应的商品，未生成关键词候选'}
    platform_sku = candidates[0]
    rows = reader.invoke('commerce_ozon_search_terms_search', {'query': platform_sku, 'limit': 100})
    items = [row for row in rows.get('items') or [] if type(row) is dict and str(row.get('sku')) == platform_sku]
    return {'source': rows.get('source') or result.get('source'), 'offer_id': offer_id or None,
            'platform_sku': platform_sku, 'period': rows.get('period') or result.get('period'),
            'snapshot_sha256': rows.get('snapshot_sha256') or result.get('snapshot_sha256'),
            'items': items, 'availability': rows.get('availability') or result.get('availability')}


def invoke(name, args, service=None):
    if name == 'commerce_listing_lineage_audit':
        return audit(args['document'])
    if name == 'commerce_listing_lineage_impact':
        return impact(args['document'], args['changed'])
    if name == 'commerce_listing_lineage_export':
        return export(args['document'])
    if name == 'commerce_listing_lineage_facts_draft':
        if service is None:
            _fail('service_required')
        dossier = service.product_evidence.get(args['case_id'])
        try:
            catalog = service.catalog.invoke('commerce_catalog_get', {'case_id': args['case_id']})
        except ValueError:
            catalog = None
        return facts_draft(dossier, catalog, args.get('supplier_source_ids', []),
                           _store_terms(service, args, dossier, catalog) if args.get('include_store_keywords') else None)
    raise ValueError('unknown_tool')


def definitions(schema, S=None):
    document = {'type': 'object', 'description': SCHEMA + '：facts/claims/fields 必填，keywords/restricted_terms 可选'}
    changed = {'type': 'object', 'description': '至少一项：fact_ids、keyword_ids、claim_ids'}
    return [
        ('commerce_listing_lineage_audit',
         '按调用者提供的本品事实、关键词、卖点声明和Listing字段核对证据血缘：缺证据或含受限词的声明及引用它的字段返回HOLD。只读草稿检查，不生成文案、不证明事实或合规、不上架。',
         schema({'document': document}, ['document'])),
        ('commerce_listing_lineage_impact',
         '按Fact/Keyword/Claim ID定位同一文档中受影响的声明与各渠道Listing字段，供局部修改；只读，仅覆盖已登记引用。',
         schema({'document': document, 'changed': changed}, ['document', 'changed'])),
        ('commerce_listing_lineage_export',
         '把已审核的血缘文档导出为四张可导入多维表格的CSV文本（事实、关键词、声明、Listing字段）；只读，不写入飞书或任何外部系统。',
         schema({'document': document}, ['document'])),
        ('commerce_listing_lineage_facts_draft',
         '从同商品已登记的资料只读整理本品事实与关键词候选（proof一律为空、待人工确认）；货源记录单独列出，需人工确认同款并以 supplier_source_ids 点名才成为事实；include_store_keywords 时附本店该 SKU 真实搜索词候选。不保存、不核实实物、不代表全平台热搜。',
         schema({'case_id': S or {'type': 'string', 'minLength': 1, 'maxLength': 160},
                 'supplier_source_ids': {'type': 'array', 'maxItems': 50,
                                         'items': {'type': 'string', 'minLength': 1, 'maxLength': 160}},
                 'include_store_keywords': {'type': 'boolean'}}, ['case_id'])),
    ]
