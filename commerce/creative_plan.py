"""Evidence-backed local creative draft plans; never submits generation."""
import re


def plan(brief):
    if not isinstance(brief, dict):
        raise ValueError('invalid_brief')
    product = brief.get('product') or {}
    if not isinstance(product, dict):
        raise ValueError('invalid_product')
    name = product.get('name', '')
    if not isinstance(name, str) or len(name) > 120:
        raise ValueError('invalid_product_name')
    name = name.strip()
    facts = []
    seen = set()
    for item in product.get('verified_facts', []):
        if not isinstance(item, dict):
            continue
        key, text, source = (item.get(k) for k in ('id', 'text', 'evidence_ref'))
        if not all(isinstance(v, str) and v.strip() for v in (key, text, source)):
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', key) or len(text) > 500 or len(source) > 1000 or key in seen:
            continue
        seen.add(key)
        facts.append({'id': key, 'text': text.strip(), 'evidence_ref': source.strip()})
    ready = bool(name and facts)
    ids = [f['id'] for f in facts]
    body = '；'.join(f['text'] for f in facts)
    hooks = [('detail', '先看清'+name+'的这些细节。'),
             ('selection', '选择'+name+'，先核对这些信息。'),
             ('demonstration', '用一段演示说明'+name+'。')]
    scripts = [{'angle': angle, 'hook': hook, 'body': body,
                'cta': '查看商品规格，再确认是否适合自己的使用场景。',
                'fact_ids': list(ids)} for angle, hook in hooks] if ready else []
    roles = [('hook', 0, 3000), ('problem', 3000, 8000),
             ('demonstration', 8000, 18000), ('evidence_or_objection', 18000, 24000),
             ('call_to_action', 24000, 30000)]
    return {'status': 'draft_ready' if ready else 'needs_inputs',
            'generator': 'local_evidence_template',
            'external_generation_submitted': False,
            'missing': ([] if name else ['product_name']) + ([] if facts else ['evidenced_product_facts']),
            'facts': facts, 'scripts': scripts,
            'language_status': 'Chinese scaffold; target-language rewriting requires separate validation',
            'image_plans': [{'kind': k, 'preserve_product_identity': True,
                             'fact_ids': list(ids), 'status': 'not_rendered'}
                            for k in ['product_main', 'usage_scene', 'advertisement']],
            'video_plan': {'status': 'not_rendered', 'duration_ms': 30000,
                           'segments': [{'role': r, 'start_ms': a, 'end_ms': b,
                                         'fact_ids': list(ids) if r == 'demonstration' else []}
                                        for r, a, b in roles]}}
