"""Private Ozon read-only sync and Feishu notification outbox.

Credentials are accepted only by the local setup HTTP route, never MCP tools.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from research import canonical, digest
import ozon_reader
import feishu_sender
from sync_guard import can_send, delivery_state

DEFAULTS = dict(store_label='Ozon 俄罗斯',fulfillment_modes=['OGL'],lookback_days=30,
                interval_seconds=120,low_stock_threshold=5,max_age_seconds=600,
                stock_basis='unconfirmed',sync_enabled=False,notifications_enabled=False,
                orders_scope_confirmed=False,feishu_test_verified=False,feishu_received_confirmed=False,feishu_target_label='')
PENDING = {'awaiting_packaging','awaiting_deliver','awaiting_dispatch','awaiting_approve'}
STATUS_ZH = {'awaiting_packaging':'待备货','awaiting_deliver':'待交接配送','awaiting_dispatch':'待发货','awaiting_approve':'待确认','delivering':'配送中','delivered':'已送达','cancelled':'已取消','arbitration':'争议处理中','not_accepted':'未接收','driver_pickup':'配送员取件中','sent_by_seller':'卖家已发出'}


def now(): return datetime.now(timezone.utc).isoformat()


class LiveConnections:
    def __init__(self, core, state):
        self.core=core;self.state=Path(state);self.path=self.state/'live-connections.json'
        self.lock=threading.Lock();self.config_lock=threading.RLock();self.tickets={};self.timer=None
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS live_jobs(id TEXT PRIMARY KEY,status TEXT,started TEXT,finished TEXT,result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS live_snapshots(id TEXT PRIMARY KEY,connection TEXT,kind TEXT,payload TEXT,sha TEXT,observed TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS live_latest(connection TEXT,kind TEXT,snapshot TEXT,PRIMARY KEY(connection,kind))')
            db.execute('CREATE TABLE IF NOT EXISTS live_seen(connection TEXT,kind TEXT,entity TEXT,state TEXT,episode INTEGER,PRIMARY KEY(connection,kind,entity))')
            db.execute('CREATE TABLE IF NOT EXISTS live_outbox(id TEXT PRIMARY KEY,event_key TEXT UNIQUE,connection TEXT,channel TEXT,status TEXT,message TEXT,created TEXT,updated TEXT,receipt TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS live_http(id INTEGER PRIMARY KEY AUTOINCREMENT,job TEXT,endpoint TEXT,request_sha TEXT,response_sha TEXT,error TEXT,at TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS live_ack(alert TEXT PRIMARY KEY,at TEXT)')
            db.execute("UPDATE live_jobs SET status='interrupted',finished=?,result=? WHERE status='running'",(now(),canonical({'error':'interrupted_no_snapshot_claim'})))
            db.execute("UPDATE live_outbox SET status='unknown',updated=?,receipt=? WHERE status='sending'",(now(),canonical({'code':'interrupted_delivery_unknown'})))

    def config(self):
        with self.config_lock:
            if not self.path.exists(): return dict(DEFAULTS)
            if self.path.is_symlink(): raise ValueError('private_config_must_not_be_symlink')
            return {**DEFAULTS,**json.loads(self.path.read_text())}

    def _save(self, value):
        self.state.mkdir(exist_ok=True,parents=True,mode=0o700)
        temporary=self.path.with_name('live-connections.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False)
        temporary.chmod(0o600);os.replace(temporary,self.path);self.path.chmod(0o600)

    @staticmethod
    def channel(config): return digest(config.get('feishu_webhook','')+'\n'+config.get('feishu_target_label',''))[:24]

    def configure(self, values):
        allowed={'store_label','fulfillment_modes','ozon_client_id','ozon_api_key','lookback_days','interval_seconds','low_stock_threshold','max_age_seconds','stock_basis','basis_confirmed','orders_scope_confirmed','feishu_webhook','feishu_signing_secret','feishu_target_label','sync_enabled','notifications_enabled','feishu_received_confirmed'}
        if not isinstance(values,dict) or set(values)-allowed:raise ValueError('invalid_setup_fields')
        with self.config_lock:
            old=self.config();new={**old,**{k:v for k,v in values.items() if k not in ('basis_confirmed',)}}
            for key in ('ozon_client_id','ozon_api_key','feishu_webhook','feishu_signing_secret'):
                if key in values and values[key]=='':new[key]=old.get(key,'')
            for key in ('store_label','feishu_target_label'):
                if not isinstance(new[key],str) or len(new[key])>100:raise ValueError('invalid_setup_label')
            modes=new['fulfillment_modes']
            if not isinstance(modes,list) or not modes or any(not isinstance(m,str)for m in modes) or len(set(modes))!=len(modes) or set(modes)-{'OGL','FBS','realFBS','FBO'}:raise ValueError('select_fulfillment_modes')
            for key,minimum,maximum in [('lookback_days',1,90),('interval_seconds',60,3600),('low_stock_threshold',0,1000000),('max_age_seconds',120,86400)]:
                if type(new[key]) is not int or not minimum<=new[key]<=maximum:raise ValueError('invalid_'+key)
            for key in ('sync_enabled','notifications_enabled','feishu_received_confirmed','orders_scope_confirmed'):
                if type(new[key]) is not bool:raise ValueError('invalid_setup_toggle')
            client=new.get('ozon_client_id','');key=new.get('ozon_api_key','')
            if not isinstance(client,str) or not client.isdigit() or len(client)>30:raise ValueError('invalid_client_id')
            if not isinstance(key,str) or not 8<=len(key)<=500:raise ValueError('invalid_ozon_api_key')
            if new.get('feishu_webhook'):feishu_sender.validate_webhook(new['feishu_webhook'])
            if not isinstance(new.get('feishu_signing_secret',''),str) or len(new.get('feishu_signing_secret',''))>500:raise ValueError('invalid_signing_secret')
            account_changed=client!=old.get('ozon_client_id') or modes!=old.get('fulfillment_modes')
            if account_changed:
                new['connection_id']=str(uuid.uuid4());new['stock_basis']='unconfirmed';new['orders_scope_confirmed']=False;new['sync_enabled']=False;new['notifications_enabled']=False
            if not new.get('connection_id'):new['connection_id']=str(uuid.uuid4())
            if new['orders_scope_confirmed'] and not old.get('orders_scope_confirmed'):
                sample=self.snapshot(new['connection_id'],'orders')
                if not sample:raise ValueError('fetch_orders_before_scope_review')
                new['orders_scope_review_snapshot']=sample['sha256'];new['orders_scope_reviewed_at']=now()
            channel_changed=self.channel(new)!=self.channel(old) or new.get('feishu_signing_secret')!=old.get('feishu_signing_secret')
            if channel_changed:new['feishu_test_verified']=False;new['feishu_received_confirmed']=False;new['notifications_enabled']=False
            basis=new['stock_basis']
            if basis not in ('unconfirmed','present_minus_reserved','present_is_available'):raise ValueError('invalid_stock_basis')
            if basis!='unconfirmed' and basis!=old.get('stock_basis'):
                snapshot=self.snapshot(new['connection_id'],'stock')
                if not snapshot or values.get('basis_confirmed') is not True:raise ValueError('review_live_stock_before_confirming_basis')
                new['basis_reviewed_at']=now();new['basis_review_snapshot']=snapshot['sha256']
            if new['notifications_enabled']:
                if not new.get('feishu_webhook') or not new.get('feishu_target_label') or not new.get('feishu_test_verified') or not new.get('feishu_received_confirmed'):raise ValueError('verify_feishu_test_and_confirm_receipt_first')
                if not self.snapshot(new['connection_id'],'orders'):raise ValueError('establish_orders_baseline_first')
                if not new['orders_scope_confirmed']:raise ValueError('review_orders_scope_first')
            if new['sync_enabled'] and not self.snapshot(new['connection_id'],'orders'):raise ValueError('complete_manual_sync_first')
            if new['sync_enabled'] and not new['orders_scope_confirmed']:raise ValueError('review_orders_scope_first')
            self._save(new)
        return self.status()

    def snapshot(self, connection, kind):
        with self.core.db() as db:row=db.execute('SELECT s.id,s.payload,s.sha,s.observed FROM live_latest l JOIN live_snapshots s ON l.snapshot=s.id WHERE l.connection=? AND l.kind=?',(connection,kind)).fetchone()
        return dict(id=row[0],data=json.loads(row[1]),sha256=row[2],observed_at=row[3]) if row else None

    def _fresh(self, snapshot, config):
        if not snapshot:return False
        dt=datetime.fromisoformat(snapshot['observed_at'])
        return 0<=(datetime.now(timezone.utc)-dt).total_seconds()<=config['max_age_seconds']

    def status(self, samples=False):
        config=self.config();connection=config.get('connection_id','')
        orders=self.snapshot(connection,'orders');stock=self.snapshot(connection,'stock')
        with self.core.db() as db:
            job=db.execute('SELECT id,status,started,finished,result FROM live_jobs ORDER BY started DESC LIMIT 1').fetchone()
            outbox=[dict(status=r[0],count=r[1])for r in db.execute('SELECT status,count(*) FROM live_outbox WHERE connection=? GROUP BY status',(connection,))]
        def summary(snapshot):return {'available':bool(snapshot),'fresh':self._fresh(snapshot,config),'count':len(snapshot['data']['records']) if snapshot else None,'observed_at':snapshot['observed_at'] if snapshot else None,'sha256':snapshot['sha256'] if snapshot else None}
        result=dict(configured=bool(config.get('ozon_client_id') and config.get('ozon_api_key')),store_label=config['store_label'],market='RU',fulfillment_modes=config['fulfillment_modes'],
                    credentials_present={'ozon_client_id':bool(config.get('ozon_client_id')),'ozon_api_key':bool(config.get('ozon_api_key')),'feishu_webhook':bool(config.get('feishu_webhook')),'feishu_signing_secret':bool(config.get('feishu_signing_secret'))},
                    lookback_days=config['lookback_days'],interval_seconds=config['interval_seconds'],low_stock_threshold=config['low_stock_threshold'],max_age_seconds=config['max_age_seconds'],
                    stock_basis=config['stock_basis'],orders_scope_confirmed=config['orders_scope_confirmed'],sync_enabled=config['sync_enabled'],notifications_enabled=config['notifications_enabled'],feishu_test_verified=config['feishu_test_verified'],feishu_received_confirmed=config['feishu_received_confirmed'],
                    feishu_target_label=config['feishu_target_label'],orders=summary(orders),stock=summary(stock),outbox=outbox,timer_running=bool(self.timer and self.timer.is_alive()),
                    last_job=dict(id=job[0],status=job[1],started=job[2],finished=job[3],result=json.loads(job[4]) if job[4] else None) if job else None)
        if samples:
            result['order_samples']=orders['data']['records'][:8] if orders else []
            result['stock_samples']=self.inventory_rows()[:10]
        return result

    def _request(self, job, path, body, client, key):
        response_sha=None;error=None
        try:
            value,response_sha=ozon_reader.post(path,body,client,key);return value,response_sha
        except ozon_reader.ConnectionIssue as issue:error=issue.code;raise
        finally:
            with self.core.db() as db:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at) VALUES (?,?,?,?,?,?)',(job,path,digest(canonical(body)),response_sha,error,now()))

    def start_sync(self):
        config=self.config()
        if not config.get('ozon_client_id') or not config.get('ozon_api_key') or not config['fulfillment_modes']:raise ValueError('configure_ozon_first')
        if not self.lock.acquire(blocking=False):
            with self.core.db() as db:row=db.execute("SELECT id FROM live_jobs WHERE status='running' ORDER BY started DESC LIMIT 1").fetchone()
            return {'id':row[0] if row else None,'status':'running'}
        ident=str(uuid.uuid4())
        try:
            with self.core.db() as db:db.execute('INSERT INTO live_jobs VALUES (?,?,?,?,?)',(ident,'running',now(),None,None))
            threading.Thread(target=self._sync,args=(ident,config),daemon=True,name='commerce-ozon-readonly-sync').start()
        except Exception:
            self.lock.release()
            raise
        return {'id':ident,'status':'running'}

    def _sync(self, ident, config):
        results={};connection=config['connection_id']
        try:
            for kind in ('orders','stock'):
                try:
                    batch=ozon_reader.fetch(config,kind,request=lambda *args:self._request(ident,*args))
                    if self.config().get('connection_id')!=connection:
                        results[kind]={'status':'superseded'};continue
                    had_baseline=self.snapshot(connection,kind) is not None
                    self._publish(connection,kind,batch,config,had_baseline)
                    results[kind]={'status':'success','count':len(batch['records']),'baseline_only':not had_baseline}
                except ozon_reader.ConnectionIssue as issue:results[kind]={'status':'failed','code':issue.code,'http_status':issue.http_status}
                except Exception:results[kind]={'status':'failed','code':'sync_projection_failed'}
            status='success' if all(r['status']=='success' for r in results.values()) else 'partial' if any(r['status']=='success'for r in results.values()) else 'failed'
            with self.core.db() as db:db.execute('UPDATE live_jobs SET status=?,finished=?,result=? WHERE id=?',(status,now(),canonical(results),ident))
        finally:self.lock.release()

    def _enqueue(self, db, config, event_key, message):
        if not config.get('notifications_enabled') or not config.get('feishu_test_verified'):return
        ident=str(uuid.uuid4());at=now()
        db.execute('INSERT OR IGNORE INTO live_outbox VALUES (?,?,?,?,?,?,?,?,?)',(ident,event_key,config['connection_id'],self.channel(config),'pending',message,at,at,None))

    def _publish(self, connection, kind, batch, config, baseline):
        encoded=canonical(batch);sha=digest(encoded);snapshot=str(uuid.uuid4())
        current_config=self.config()
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO live_snapshots VALUES (?,?,?,?,?,?)',(snapshot,connection,kind,encoded,sha,batch['observed_at']))
            db.execute('INSERT OR REPLACE INTO live_latest VALUES (?,?,?)',(connection,kind,snapshot))
            if kind=='orders':
                for record in batch['records']:
                    entity=record['posting_number'];old=db.execute('SELECT state FROM live_seen WHERE connection=? AND kind=? AND entity=?',(connection,kind,entity)).fetchone()
                    db.execute('INSERT OR REPLACE INTO live_seen VALUES (?,?,?,?,?)',(connection,kind,entity,record['status'],0))
                    if baseline and old is None and record['status'] in PENDING:
                        lines=['Ozon 俄罗斯｜新发现待处理发货单',f"店铺：{config['store_label']}",f"发货单：{entity}",f"平台状态：{record['status']}",f"来源核对时间：{batch['observed_at']}"]
                        lines.extend(f"SKU {p['offer_id'] or p['sku']} × {p['quantity']}"for p in record['products'][:12])
                        if record['created_at']:lines.append('平台订单时间：'+record['created_at'])
                        lines.append('来源：Ozon Seller API，只读同步。未执行发货。')
                        self._enqueue(db,current_config,'order:'+connection+':'+entity,'\n'.join(lines))
            else:
                for record in self._stock_rows(batch,config):
                    entity=record['key'];available=record['available'];level='unknown' if available is None else 'zero' if available==0 else 'low' if available<=config['low_stock_threshold'] else 'normal'
                    old=db.execute('SELECT state,episode FROM live_seen WHERE connection=? AND kind=? AND entity=?',(connection,kind,entity)).fetchone()
                    episode=(old[1] if old else 0)+(1 if old and old[0]=='normal' and level in ('low','zero') else 0)
                    db.execute('INSERT OR REPLACE INTO live_seen VALUES (?,?,?,?,?)',(connection,kind,entity,level,episode))
                    if baseline and available is not None and level in ('low','zero') and (not old or old[0] not in ('low','zero') or old[0]=='low' and level=='zero'):
                        text='\n'.join(['Ozon 俄罗斯｜库存预警',f"店铺：{config['store_label']}",f"SKU：{record['offer_id'] or record['sku'] or record['product_id']}",f"范围：{record['type']} 按履约方式汇总（非单仓）",f"核对口径的可售数：{available}；提醒阈值：{config['low_stock_threshold']}",f"来源时间：{batch['observed_at']}",'建议核对补货；未计算确定采购量，也未修改库存。'])
                        self._enqueue(db,current_config,f'stock:{connection}:{entity}:{episode}:{level}',text)

    def _stock_rows(self, batch, config):
        output=[]
        for product in batch['records']:
            for stock in product['stocks']:
                available=None
                if config['stock_basis']=='present_is_available':available=stock['present']
                elif config['stock_basis']=='present_minus_reserved' and stock['present']>=stock['reserved']:available=stock['present']-stock['reserved']
                output.append(dict(key=product['product_id']+':'+stock['type'],product_id=product['product_id'],offer_id=product['offer_id'],**stock,
                                   available=available,scope='履约方式汇总，非单仓',observed_at=batch['observed_at']))
        return output

    def inventory_rows(self):
        config=self.config();snapshot=self.snapshot(config.get('connection_id',''),'stock')
        return self._stock_rows(snapshot['data'],config) if snapshot else []

    def order_rows(self):
        config=self.config();snapshot=self.snapshot(config.get('connection_id',''),'orders')
        return snapshot['data']['records'] if snapshot else []

    def workbench(self, name, args):
        config=self.config();connection=config.get('connection_id','')
        orders=self.snapshot(connection,'orders');stock=self.snapshot(connection,'stock')
        selected=(args.get('platform','all') in ('all','ozon') and args.get('store_id','all') in ('all','ozon-live') and args.get('market','all') in ('all','RU'))
        order_rows=[];product_rows=[]
        if selected and orders:
            for row in orders['data']['records']:
                items=row['products'];skus=', '.join(p['offer_id'] or p['sku'] for p in items)
                order_rows.append(dict(id=row['posting_number'],platform='ozon',store_id='ozon-live',store=config['store_label'],market='RU',product='；'.join((p['name'] or p['offer_id'] or p['sku'])+' × '+str(p['quantity'])for p in items),sku=skus,amount=None,currency=None,status=row['status'],observed_at=orders['observed_at'],source_sha256=orders['sha256'],data_source='ozon_api',stale=not self._fresh(orders,config)))
        if selected and stock:
            for row in self._stock_rows(stock['data'],config):
                product_rows.append(dict(stock_row_key=row['key'],sku=row['offer_id'] or row['sku'] or row['product_id'],name=row['offer_id'] or 'Ozon 商品 '+row['product_id'],platform='ozon',available=row['available'] if self._fresh(stock,config) else None,threshold=config['low_stock_threshold'],price=None,currency=None,scope=row['type']+' 汇总（非单仓）',observed_at=stock['observed_at'],source_sha256=stock['sha256'],data_source='ozon_api',stale=not self._fresh(stock,config)))
        if name=='commerce_orders_list':
            for row in order_rows:row['status_zh']=STATUS_ZH.get(row['status'],'待翻译校对：'+row['status'])
            query=args.get('query','').lower();rows=[r for r in order_rows if (not args.get('status') or r['status']==args['status']) and query in canonical(r).lower()]
            return dict(mode='live',orders=rows,total=len(rows),data_source='ozon_api' if orders else 'not_connected',observed_at=orders['observed_at'] if orders else None,scope_confirmed=config['orders_scope_confirmed'],stale=not self._fresh(orders,config))
        if name=='commerce_products_list':return dict(mode='live',products=product_rows,data_source='ozon_api' if stock else 'not_connected',stock_basis=config['stock_basis'],stale=not self._fresh(stock,config))
        return dict(mode='live',currency='USD',timezone='Asia/Shanghai',rate_note='尚无经过核对的销售额和汇率；订单为同步窗口内发货单，库存按已核对口径展示。',sales=None,orders=len(order_rows) if selected and orders else None,pending=sum(r['status'] in PENDING for r in order_rows) if selected and orders else None,stock_alerts=sum(p['available']<=p['threshold']for p in product_rows if p['available'] is not None) if selected and stock and config['stock_basis']!='unconfirmed' and self._fresh(stock,config) else None,platforms=[],updated_at=now(),data_source='ozon_api' if orders or stock else 'not_connected',orders_label='同步发货单',pending_label='待处理发货单')

    def alerts(self):
        config=self.config();connection=config.get('connection_id','');orders=self.snapshot(connection,'orders');stock=self.snapshot(connection,'stock')
        alerts=[]
        with self.core.db() as db:ack={r[0]for r in db.execute('SELECT alert FROM live_ack')}
        def add(kind,entity,title,detail,severity,snapshot,sku='',order=None):
            ident=digest(connection+':'+kind+':'+entity)[:24];fresh=self._fresh(snapshot,config)
            alerts.append(dict(id=ident,kind=kind,title=title,detail=detail,severity=severity,status='suspended' if not fresh else 'acknowledged' if ident in ack else 'active',platform='ozon',store_id=config['store_label'],market='RU',warehouse='接口返回范围，库存为履约方式汇总',sku=sku,order_id=order,observed_at=snapshot['observed_at'],source_ref='Ozon Seller API / snapshot '+snapshot['id'],source_sha256=snapshot['sha256'],source='ozon_api',rules={'max_age_minutes':config['max_age_seconds']/60,'dispatch_warning_hours':0},delivery='feishu_enabled' if config['notifications_enabled'] else 'workbench_only'))
        if orders:
            for order in orders['data']['records']:
                if order['status'] not in PENDING:continue
                skus=', '.join(p['offer_id'] or p['sku'] for p in order['products'])
                title='平台履约订单待处理状态' if order['fulfillment']=='FBO' else '待备货' if order['status']=='awaiting_packaging' else '待发货 / 待核对'
                detail='平台原始状态：'+order['status']+'。'
                if order['ship_by']:detail+='接口 shipment_date：'+order['ship_by']+'（计划发货字段，尚未自动当作违约截止）。'
                add('live_order',order['posting_number'],title,detail,'P1',orders,skus,order['posting_number'])
        if stock:
            for row in self._stock_rows(stock['data'],config):
                if row['available'] is not None and row['available']<=config['low_stock_threshold']:
                    add('live_stock',row['key'],'可售库存为零' if row['available']==0 else '低库存，请核对补货',f"履约范围 {row['type']}：可售 {row['available']}，提醒阈值 {config['low_stock_threshold']}。未填写需求和交期，不推断确定采购量。",'P0' if row['available']==0 else 'P1',stock,row['offer_id'] or row['sku'] or row['product_id'])
        return dict(alerts=alerts,stock_plans=[],mode='ozon_api',rules={'max_age_minutes':config['max_age_seconds']/60,'dispatch_warning_hours':0,'overstock_days':90},observation_count=len(self.order_rows())+len(self.inventory_rows()),generated_at=now(),connection={'platform':'ozon','market':'RU','live_sync':'connected' if self._fresh(orders,config) and self._fresh(stock,config) else 'partial_or_stale','notification':'enabled' if config['notifications_enabled'] else 'not_enabled','server_timer':'running' if self.timer and self.timer.is_alive() else 'not_started'},notice='来自已保存的 Ozon 只读快照；超过有效期挂起，已阅不代表处理完成。')

    def acknowledge(self, ident):
        if ident not in {a['id']for a in self.alerts()['alerts']}:raise ValueError('live_alert_not_found')
        with self.core.db() as db:db.execute('INSERT OR REPLACE INTO live_ack VALUES (?,?)',(ident,now()))
        return {'id':ident,'status':'acknowledged'}

    def export_evidence(self):
        config=self.config();connection=config.get('connection_id','')
        snapshots={kind:self.snapshot(connection,kind) for kind in ('orders','stock')}
        with self.core.db() as db:
            deliveries=[dict(id=r[0],status=r[1],created_at=r[2],updated_at=r[3],receipt=json.loads(r[4]) if r[4] else None) for r in db.execute('SELECT id,status,created,updated,receipt FROM live_outbox WHERE connection=? ORDER BY created',(connection,))]
        document=dict(schema='ozon-live-evidence-v1',exported_at=now(),scope={'market':'RU','modes':config['fulfillment_modes'],'orders_reviewed':config['orders_scope_confirmed'],'stock_basis':config['stock_basis']},snapshots=snapshots,delivery_receipts=deliveries,
                      field_zh={'posting_number':'发货单号','status':'平台原始状态','products':'商品明细','offer_id':'卖家商品编码','quantity':'数量','present':'平台原始库存字段，含义以核对口径为准','reserved':'平台预留字段','type':'履约方式范围','observed_at':'来源核对时间','sha256':'快照哈希','response_sha256':'原始响应哈希'},
                      status_translation=STATUS_ZH,product_translation_status='商品名称保留平台原文，中文翻译待校对',privacy='不包含凭据或买家身份；保留规范化业务字段、请求范围、响应哈希和发送回执。响应哈希不等于外部事实已独立核实。')
        return {'filename':'ozon-live-evidence.json','content':json.dumps(document,ensure_ascii=False,indent=2)}

    def _current_message(self, event, config):
        connection=config['connection_id'];order_prefix='order:'+connection+':'
        if event.startswith(order_prefix):
            snapshot=self.snapshot(connection,'orders')
            if not self._fresh(snapshot,config):return None,'waiting_fresh_data',None
            posting=event[len(order_prefix):];record=next((x for x in snapshot['data']['records'] if x['posting_number']==posting),None)
            if not record or record['status'] not in PENDING:return None,'order_no_longer_pending',snapshot['sha256']
            lines=['Ozon 俄罗斯｜新发现待处理发货单',f"店铺：{config['store_label']}",f"发货单：{posting}",f"平台状态：{record['status']}",f"来源核对时间：{snapshot['observed_at']}"]
            lines.extend(f"SKU {p['offer_id'] or p['sku']} × {p['quantity']}"for p in record['products'][:12])
            lines.append('来源：Ozon Seller API，只读同步。未执行发货。')
            return '\n'.join(lines),None,snapshot['sha256']
        if event.startswith('stock:'+connection+':'):
            snapshot=self.snapshot(connection,'stock')
            if not self._fresh(snapshot,config):return None,'waiting_fresh_data',None
            entity=event[len('stock:'+connection+':'):].rsplit(':',2)[0]
            row=next((x for x in self._stock_rows(snapshot['data'],config) if x['key']==entity),None)
            if not row or row['available'] is None or row['available']>config['low_stock_threshold']:return None,'stock_no_longer_low',snapshot['sha256']
            text='\n'.join(['Ozon 俄罗斯｜库存预警',f"店铺：{config['store_label']}",f"SKU：{row['offer_id'] or row['sku'] or row['product_id']}",f"范围：{row['type']} 汇总（非单仓）",f"核对口径的可售数：{row['available']}；提醒阈值：{config['low_stock_threshold']}",f"来源时间：{snapshot['observed_at']}",'建议核对补货；未推断确定采购量，未修改库存。'])
            return text,None,snapshot['sha256']
        return None,'unknown_notification_event',None

    def test_feishu(self):
        config=self.config()
        if not config.get('feishu_webhook') or not config.get('feishu_target_label'):raise ValueError('configure_feishu_target_first')
        ident=str(uuid.uuid4());at=now()
        message='电商工作台｜连接测试\n这是一条由你在本机配置页触发的测试消息。\n接收目标标签：'+config['feishu_target_label']+'\n未包含客户信息，未执行店铺操作。'
        with self.core.db() as db:db.execute('INSERT INTO live_outbox VALUES (?,?,?,?,?,?,?,?,?)',(ident,'test:'+ident,config['connection_id'],self.channel(config),'pending',message,at,at,None))
        return self.dispatch(ident,allow_test=True)

    def dispatch(self, ident=None, allow_test=False):
        config=self.config()
        if not allow_test and not(config.get('notifications_enabled') and config.get('feishu_test_verified')):return {'status':'disabled'}
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            query='SELECT id,channel,status,message,created,event_key FROM live_outbox WHERE connection=? AND status=?';args=[config.get('connection_id',''),'pending']
            if ident:query+=' AND id=?';args.append(ident)
            row=db.execute(query+' ORDER BY created LIMIT 1',args).fetchone()
            if not row:return {'status':'nothing_pending'}
            if row[1]!=self.channel(config):
                db.execute("UPDATE live_outbox SET status='failed',updated=?,receipt=? WHERE id=?",(now(),canonical({'code':'channel_changed_no_retarget'}),row[0]));return {'status':'failed','code':'channel_changed_no_retarget'}
            if not can_send(row[2]):return {'status':row[2]}
            message=row[3];source_sha=None
            if not allow_test:
                message,error,source_sha=self._current_message(row[5],config)
                if error=='waiting_fresh_data':return {'status':error}
                if error:
                    db.execute("UPDATE live_outbox SET status='failed',updated=?,receipt=? WHERE id=?",(now(),canonical({'code':error}),row[0]));return {'status':'failed','code':error}
            db.execute("UPDATE live_outbox SET status='sending',updated=? WHERE id=?",(now(),row[0]))
        result=feishu_sender.send(config['feishu_webhook'],config.get('feishu_signing_secret',''),message);status=delivery_state('sending',result['outcome'])
        result.update(message_sha256=digest(message),source_snapshot_sha256=source_sha)
        with self.core.db() as db:db.execute('UPDATE live_outbox SET status=?,updated=?,receipt=? WHERE id=?',(status,now(),canonical(result),row[0]))
        if allow_test and status=='sent':
            with self.config_lock:
                fresh=self.config()
                if self.channel(fresh)==row[1]:fresh['feishu_test_verified']=True;self._save(fresh)
        return {'id':row[0],'status':status,'code':result['code']}

    def start_timer(self):
        if self.timer and self.timer.is_alive():return
        def run():
            while True:
                time.sleep(15)
                try:
                    config=self.config()
                    if config.get('sync_enabled'):
                        with self.core.db() as db:row=db.execute('SELECT started FROM live_jobs ORDER BY started DESC LIMIT 1').fetchone()
                        if not row or (datetime.now(timezone.utc)-datetime.fromisoformat(row[0])).total_seconds()>=config['interval_seconds']:self.start_sync()
                    self.dispatch()
                except Exception:pass  # Public status/outbox retains prior result; never print secrets.
        self.timer=threading.Thread(target=run,daemon=True,name='commerce-live-sync-clock');self.timer.start()

    def new_setup_ticket(self):
        ticket=secrets.token_urlsafe(32);self.tickets[ticket]=time.monotonic()+120;return ticket

    def consume_ticket(self, ticket):
        deadline=self.tickets.pop(ticket,None)
        return deadline is not None and deadline>=time.monotonic()

    def open_setup(self, origin):
        url=origin+'/setup?ticket='+self.new_setup_ticket()
        opened=webbrowser.open(url)
        return {'opened':bool(opened),'message':'本机配置页已请求打开，密钥只在该页面填写。'}
