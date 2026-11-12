"""Durable local alerts from explicit, evidenced observations. No shop writes or messaging."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_CEILING
import json
import re
import threading
from operations_analysis import number, restock_plan, STOCK_FIELDS
from research import canonical, digest

VERSION = 'ops-alerts-v1'
DEFAULT_RULES = {'max_age_minutes': 60, 'dispatch_warning_hours': 24, 'overstock_days': 90}
PENDING = ('paid', 'awaiting_packaging', 'awaiting_dispatch')


def utc(): return datetime.now(timezone.utc)
def iso(value): return value.astimezone(timezone.utc).isoformat()


def date(value):
    if not isinstance(value, str): raise ValueError('invalid_observation_time')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result.astimezone(timezone.utc)
    except ValueError: raise ValueError('invalid_observation_time') from None


def text(value, name, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum: raise ValueError('invalid_' + name)
    return value


def validate(record, current=None):
    current = current or utc()
    common = {'event_id', 'platform', 'store_id', 'market', 'fulfillment', 'warehouse', 'observed_at', 'source_ref', 'kind', 'data'}
    if not isinstance(record, dict) or set(record) != common or len(canonical(record).encode()) > 20000: raise ValueError('invalid_observation')
    for key in ('event_id', 'store_id', 'market', 'warehouse', 'source_ref'): text(record[key], key, 2000 if key == 'source_ref' else 160)
    if record['platform'] not in ('ozon', 'tiktok', 'amazon', 'mercado', 'temu'): raise ValueError('invalid_platform')
    if record['fulfillment'] not in ('unknown', 'FBO', 'FBS', 'realFBS', 'other'): raise ValueError('invalid_fulfillment')
    if date(record['observed_at']) > current + timedelta(minutes=2): raise ValueError('observation_in_future')
    data = record['data']
    if not isinstance(data, dict): raise ValueError('invalid_observation_data')
    text(data.get('sku'), 'sku')
    if record['kind'] == 'order':
        if set(data) != {'order_id', 'sku', 'quantity', 'status', 'ship_by'}: raise ValueError('invalid_order_fields')
        text(data['order_id'], 'order_id'); number(data['quantity'], 'quantity', minimum=1, integer=True)
        if data['status'] not in (*PENDING, 'shipped', 'cancelled', 'completed'): raise ValueError('invalid_order_status')
        if data['ship_by'] is not None: date(data['ship_by'])
    elif record['kind'] == 'stock':
        if set(data) != {'sku', *STOCK_FIELDS, 'inbound_units', 'inbound_due_at'}: raise ValueError('invalid_stock_fields')
        for key in STOCK_FIELDS:
            value = data[key]
            if value is not None:
                low = 1 if key in ('window_days', 'pack_size') else 0
                high = 365 if key.endswith('_days') else 10**9 if key == 'pack_size' else 10**12
                number(value, key, minimum=low, maximum=high, integer=True)
        if data['inbound_units'] is not None: number(data['inbound_units'], 'inbound_units', integer=True)
        if data['inbound_due_at'] is not None: date(data['inbound_due_at'])
    else: raise ValueError('invalid_observation_kind')
    return record


def stock_plan(data, observed, current=None):
    current = current or observed
    base = restock_plan({key: data[key] for key in STOCK_FIELDS})
    result = {**base, 'current_cover': base['days_of_cover'], 'eligible_inbound': 0, 'inbound_note': ''}
    if data['inbound_units'] is None or data['inbound_units'] > 0 and data['inbound_due_at'] is None:
        result.update(status='HOLD', suggested_qty=None, reason='inbound_unknown'); return result
    if base['status'] != 'CALCULATED': return result
    velocity = Decimal(str(data['sold_units'])) / Decimal(str(data['window_days']))
    cover = Decimal(str(data['available'])) / velocity
    lead = Decimal(str(data['lead_time_days'])); safety = Decimal(str(data['safety_days']))
    inbound = data['inbound_units']
    if inbound:
        due = date(data['inbound_due_at'])
        cutoff = observed + timedelta(days=float(min(cover, lead + safety)))
        if current < due <= cutoff:
            result['eligible_inbound'] = inbound
            result['inbound_note'] = '仅按预计在断货前且规划期内到达的在途扣减，需核对实际到货'
        else:
            result['inbound_note'] = '在途逾期、晚于预计断货或超出规划期，本次未扣减，请复核'
    effective = (Decimal(str(data['available'])) + result['eligible_inbound']) / velocity
    target = velocity * (lead + safety)
    quantity = max(Decimal(0), target - Decimal(str(data['available'])) - result['eligible_inbound'])
    pack = Decimal(str(data['pack_size']))
    result.update(days_of_cover=float(effective.quantize(Decimal('.01'))),
                  suggested_qty=int((quantity / pack).to_integral_value(rounding=ROUND_CEILING) * pack),
                  urgency='P0' if effective <= lead else 'P1' if effective <= lead + safety else 'P2')
    return result


def derive(record, rules, current):
    observed = date(record['observed_at']); data = record['data']; alerts = []
    def add(kind, title, severity, detail): alerts.append(dict(kind=kind, title=title, severity=severity, detail=detail))
    if record['kind'] == 'order' and data['status'] not in PENDING: return alerts, None
    if current - observed > timedelta(minutes=rules['max_age_minutes']):
        add('data_stale', '数据已陈旧，需重新同步或导入', 'P1', '暂停依据该记录判断当前库存和履约状态；原提醒保留为挂起。')
        return alerts, None
    if record['kind'] == 'order':
        if data['status'] in PENDING:
            add('order_observed', '新增待处理订单记录', 'P2', '本地首次观察到的待处理订单，不代表刚刚成交；以来源订单时间和状态为准。')
            if record['fulfillment'] == 'unknown':
                add('fulfillment_unknown', '履约方式待确认', 'P1', '暂不判断由商家还是平台负责备货发货。')
            elif record['fulfillment'] == 'FBO' and record['platform'] == 'ozon':
                pass  # Do not tell a seller to pack an Ozon-fulfilled order.
            else:
                add('prepare' if data['status'] != 'awaiting_dispatch' else 'dispatch', '待备货' if data['status'] != 'awaiting_dispatch' else '待发货', 'P1', '根据导入的订单状态生成，请核对平台当前记录。')
                if data['ship_by'] is None: add('deadline_unknown', '发货截止时间缺失', 'P1', '不推断平台的履约时限，请从订单原文补充带时区的截止时间。')
                elif date(data['ship_by']) <= current + timedelta(hours=rules['dispatch_warning_hours']):
                    overdue = date(data['ship_by']) <= current
                    add('dispatch_deadline', '已超过记录的发货截止时间' if overdue else '临近发货截止时间', 'P0' if overdue else 'P1', '截止时间：' + data['ship_by'])
        return alerts, None
    plan = stock_plan(data, observed, current)
    if data['available'] == 0: add('out_of_stock', '可售库存为零', 'P0', '仅代表该店铺、仓库、SKU 的本次记录；建议核对可售状态及推广。')
    if plan['status'] != 'CALCULATED':
        add('stock_input_missing', '补货测算待补数据', 'P1', '缺销量窗口、交期、在途信息或没有观测到需求，补货量保持未知。')
    elif plan['urgency'] in ('P0', 'P1'):
        add('restock', '库存覆盖不足，建议核对补货', plan['urgency'], f"记录时库存覆盖 {plan['current_cover']} 天；计入符合时间条件的在途后 {plan['days_of_cover']} 天；整箱测算 {plan['suggested_qty']} 件。")
    elif plan['days_of_cover'] >= rules['overstock_days']:
        add('overstock', '库存覆盖较长，建议复核积压', 'P2', '可比较定向推广、组合销售和优惠方案；先确认季节性与未来需求。')
    if plan['inbound_note'] and not plan['eligible_inbound']: add('inbound_review', '在途到货时间需要复核', 'P1', plan['inbound_note'])
    return alerts, plan


class OperationsAlerts:
    def __init__(self, core):
        self.core = core
        self._timer = None; self.last_tick = None; self.timer_error = None
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS ops_events (scope TEXT,event_id TEXT,payload TEXT,hash TEXT,entity TEXT,observed TEXT,created TEXT,PRIMARY KEY(scope,event_id))')
            db.execute('CREATE TABLE IF NOT EXISTS ops_latest (scope TEXT,entity TEXT,event_id TEXT,observed TEXT,PRIMARY KEY(scope,entity))')
            db.execute('CREATE TABLE IF NOT EXISTS ops_alerts (id TEXT PRIMARY KEY,scope TEXT,entity TEXT,kind TEXT,status TEXT,payload TEXT,created TEXT,updated TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS ops_audit (id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT,alert_id TEXT,action TEXT,at TEXT,evidence_hash TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS ops_rules (scope TEXT PRIMARY KEY,payload TEXT)')

    def start_timer(self):
        if self._timer and self._timer.is_alive(): return
        def run():
            while True:
                threading.Event().wait(60)
                try:
                    self.list(False); self.list(True); self.last_tick = iso(utc()); self.timer_error = None
                except Exception: self.timer_error = 'local_alert_evaluation_failed'
        self._timer = threading.Thread(target=run, name='commerce-local-alert-clock', daemon=True); self._timer.start()

    @staticmethod
    def scope(demo):
        if type(demo) is not bool: raise ValueError('invalid_demo')
        return 'demo' if demo else 'manual_import'

    def rules(self, demo=False, rules=None):
        scope = self.scope(demo)
        if rules is not None:
            if not isinstance(rules, dict) or set(rules) != set(DEFAULT_RULES): raise ValueError('invalid_alert_rules')
            for key, value in rules.items(): number(value, key, minimum=1, maximum=10080 if key == 'max_age_minutes' else 365, integer=True)
            with self.core.db() as db: db.execute('INSERT OR REPLACE INTO ops_rules VALUES (?,?)', (scope, canonical(rules)))
        with self.core.db() as db: row = db.execute('SELECT payload FROM ops_rules WHERE scope=?', (scope,)).fetchone()
        return json.loads(row[0]) if row else dict(DEFAULT_RULES)

    def record(self, record, demo=False, current=None):
        current = current or utc(); validate(record, current); scope = self.scope(demo)
        data = record['data']; entity = digest(canonical([record[k] for k in ('platform', 'store_id', 'market', 'warehouse', 'kind')] + [data.get('order_id'), data['sku']]))
        payload = canonical(record); sha = digest(payload); observed = iso(date(record['observed_at']))
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT hash FROM ops_events WHERE scope=? AND event_id=?', (scope, record['event_id'])).fetchone()
            if old:
                if old[0] != sha: raise ValueError('observation_id_conflict')
                return dict(status='duplicate', event_id=record['event_id'], sha256=sha)
            latest = db.execute('SELECT observed FROM ops_latest WHERE scope=? AND entity=?', (scope, entity)).fetchone()
            if latest and latest[0] == observed: raise ValueError('observation_time_conflict_use_new_timestamp')
            db.execute('INSERT INTO ops_events VALUES (?,?,?,?,?,?,?)', (scope, record['event_id'], payload, sha, entity, observed, iso(current)))
            ignored = bool(latest and latest[0] > observed)
            if not ignored: db.execute('INSERT OR REPLACE INTO ops_latest VALUES (?,?,?,?)', (scope, entity, record['event_id'], observed))
        self.list(demo, current)
        return dict(status='stored_history_only' if ignored else 'recorded', event_id=record['event_id'], sha256=sha, source='synthetic' if demo else 'manual_import_unverified')

    def list(self, demo=False, current=None):
        current = current or utc(); scope = self.scope(demo); rules = self.rules(demo); plans = []
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT e.payload,e.hash,e.entity FROM ops_latest l JOIN ops_events e ON e.scope=l.scope AND e.event_id=l.event_id WHERE l.scope=?', (scope,)).fetchall()
            for payload, sha, entity in rows:
                record = json.loads(payload); expected, plan = derive(record, rules, current)
                if plan is not None: plans.append(dict(platform=record['platform'], store_id=record['store_id'], warehouse=record['warehouse'], sku=record['data']['sku'], plan=plan, source_sha256=sha, observed_at=record['observed_at']))
                kinds = set()
                for item in expected:
                    ident = digest(scope + entity + item['kind'])[:24]; kinds.add(item['kind'])
                    body = dict(**item, platform=record['platform'], store_id=record['store_id'], market=record['market'], warehouse=record['warehouse'], sku=record['data']['sku'], order_id=record['data'].get('order_id'), observed_at=record['observed_at'], source_ref=record['source_ref'], source_sha256=sha, source='synthetic' if demo else 'manual_import_unverified', rules=rules, delivery='workbench_only')
                    frozen = canonical(body)
                    old = db.execute('SELECT status,payload FROM ops_alerts WHERE id=?', (ident,)).fetchone()
                    status = old[0] if old and old[0] in ('active', 'acknowledged') and json.loads(old[1])['severity'] == item['severity'] else 'active'
                    if not old:
                        db.execute('INSERT INTO ops_alerts VALUES (?,?,?,?,?,?,?,?)', (ident, scope, entity, item['kind'], status, frozen, iso(current), iso(current)))
                        db.execute('INSERT INTO ops_audit(scope,alert_id,action,at,evidence_hash) VALUES (?,?,?,?,?)', (scope, ident, 'created', iso(current), sha))
                    elif old != (status, frozen):
                        db.execute('UPDATE ops_alerts SET status=?,payload=?,updated=? WHERE id=?', (status, frozen, iso(current), ident))
                        db.execute('INSERT INTO ops_audit(scope,alert_id,action,at,evidence_hash) VALUES (?,?,?,?,?)', (scope, ident, 'updated', iso(current), sha))
                stale = any(x['kind'] == 'data_stale' for x in expected)
                for ident, kind, status in db.execute('SELECT id,kind,status FROM ops_alerts WHERE scope=? AND entity=?', (scope, entity)).fetchall():
                    if kind in kinds: continue
                    next_status = 'suspended' if stale else 'resolved'
                    if status != next_status:
                        db.execute('UPDATE ops_alerts SET status=?,updated=? WHERE id=?', (next_status, iso(current), ident))
                        db.execute('INSERT INTO ops_audit(scope,alert_id,action,at,evidence_hash) VALUES (?,?,?,?,?)', (scope, ident, next_status, iso(current), sha))
            alerts = [dict(json.loads(row[2]), id=row[0], status=row[1], updated_at=row[3]) for row in db.execute('SELECT id,status,payload,updated FROM ops_alerts WHERE scope=? ORDER BY updated DESC LIMIT 200', (scope,))]
        alerts.sort(key=lambda x: (x['status'] != 'active', x['severity'], x['store_id']))
        return dict(alerts=alerts, stock_plans=plans, rules=rules, mode=scope, observation_count=len(rows), generated_at=iso(current),
                    connection=dict(platform='ozon', market='RU', fulfillment='not_selected', live_sync='not_connected', notification='not_configured', server_timer='running' if self._timer and self._timer.is_alive() else 'not_started', last_tick=self.last_tick, timer_error=self.timer_error),
                    notice='导入记录生成的本地提醒；已阅不等于已处理；没有向手机或店铺发送操作。')

    def acknowledge(self, ident, demo=False):
        scope = self.scope(demo)
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE'); row = db.execute('SELECT status,payload FROM ops_alerts WHERE id=? AND scope=?', (ident, scope)).fetchone()
            if not row: raise ValueError('alert_not_found')
            if row[0] == 'active':
                db.execute("UPDATE ops_alerts SET status='acknowledged',updated=? WHERE id=?", (iso(utc()), ident))
                db.execute('INSERT INTO ops_audit(scope,alert_id,action,at,evidence_hash) VALUES (?,?,?,?,?)', (scope, ident, 'acknowledged', iso(utc()), json.loads(row[1])['source_sha256']))
        return {'id': ident, 'status': 'acknowledged' if row[0] == 'active' else row[0]}

    def export(self, demo=False):
        state = self.list(demo); scope = self.scope(demo)
        with self.core.db() as db:
            events = [dict(record=json.loads(r[0]), sha256=r[1]) for r in db.execute('SELECT payload,hash FROM ops_events WHERE scope=? ORDER BY created', (scope,))]
            audit = [dict(alert_id=r[0], action=r[1], at=r[2], evidence_hash=r[3]) for r in db.execute('SELECT alert_id,action,at,evidence_hash FROM ops_audit WHERE scope=? ORDER BY id', (scope,))]
        payload = dict(version=VERSION, state=state, observations=events, audit=audit, provenance='caller_supplied_not_independently_verified')
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return dict(content=content, sha256=digest(content), filename='commerce-alerts-' + scope + '.json')
