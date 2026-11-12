"""Validate and export private social research packages without external calls."""
import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from urllib.parse import urlsplit

VERSION = 'commerce-social-intelligence-v1'
ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = {'commerce': '电商选品与市场趋势', 'ai': 'AI 工具与自动化', 'news': '行业新闻与热点'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def content_hash(record):
    return digest(canonical({'record_id': record['record_id'],
        'source': {k: record['source'][k] for k in ('platform', 'url', 'kind')},
        'published': record['published'],
        'original': {k: record['original'][k] for k in ('text', 'language')}}))


def record_hash(record):
    return digest(canonical({k: v for k, v in record.items() if k != 'record_sha256'}))


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        assert parsed.tzinfo is not None
        return parsed
    except (ValueError, TypeError, AttributeError, AssertionError):
        raise ValueError('timezone_required') from None


def web_url(value):
    if value is None:
        return True
    try:
        u = urlsplit(value)
        return u.scheme in ('https', 'http') and bool(u.hostname) and not u.username and not u.password and not re.search(r'[\s<>"\x00-\x1f\\]', value)
    except (ValueError, TypeError):
        return False


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_schema(value, schema, root=None, path='$'):
    """Small interpreter for the exact JSON Schema vocabulary used in schema.json."""
    root = root or schema
    if '$ref' in schema:
        target = root
        for key in schema['$ref'].removeprefix('#/').split('/'):
            target = target[key]
        return validate_schema(value, target, root, path)
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool, 'null': type(None)}
    if 'type' in schema:
        allowed = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        require(any(isinstance(value, types[t]) and not (isinstance(value, bool) and t in ('number', 'integer')) for t in allowed), path + ':type')
    if 'const' in schema:
        require(value == schema['const'], path + ':const')
    if 'enum' in schema:
        require(value in schema['enum'], path + ':enum')
    if isinstance(value, dict):
        require(set(schema.get('required', [])) <= set(value), path + ':required')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            require(set(value) <= set(props), path + ':unknown_field')
        for key, child in value.items():
            if key in props:
                validate_schema(child, props[key], root, path + '.' + key)
    if isinstance(value, list):
        require(len(value) >= schema.get('minItems', 0), path + ':minItems')
        require(len(value) <= schema.get('maxItems', 100000), path + ':maxItems')
        for i, child in enumerate(value):
            validate_schema(child, schema.get('items', {}), root, path + '[' + str(i) + ']')
    if isinstance(value, str):
        require(len(value) >= schema.get('minLength', 0) and len(value) <= schema.get('maxLength', 100000), path + ':length')
        if 'pattern' in schema:
            require(re.search(schema['pattern'], value) is not None, path + ':pattern')
        if schema.get('format') == 'date-time':
            timestamp(value)
        if schema.get('format') == 'uri':
            require(web_url(value), path + ':url')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        require(value >= schema.get('minimum', float('-inf')), path + ':minimum')


def asset_path(base, value):
    rel = PurePosixPath(value)
    require(not rel.is_absolute() and bool(rel.parts) and all(p not in ('.', '..') for p in rel.parts) and '\\' not in value and ':' not in value, 'unsafe_asset_path')
    require(len(rel.parts) > 1 and rel.parts[0] == 'evidence', 'asset_prefix_required')
    path = base.joinpath(*rel.parts).resolve()
    require(path.is_relative_to(base.resolve()), 'asset_outside_package')
    return path


