"""Immutable join between captured article evidence and an unreviewed translation."""
from copy import deepcopy
from hashlib import sha256
import re
from urllib.parse import urlsplit

def require(condition):
    if not condition:raise ValueError('invalid_article_evidence_binding')

def text_hash(value):return sha256(value.encode('utf-8')).hexdigest()

def bind(article,translated=None):
    require(isinstance(article,dict))
    text=article.get('text')
    require(isinstance(text,str) and bool(text.strip()))
    require(text_hash(text)==article.get('content_sha256'))
    require(isinstance(article.get('record_sha256'),str) and bool(re.fullmatch('[a-f0-9]{64}',article['record_sha256'])))
    require(isinstance(article.get('source_url'),str))
    url=urlsplit(article['source_url'])
    require(url.scheme=='https' and bool(url.hostname) and not url.username and not url.password)
    require(isinstance(article.get('captured_at'),str) and bool(article['captured_at']))
    routes=article.get('routes')
    require(isinstance(routes,list) and all(isinstance(x,str) and x for x in routes) and len(set(routes))>=2)
    result=deepcopy(article)
    if translated is not None:
        require(isinstance(translated,dict))
        zh=translated.get('zh')
        require(isinstance(zh,str) and bool(zh.strip()))
        require(translated.get('original_sha256')==article['content_sha256'])
        require(translated.get('zh_sha256')==text_hash(zh))
        result['translation']=dict(deepcopy(translated),status='pending_review',independently_verified=False)
    return result
