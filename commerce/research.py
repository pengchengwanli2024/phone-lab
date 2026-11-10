"""Local research templates and evidence-preserving bilingual exports.

These are collection checklists, not marketplace publication schemas. A URL,
timestamp, hash or model output is never treated as proof of truth.
"""
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import re
from urllib.parse import urlparse

VERSION = 'research-v1'
COMMON = [
    ('title', '商品标题', True, True), ('description', '描述与卖点', True, True),
    ('category', '类目路径与类目 ID', True, True), ('attributes', '属性、材质与规格', True, True),
    ('variants', '变体、颜色、尺码与 SKU 对应', True, True),
    ('price', '价格、币种、促销条件', True, False),
    ('availability', '库存与可售状态', True, True),
    ('images', '主图、附图链接及截图索引', True, False),
    ('dimensions', '商品与包装尺寸（带单位）', True, False),
    ('weight', '商品与包装重量（带单位）', True, False),
    ('brand', '品牌与型号', False, True), ('reviews', '评论、评分与样本范围', False, True),
    ('search_context', '搜索词、排序、国家、语言与采集覆盖', False, True),
    ('policy_notes', '合规、限制与资料冲突', False, True),
]
EXTRA = {
    'research': [('subject', '调研主题与范围', True, True), ('findings', '来源中的关键陈述', True, True), ('limitations', '样本限制、反例与冲突', True, True)],
    'ozon': [('product_id', 'Ozon 商品 ID / offer_id', True, False), ('fulfillment', 'FBO / FBS / realFBS 与仓库范围', True, True), ('barcode', '条码或明确缺失原因', False, False), ('rich_content', 'Rich Content 与媒体覆盖', False, True)],
    'tiktok': [('product_id', 'TikTok 商品 ID 与 SKU ID', True, False), ('fulfillment', '站点、配送方式与运费', True, True), ('video_context', '关联视频、直播与样本时间', False, True), ('qualification', '品牌授权与类目资质线索', False, True)],
    'amazon': [('asin', 'ASIN 与父子体关系', True, False), ('product_type', 'Product Type 与类目属性版本', True, True), ('bullet_points', 'Bullet Points 原文', True, True), ('fulfillment', 'FBA / FBM、卖家与配送条件', True, True), ('gtin', 'GTIN / UPC / EAN 或豁免线索', False, False)],
    'mercado': [('item_id', 'Item ID 与站点', True, False), ('condition', '新品 / 二手等成色', True, True), ('listing_type', '刊登类型与 Catalog 对应', True, True), ('shipping', '物流方式、覆盖与包邮条件', True, True)],
    'temu': [('goods_id', 'Goods ID / SKU ID', True, False), ('operating_mode', '站点与全托管 / 半托管 / 本地模式', True, True), ('sales_attributes', '销售属性、父子条件与变体组合', True, True), ('compliance', '产地、资质与类目合规资料', True, True)],
}
REFERENCES = {
    'ozon': [('Ozon 商品内容质量参考（不硬编码评分）', 'https://docs.ozon.com/retail/actions/rating/')],
    'tiktok': [('TikTok Shop US Listing Quality', 'https://seller-us.tiktok.com/university/essay?knowledge_id=481891871868714')],
    'amazon': [('Amazon Product Type Definitions', 'https://developer-docs.amazon/sp-api/docs/product-type-definitions-api')],
    'mercado': [('Mercado Libre category attributes', 'https://global-selling.mercadolibre.com/devsite/manage-questions-answers-global-selling/atributtes-global-selling')],
    'temu': [('Temu US 属性模板', 'https://partner-us.temu.com/documentation?menu_code=38e79b35d2cb463d85619c1c786dd303&sub_menu_code=c1bf67656f404183997c74675c635087')],
    'research': [],
}


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def template(platform):
    if platform not in EXTRA:
        raise ValueError('invalid_collection_platform')
    definitions = EXTRA[platform] if platform == 'research' else COMMON + EXTRA[platform]
    fields = [dict(key=k, label=label, required=required, translatable=translate) for k, label, required, translate in definitions]
    return dict(version=VERSION, platform=platform, fields=fields,
                references=[dict(title=t, url=u, checked_on='2026-11-10', scope='reference_only') for t, u in REFERENCES[platform]],
                boundary='本项目的资料采集清单；不等于平台或类目的全部必填属性，不保证排名或上架。',
                record=dict(version=VERSION, platform=platform, market='', language='',
                            source_url='', captured_at='', raw_excerpt='', evidence_note='',
                            category_rules_url='', category_rules_checked=False,
                            fields={f['key']: dict(original='', zh='', reviewed=False, kind='source_statement', source_url='', locator='') for f in fields}))


