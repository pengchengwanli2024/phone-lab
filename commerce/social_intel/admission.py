"""Pure admission boundary; never fetch URLs or mutate a research bundle."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
try:
    from . import package as contract
except ImportError:
    import package as contract

POSTS = {
    'x': ({'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'}, r'/(?:[A-Za-z0-9_]+/status|i/status)/[0-9]{8,30}/?'),
    'tiktok': ({'tiktok.com', 'www.tiktok.com'}, r'/@[A-Za-z0-9._]+/(?:video|photo)/[0-9]{8,30}/?'),
}

def check_link(source):
    if source['kind'] != 'permalink':
        return
    url = urlsplit(source['url'])
    if url.scheme != 'https' or url.username or url.password or url.fragment:
        raise ValueError('invalid_social_permalink')
    if source['platform'] in POSTS:
        hosts, pattern = POSTS[source['platform']]
        valid = url.hostname in hosts and re.fullmatch(pattern, url.path)
    else:
        valid = bool(url.path.strip('/'))
    if not valid:
        raise ValueError('invalid_social_permalink')

def check_assets(bundle, base):
    size = 0
    try:
        for asset in bundle['assets']:
            cursor = base
            for part in Path(asset['path']).parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError('social_evidence_symlink')
            target = contract.asset_path(base, asset['path'])
            if not target.is_file():
                raise ValueError('social_evidence_missing')
            size += target.stat().st_size
            if size > 64 * 1024 * 1024:
                raise ValueError('social_evidence_too_large')
    except OSError:
        raise ValueError('social_evidence_unavailable') from None

def prepare(bundle, base):
    schema = json.loads(Path(contract.__file__).with_name('schema.json').read_text())
    contract.validate_schema(bundle, schema)
    encoded = contract.canonical(bundle)
    if len(encoded.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('social_metadata_too_large')
    check_assets(bundle, Path(base))
    contract.validate(bundle, Path(base))
    for record in bundle['records'] + bundle['record_versions']:
        check_link(record['source'])
    return {'fingerprint': contract.digest(encoded),
            'record_ids': [r['record_id'] for r in bundle['records']],
            'selected_count': sum(r['ranking']['selected'] for r in bundle['records'])}
