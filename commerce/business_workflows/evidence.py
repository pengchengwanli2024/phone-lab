"""Pure evidence snapshots. Validity never grants commerce authorization."""
import hashlib
import json
import math
import re

KINDS = frozenset(('review', 'support', 'listing', 'price', 'shipping', 'refund', 'purchase', 'advertising'))
ENVELOPE_KEYS = {'schema', 'kind', 'scope', 'sources', 'content', 'synthetic', 'draft_sha256', 'external_execution_allowed'}

def _json(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for child in value: _json(child)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for child in value.values(): _json(child)
        return
    raise ValueError('invalid_draft')

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def _sources(rows):
    if type(rows) is not list or not rows:
        raise ValueError('invalid_sources')
    by_id = {}
    for row in rows:
        if type(row) is not dict or set(row) != {'id', 'version', 'sha256'}:
            raise ValueError('invalid_sources')
        ident = row['id']
        if type(ident) is not str or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', ident) or ident in by_id:
            raise ValueError('invalid_sources')
        if type(row['version']) is not int or row['version'] <= 0:
            raise ValueError('invalid_sources')
        if type(row['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ValueError('invalid_sources')
        by_id[ident] = dict(row)
    return [by_id[key] for key in sorted(by_id)]

def freeze(kind, scope, sources, content, synthetic=False):
    try:
        if type(kind) is not str or kind not in KINDS:
            raise ValueError('invalid_kind')
        if type(scope) is not dict or set(scope) != {'platform', 'store_ref', 'subject_ref'}:
            raise ValueError('invalid_scope')
        for key, value in scope.items():
            if key == 'store_ref' and value is None: continue
            if type(value) is not str or not value.strip() or len(value) > 160:
                raise ValueError('invalid_scope')
        if type(content) is not dict or type(synthetic) is not bool:
            raise ValueError('invalid_content')
        _json(content)
        body = {'schema':'commerce-evidence-draft-v1', 'kind':kind, 'scope':scope,
                'sources':_sources(sources), 'content':content, 'synthetic':synthetic}
        raw = _canonical(body)
        result = json.loads(raw)
        result.update(draft_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(), external_execution_allowed=False)
        return result
    except (TypeError, ValueError, RecursionError, OverflowError):
        raise ValueError('invalid_draft') from None

def recheck(frozen, current_sources):
    invalid = {'status':'invalid', 'changed_ids':[], 'external_execution_allowed':False}
    try:
        if type(frozen) is not dict or set(frozen) != ENVELOPE_KEYS:
            return invalid
        if frozen['schema'] != 'commerce-evidence-draft-v1' or frozen['external_execution_allowed'] is not False:
            return invalid
        expected = freeze(frozen['kind'], frozen['scope'], frozen['sources'], frozen['content'], frozen['synthetic'])
        if type(frozen['draft_sha256']) is not str or frozen['draft_sha256'] != expected['draft_sha256']:
            return invalid
        current = {row['id']:row for row in _sources(current_sources)}
        changed = sorted(row['id'] for row in expected['sources'] if current.get(row['id']) != row)
        return {'status':'stale' if changed else 'current', 'changed_ids':changed, 'external_execution_allowed':False}
    except Exception:
        return invalid
