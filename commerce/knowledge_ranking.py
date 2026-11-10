"""Scoped bilingual lexical ranking adapted from KJDS; see THIRD_PARTY_NOTICES.md.

The caller supplies already-authorized documents. This module opens no files.
"""
import math
from pathlib import PurePosixPath
import re


SYNONYMS = {
    '选品': ('selection', 'product research', 'screening'),
    '库存': ('inventory', 'stock'), '补货': ('restock', 'replenish', 'replenishment'),
    '缺货': ('stockout', 'out of stock'), '断货': ('stockout', 'out of stock'),
    '广告': ('ads', 'advertising', 'campaign', 'ppc'),
    '关键词': ('keyword', 'search term'), '利润': ('profit', 'margin', 'contribution'),
    '退货': ('return', 'returns'), '退款': ('refund', 'refunds'),
    '客服': ('customer service', 'customer support'),
    '发货': ('shipping', 'fulfillment'), '物流': ('logistics', 'shipping'),
    '订单': ('order', 'orders'), '授权': ('authorization', 'oauth'),
}
STOPWORDS = ('可不可以', '有没有', '怎么样', '怎么办', '为什么', '如何', '怎么',
             '帮我', '请问', '一下', '需要', '应该', '我们', '我的', '的', '和', '吗')
ENGLISH_STOP = {'how', 'to', 'the', 'a', 'is', 'with', 'and', 'for', 'please', 'me'}


def query_terms(query):
    result = []
    for run in re.findall(r'[\u3400-\u9fff]+|[^\W_]+', query.casefold()):
        if re.fullmatch(r'[\u3400-\u9fff]+', run):
            for word in STOPWORDS:
                run = run.replace(word, ' ')
            for piece in run.split():
                result.extend(piece[i:i+2] for i in range(max(0, len(piece)-1)))
                if len(piece) <= 8:
                    result.append(piece)
        elif run not in ENGLISH_STOP:
            result.append(run)
    return list(dict.fromkeys(t for t in result if t))[:32]


def occurrences(text, term):
    if term.isascii():
        return min(3, len(re.findall(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', text)))
    return min(3, text.count(term))


def alternatives(term):
    values = {term: 1.0}
    for chinese, english in SYNONYMS.items():
        if term == chinese or term in english:
            for item in (chinese, *english):
                values[item] = max(values.get(item, 0), 0.6)
    return values


def ranked_notes(documents, query, limit=20):
    groups = [alternatives(term) for term in query_terms(query)]
    if not groups:
        return []
    prepared = []
    for doc in documents:
        content = doc['content']
        heading = re.search(r'^#\s+(.+)$', content, re.M)
        title = PurePosixPath(doc['path']).stem + ' ' + (heading[1] if heading else '')
        prepared.append((doc, title.casefold(), content.casefold()))
    weighted = []
    for group in groups:
        df = sum(any(occurrences(title + '\n' + body, term) for term in group) for _, title, body in prepared)
        weighted.append((group, math.log((len(prepared) + 2) / (df + 1)) + 0.3))
    scored = []
    for doc, title, body in prepared:
        score, covered, anchors = 0.0, 0, []
        for group, idf in weighted:
            gains = [(term, (6 * occurrences(title, term) + occurrences(body, term)) * weight) for term, weight in group.items()]
            term, gain = max(gains, key=lambda item: item[1])
            if gain:
                score += gain * idf
                covered += 1
                if term in body:
                    anchors.append(body.index(term))
        if not covered:
            continue
        score *= 1 + 0.3 * (covered - 1)
        # casefold can change string length; conservatively fall back to the beginning.
        idx = min(anchors) if anchors and len(body) == len(doc['content']) else 0
        start = max(0, idx - 60)
        scored.append({'path': doc['path'], 'excerpt': doc['content'][start:start+280],
                       'score': round(score, 6), 'matched_concepts': covered})
    return sorted(scored, key=lambda row: (-row['score'], row['path']))[:limit]