def validate(bundle, base):
    schema = json.loads(Path(__file__).with_name('schema.json').read_text())
    validate_schema(bundle, schema)
    assets = {a['evidence_id']: a for a in bundle['assets']}
    records = {r['record_id']: r for r in bundle['records']}
    require(len(assets) == len(bundle['assets']) and len(records) == len(bundle['records']), 'duplicate_identity')
    for a in assets.values():
        p = asset_path(base, a['path'])
        require(p.is_file() and not p.is_symlink(), 'missing_asset')
        require(hashlib.sha256(p.read_bytes()).hexdigest() == a['sha256'], 'asset_hash_mismatch')
    ranks = set()
    versions = {(r['record_id'], r['record_sha256']): r for r in bundle['record_versions']}
    require(len(versions) == len(bundle['record_versions']), 'duplicate_version')
    versions.update({(r['record_id'], r['record_sha256']): r for r in records.values()})
    for r in versions.values():
        require(r['content_sha256'] == content_hash(r), 'content_hash_mismatch')
        require(r['record_sha256'] == record_hash(r), 'record_hash_mismatch')
        require(set(r['evidence_ids']) <= set(assets), 'unknown_evidence')
        require(r['original']['evidence_id'] in r['evidence_ids'], 'unbound_original')
        require(r['translation']['original_sha256'] == digest(r['original']['text']), 'stale_translation')
        require(r['source']['kind'] == 'unavailable' or r['source']['url'] is not None, 'source_url_required')
        if r['ranking']['selected']:
            require(r['source']['kind'] == 'permalink' and r['source']['access'] == 'observed' and bool(r['original']['text'].strip()), 'top_requires_observed_permalink_and_excerpt')
            require(r['ranking']['rank'] is not None and r['ranking']['basis_sha256'] is not None, 'top_requires_basis')
            require(r['ranking']['rank'] <= bundle['scope']['top_per_category'], 'rank_out_of_scope')
            if records.get(r['record_id']) is r:
                key = (r['category'], r['ranking']['rank'])
                require(key not in ranks, 'duplicate_rank')
                ranks.add(key)
        else:
            require(r['ranking']['rank'] is None, 'unselected_rank')
        for metric in r['metrics']:
            require(metric['evidence_id'] in r['evidence_ids'], 'unbound_metric')
    for group in ('attempts', 'events'):
        require(len({x['id'] for x in bundle[group]}) == len(bundle[group]), 'duplicate_' + group)
        for event in bundle[group]:
            require(set(event['evidence_ids']) <= set(assets), 'unknown_event_evidence')
            if group == 'attempts':
                require(timestamp(event['ended_at']) >= timestamp(event['started_at']), 'attempt_time_order')
            elif event['record_id'] is not None:
                bound = versions.get((event['record_id'], event['record_sha256']))
                require(bound is not None and event['content_sha256'] == bound['content_sha256'], 'event_version_mismatch')
            else:
                require(event['content_sha256'] is None and event['record_sha256'] is None, 'unbound_event_hash')
    return bundle


def markdown(bundle):
    lines = ['# 本轮社交信息观察', '', '这是实际采集样本；TOP 是本轮研究排序。未补齐出处的记录不进入 TOP。', '', '批次：' + bundle['batch_id'], '', bundle['scope']['limitations'], '']
    for key, title in CATEGORIES.items():
        rows = [r for r in bundle['records'] if r['category'] == key]
        count = sum(r['ranking']['selected'] for r in rows)
        lines += ['## ' + title, '', f'正式入选 {count} / {bundle["scope"]["top_per_category"]}；候选 {len(rows)}。', '']
        if not rows:
            lines += ['本轮尚无满足来源与证据要求的内容。', '']
        for r in rows:
            lines += ['### ' + r['title_zh'], '', r['summary_zh'], '', '来源：' + (r['source']['url'] or '单条链接尚未取得'), '', '发布时间（原始显示）：' + r['published']['display'] + '；采集：' + r['captured_at'], '', '原文：' + r['original']['text'], '', '中文翻译：' + r['translation']['zh'], '', '价值判断：' + r['ranking']['reason'], '', '下一步：' + r['next_action'], '', '限制：' + '；'.join(r['limitations']), '', '版本：`' + r['content_sha256'] + '`', '']
    lines += ['## 采集过程', '']
    for a in bundle['attempts']:
        lines += [f'- {a["started_at"]} → {a["ended_at"]} · {a["platform"]} · {a["query"]} · {a["status"]} · {a["reason"]}']
    lines += ['', '## 证据索引', '']
    for a in bundle['assets']:
        lines += [f'- {a["evidence_id"]} · {a["path"]} · SHA-256 `{a["sha256"]}` · {a["locator"]}']
    return '\n'.join(lines) + '\n'


