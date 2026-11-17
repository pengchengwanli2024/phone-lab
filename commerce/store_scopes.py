"""Explicit local store grouping for views; never changes evidence or authorization."""
import json
import time
from research import canonical, digest


def definitions(schema, string):
    return [
        ('commerce_store_scope_list', '读取准确来源身份与本机店铺视图关联，不同步店铺', schema({'demo': {'type': 'boolean'}})),
        ('commerce_store_scope_link', '明确关联或分开同一店铺的资料来源；仅影响视图，不修改原记录或平台权限', schema({
            'demo': {'type': 'boolean'}, 'source_id': string, 'store_scope': string,
            'expected_catalog_sha256': string, 'expected_revision': {'type': 'integer', 'minimum': 0},
            'confirmed': {'type': 'boolean'}, 'idempotency_key': string,
        }, ['source_id', 'store_scope', 'expected_catalog_sha256', 'expected_revision', 'confirmed', 'idempotency_key'])),
    ]


def source_id(kind, platform, market, reference, demo=False):
    return 'store_source_' + digest(canonical([demo, kind, platform, market, reference]))[:32]


class StoreScopes:
    def __init__(self, service):
        self.service, self.core = service, service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS store_scope_links(mode TEXT,source_id TEXT,target_id TEXT,revision INTEGER,source_sha TEXT,target_sha TEXT,PRIMARY KEY(mode,source_id))')
            db.execute('CREATE TABLE IF NOT EXISTS store_scope_events(request_key TEXT PRIMARY KEY,request_sha TEXT,source_id TEXT,target_id TEXT,revision INTEGER,created REAL)')

    @staticmethod
    def mode(demo):
        if type(demo) is not bool:
            raise ValueError('invalid_demo')
        return 'demo' if demo else 'real'

    def catalog(self, demo=False, *, internal=False):
        mode = self.mode(demo)
        sources, unavailable, references = {}, [], {}

        def add(kind, platform, market, reference, label, revision=''):
            if not isinstance(reference, str) or not reference or not platform or not market:
                return
            ident = source_id(kind, platform, market, reference, demo)
            references[ident] = dict(id=ident,kind=kind,platform=platform,market=market,reference=reference,label=label or reference)
            sources[ident] = dict(id=ident, kind=kind, platform=platform, market=market,
                                 label=label or reference, sha256=digest(canonical([ident, revision])))

        if not demo:
            try:
                config = self.service.live.config()
                add('live', 'ozon', 'RU', config.get('connection_id', ''), config.get('store_label', 'Ozon'))
            except Exception:
                unavailable.append('live')
            try:
                # Read configuration identities only; listing() also recovers jobs.
                with self.service.platforms.configs() as values:
                    for entry in values.values():
                        add('platform', entry['platform'], entry['market'], entry['store_id'], entry['label'], entry['revision'])
            except Exception:
                unavailable.append('platforms')
        with self.core.db() as db:
            observations = db.execute("SELECT json_extract(e.payload,'$.platform'),json_extract(e.payload,'$.market'),json_extract(e.payload,'$.store_id') FROM ops_latest l JOIN ops_events e ON e.scope=l.scope AND e.event_id=l.event_id WHERE l.scope=?", ('demo' if demo else 'manual_import',)).fetchall()
            for row in observations:
                add('manual', row[0], row[1], row[2], row[2])
            targets = db.execute("SELECT json_extract(f.payload,'$.target') FROM form_drafts f JOIN org_cases c ON c.id=json_extract(f.scope,'$.case_id') WHERE json_extract(f.scope,'$.module')='product_workspace' AND json_extract(f.payload,'$.target') IS NOT NULL AND COALESCE(json_extract(c.scope,'$.synthetic'),0)=?", (int(demo),)).fetchall()
            for row in targets:
                target = json.loads(row[0])
                add('listing', target.get('platform'), target.get('market'), target.get('store_ref'), target.get('store_ref'))
            links = {row[0]: row[1:] for row in db.execute('SELECT source_id,target_id,revision,source_sha,target_sha FROM store_scope_links WHERE mode=?', (mode,))}
        mapping = {ident: ident for ident in sources}
        for ident, item in sources.items():
            link = links.get(ident)
            target = sources.get(link[0]) if link else None
            # A changed account/configuration requires a fresh explicit link.
            current = bool(link and target and item['sha256'] == link[2] and target['sha256'] == link[3])
            item.update(revision=link[1] if link else 0, linked_to=link[0] if link else ident,
                        link_current=not link or current, linked=bool(current and link[0] != ident))
            if current:
                mapping[ident] = link[0]
        # Imported data can never create chains or silently follow a target's move.
        for ident, target in list(mapping.items()):
            if mapping.get(target) != target:
                mapping[ident] = ident
                sources[ident]['link_current'] = False
        groups = {}
        for ident, target in mapping.items():
            group = groups.setdefault(target, dict(id=target, label=sources[target]['label'], platform=sources[target]['platform'], market=sources[target]['market'], source_ids=[]))
            group['source_ids'].append(ident)
        result = dict(schema='commerce-store-scopes-v1', demo=demo,
                      stores=sorted(groups.values(), key=lambda row: (row['platform'], row['market'], row['label'], row['id'])),
                      sources=sorted(sources.values(), key=lambda row: row['id']), mapping=mapping,
                      complete=not unavailable, unavailable=unavailable, authorization_changed=False)
        result['sha256'] = digest(canonical(result))
        if internal:
            result['_references'] = references
        return result

    def resolve_members(self, store_scope, demo=False):
        catalog = self.selection(store_scope,demo,self.catalog(demo,internal=True))
        references=catalog.pop('_references')
        members=[{**references[ident],'sha256':next(item['sha256']for item in catalog['sources']if item['id']==ident)} for ident,target in catalog['mapping'].items() if store_scope=='all' or target==store_scope]
        return dict(catalog_sha256=catalog['sha256'],complete=catalog['complete'],unavailable=catalog['unavailable'],members=members,catalog=catalog)

    def selection(self, store_scope='all', demo=False, catalog=None):
        if not isinstance(store_scope,str) or not 1<=len(store_scope)<=160:raise ValueError('store_scope_not_found')
        value = catalog or self.catalog(demo)
        if store_scope not in ('all', 'unassigned') and store_scope not in {item['id'] for item in value['stores']}:
            raise ValueError('store_scope_not_found')
        return value

    def target_scope(self, target, catalog):
        ident = source_id('listing', target.get('platform'), target.get('market'), target.get('store_ref'), catalog['demo'])
        return catalog['mapping'].get(ident)

    def includes_target(self, target, store_scope, catalog):
        value = self.target_scope(target, catalog)
        return store_scope == 'all' or (value is None if store_scope == 'unassigned' else value == store_scope)

    def project(self, value, store_scope='all'):
        catalog = self.selection(store_scope, value['demo'])
        mapping, demo = catalog['mapping'], value['demo']
        config = self.service.live.config() if not demo else {}
        live_id = source_id('live', 'ozon', 'RU', config.get('connection_id', ''), demo)
        def selected(ident):
            current = mapping.get(ident)
            return store_scope == 'all' or (current is None if store_scope == 'unassigned' else current == store_scope)
        for field, kind in [('live_alerts', 'live'), ('imported_alerts', 'manual')]:
            if value.get(field) is not None:
                value[field] = {**value[field], 'alerts': [{**row, 'store_scope': mapping.get(live_id if kind == 'live' else source_id(kind, row['platform'], row['market'], row['store_id'], demo))} for row in value[field]['alerts'] if selected(live_id if kind == 'live' else source_id(kind, row['platform'], row['market'], row['store_id'], demo))]}
        case_scopes = {}
        with self.core.db() as db:
            for ident, connection, raw in db.execute('SELECT id,connection,scope FROM org_cases'):
                scope = json.loads(raw)
                if (scope.get('synthetic') is True) != demo:
                    continue
                ids = {mapping[live_id]} if not demo and connection and connection == config.get('connection_id') and live_id in mapping else set()
                case_scopes[ident] = ids
            for case_id, raw in db.execute("SELECT json_extract(scope,'$.case_id'),json_extract(payload,'$.target') FROM form_drafts WHERE json_extract(scope,'$.module')='product_workspace' AND json_extract(payload,'$.target') IS NOT NULL"):
                target = self.target_scope(json.loads(raw), catalog)
                if case_id in case_scopes and target:
                    case_scopes[case_id].add(target)
        value['products'] = [{**item, 'store_scopes': sorted(case_scopes.get(item['id'], set()))} for item in value['products'] if store_scope == 'all' or (not case_scopes.get(item['id']) if store_scope == 'unassigned' else store_scope in case_scopes.get(item['id'], set()))]
        if value.get('platforms'):
            value['platforms'] = {**value['platforms'], 'stores': [item for item in value['platforms']['stores'] if selected(source_id('platform', item['platform'], item['market'], item['store_id'], demo))]}
        if not selected(live_id):
            value['live'] = None
        value.update(store_scope=store_scope, store_scopes=catalog)
        # Attention/channels are global services and remain explicitly global.
        return value

    def link(self, source_id, store_scope, expected_catalog_sha256, expected_revision, confirmed, idempotency_key, demo=False):
        mode = self.mode(demo)
        if confirmed is not True or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('store_scope_confirmation_required')
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 160:
            raise ValueError('store_scope_invalid_request')
        request_sha = digest(canonical([mode, source_id, store_scope, expected_catalog_sha256, expected_revision]))
        with self.core.atomic():
            with self.core.db() as db:
                prior = db.execute('SELECT request_sha FROM store_scope_events WHERE request_key=?', (idempotency_key,)).fetchone()
                if prior:
                    if prior[0] != request_sha:
                        raise ValueError('store_scope_idempotency_conflict')
                    return self.catalog(demo)
                catalog = self.catalog(demo)
                if catalog['sha256'] != expected_catalog_sha256:
                    raise ValueError('store_scope_catalog_changed')
                sources = {item['id']: item for item in catalog['sources']}
                source, target = sources.get(source_id), sources.get(store_scope)
                if not source or not target or source['revision'] != expected_revision:
                    raise ValueError('store_scope_revision_conflict')
                if source['platform'] != target['platform'] or source['market'] != target['market']:
                    raise ValueError('store_scope_boundary_mismatch')
                if source_id != store_scope and (store_scope not in {item['id'] for item in catalog['stores']} or any(group != source_id and parent == source_id for group, parent in catalog['mapping'].items())):
                    raise ValueError('store_scope_link_chain_forbidden')
                revision = expected_revision + 1
                db.execute('INSERT OR REPLACE INTO store_scope_links VALUES(?,?,?,?,?,?)', (mode, source_id, store_scope, revision, source['sha256'], target['sha256']))
                db.execute('INSERT INTO store_scope_events VALUES(?,?,?,?,?,?)', (idempotency_key, request_sha, source_id, store_scope, revision, time.time()))
        return self.catalog(demo)

    def invoke(self, name, args):
        return self.catalog(**args) if name == 'commerce_store_scope_list' else self.link(**args)
