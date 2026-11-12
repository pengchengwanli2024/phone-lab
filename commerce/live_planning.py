"""Evidence-bound local restock drafts and connection diagnostics. No outbound I/O."""
from datetime import datetime, timezone
import json
import re
import uuid
from operations_analysis import number, STOCK_FIELDS
from ops_alerts import stock_plan, date
from research import canonical, digest

FIELDS=('sold_units','window_days','lead_time_days','safety_days','pack_size','inbound_units','inbound_due_at','source_ref','demand_observed_at')
REASONS={
    'stock_missing':'尚未取得库存快照', 'stock_stale':'库存快照已过期，请先同步',
    'stock_basis_unconfirmed':'可售库存口径尚未核对', 'orders_scope_unconfirmed':'OGL 订单范围尚未核对',
    'source_changed':'库存快照已更新，请按新快照重新保存测算', 'basis_changed':'库存口径已改变，请重新测算',
    'row_missing':'该商品或履约范围已不在最新库存中', 'available_unknown':'可售数量未知或平台字段异常',
    'demand_evidence_missing':'请提供销量窗口的来源与实际核对时间', 'demand_evidence_stale':'销量资料超过 24 小时，请重新核对',
    'inbound_delivery_needs_review':'在途预计到达时间已过，请核对实际到货',
    'inbound_unknown':'请明确在途数量；有在途时填写预计到达时间', 'no_demand_observed':'观察窗口内销量为零，暂不推断补货量',
}
SYNC_ERRORS={'ozon_network_error':'连接失败，请检查本机网络与代理后重试','ozon_auth_or_permission':'身份验证或读取权限不足，请核对只读凭据','ozon_rate_limited':'平台限流，请稍后再试','ozon_http_error':'平台接口返回错误，请检查同步记录','unexpected_orders_schema':'订单返回结构变化，需核对解析范围','unexpected_stock_schema':'库存返回结构变化，需核对解析范围'}


