"""Exact store-view reads, independent of runtime recovery and alert evaluation."""
import copy
import json
import re

from agent_runtime.policy import canonical
from store_scopes import source_id

SCOPE = re.compile(r'store_source_[a-f0-9]{32}')
SHA = re.compile(r'[a-f0-9]{64}')


def selected(context):
    return context.get('store_scope') is not None


def arguments(context, page=None):
    """Arguments are fixed by the thread and the frozen per-question version."""
    if not selected(context):
        raise ValueError('agent_workspace_scope_changed')
    filters = page.get('filters', {}) if isinstance(page, dict) else {}
    refs = page.get('source_refs', {}) if isinstance(page, dict) else {}
    version = refs.get('store_scope')
    if not isinstance(page, dict) or page.get('page') != 'store-ops' or filters.get('scope') != context['store_scope'] or not isinstance(version, str) or not SHA.fullmatch(version):
        raise ValueError('copilot_page_scope_changed')
    return {'demo': context.get('demo', False), 'store_scope': context['store_scope'],
            'expected_catalog_sha256': version}


def _resolve(service, store_scope, demo, expected=None):
    if type(demo) is not bool or store_scope != 'unassigned' and (not isinstance(store_scope, str) or not SCOPE.fullmatch(store_scope)):
        raise ValueError('store_scope_not_found')
    value = service.store_scopes.resolve_members(store_scope, demo)
    if not value['complete']:
        raise ValueError('store_scope_source_unavailable')
    if expected is not None and (not isinstance(expected, str) or not SHA.fullmatch(expected) or value['catalog_sha256'] != expected):
        raise ValueError('store_scope_catalog_changed')
    return value


def validate_binding(service, context, page):
    if not selected(context):
        return None
    args = arguments(context, page)
    value = _resolve(service, args['store_scope'], args['demo'], args['expected_catalog_sha256'])
    # A store view narrows existing authority; it cannot replace an old explicit
    # source ID or an object binding with an unrelated group identity.
    if context.get('store_id', 'all') != 'all' or context.get('entity') or context.get('calculator'):
        raise ValueError('copilot_page_scope_changed')
    groups = value['catalog']['stores']
    group = next((row for row in groups if row['id'] == args['store_scope']), None)
    for field in ('platform', 'market'):
        if context.get(field, 'all') != 'all' and (group is None or context[field] != group[field]):
            raise ValueError('copilot_page_scope_changed')
    return value


def _products(service, db, selection, store_scope, demo):
    members, catalog = selection['members'], selection['catalog']
    current_connection=service.live.config().get('connection_id','')
    conditions, params = [], [int(demo),current_connection]
    for member in members:
        if member['kind'] == 'live':
            conditions.append('c.connection=?'); params.append(member['reference'])
        elif member['kind'] == 'listing':
            conditions.append("EXISTS(SELECT 1 FROM form_drafts f WHERE json_extract(f.scope,'$.module')='product_workspace' AND json_extract(f.scope,'$.case_id')=c.id AND json_extract(f.payload,'$.target.platform')=? AND json_extract(f.payload,'$.target.market')=? AND json_extract(f.payload,'$.target.store_ref')=?)")
            params.extend(member[k] for k in ('platform', 'market', 'reference'))
    if store_scope == 'unassigned':
        live = service.live.config().get('connection_id') if not demo else None
        known = list(catalog['mapping'])
        conditions = ['(?=\'\' OR c.connection IS NULL OR c.connection!=?)']
        params.extend([live or '', live or ''])
        if known:
            marks = ','.join('?' for _ in known)
            db.create_function('store_source_id', 3, lambda p, m, r: source_id('listing', p, m, r, demo), deterministic=True)
            conditions.append("NOT EXISTS(SELECT 1 FROM form_drafts f WHERE json_extract(f.scope,'$.module')='product_workspace' AND json_extract(f.scope,'$.case_id')=c.id AND store_source_id(json_extract(f.payload,'$.target.platform'),json_extract(f.payload,'$.target.market'),json_extract(f.payload,'$.target.store_ref')) IN (" + marks + '))')
            params.extend(known)
        combine = ' AND '
    else:
        combine = ' OR '
    if not conditions:
        return []
    sql = "SELECT c.id,COALESCE(NULLIF(json_extract(c.scope,'$.label'),''),NULLIF(json_extract(c.scope,'$.sku'),''),'未命名商品'),json_extract(c.scope,'$.platform'),json_extract(c.scope,'$.market'),json_extract(c.scope,'$.origin') FROM org_cases c WHERE COALESCE(json_extract(c.scope,'$.synthetic'),0)=? AND (c.connection=? OR (c.connection='' AND json_extract(c.scope,'$.origin')='research_candidate_not_inventory' AND json_extract(c.scope,'$.research_task_id') IS NOT NULL)) AND (" + combine.join(conditions) + ') ORDER BY c.created DESC,c.id'
    return [dict(id=row[0], name=row[1], platform=row[2], market=row[3], candidate=row[4] == 'research_candidate_not_inventory', synthetic=demo, store_scopes=[] if store_scope == 'unassigned' else [store_scope]) for row in db.execute(sql, params)]


