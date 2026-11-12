"""A2UI 1.0 cost surfaces, sharing the existing task ledger and calculator.

The optional JSON Schema dependency is loaded only on A2UI calls. No network
schema resolution, model-authored code, marketplace I/O, or implicit defaults.
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from operations_analysis import UNIT_FIELDS, RATES, number

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / 'catalog.json').read_text())
CATALOG_ID = CATALOG['catalogId']
ACTION = 'commerce.cost.calculate'
CURRENCIES = ('CNY', 'USD', 'RUB', 'EUR', 'GBP', 'JPY', 'SGD', 'MXN', 'BRL', 'AED', 'SAR', 'TRY', 'ZAR', 'NGN', 'KES', 'ETB')
LABELS = dict(zip(UNIT_FIELDS, ('测算币种', '单件售价', '采购成本', '国内运费', '包装成本', '履约费用', '其他固定费用', '平台佣金率', '支付费率', '退货预留比例', '广告费用比例')))
SOURCE = '来源：本次用户输入，尚未经独立核实。金额均使用所选币种，不自动换汇；费率以售价为基数。结果为贡献测算草稿，不是净利润或结算账单。'
BOUND_SOURCE = '来源：当前商品工作项的已保存参数与原有产物，尚未经独立核实。金额同币种，不自动换汇；结果为贡献测算草稿。'
_validators = None


def validators():
    global _validators
    if _validators is None:
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            raise ValueError('a2ui_dependency_missing') from None
        documents = [(ROOT / 'spec' / name) for name in ('agent_to_renderer.json', 'renderer_to_agent.json', 'common_types.json', 'catalog_definition.json')]
        registry = Registry(retrieve=lambda uri: (_ for _ in ()).throw(ValueError('a2ui_remote_schema_forbidden')))
        for path in documents:
            doc = json.loads(path.read_text())
            registry = registry.with_resource(doc['$id'], Resource.from_contents(doc))
        registry = registry.with_resource('https://a2ui.org/specification/v1_0/catalog.json', Resource.from_contents(CATALOG))
        candidate = {p.stem: Draft202012Validator(json.loads(p.read_text()), registry=registry) for p in documents}
        candidate['catalog_definition'].validate(CATALOG)
        _validators = candidate
    return _validators


def validate_input(data):
    if not isinstance(data, dict) or set(data) - set(UNIT_FIELDS):
        raise ValueError('invalid_analysis_input')
    for key, value in data.items():
        if value is None:
            continue
        if key == 'currency':
            if not isinstance(value, str) or value not in CURRENCIES:
                raise ValueError('invalid_currency')
        else:
            number(value, key, minimum=.01 if key == 'price' else 0, maximum=1 if key in RATES else 10**12)


def validate_surface(messages):
    try:
        if len(json.dumps(messages, allow_nan=False).encode()) > 65536 or not isinstance(messages, list) or len(messages) != 1:
            raise ValueError('a2ui_invalid_surface')
        validators()['agent_to_renderer'].validate(messages[0])
        surface = messages[0]['createSurface']
        if surface['catalogId'] != CATALOG_ID or surface.get('sendDataModel', False):
            raise ValueError('a2ui_invalid_catalog')
        nodes = surface['components']
        if not 1 <= len(nodes) <= 48:
            raise ValueError('a2ui_invalid_surface')
        graph = {n['id']: n.get('children', []) for n in nodes}
        if len(graph) != len(nodes):
            raise ValueError('a2ui_duplicate_component')
        seen = set()
        def visit(ident, depth):
            if ident in seen or ident not in graph or depth > 8:
                raise ValueError('a2ui_invalid_tree')
            seen.add(ident)
            for child in graph[ident]:
                visit(child, depth + 1)
        visit('root', 0)
        if len(seen) != len(graph):
            raise ValueError('a2ui_orphan_component')
    except (KeyError, TypeError, RecursionError):
        raise ValueError('a2ui_invalid_surface') from None
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError('a2ui_schema_rejected') from None
    return True


def data_model(data, result, source=SOURCE):
    display = {'status': '填写参数后计算。未知费用请留空，确认无此费用时填 0。', 'contribution': '单件贡献：—', 'total_cost': '单件总成本：—', 'contribution_rate': '贡献率：—', 'source': source}
    if result:
        if result['status'] == 'HOLD':
            display['status'] = '待补数据：' + '、'.join(LABELS[k] for k in result['missing'])
        else:
            display.update(status='已按本次参数计算 · 待审阅', contribution=f"单件贡献：{result['contribution']:.2f} {result['currency']}", total_cost=f"单件总成本：{result['total_cost']:.2f} {result['currency']}", contribution_rate=f"贡献率：{result['contribution_rate'] * 100:g}%")
    return {'input': data, 'display': display}


def messages(ident, data, result, source=SOURCE):
    fields = ['field_' + key for key in UNIT_FIELDS]
    nodes = [{'id': 'root', 'component': 'Column', 'children': ['fields', 'output']},
             {'id': 'fields', 'component': 'Column', 'children': fields + ['calculate']},
             {'id': 'output', 'component': 'Column', 'children': ['status', 'contribution', 'contribution_rate', 'total_cost', 'source']}]
    for key in UNIT_FIELDS:
        node = {'id': 'field_' + key, 'component': 'CurrencyField' if key == 'currency' else 'NumberField', 'label': LABELS[key], 'value': {'@path': '/input/' + key}}
        if key != 'currency':
            node.update(minimum=.01 if key == 'price' else 0, maximum=1 if key in RATES else 10**12, unit='fraction' if key in RATES else 'amount')
        nodes.append(node)
    nodes.append({'id': 'calculate', 'component': 'Button', 'label': '计算单件贡献', 'action': {'event': {'name': ACTION, 'context': {}}}})
    for key in ('status', 'contribution', 'contribution_rate', 'total_cost', 'source'):
        nodes.append({'id': key, 'component': 'Text', 'text': {'@path': '/display/' + key}, 'variant': 'caption' if key == 'source' else 'body'})
    payload = [{'version': '1.0', 'createSurface': {'surfaceId': ident, 'catalogId': CATALOG_ID, 'components': nodes, 'dataModel': data_model(data, result, source)}}]
    validate_surface(payload)
    return payload


class CostSurfaces:
    def __init__(self, core, calculator, workspace=None):
        self.core, self.calculator, self.workspace = core, calculator, workspace
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS a2ui_settings (id TEXT PRIMARY KEY, enabled INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS a2ui_cost_surfaces (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, revision INTEGER NOT NULL, input TEXT NOT NULL, result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS a2ui_requests (request_key TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT NOT NULL)')
            # Only identity and rendering confirmation live here. Product cost
            # input, revisions and economics artifacts remain in ProductWorkspace.
            db.execute('CREATE TABLE IF NOT EXISTS a2ui_product_bindings (surface_id TEXT PRIMARY KEY, case_id TEXT UNIQUE NOT NULL, calculated_revision INTEGER, calculated_source TEXT)')

    @staticmethod
    def request_key(value):
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 160):
            raise ValueError('invalid_idempotency_key')

    def replay(self, db, key, request):
        self.request_key(key)
        if key is None: return None
        row = db.execute('SELECT request,response FROM a2ui_requests WHERE request_key=?', (key,)).fetchone()
        if row:
            if row[0] != request: raise ValueError('idempotency_conflict')
            return json.loads(row[1])
        if db.execute('SELECT count(*) FROM a2ui_requests').fetchone()[0] >= 20000:
            raise ValueError('a2ui_capacity_reached')
        return None

    @staticmethod
    def record(db, key, request, response):
        if key is not None:
            db.execute('INSERT INTO a2ui_requests VALUES (?,?,?)', (key, request, json.dumps(response, ensure_ascii=False, allow_nan=False)))

    def listing(self):
        with self.core.db() as db:
            rows = db.execute('SELECT id,task_id,revision FROM a2ui_cost_surfaces ORDER BY rowid DESC LIMIT 100').fetchall()
        items = []
        for row in rows:
            try:
                item = self.get(row[0])
            except ValueError as exc:
                if str(exc) in ('case_not_found', 'organization_case_not_found', 'a2ui_workspace_unavailable'):
                    continue
                raise
            items.append({k: item[k] for k in ('surface_id', 'task_id', 'revision')} | ({'binding': item['binding']} if 'binding' in item else {}))
        return {'surfaces': items}

    def enabled(self):
        with self.core.db() as db:
            row = db.execute("SELECT enabled FROM a2ui_settings WHERE id='cost'").fetchone()
        return bool(row[0]) if row else True

    def set_enabled(self, enabled):
        if type(enabled) is not bool: raise ValueError('invalid_enabled')
        with self.core.db() as db:
            db.execute("INSERT OR REPLACE INTO a2ui_settings VALUES ('cost',?)", (int(enabled),))
        return {'enabled': enabled}

    def create(self, idempotency_key=None, *, case_id=None, expected_source_sha256=None):
        if not self.enabled(): raise ValueError('a2ui_disabled')
        if case_id is not None:
            return self._create_bound(case_id, expected_source_sha256, idempotency_key)
        if expected_source_sha256 is not None:
            raise ValueError('a2ui_binding_required')
        ident = 'cost_' + uuid.uuid4().hex
        messages(ident, {}, None)  # Validate dependencies before creating any task.
        with self.core.atomic() as db:
            previous = self.replay(db, idempotency_key, 'create')
            if previous: return self.get(previous['surface_id'])
            if db.execute('SELECT count(*) FROM a2ui_cost_surfaces').fetchone()[0] >= 512:
                raise ValueError('a2ui_capacity_reached')
            task = self.core.invoke('commerce_task_create', {'idempotency_key': ident, 'kind': 'analysis', 'input': {'title': 'A2UI 单件成本测算', 'surface_id': ident, 'data_source': 'caller_input'}})
            db.execute('INSERT INTO a2ui_cost_surfaces VALUES (?,?,0,?,NULL)', (ident, task['id'], '{}'))
            self.record(db, idempotency_key, 'create', {'surface_id': ident})
        return self.get(ident)

    def get(self, ident):
        if not isinstance(ident, str) or not re.fullmatch(r'cost_[0-9a-f]{32}', ident): raise ValueError('invalid_surface_id')
        with self.core.db() as db:
            row = db.execute('SELECT * FROM a2ui_cost_surfaces WHERE id=?', (ident,)).fetchone()
            binding = db.execute('SELECT case_id,calculated_revision,calculated_source FROM a2ui_product_bindings WHERE surface_id=?', (ident,)).fetchone()
        if row is None: raise ValueError('a2ui_surface_not_found')
        if binding:
            with self.core.atomic(reuse=True) as db:
                return self._bound_projection(db, ident)
        return self.present(row)

    @staticmethod
    def present(row):
        ident = row[0]
        data, result = json.loads(row[3]), json.loads(row[4]) if row[4] else None
        return CostSurfaces.projection(ident, row[1], row[2], data, result)

    @staticmethod
    def projection(ident, task_id, revision, data, result, source=SOURCE):
        model = data_model(data, result, source)
        return {'surface_id': ident, 'task_id': task_id, 'revision': revision, 'input': data, 'result': result, 'messages': messages(ident, data, result, source), 'updates': [{'version': '1.0', 'updateDataModel': {'surfaceId': ident, 'path': '/', 'value': model}}], 'text': '\n'.join(model['display'].values()), 'fallback': 'standard_cost_form'}

    def _workspace(self):
        if self.workspace is None:
            raise ValueError('a2ui_workspace_unavailable')
        return self.workspace

    @staticmethod
    def _binding_args(case_id, source):
        if not isinstance(case_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,160}', case_id) or not isinstance(source, str) or not re.fullmatch('[0-9a-f]{64}', source):
            raise ValueError('a2ui_binding_required')

    def _bound_projection(self, db, ident):
        binding = db.execute('SELECT case_id,calculated_revision,calculated_source FROM a2ui_product_bindings WHERE surface_id=?', (ident,)).fetchone()
        if binding is None:
            raise ValueError('a2ui_surface_not_found')
        current = self._workspace().get(binding[0])  # Includes active connection and exact case scope checks.
        cost = current['forms']['cost']
        artifact = current['artifacts']['economics']
        data = (cost['payload'] or {}).get('input', {}) if cost['payload'] is not None else (artifact or {}).get('payload', {})
        stale = bool(cost['stale'] or artifact and not artifact['intact'] or binding[2] is not None and binding[2] != current['source_sha256'])
        confirmed = binding[1] == cost['revision'] and binding[2] == current['source_sha256']
        result = current['calculation'] if confirmed and not stale else None
        tasks = [t['id'] for t in current['tasks']]
        value = self.projection(ident, tasks[0] if tasks else None, cost['revision'], data, result, BOUND_SOURCE)
        value.update(task_ids=tasks, task_created=False, binding={'case_id': binding[0], 'source_sha256': current['source_sha256'], 'cost_revision': cost['revision'], 'stale': stale, 'cost_source_sha256': cost['source_sha256'], 'economics_artifact_id': artifact['id'] if artifact else None})
        if stale:
            model = value['messages'][0]['createSurface']['dataModel']
            model['display']['status'] = '商品依据已变化，保留原参数供核对；重新读取并保存后再测算。'
            value['updates'][0]['updateDataModel']['value'] = model
            value['text'] = '\n'.join(model['display'].values())
        return value

    def _create_bound(self, case_id, source, key):
        self._binding_args(case_id, source)
        workspace = self._workspace()
        request = json.dumps(dict(operation='create_bound', case_id=case_id, source=source), sort_keys=True)
        with self.core.atomic(reuse=True) as db:
            previous = self.replay(db, key, request)
            if previous:
                return self.get(previous['surface_id'])
            workspace.guard(case_id, source)
            existing = db.execute('SELECT surface_id FROM a2ui_product_bindings WHERE case_id=?', (case_id,)).fetchone()
            if existing:
                ident = existing[0]
            else:
                if db.execute('SELECT count(*) FROM a2ui_cost_surfaces').fetchone()[0] >= 512:
                    raise ValueError('a2ui_capacity_reached')
                snapshot = workspace.get(case_id)
                cost, artifact = snapshot['forms']['cost'], snapshot['artifacts']['economics']
                data = (cost['payload'] or {}).get('input', {}) if cost['payload'] is not None else (artifact or {}).get('payload', {})
                messages('cost_' + '0' * 32, data, None)  # Fail before writes if optional schemas are unavailable.
                confirmed = bool(artifact and artifact['intact'] and not cost['stale'] and artifact['payload'] == data)
                ident = 'cost_' + uuid.uuid4().hex
                db.execute('INSERT INTO a2ui_cost_surfaces VALUES (?, ?, 0, ?, NULL)', (ident, '', '{}'))
                db.execute('INSERT INTO a2ui_product_bindings VALUES (?,?,?,?)', (ident, case_id, cost['revision'] if confirmed else None, source if confirmed else None))
            value = self._bound_projection(db, ident)
            self.record(db, key, request, {'surface_id': ident})
            return value

    def _update_bound(self, ident, revision, data, calculate, key, case_id, source):
        self._binding_args(case_id, source)
        request = json.dumps(dict(operation='bound_cost', surface_id=ident, case_id=case_id, source=source, revision=revision, input=data, calculate=calculate), sort_keys=True, allow_nan=False)
        with self.core.atomic(reuse=True) as db:
            binding = db.execute('SELECT case_id FROM a2ui_product_bindings WHERE surface_id=?', (ident,)).fetchone()
            if binding is None or binding[0] != case_id:
                raise ValueError('a2ui_case_mismatch')
            current = self._bound_projection(db, ident)  # Recheck scope even for a replayed receipt.
            previous = self.replay(db, key, request)
            if previous:
                # A replay is a receipt, never permission to overwrite newer work.
                if previous['binding']['source_sha256'] != current['binding']['source_sha256']:
                    raise ValueError('workspace_source_changed')
                if previous['revision'] != current['revision']:
                    raise ValueError('form_draft_conflict')
                return previous
            workspace = self._workspace()
            workspace.guard(case_id, source)
            saved = workspace.save(case_id, 'cost', {'input': data}, revision, source, _reuse=True)
            db.execute('UPDATE a2ui_product_bindings SET calculated_revision=NULL,calculated_source=NULL WHERE surface_id=?', (ident,))
            if calculate:
                workspace.calculate(case_id, saved['revision'], source, _reuse=True)
                latest = workspace.get(case_id)
                db.execute('UPDATE a2ui_product_bindings SET calculated_revision=?,calculated_source=? WHERE surface_id=?', (latest['forms']['cost']['revision'], latest['source_sha256'], ident))
            response = self._bound_projection(db, ident)
            self.record(db, key, request, response)
            return response

    def update(self, ident, revision, data, calculate=False, idempotency_key=None, *, case_id=None, expected_source_sha256=None):
        if not self.enabled(): raise ValueError('a2ui_disabled')
        if type(revision) is not int or revision < 0: raise ValueError('invalid_revision')
        validate_input(data)
        current = self.get(ident)
        if 'binding' in current:
            return self._update_bound(ident, revision, data, calculate, idempotency_key, case_id, expected_source_sha256)
        if case_id is not None or expected_source_sha256 is not None:
            raise ValueError('a2ui_case_mismatch')
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False)
        request = json.dumps(dict(surface_id=ident, revision=revision, input=data, calculate=calculate), sort_keys=True, allow_nan=False)
        with self.core.atomic() as db:
            previous = self.replay(db, idempotency_key, request)
            if previous: return previous
            result = self.calculator(data) if calculate else None
            changed = db.execute('UPDATE a2ui_cost_surfaces SET revision=revision+1,input=?,result=? WHERE id=? AND revision=?', (encoded, json.dumps(result, allow_nan=False) if result is not None else None, ident, revision)).rowcount
            if not changed: raise ValueError('a2ui_revision_conflict')
            row = db.execute('SELECT * FROM a2ui_cost_surfaces WHERE id=?', (ident,)).fetchone()
            response = self.present(row)
            self.record(db, idempotency_key, request, response)
            return response

    def action(self, event, revision, data, idempotency_key=None, *, case_id=None, expected_source_sha256=None):
        try:
            if len(json.dumps(event, allow_nan=False).encode()) > 4096:
                raise ValueError('a2ui_action_too_large')
            validators()['renderer_to_agent'].validate(event)
            action = event['action']
            if set(action) != {'name', 'surfaceId', 'sourceComponentId', 'timestamp', 'context'} or action['name'] != ACTION or action['sourceComponentId'] != 'calculate' or action['context'] != {}:
                raise ValueError('a2ui_action_forbidden')
            if datetime.fromisoformat(action['timestamp'].replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('a2ui_invalid_timestamp')
        except Exception:
            raise ValueError('a2ui_action_forbidden') from None
        return self.update(action['surfaceId'], revision, data, calculate=True, idempotency_key=idempotency_key, case_id=case_id, expected_source_sha256=expected_source_sha256)


def definitions(schema):
    string = {'type': 'string', 'maxLength': 100}
    revision = {'type': 'string', 'pattern': '^[0-9]{1,10}$', 'maxLength': 10}
    optional_key = {'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 160}}
    binding = {'case_id': {'type': 'string', 'minLength': 1, 'maxLength': 160}, 'expected_source_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$', 'maxLength': 64}}
    return [
        ('commerce_a2ui_status', '读取成本 Surface 开关与协议；宿主不支持时使用标准成本表单', schema()),
        ('commerce_a2ui_set_enabled', '启用或关闭成本 Surface；不修改店铺或计算接口', schema({'enabled': {'type': 'boolean'}}, ['enabled'])),
        ('commerce_a2ui_catalog', '读取受控 Commerce A2UI 1.0 Catalog', schema()),
        ('commerce_a2ui_create', '创建通用成本或按明确商品来源绑定原成本草稿；同键/同商品沿用，不自动派发商品任务', schema({**optional_key, **binding})),
        ('commerce_a2ui_list', '读取本机已保存成本 Surface 的稳定引用，不新建记录或任务', schema()),
        ('commerce_a2ui_get', '读取共享成本 Surface、真实计算结果与文本回退', schema({'surface_id': string}, ['surface_id'])),
        ('commerce_a2ui_update', '以原成本修订和商品来源校验保存参数并清除旧结果；绑定时须同时传case_id和expected_source_sha256', schema({'surface_id': string, 'revision': revision, 'input': {'type': 'object'}, **optional_key, **binding}, ['surface_id', 'revision', 'input'])),
        ('commerce_a2ui_action', '校验A2UI用户事件；绑定商品复用原保存/计算交接，须传case_id和expected_source_sha256', schema({'event': {'type': 'object'}, 'revision': revision, 'input': {'type': 'object'}, **optional_key, **binding}, ['event', 'revision', 'input'])),
    ]


def dispatch(surfaces, name, args):
    if name == 'commerce_a2ui_status': return {'enabled': surfaces.enabled(), 'protocol': '1.0', 'catalog_id': CATALOG_ID, 'fallback': 'standard_cost_form', 'host_native_rendering': 'not_assumed'}
    if name == 'commerce_a2ui_set_enabled': return surfaces.set_enabled(args['enabled'])
    if name == 'commerce_a2ui_catalog': return CATALOG
    binding = {k: args[k] for k in ('case_id', 'expected_source_sha256') if k in args}
    if name == 'commerce_a2ui_create': return surfaces.create(args.get('idempotency_key'), **binding)
    if name == 'commerce_a2ui_list': return surfaces.listing()
    if name == 'commerce_a2ui_get': return surfaces.get(args['surface_id'])
    revision = args.get('revision')
    if not isinstance(revision, str) or not re.fullmatch('[0-9]{1,10}', revision): raise ValueError('invalid_revision')
    if name == 'commerce_a2ui_update': return surfaces.update(args['surface_id'], int(revision), args['input'], idempotency_key=args.get('idempotency_key'), **binding)
    if name == 'commerce_a2ui_action': return surfaces.action(args['event'], int(revision), args['input'], idempotency_key=args.get('idempotency_key'), **binding)
    raise ValueError('unknown_tool')