class LivePlanning:
    def __init__(self, live):
        self.live=live;self.core=live.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS live_restock(id TEXT PRIMARY KEY,connection TEXT,idem TEXT,input_sha TEXT,payload TEXT,created TEXT,UNIQUE(connection,idem))')

    @staticmethod
    def clock():return datetime.now(timezone.utc)

    def readiness(self):
        status=self.live.status();credentials=status['credentials_present'];checks=[]
        def add(key,label,ok,detail,action):checks.append(dict(key=key,label=label,status='ready' if ok else 'needs_action',detail=detail,action=None if ok else action))
        add('credentials','Ozon 只读凭据',status['configured'],'已在本机保存' if status['configured'] else '先在私有向导保存凭据','setup')
        for kind,label in [('orders','订单快照'),('stock','库存快照')]:
            s=status[kind];latest=((status['last_job'] or {}).get('result') or {}).get(kind,{})
            detail='有效期内' if s['fresh'] else '已有快照已过期，旧记录保留作证据' if s['available'] else '尚未取得完整快照'
            if latest.get('status')=='failed':detail+='；最近同步：'+SYNC_ERRORS.get(latest.get('code'),'读取未完成，旧快照未覆盖')
            add(kind,label,s['fresh'] and latest.get('status')!='failed',detail,'sync')
        add('order_scope','OGL 订单范围核对',status['orders_scope_confirmed'],'核对相同时间窗口、发货单号、SKU 和数量','setup')
        add('stock_basis','可售库存口径',status['stock_basis']!='unconfirmed','核对 present、reserved 与后台可售数量','setup')
        add('sync','自动同步',status['sync_enabled'],'开启后才会按设定间隔读取','setup')
        add('feishu','飞书目标群',credentials['feishu_webhook'] and bool(status['feishu_target_label']),'请在私有向导填写指定群机器人','setup')
        add('test','飞书接口测试',status['feishu_test_verified'],'接口接收回执与手机弹通知分别核对','setup')
        add('receipt','目标群收件确认',status['feishu_received_confirmed'],'到实际目标群核对测试消息','setup')
        add('notifications','飞书提醒开关',status['notifications_enabled'],'只有开启后新事件才会入通知队列','setup')
        deliveries=[];connection=self.live.config().get('connection_id','')
        with self.core.db() as db:
            for row in db.execute('SELECT id,status,created,updated,receipt FROM live_outbox WHERE connection=? ORDER BY created DESC LIMIT 30',(connection,)):
                receipt=json.loads(row[4]) if row[4] else {}
                deliveries.append(dict(id=row[0],status=row[1],created_at=row[2],updated_at=row[3],code=receipt.get('code'),message_sha256=receipt.get('message_sha256'),source_snapshot_sha256=receipt.get('source_snapshot_sha256')))
        return dict(checks=checks,complete=sum(c['status']=='ready' for c in checks),total=len(checks),deliveries=deliveries,notice='发送结果不明先核对目标群，不自动重发。已发送表示接口回执确认，不保证手机已弹通知。')

    def candidates(self):
        config=self.live.config();snapshot=self.live.snapshot(config.get('connection_id',''),'stock')
        rows=self.live._stock_rows(snapshot['data'],config) if snapshot else []
        for row in rows:
            row['source_sha256']=snapshot['sha256'];row['fresh']=self.live._fresh(snapshot,config)
            if not row['fresh']:row['available']=None
        return rows

    def _guard(self, config, snapshot, row, data, current):
        reasons=[]
        if not snapshot:reasons.append('stock_missing')
        elif not self.live._fresh(snapshot,config):reasons.append('stock_stale')
        if not row:reasons.append('row_missing')
        elif row['available'] is None:reasons.append('available_unknown')
        if config['stock_basis']=='unconfirmed':reasons.append('stock_basis_unconfirmed')
        if not config['orders_scope_confirmed']:reasons.append('orders_scope_unconfirmed')
        if not data.get('source_ref') or not data.get('demand_observed_at'):reasons.append('demand_evidence_missing')
        elif (current-date(data['demand_observed_at'])).total_seconds()>86400:reasons.append('demand_evidence_stale')
        if data.get('inbound_units',0) and data.get('inbound_due_at') and date(data['inbound_due_at'])<=current:reasons.append('inbound_delivery_needs_review')
        return reasons

    def save(self, row_key, source_sha256, input, idempotency_key):
        if not isinstance(row_key,str) or not 1<=len(row_key)<=240 or not isinstance(source_sha256,str) or not re.fullmatch('[a-f0-9]{64}',source_sha256):raise ValueError('invalid_stock_reference')
        if not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=160:raise ValueError('invalid_idempotency_key')
        if not isinstance(input,dict) or set(input)-set(FIELDS):raise ValueError('invalid_restock_input')
        data={key:input.get(key) for key in FIELDS};current=self.clock()
        for key in FIELDS[:6]:
            if data[key] is not None:number(data[key],key,minimum=1 if key in ('window_days','pack_size') else 0,maximum=365 if key.endswith('_days') else 10**9 if key=='pack_size' else 10**12,integer=True)
        if data['source_ref'] is not None and (not isinstance(data['source_ref'],str) or len(data['source_ref'])>1000):raise ValueError('invalid_source_ref')
        if isinstance(data['source_ref'],str):data['source_ref']=data['source_ref'].strip()
        for key in ('inbound_due_at','demand_observed_at'):
            if data[key] is not None:date(data[key])
        if data['demand_observed_at'] and date(data['demand_observed_at'])>current:raise ValueError('future_demand_observation')
        config=self.live.config();connection=config.get('connection_id','')
        frozen=dict(row_key=row_key,source_sha256=source_sha256,input=data);sha=digest(canonical(frozen))
        with self.core.db() as db:
            old=db.execute('SELECT id,input_sha,payload FROM live_restock WHERE connection=? AND idem=?',(connection,idempotency_key)).fetchone()
        if old:
            if old[1]!=sha:raise ValueError('idempotency_conflict')
            return self.present(old[0],json.loads(old[2]))
        snapshot=self.live.snapshot(connection,'stock')
        if not snapshot or snapshot['sha256']!=source_sha256:raise ValueError('stock_source_changed_refresh_first')
        matches=[r for r in self.live._stock_rows(snapshot['data'],config) if r['key']==row_key]
        if len(matches)>1:raise ValueError('ambiguous_stock_row')
        row=matches[0] if matches else None
        if not row:raise ValueError('stock_row_not_found')
        values={key:data.get(key) for key in (*STOCK_FIELDS,'inbound_units','inbound_due_at')};values['available']=row['available']
        result=stock_plan(values,date(snapshot['observed_at']),current)
        result['assumptions']=['按明确提供的销量窗口外推，需求变化需重新评估。','仅扣减预计在断货前且规划期内到达的在途，实际到货仍需核对。','库存按所选履约范围汇总，草稿不执行采购或修改库存。']
        reasons=self._guard(config,snapshot,row,data,current)
        if reasons:result.update(status='HOLD',suggested_qty=None)
        payload=dict(input=data,demand_source_status='caller_provided_not_independently_verified',stock=row,stock_basis=config['stock_basis'],snapshot_sha256=snapshot['sha256'],snapshot_id=snapshot['id'],source_evidence=snapshot['data']['evidence'],result=result,reasons=reasons,created_at=current.isoformat(),scope='履约方式汇总，非单仓',review_required=True,marketplace_writes=False)
        ident=str(uuid.uuid4())
        with self.core.db() as db:
            db.execute('INSERT OR IGNORE INTO live_restock VALUES (?,?,?,?,?,?)',(ident,connection,idempotency_key,sha,canonical(payload),payload['created_at']))
            saved=db.execute('SELECT id,input_sha,payload FROM live_restock WHERE connection=? AND idem=?',(connection,idempotency_key)).fetchone()
        if saved[1]!=sha:raise ValueError('idempotency_conflict')
        return self.present(saved[0],json.loads(saved[2]))

    def present(self, ident, payload):
        config=self.live.config();snapshot=self.live.snapshot(config.get('connection_id',''),'stock');current=self.clock()
        row=next((r for r in self.candidates() if r['key']==payload['stock']['key']),None)
        reasons=self._guard(config,snapshot,row,payload['input'],current)
        if snapshot and snapshot['sha256']!=payload['snapshot_sha256']:reasons.append('source_changed')
        if config['stock_basis']!=payload['stock_basis']:reasons.append('basis_changed')
        reasons=list(dict.fromkeys(payload['reasons']+reasons))
        result=dict(payload['result'])
        if reasons:result.update(status='HOLD',suggested_qty=None)
        return dict(id=ident,**payload,current_result=result,current_reasons=reasons,reason_zh=[REASONS[r] for r in reasons],historical_result_notice='result 为保存时的历史测算，current_result 为当前可用性；均需人工复核。')

    def list(self):
        connection=self.live.config().get('connection_id','')
        with self.core.db() as db:rows=db.execute('SELECT id,payload FROM live_restock WHERE connection=? ORDER BY created DESC LIMIT 30',(connection,)).fetchall()
        return dict(candidates=self.candidates(),plans=[self.present(r[0],json.loads(r[1])) for r in rows],field_zh={'sold_units':'窗口销量','window_days':'销量观察天数','lead_time_days':'到货交期天数','safety_days':'安全库存天数','pack_size':'每箱件数','inbound_units':'已确认在途数量','inbound_due_at':'在途预计到达时间','source_ref':'销量来源','demand_observed_at':'销量资料实际核对时间'})

    def export(self, ident):
        connection=self.live.config().get('connection_id','')
        with self.core.db() as db:row=db.execute('SELECT payload FROM live_restock WHERE id=? AND connection=?',(ident,connection)).fetchone()
        if not row:raise ValueError('restock_plan_not_found')
        plan=self.present(ident,json.loads(row[0]));document=dict(schema='live-restock-evidence-v1',plan=plan,field_zh=self.list()['field_zh'],assumptions_zh=['按手工核对的销量窗口外推，需求可能变化。','仅按已核对口径的库存与符合到达条件的在途测算。','计划为本地草稿，不执行采购或修改库存。'],translation_status='中文字段说明已提供，SKU 与销量来源原文保留，需人工校对。')
        document['sha256']=digest(canonical(document))
        return dict(filename='ozon-restock-evidence.json',content=json.dumps(document,ensure_ascii=False,indent=2))