def _imported_alerts(db, members, demo, store_scope):
    clauses, args = [], ['demo' if demo else 'manual_import']
    for member in members:
        if member['kind'] == 'manual':
            clauses.append("(json_extract(payload,'$.platform')=? AND json_extract(payload,'$.market')=? AND json_extract(payload,'$.store_id')=?)")
            args.extend(member[k] for k in ('platform', 'market', 'reference'))
    if not clauses:
        return {'alerts': [], 'read_mode': 'saved_alerts_no_evaluation'}
    rows = db.execute('SELECT id,status,payload,updated FROM ops_alerts WHERE scope=? AND (' + ' OR '.join(clauses) + ') ORDER BY updated DESC,id', args)
    return {'alerts': [{**json.loads(row[2]), 'id': row[0], 'status': row[1], 'updated_at': row[3], 'store_scope': store_scope} for row in rows], 'read_mode': 'saved_alerts_no_evaluation'}


def workbench(service, demo=False, store_scope='all', expected_catalog_sha256=None):
    value = _resolve(service, store_scope, demo, expected_catalog_sha256)
    members = value['members']
    with service.core.db() as db:
        if not db.in_transaction:
            db.execute('BEGIN')
        products = _products(service, db, value, store_scope, demo)
        imported = _imported_alerts(db, members, demo, store_scope)
    live, live_alerts, stores = None, None, []
    for member in members:
        if member['kind'] == 'live':
            config = service.live.config()
            if config.get('connection_id') != member['reference']:
                raise ValueError('store_scope_catalog_changed')
            live = {'configured': bool(config.get('ozon_client_id') and config.get('ozon_api_key')),
                    'orders_scope_confirmed': bool(config.get('orders_scope_confirmed')),
                    'notifications_enabled': bool(config.get('notifications_enabled')),
                    'feishu_received_confirmed': bool(config.get('feishu_received_confirmed'))}
            for kind in ('orders', 'stock', 'sales'):
                snapshot = service.live.snapshot(member['reference'], kind)
                live[kind] = {'available': bool(snapshot), 'fresh': service.live._fresh(snapshot, config),
                              'count': len(snapshot['data']['records']) if snapshot else None,
                              'observed_at': snapshot['observed_at'] if snapshot else None}
            live_alerts = service.live.alerts()
            for row in live_alerts['alerts']:
                row['store_scope'] = store_scope
        elif member['kind'] == 'platform':
            from platform_connections.protocols import CATALOG
            config = service.platforms.config(member['reference'])
            if (config['platform'], config['market']) != (member['platform'], member['market']):
                raise ValueError('store_scope_catalog_changed')
            snapshots = {}
            for resource in CATALOG[config['platform']]['resources']:
                raw = service.platforms.snapshot(member['reference'], resource)
                snapshots[resource] = {k: raw[k] for k in ('available', 'fresh', 'configuration_current', 'record_count', 'observed_at')}
            stores.append({'store_id': member['reference'], 'label': member['label'], 'platform': member['platform'], 'market': member['market'],
                           'configured': all(bool(config.get(k)) for k in CATALOG[config['platform']]['secrets']), 'scope_reviewed': bool(config.get('scope_reviewed')), 'snapshots': snapshots})
    # Recheck after reading sources, without recovering jobs or recomputing alerts.
    _resolve(service, store_scope, demo, value['catalog_sha256'])
    return {'schema': 'commerce-store-workbench-v1', 'demo': demo, 'store_scope': store_scope,
            'store_scopes': value['catalog'], 'selected_scope': {'id': store_scope, 'catalog_sha256': value['catalog_sha256'],
                'source_ids': [m['id'] for m in members], 'complete': True},
            'products': products, 'imported_alerts': imported, 'live_alerts': live_alerts, 'live': live,
            'platforms': {'stores': stores}, 'attention': None, 'channels': None, 'global_fields': [], 'unavailable': [],
            'access': {'deployment': 'local_only', 'remote_access_enabled': False, 'platform_writes_enabled': False},
            'external_messages_sent': False, 'read_only': True}