def string(value, maximum=16000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError('invalid_research_text')
    return value


def web_url(value):
    try:
        parsed = urlparse(value)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def numbers(text):
    # A conservative drift flag: locale/thousands conversions require human review too.
    return Counter(re.findall(r'(?<!\w)[+-]?\d+(?:[.,]\d+)*(?:\s*%)?', text))


def drift(original, translated):
    warnings = []
    if numbers(original) != numbers(translated):
        warnings.append('数字或百分数与原文不一致，请核对小数和千位分隔符')
    tokens = r'\b(?:USD|CNY|RUB|EUR|GBP|JPY|AED|SAR|MXN|BRL|kg|mg|cm|mm|ml|GB|mAh)\b|[$€£¥₽]'
    if Counter(re.findall(tokens, original, re.I)) != Counter(re.findall(tokens, translated, re.I)):
        warnings.append('币种或单位标记变化，请核对后保留原标记')
    return warnings


def validate(record):
    if not isinstance(record, dict) or len(canonical(record)) > 100000:
        raise ValueError('invalid_research_record')
    spec = template(record.get('platform'))
    allowed = set(spec['record'])
    if set(record) - allowed or record.get('version') != VERSION:
        raise ValueError('invalid_research_version_or_fields')
    for key in ('market', 'language', 'source_url', 'captured_at', 'raw_excerpt', 'evidence_note', 'category_rules_url'):
        string(record.get(key, ''))
    if type(record.get('category_rules_checked', False)) is not bool:
        raise ValueError('invalid_category_review')
    fields = record.get('fields', {})
    if not isinstance(fields, dict) or set(fields) - {f['key'] for f in spec['fields']}:
        raise ValueError('invalid_collection_fields')
    issues, rows = [], []
    def issue(field, message):
        issues.append(dict(field=field, message=message))
    if not record.get('market', '').strip(): issue('market', '请记录国家站点或调研地区')
    if not record.get('language', '').strip(): issue('language', '请记录原文语言')
    if not web_url(record.get('source_url', '')): issue('source_url', '来源必须是有效的 HTTP(S) 链接')
    try:
        captured = datetime.fromisoformat(record.get('captured_at', '').replace('Z', '+00:00'))
        if captured.tzinfo is None or captured > datetime.now(timezone.utc): raise ValueError()
    except ValueError:
        issue('captured_at', '请提供带时区且不在未来的实际采集时间')
    if not record.get('raw_excerpt', '').strip(): issue('raw_excerpt', '请保留支持结论的原文摘录')
    if spec['platform'] != 'research' and (not record.get('category_rules_checked') or not web_url(record.get('category_rules_url', ''))):
        issue('category_rules_checked', '请按实际站点及类目核对当前必填属性，并记录规则链接')
    for definition in spec['fields']:
        key = definition['key']; value = fields.get(key, {})
        if not isinstance(value, dict) or set(value) - {'original', 'zh', 'reviewed', 'kind', 'source_url', 'locator', 'translation'}:
            raise ValueError('invalid_research_field')
        original = string(value.get('original', ''), 6000)
        zh = string(value.get('zh', ''), 6000)
        locator = string(value.get('locator', ''), 500)
        url = string(value.get('source_url', ''), 2000) or record.get('source_url', '')
        reviewed = value.get('reviewed', False)
        kind = value.get('kind', 'source_statement')
        if type(reviewed) is not bool or kind not in ('source_statement', 'inference', 'conflict', 'unverified'):
            raise ValueError('invalid_research_review')
        if definition['required'] and not original.strip(): issue(key, definition['label'] + '：缺少原文或明确的缺失说明')
        warnings = []
        if original.strip():
            if not web_url(url): issue(key, definition['label'] + '：缺少有效来源')
            if not locator.strip(): issue(key, definition['label'] + '：请填写原文中的位置或证据文件索引')
            if kind in ('conflict', 'unverified'): issue(key, definition['label'] + '：存在冲突或待核实内容')
            if definition['translatable']:
                if not zh.strip(): issue(key, definition['label'] + '：待翻译为中文')
                elif not reviewed: issue(key, definition['label'] + '：中文译文待校对')
                warnings = drift(original, zh) if zh.strip() else []
                for warning in warnings: issue(key, definition['label'] + '：' + warning)
        translation = value.get('translation')
        # Preserve only known translation provenance; caller-supplied model metadata is unverified.
        if translation is not None:
            if not isinstance(translation, dict) or len(canonical(translation)) > 5000: raise ValueError('invalid_translation_provenance')
        rows.append(dict(**definition, original=original, zh=zh, reviewed=reviewed,
                         kind=kind, source_url=url, locator=locator,
                         original_sha256=digest(original), translation=translation,
                         translation_status='not_required' if not definition['translatable'] or not original.strip() else 'missing' if not zh.strip() else 'reviewed_by_user' if reviewed else 'pending_review',
                         warnings=warnings))
    return dict(status='HOLD' if issues else 'REVIEWED_DRAFT', issues=issues, rows=rows,
                evidence_status='caller_supplied_not_independently_verified',
                publication_ready=False, marketplace_writes=False,
                notice='完整性与格式检查不能证明来源真实；人工校对也不等于独立事实核查。')


def export(record, final=False):
    checked = validate(record)
    if final and checked['issues']:
        raise ValueError('research_incomplete_or_unreviewed')
    payload = dict(schema=VERSION, exported_at=datetime.now(timezone.utc).isoformat(),
                   status='REVIEWED_RESEARCH' if final else 'DRAFT', record=record,
                   verification=checked, raw_excerpt_sha256=digest(record.get('raw_excerpt', '')),
                   references=template(record['platform'])['references'])
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    # The JSON bundle includes the exact original; the CSV points to its SHA-256.
    bundle_hash = digest(content)
    output = io.StringIO(newline=''); writer = csv.writer(output)
    writer.writerow(['文件状态', '平台', '地区', '原文语言', '字段', '原文', '中文翻译', '翻译状态', '陈述类型', '来源链接', '采集时间', '原文位置/证据索引', '字段原文SHA256', '原文摘录SHA256', '证据JSON_SHA256', '完整性问题'])
    for row in checked['rows']:
        cells = [payload['status'], record['platform'], record.get('market', ''), record.get('language', ''), row['label'], row['original'], row['zh'], row['translation_status'], row['kind'], row['source_url'], record.get('captured_at', ''), row['locator'], row['original_sha256'], payload['raw_excerpt_sha256'], bundle_hash, '；'.join(x['message'] for x in checked['issues'] if x['field'] == row['key'])]
        # Spreadsheet formula injection: quoting alone does not stop formula evaluation.
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value for value in cells])
    return dict(status=payload['status'], json=content, csv='\ufeff' + output.getvalue(),
                sha256=bundle_hash, filename='commerce-' + record['platform'] + '-' + payload['status'].lower(),
                issues=checked['issues'])
