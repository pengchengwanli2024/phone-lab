"""Source-reviewed feature recipes; preparing an order grants no execution."""
import json
import re

from . import workspace
from .workspace import digest

CATALOG = 'commerce/engineering/features.json'
FIELDS = {'id', 'title', 'files', 'writable_paths', 'checks'}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,79}', value):
        raise ValueError('engineering_invalid_feature_id')
    return value


class FeatureMap:
    def __init__(self, project):
        self.project = project

    def _load(self):
        path = workspace.source_file(self.project, CATALOG)
        if not path.is_file() or path.stat().st_size > 32000: raise ValueError('engineering_feature_catalog_unavailable')
        try: doc = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError): raise ValueError('engineering_invalid_feature_catalog') from None
        if (type(doc) is not dict or set(doc) != {'schema', 'features'} or type(doc['schema']) is not int or doc['schema'] != 1
                or type(doc['features']) is not list or not 1 <= len(doc['features']) <= 32):
            raise ValueError('engineering_invalid_feature_catalog')
        found = {}
        for row in doc['features']:
            if type(row) is not dict or set(row) != FIELDS: raise ValueError('engineering_invalid_feature_catalog')
            ident = identifier(row['id'])
            if (ident in found or not isinstance(row['title'], str) or not row['title'].strip() or len(row['title']) > 160
                    or any(ord(c) < 32 for c in row['title'])
                    or any(type(row[k]) is not list or any(not isinstance(p, str) for p in row[k]) for k in ('files', 'writable_paths'))):
                raise ValueError('engineering_invalid_feature_catalog')
            workspace.validate_checks(row['checks'], row['files'], row['writable_paths'])
            # Validate every declaration, including paths not used by a check.
            for name in row['files'] + row['writable_paths']: workspace.relative(name)
            found[ident] = row
        return found

    def _describe(self, row):
        _, manifest = workspace.capture(self.project, row['files'], row['writable_paths'])
        return {**row, 'recipe_sha256': digest(row), 'source_manifest': manifest, 'source_sha256': digest(manifest),
                'verification_status': 'not_run', 'grants_execution': False}

    def get(self, feature_id):
        rows = self._load();identifier(feature_id)
        if feature_id not in rows: raise ValueError('engineering_feature_not_found')
        return self._describe(rows[feature_id])

    def listing(self, query=''):
        if not isinstance(query, str) or len(query) > 100 or any(ord(c) < 32 for c in query):
            raise ValueError('engineering_invalid_feature_query')
        terms = query.casefold().split();items = []
        for row in self._load().values():
            if all(term in (row['id'] + ' ' + row['title']).casefold() for term in terms):
                item = self._describe(row)
                items.append({k: item[k] for k in ('id', 'title', 'recipe_sha256', 'source_sha256', 'verification_status')})
        return {'items': items, 'total': len(items), 'grants_execution': False, 'model_calls': 0}

    def bind(self, reference, request, manifest):
        if (type(reference) is not dict or set(reference) != {'id', 'recipe_sha256', 'source_sha256'}
                or any(not isinstance(reference[k], str) or not re.fullmatch('[0-9a-f]{64}', reference[k]) for k in ('recipe_sha256', 'source_sha256'))):
            raise ValueError('engineering_invalid_feature_reference')
        item = self.get(reference['id'])
        if item['recipe_sha256'] != reference['recipe_sha256']: raise ValueError('engineering_feature_changed')
        if any(request[k] != item[k] for k in ('files', 'writable_paths', 'checks')): raise ValueError('engineering_feature_scope_changed')
        if item['source_manifest'] != manifest or item['source_sha256'] != reference['source_sha256']:
            raise ValueError('engineering_feature_source_changed')
        return item