def projection(value):
    """Never expose global catalog, source references, customers or credentials."""
    fields = ('status', 'kind', 'severity', 'observed_at', 'source_sha256')
    alerts = []
    for field in ('imported_alerts', 'live_alerts'):
        rows = (value.get(field) or {}).get('alerts', [])
        alerts.extend({k: row[k] for k in fields if k in row} for row in rows[:20])
    products = value.get('products', [])
    total_alerts = sum(len((value.get(k) or {}).get('alerts', [])) for k in ('imported_alerts', 'live_alerts'))
    result = {'schema': 'commerce-store-workbench-model-v1', 'demo': value['demo'], 'store_scope': value['store_scope'], 'read_scope': 'selected_store_view_only',
            'selected_scope': copy.deepcopy(value['selected_scope']), 'read_only': True, 'external_execution_allowed': False,
            'products': [{k: row[k] for k in ('id', 'platform', 'market', 'candidate', 'synthetic') if k in row} for row in products[:20]],
            'product_total': len(products), 'products_truncated': len(products) > 20,
            'alerts': alerts[:20], 'alert_total': total_alerts,
            'alerts_truncated': total_alerts > 20, 'alert_read_mode': 'saved_or_selected_snapshot_no_evaluation',
            'live': {k: copy.deepcopy(value['live'][k]) for k in ('orders', 'stock', 'sales') if k in (value.get('live') or {})},
            'platforms': [{'platform': row['platform'], 'market': row['market'], 'configured': row['configured'],
                           'scope_reviewed': row['scope_reviewed'], 'snapshots': copy.deepcopy(row['snapshots'])} for row in (value.get('platforms') or {}).get('stores', [])],
            'unavailable': value.get('unavailable', []), 'global_fields': []}
    result['selected_scope']['source_total']=len(result['selected_scope'].get('source_ids',[]))
    lists=[result['products'],result['alerts'],result['platforms'],result['selected_scope']['source_ids']]
    while len(canonical(result).encode())>14000 and any(lists):
        max(lists,key=lambda rows:len(canonical(rows).encode())).pop()
    result['products_truncated']=len(result['products'])<len(products)
    result['alerts_truncated']=len(result['alerts'])<total_alerts
    result['selected_scope']['sources_truncated']=len(result['selected_scope']['source_ids'])<result['selected_scope']['source_total']
    result['platform_total']=len((value.get('platforms') or {}).get('stores',[]))
    result['platforms_truncated']=len(result['platforms'])<result['platform_total']
    return result
