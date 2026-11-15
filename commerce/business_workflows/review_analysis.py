"""Lexical review topics with source-bound deduplication; no sentiment inference.

Capability design informed by Personal Agent OS commerce_reviews.py. Results
remain operator-imported evidence and cannot authorize a business action.
"""
import re


MIN_SAMPLE = 20
# Keep the original five labels stable for existing consumers.
TOPICS = {
    '物流与包装': ('物流', '包装', '快递', 'shipping', 'delivery', 'package', 'packaging', 'box', 'carton', 'достав', 'упаков', 'коробк', 'задерж'),
    '尺寸与适配': ('尺寸', '大小', '规格', 'size', 'fit', 'dimension', 'dimensions', 'small', 'large', 'размер', 'маленьк', 'больш', 'габарит'),
    '耐用与质量': ('耐用', '质量', '破损', '坏', '开裂', 'durable', 'durability', 'quality', 'broken', 'broke', 'defect', 'crack', 'качеств', 'сломан', 'хрупк', 'трещин', 'брак'),
    '价格与价值': ('价格', '贵', '便宜', 'price', 'value', 'expensive', 'cheap', 'цен', 'дорог', 'дешев', 'стоимост'),
    '使用体验': ('使用', '方便', '便携', '好用', 'use', 'portable', 'convenient', 'easy', 'love', 'удоб', 'использ'),
    '安装与装配': ('安装', '装配', '难装', 'install', 'installation', 'assembly', 'assemble', 'screw', 'mount', 'сборк', 'креп', 'монтаж', 'саморез', 'болт'),
    '材质与气味': ('材质', '气味', '味道', 'smell', 'odor', 'material', 'wood', 'fabric', 'материал', 'запах', 'дерев', 'ткань', 'джут', 'сизал'),
}
PATTERNS = {
    label: tuple(re.compile(r'(?<!\w)' + re.escape(word) + r'(?!\w)') if word.isascii() else word
                 for word in words)
    for label, words in TOPICS.items()
}


def summarize(sources):
    unique = {}
    input_count = 0
    for source in sources:
        for row in source['document']['records']:
            input_count += 1
            # IDs are only meaningful inside the selected subject and origin.
            # _selected already enforces the subject/synthetic scope boundary.
            identity = (source['document']['origin_ref'], row['id'])
            if identity in unique:
                if unique[identity][0] != row:
                    raise ValueError('business_review_identity_conflict')
                continue
            unique[identity] = (row, {'source_id': source['id'], 'version': source['version'],
                                      'record_id': row['id'], 'quote': row['text'][:320]})
    buckets = {name: [] for name in TOPICS}
    ratings = {str(n): 0 for n in range(1, 6)}
    missing = unmatched = 0
    low_ratings = []
    for row, evidence in unique.values():
        rating = row['rating']
        if rating is None:
            missing += 1
        else:
            ratings[str(rating)] += 1
            if rating <= 2:
                low_ratings.append(evidence)
        text = row['text'].casefold()
        matched = False
        for name, patterns in PATTERNS.items():
            if any((pattern in text) if isinstance(pattern, str) else pattern.search(text) for pattern in patterns):
                matched = True
                buckets[name].append((rating, evidence))
        if not matched:
            unmatched += 1
    total = len(unique)
    insufficient = total < MIN_SAMPLE
    notice = '规则命中，一条评论可命中多个主题；不代表情感、真实用户比例或选品结论。导入资料未独立核实。'
    if insufficient:
        notice += f'去重后仅{total}条，不足{MIN_SAMPLE}条，样本不足。'
    topics = []
    for name, rows in buckets.items():
        rated = [rating for rating, _ in rows if rating is not None]
        topics.append({'label': name, 'count': len(rows), 'rated_count': len(rated),
                       'average_rating': round(sum(rated) / len(rated), 2) if rated else None,
                       'evidence': [e for _, e in rows[:20]], 'evidence_truncated': len(rows) > 20})
    return {'method': 'keyword_topics_v2', 'notice': notice,
            'input_records': input_count, 'total_records': total, 'duplicate_records': input_count - total,
            'deduplication_key': 'selected_scope+origin_ref+record_id',
            'sample_insufficient': insufficient, 'minimum_sample': MIN_SAMPLE,
            'rating_counts': ratings, 'missing_rating': missing, 'unmatched': unmatched, 'topics': topics,
            'pain_points': {'method': 'explicit_rating_lte_2_not_inferred_sentiment',
                            'count': len(low_ratings), 'evidence': low_ratings[:20],
                            'evidence_truncated': len(low_ratings) > 20}}
