"""Scope-bound local work; source records and original tasks remain immutable."""
import hashlib
import json
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def definitions(schema, string, filters):
    return [
        ('commerce_workflow_task_create', '从明确订单或商品保存带来源版本的本地待办；不执行店铺操作', schema({**filters, 'entity_kind': {'type': 'string', 'enum': ['order', 'product']}, 'entity_id': string, 'expected_source_sha256': string, 'idempotency_key': string}, ['entity_kind', 'entity_id', 'idempotency_key'])),
        ('commerce_task_continue', '保留原任务，为补齐的明确本地操作创建关联后续任务；不自动执行', schema({'task_id': string, 'operation': {'type': 'string', 'enum': ['report', 'unit_economics', 'restock_plan']}, 'input': {'type': 'object'}, 'idempotency_key': string}, ['task_id', 'operation', 'input', 'idempotency_key'])),
    ]


class WorkflowContinuity:
    def __init__(self, service):
        self.service = service
        self.core = service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS report_scopes(report_id TEXT PRIMARY KEY,request TEXT NOT NULL,scope TEXT NOT NULL)')

    def report(self, args):
        scope = {k: args.get(k, default) for k, default in [('demo', False), ('platform', 'all'), ('store_id', 'all'), ('market', 'all'), ('period', '30')]}
        request = canonical(scope)
        key = args['idempotency_key']
        if not key.strip():
            raise ValueError('invalid_idempotency_key')
        mode = 'demo' if scope['demo'] else 'live'
        with self.core.db() as db:
            old = db.execute('SELECT id,mode,content,created_at FROM reports WHERE idem=?', (key,)).fetchone()
            if old:
                saved = db.execute('SELECT request,scope FROM report_scopes WHERE report_id=?', (old[0],)).fetchone()
                if old[1] != mode or (saved and saved[0] != request) or (not saved and any(scope[k] != 'all' for k in ('platform', 'store_id', 'market'))):
                    raise ValueError('idempotency_conflict')
                return self.present(old, json.loads(saved[1]) if saved else None)
        filters = {k: scope[k] for k in ('demo', 'platform', 'store_id', 'market')}
        if scope['demo']:
            data = self.service.invoke('commerce_dashboard', filters)
            body = '模拟数据，仅供界面验证。\n\n当前范围示例销售额合计 USD {:,}；待处理订单 {}，库存预警 {}。'.format(data['sales'], data['pending'], data['stock_alerts'])
            evidence = {'source': 'synthetic', 'snapshot_sha256': digest({k: v for k, v in data.items() if k != 'updated_at'})}
        else:
            live = self.service.live.status()
            # Only the existing Ozon/RU snapshot can be summarized by this adapter.
            compatible = scope['platform'] in ('all', 'ozon') and scope['store_id'] in ('all', 'ozon-live') and scope['market'] in ('all', 'RU')
            if compatible and (live['orders']['available'] or live['stock']['available']):
                body = '真实模式 · Ozon 只读快照。\n\n'
                for field, label in [('orders', '履约记录'), ('stock', '库存来源记录')]:
                    snapshot = live[field]
                    body += label + '：' + (str(snapshot['count']) + ' 条；采集于 ' + str(snapshot['observed_at']) + '；' + ('新鲜' if snapshot['fresh'] else '已陈旧') if snapshot['available'] else '尚无可用快照') + '。\n'
                body += '\n订单范围：' + ('已人工核对' if live.get('orders_scope_confirmed') else '待人工核对') + '。\n\n销售额、利润和补货数量保持未知；记录条数不等于销售件数或库存总件数。'
                evidence = {k: {f: v for f, v in live[k].items() if f in ('available', 'fresh', 'count', 'observed_at', 'source_sha256')} for k in ('orders', 'stock')}
            else:
                body = '真实模式，当前范围尚无可用店铺快照，暂无可核对经营数据。\n\n请先完成平台授权、同步与数据核验。'
                evidence = {'source': 'not_available_for_selected_scope'}
            body += '\n当前快照不提供期间销售汇总，不能从近30天筛选推算销售额。'
        saved_scope = {**scope, 'evidence': evidence}
        content = '# 运营简报草稿\n\n数据模式：' + body + '\n\n报告范围：平台 ' + scope['platform'] + ' / 店铺 ' + scope['store_id'] + ' / 市场 ' + scope['market'] + '。\n\n本简报由本地模板生成，未调用 LLM，未执行平台操作。\n'
        ident = hashlib.sha256(key.encode()).hexdigest()[:20]
        stamp = datetime.now(timezone.utc).isoformat()
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT id,mode,content,created_at FROM reports WHERE idem=?', (key,)).fetchone()
            if old:
                saved = db.execute('SELECT request,scope FROM report_scopes WHERE report_id=?', (old[0],)).fetchone()
                if old[1] != mode or not saved or saved[0] != request:
                    raise ValueError('idempotency_conflict')
                return self.present(old, json.loads(saved[1]))
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?)', (ident, key, mode, content, stamp))
            db.execute('INSERT INTO report_scopes VALUES (?,?,?)', (ident, request, canonical(saved_scope)))
        return self.present((ident, mode, content, stamp), saved_scope)

    @staticmethod
    def present(row, scope):
        return {'id': row[0], 'mode': row[1], 'content': row[2], 'created_at': row[3], 'status': 'draft', 'generator': 'local_template', 'scope': scope, 'scope_status': 'recorded' if scope else 'historical_global_scope_not_recorded'}

    def source_task(self, args):
        filters = {k: args.get(k, default) for k, default in [('demo', False), ('platform', 'all'), ('store_id', 'all'), ('market', 'all')]}
        kind = args['entity_kind']
        response = self.service.invoke('commerce_orders_list' if kind == 'order' else 'commerce_products_list', filters)
        rows = response['orders' if kind == 'order' else 'products']
        selected = [r for r in rows if r.get('id' if kind == 'order' else 'sku') == args['entity_id']]
        if len(selected) != 1:
            raise ValueError('workflow_source_unavailable_or_ambiguous')
        record = selected[0]
        fingerprint = record.get('source_sha256') or digest(record)
        if args.get('expected_source_sha256') and fingerprint != args['expected_source_sha256']:
            raise ValueError('workflow_source_changed')
        scope = {**filters, 'platform': record.get('platform', filters['platform']), 'store_id': record.get('store_id', filters['store_id']), 'market': record.get('market', filters['market']), 'entity_kind': kind, 'entity_id': args['entity_id'], 'record_sha256': fingerprint}
        if record.get('stale'):
            raise ValueError('workflow_source_changed_or_stale')
        data = {'title': ('订单处理草稿 · ' if kind == 'order' else '补货分析 · ') + args['entity_id'], 'demo': filters['demo'], 'source_context': scope, 'source_record': record}
        return self.service.invoke('commerce_task_create', {'kind': 'draft' if kind == 'order' else 'analysis', 'input': data, 'idempotency_key': args['idempotency_key']})

    def continue_task(self, args):
        previous = self.core.invoke('commerce_task_get', {'task_id': args['task_id']})
        op = args['operation']
        source = previous['input']
        extra = args['input']
        if set(extra) - {'parameters', 'demo'} or ('demo' in extra and type(extra['demo']) is not bool):
            raise ValueError('workflow_invalid_followup_input')
        demo = extra.get('demo', source.get('demo', False))
        data = {'title': '接续 · ' + source.get('title', previous['kind'])[:100], 'predecessor_task_id': previous['id'], 'demo': demo}
        if source.get('source_context'):
            if demo != source['source_context']['demo']:
                raise ValueError('workflow_followup_scope_changed')
            data['source_context'] = source['source_context']
        if op != 'report':
            if not isinstance(extra.get('parameters'), dict):
                raise ValueError('calculation_parameters_required')
            data.update(local_operation=op, parameters=extra['parameters'])
        task = {'kind': 'report' if op == 'report' else 'analysis', 'input': data}
        self.service.autonomy.validate_operation(task, op)
        return self.service.invoke('commerce_task_create', {**task, 'idempotency_key': args['idempotency_key']})