def reader(bundle):
    sys.path.insert(0, str(ROOT / 'commerce/ui'))
    from build import generated
    # All source values are escaped at render time. No captured HTML is executed.
    data = json.dumps(bundle, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    css = (ROOT / 'commerce/ui/primitives.css').read_text() + '\n' + Path(__file__).with_name('reader.css').read_text()
    kit = (ROOT / 'commerce/ui/status.js').read_text() + '\n' + (ROOT / 'commerce/ui/kit.js').read_text()
    script = Path(__file__).with_name('reader.js').read_text()
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src \'self\'; connect-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>社交信息观察 · 阅读样张</title><style>' + generated() + css + '</style><body class="app"><header><p>电商工作台 / 信息聚合 / 社交观察 · 独立阅读样张</p><h1>值得跟进的信息</h1><p id="overview"></p><div id="controls"></div></header><main><nav id="records" aria-label="观察记录"></nav><article id="detail" aria-live="polite"></article></main><section id="process"></section><script>' + kit + '</script><script type="application/json" id="data">' + data + '</script><script>' + script + '</script></body></html>'


def export(bundle, base, output):
    validate(bundle, base)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Evidence follows the same relative paths, so offline exports remain usable.
    for a in bundle['assets']:
        src = asset_path(base, a['path'])
        dest = asset_path(output, a['path'])
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if src != dest:
            require(not dest.exists() or dest.read_bytes() == src.read_bytes(), 'export_asset_conflict')
            shutil.copyfile(src, dest)
        dest.chmod(0o600)
    files = {'bundle.json': json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', 'records.jsonl': ''.join(canonical({'schema': VERSION, 'batch_id': bundle['batch_id'], 'record': r, 'evidence_manifest': [a for a in bundle['assets'] if a['evidence_id'] in r['evidence_ids']]}) + '\n' for r in bundle['records']), 'report.md': markdown(bundle), 'reader.html': reader(bundle)}
    stream = [{'schema': VERSION, 'batch_id': bundle['batch_id'], 'kind': 'metadata', 'data': {'created_at': bundle['created_at'], 'scope': bundle['scope']}}]
    for group in ('records', 'record_versions', 'assets', 'attempts', 'events'):
        stream.extend({'schema': VERSION, 'batch_id': bundle['batch_id'], 'kind': group, 'data': value} for value in bundle[group])
    files['exchange.jsonl'] = ''.join(canonical(row) + '\n' for row in stream)
    rows = io.StringIO(newline='')
    writer = csv.writer(rows)
    writer.writerow(['record_id', 'title_zh', 'category', 'source_url', 'captured_at', 'selected', 'content_sha256', 'bundle_sha256'])
    for r in bundle['records']:
        # Quarantine spreadsheet formulas while retaining exact text in JSON.
        writer.writerow([("'" + str(v)) if str(v).lstrip().startswith(('=', '+', '-', '@')) else v for v in [r['record_id'], r['title_zh'], r['category'], r['source']['url'] or '', r['captured_at'], r['ranking']['selected'], r['content_sha256'], digest(files['bundle.json'])]])
    files['index.csv'] = rows.getvalue()
    for name, content in files.items():
        p = output / name
        require(not p.is_symlink(), 'export_symlink')
        p.write_text(content)
        p.chmod(0o600)
    manifest = {'schema': 'commerce-social-export-manifest-v1', 'files': {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in files}, 'evidence': {a['path']: a['sha256'] for a in bundle['assets']}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'manifest.json').chmod(0o600)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = export(json.loads(args.input.read_text()), args.input.parent, args.output)
    print(json.dumps({'status': 'exported', 'files': list(result['files']), 'evidence_count': len(result['evidence'])}))
