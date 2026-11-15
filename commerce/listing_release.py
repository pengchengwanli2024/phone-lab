"""Frozen local applications and exact external readback on original ledgers.

This module has no marketplace submission/approval authority. A user-supplied
external task reference is evidence to check, never proof this app submitted it.
"""
import copy
from datetime import datetime,timezone
import json
import re
import threading
import uuid
from research import canonical,digest
import ozon_reader
from listing_release_reads import IMPORT_PATH,PRODUCT_PATH,identifier,import_projection,product_projection

FROZEN=('schema','target','payload','source_sha256','saved_source_sha256','revision','checks',
        'delivery_package_sha256','delivery_status','invalid_source_fields','platform_schema','owner_review')


def definitions(schema,string):
    target={'case_id':string,'platform':string,'store_ref':{'type':'string','maxLength':100},'market':{'type':'string','maxLength':2}}
    event={'request_id':string,'expected_event_sha256':{'type':'string','maxLength':64},'idempotency_key':string}
    confirm={'confirmed':{'type':'boolean'},'note':{'type':'string','maxLength':2000}}
    return [
        ('commerce_listing_release_get','只读版本固定的本地发布申请、审阅和外部任务/商品回读；不提交平台',schema({**target,'request_id':string},list(target))),
        ('commerce_listing_release_create','将准确保存版本追加为本地发布申请；保留缺项和专业门禁，不排队提交平台',schema({**target,**confirm,'expected_preview_sha256':string,'idempotency_key':string},[*target,*confirm,'expected_preview_sha256','idempotency_key'])),
        ('commerce_listing_release_review','记录申请已阅、退回或撤回本地申请；不批准合规，不取消平台任务',schema({**event,**confirm,'decision':{'type':'string','enum':['acknowledged','needs_changes','withdrawn']}},[*event,*confirm,'decision'])),
        ('commerce_listing_release_bind','明确记录由用户另行提交的Ozon任务引用，等待接口核对；不证明已提交或获得本系统批准',schema({**event,'task_id':{'type':'string','maxLength':19},'source_ref':{'type':'string','maxLength':1000},'confirmed':{'type':'boolean'}},[*event,'task_id','source_ref','confirmed'])),
        ('commerce_listing_release_refresh','明确读取绑定外部任务及准确商品ID；不重放提交，导入受理不等于发布成功',schema(event,list(event))),
        ('commerce_listing_release_export','导出准确申请与回执版本的私有审阅包；不是平台导入文件或发布批准',schema({'request_id':string,'expected_event_sha256':{'type':'string','maxLength':64},'format':{'type':'string','enum':['json','html']}},['request_id','expected_event_sha256'])),
        ('commerce_listing_release_image','只读获取准确申请固定链接的产品图片预览；公开HTTPS、不携带店铺凭据，不采用最新候选替代旧版本',schema({'request_id':string,'expected_request_sha256':string,'index':{'type':'integer','minimum':0,'maximum':19}},['request_id','expected_request_sha256','index'])),
    ]


def clean_note(value,limit=2000):
    if not isinstance(value,str)or not value.strip()or len(value)>limit:raise ValueError('listing_release_note_required')
    return value.strip()


class ListingReleases:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.org=service.organization;self.live=service.live
        self.reader=ozon_reader.post;self.lock=threading.Lock();self.stopping=threading.Event();self.current=None;self.thread=None

    def invoke(self,name,args):
        return {'commerce_listing_release_get':self.get,'commerce_listing_release_create':self.create,
            'commerce_listing_release_review':self.review,'commerce_listing_release_bind':self.bind,
            'commerce_listing_release_refresh':self.refresh,'commerce_listing_release_export':self.export,'commerce_listing_release_image':self.image}[name](**args)

    @staticmethod
    def kind(target):return 'listing_release_'+digest(canonical(target))[:24]
    @staticmethod
    def event_kind(rid):return 'listing_release_event_'+rid
    @staticmethod
    def key(action,key):
        if not isinstance(key,str)or not 1<=len(key)<=160:raise ValueError('invalid_idempotency_key')
        return action+':'+digest(key)

    def binding(self,target,synthetic):
        if synthetic:return 'synthetic-listing-release'
        if target['platform']=='ozon'and target['store_ref']=='ozon-live'and target['market']=='RU':
            return self.service.listing_schema.connection(self.live.config())
        return None

    @staticmethod
    def intact(row):
        if not row:return None
        data=json.loads(row[1])
        if digest(canonical(data))!=row[2]:raise ValueError('listing_release_integrity_failed')
        return dict(id=row[0],data=data,sha256=row[2],created_at=row[3])

    def request(self,rid):
        if not isinstance(rid,str)or not re.fullmatch('[a-f0-9]{32}',rid):raise ValueError('listing_release_not_found')
        with self.core.db()as db:row=db.execute('SELECT id,payload,sha,created,kind,case_id FROM org_artifacts WHERE id=?',(rid,)).fetchone()
        if not row:raise ValueError('listing_release_not_found')
        r=self.intact(row[:4]);d=r['data']
        if d.get('schema')!='listing-release-request-v1'or row[4]!=self.kind(d['target'])or row[5]!=d['target']['case_id']:raise ValueError('listing_release_scope_mismatch')
        self.org.case(row[5])
        if digest(canonical(d['frozen']))!=d['preview_sha256']:raise ValueError('listing_release_integrity_failed')
        return r

    def head(self,r):
        with self.core.db()as db:row=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=?AND kind=?ORDER BY created DESC,id DESC LIMIT 1',(r['data']['target']['case_id'],self.event_kind(r['id']))).fetchone()
        h=self.intact(row)
        if h and(h['data']['request_id']!=r['id']or h['data']['request_sha256']!=r['sha256']):raise ValueError('listing_release_integrity_failed')
        return h

    @staticmethod
    def state(head):return copy.deepcopy(head['data']['state'])if head else dict(decision='pending',note='',external=None,observation=None,read={'status':'not_requested','error':None})

    def duplicate(self,case,kind,key,request_sha):
        with self.core.db()as db:row=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=?AND kind=?AND idem=?',(case,kind,key)).fetchone()
        old=self.intact(row)
        if old and old['data']['request_sha256']!=request_sha:raise ValueError('listing_release_idempotency_conflict')
        return old

    @staticmethod
    def receipt(value,rid):return dict(id=value['id'],sha256=value['sha256'],request_id=rid,external_operations_executed=False)

    def create(self,case_id,platform,store_ref,market,expected_preview_sha256,note,confirmed,idempotency_key):
        if confirmed is not True:raise ValueError('listing_release_confirmation_required')
        text=clean_note(note);target,_=self.service.listings.scope(case_id,platform,store_ref,market)
        kind=self.kind(target);key=self.key('create',idempotency_key);sig=digest(canonical([target,expected_preview_sha256,text,confirmed]))
        with self.live.config_lock,self.core.atomic():
            old=self.duplicate(case_id,kind,key,sig)
            if old:return self.receipt(old,old['id'])
            plan=self.service.listings.get(**target)
            if plan['preview_sha256']!=expected_preview_sha256:raise ValueError('listing_release_preview_changed')
            if not plan['revision']:raise ValueError('listing_save_required')
            if plan['stale']:raise ValueError('workspace_source_changed')
            self.service.product_workspace.guard(case_id,plan['source_sha256'])
            frozen={k:plan[k]for k in FROZEN if k in plan}
            d=dict(schema='listing-release-request-v1',target=target,preview_sha256=plan['preview_sha256'],frozen=frozen,note=text,
                synthetic=plan['synthetic'],connection_binding=self.binding(target,plan['synthetic']),request_sha256=sig,
                authority='local_request_only_no_marketplace_submission')
            result=self.org._store(case_id,kind,d,key)
            return {**result,'request_id':result['id']}

    def _write(self,r,h,state,action,key,sig,detail=None):
        d=dict(schema='listing-release-event-v1',request_id=r['id'],request_sha256=r['sha256'],previous_event_sha256=h['sha256']if h else'',
            action=action,state=state,operation_sha256=sig,detail=detail or{})
        return self.org._store(r['data']['target']['case_id'],self.event_kind(r['id']),d,key,_expected_head=h['id']if h else None)

    def event_duplicate(self,r,key,sig):
        with self.core.db()as db:row=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=?AND kind=?AND idem=?',(r['data']['target']['case_id'],self.event_kind(r['id']),key)).fetchone()
        old=self.intact(row)
        if old and old['data']['operation_sha256']!=sig:raise ValueError('listing_release_idempotency_conflict')
        return old

    @staticmethod
    def cas(h,expected):
        if not isinstance(expected,str)or(h['sha256']if h else'')!=expected:raise ValueError('listing_release_conflict')

    def review(self,request_id,expected_event_sha256,decision,note,confirmed,idempotency_key):
        if confirmed is not True or decision not in ('acknowledged','needs_changes','withdrawn'):raise ValueError('listing_release_confirmation_required')
        text=clean_note(note);key=self.key('review',idempotency_key);sig=digest(canonical([request_id,expected_event_sha256,decision,text,confirmed]))
        with self.live.config_lock,self.core.atomic():
            r=self.request(request_id);old=self.event_duplicate(r,key,sig)
            if old:return self.receipt(old,request_id)
            h=self.head(r);self.cas(h,expected_event_sha256);s=self.state(h)
            if s['decision']=='withdrawn':raise ValueError('listing_release_withdrawn')
            if decision=='acknowledged':
                current=self.service.listings.get(**r['data']['target'])
                if current['preview_sha256']!=r['data']['preview_sha256']:raise ValueError('listing_release_request_outdated')
            s.update(decision=decision,note=text)
            return {**self._write(r,h,s,'review',key,sig),'request_id':request_id}

    def bind(self,request_id,expected_event_sha256,task_id,source_ref,confirmed,idempotency_key):
        if confirmed is not True:raise ValueError('listing_release_confirmation_required')
        if not isinstance(task_id,str):raise ValueError('listing_release_invalid_identifier')
        task_id=identifier(task_id);source=clean_note(source_ref,1000);key=self.key('bind',idempotency_key)
        sig=digest(canonical([request_id,expected_event_sha256,task_id,source,confirmed]))
        with self.live.config_lock,self.core.atomic()as db:
            r=self.request(request_id);d=r['data'];t=d['target'];old=self.event_duplicate(r,key,sig)
            if old:return self.receipt(old,request_id)
            if t['platform']!='ozon'or t['store_ref']!='ozon-live'or t['market']!='RU':raise ValueError('listing_release_readback_not_supported')
            if self.binding(t,d['synthetic'])!=d['connection_binding']:raise ValueError('listing_release_connection_changed')
            sku=d['frozen']['payload']['fields']['sku']
            if not sku:raise ValueError('listing_release_sku_required')
            prior=db.execute("SELECT payload FROM org_artifacts WHERE json_extract(payload,'$.action')='bind'AND json_extract(payload,'$.detail.connection_binding')=?AND json_extract(payload,'$.state.external.task_id')=?AND json_extract(payload,'$.detail.sku')=?",(d['connection_binding'],task_id,sku)).fetchall()
            if any(json.loads(row[0])['request_id']!=request_id for row in prior):raise ValueError('listing_release_external_reference_in_use')
            h=self.head(r);self.cas(h,expected_event_sha256);s=self.state(h)
            if s['decision']=='withdrawn':raise ValueError('listing_release_withdrawn')
            s.update(external=dict(task_id=task_id,source_ref=source),observation=None,read={'status':'not_requested','error':None})
            return {**self._write(r,h,s,'bind',key,sig,dict(connection_binding=d['connection_binding'],sku=sku)),'request_id':request_id}

    def credentials(self,r):
        d=r['data'];t=d['target']
        if d['synthetic']:raise ValueError('listing_release_demo_no_network')
        if t['platform']!='ozon'or t['store_ref']!='ozon-live'or t['market']!='RU':raise ValueError('listing_release_readback_not_supported')
        c=self.live.config()
        if not c.get('ozon_client_id')or not c.get('ozon_api_key'):raise ValueError('configure_ozon_first')
        if self.binding(t,False)!=d['connection_binding']:raise ValueError('listing_release_connection_changed')
        return c

    def refresh(self,request_id,expected_event_sha256,idempotency_key):
        key=self.key('read',idempotency_key);sig=digest(canonical([request_id,expected_event_sha256]));r=self.request(request_id)
        old=self.event_duplicate(r,key,sig)
        if old:return self.receipt(old,request_id)
        self.credentials(r)
        if self.stopping.is_set():raise ValueError('listing_release_stopped')
        if not self.lock.acquire(blocking=False):raise ValueError('listing_release_read_busy')
        launched=False
        try:
            with self.live.config_lock,self.core.atomic():
                r=self.request(request_id);old=self.event_duplicate(r,key,sig)
                if old:return self.receipt(old,request_id)
                c=self.credentials(r);h=self.head(r);self.cas(h,expected_event_sha256);s=self.state(h)
                if not s['external']:raise ValueError('listing_release_external_reference_required')
                job=dict(id=uuid.uuid4().hex,request_id=request_id,task_id=s['external']['task_id'])
                s['read']=dict(id=job['id'],status='running',error=None)
                value=self._write(r,h,s,'read_started',key,sig);self.current=job
            self.thread=threading.Thread(target=self.run,args=(r,c,job),daemon=True,name='ozon-release-readback');self.thread.start();launched=True
            return {**value,'request_id':request_id}
        except Exception:self.current=None;raise
        finally:
            if not launched:self.lock.release()

    @staticmethod
    def error(exc):
        code=exc.code if isinstance(exc,ozon_reader.ConnectionIssue)else str(exc)
        allowed={'listing_release_response_schema','listing_release_invalid_identifier','listing_release_connection_changed','listing_release_read_interrupted','ozon_auth_or_permission','ozon_network_error','ozon_rate_limited','ozon_http_error','response_too_large','unexpected_response_schema'}
        return code if code in allowed else'listing_release_read_failed'

    def fetch(self,job,path,body,c,project):
        raw_sha=None;err=None
        try:
            payload,raw_sha=self.reader(path,body,c['ozon_client_id'],c['ozon_api_key'])
            if not isinstance(raw_sha,str)or not re.fullmatch('[a-f0-9]{64}',raw_sha):raise ValueError('listing_release_response_schema')
            result=project(payload)
            return dict(endpoint=path,request_sha256=digest(canonical(body)),response_sha256=raw_sha,projection=result)
        except Exception as exc:err=self.error(exc);raise
        finally:
            with self.core.db()as db:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at)VALUES(?,?,?,?,?,?)',(job['id'],path,digest(canonical(body)),raw_sha,err,datetime.now(timezone.utc).isoformat()))

    def run(self,r,c,job):
        buffers=[];observation=None;error=None
        try:
            sku=r['data']['frozen']['payload']['fields']['sku']
            self.credentials(r)
            source=self.fetch(job,IMPORT_PATH,{'task_id':int(job['task_id'])},c,lambda p:import_projection(p,sku));buffers.append(source)
            imported=source['projection'];observation=dict(status=imported['status'],import_confirmed=False,external_task_id=job['task_id'])
            if imported['status']=='awaiting_product_readback':
                product=imported['record']['product_id']
                self.credentials(r)
                source=self.fetch(job,PRODUCT_PATH,{'product_id':[int(product)]},c,lambda p:product_projection(p,sku,product));buffers.append(source)
                record=source['projection']['record'];flags=record['statuses']if record else{}
                observation.update(status=source['projection']['status'],import_confirmed=source['projection']['status']=='product_observed'and flags.get('is_created')is True and flags.get('is_failed')is False)
            if self.stopping.is_set():raise ValueError('listing_release_read_interrupted')
        except Exception as exc:error=self.error(exc)
        try:
            with self.live.config_lock,self.core.atomic()as db:
                r=self.request(r['id']);h=self.head(r);s=self.state(h);now=datetime.now(timezone.utc).isoformat()
                if self.binding(r['data']['target'],r['data']['synthetic'])!=r['data']['connection_binding']:error='listing_release_connection_changed';buffers=[]
                evidence=[]
                for data in buffers:
                    data={**data,'scope':dict(request_id=r['id'],task_id=job['task_id'],sku=r['data']['frozen']['payload']['fields']['sku'])}
                    encoded=canonical(data);sha=digest(encoded);snapshot=uuid.uuid4().hex;kind='listing-release:'+digest(canonical(data['scope']))[:32]+':'+('import'if data['endpoint']==IMPORT_PATH else'product')
                    db.execute('INSERT INTO live_snapshots VALUES(?,?,?,?,?,?)',(snapshot,r['data']['connection_binding'],kind,encoded,sha,now))
                    db.execute('INSERT OR REPLACE INTO live_latest VALUES(?,?,?)',(r['data']['connection_binding'],kind,snapshot))
                    evidence.append(dict(snapshot_id=snapshot,sha256=sha,observed_at=now,endpoint=data['endpoint']))
                same=bool(s['external']and s['external']['task_id']==job['task_id'])
                if same:
                    s['read']=dict(id=job['id'],status='failed'if error else'succeeded',error=error,evidence=evidence)
                    if not error:s['observation']={**observation,'evidence':evidence,'observed_at':now}
                self._write(r,h,s,'read_failed'if error else'read_completed'if same else'read_superseded',self.key('result',job['id']),digest(canonical([job,error,evidence])),dict(capture_for_task=job['task_id'],adopted=same,error=error,evidence=evidence))
        finally:
            self.current=None;self.lock.release()

    def source(self,r,ref):
        with self.core.db()as db:row=db.execute('SELECT connection,payload,sha FROM live_snapshots WHERE id=?',(ref['snapshot_id'],)).fetchone()
        if not row or row[0]!=r['data']['connection_binding']or row[2]!=ref['sha256']or digest(row[1])!=ref['sha256']:raise ValueError('listing_release_integrity_failed')
        data=json.loads(row[1])
        if data['scope']['request_id']!=r['id']or data['scope']['sku']!=r['data']['frozen']['payload']['fields']['sku']:raise ValueError('listing_release_integrity_failed')
        return data

    def public(self,r,plan):
        d=r['data'];h=self.head(r);s=self.state(h);missing=[x['id']for x in d['frozen']['checks']if x['status']!='prepared']
        current=plan['preview_sha256']==d['preview_sha256'];read=s['read']
        if read['status']=='running'and(not self.current or self.current['id']!=read['id']):read={**read,'status':'interrupted','error':'listing_release_read_interrupted_no_automatic_retry'}
        observation=s['observation'];differences=[];import_record=None;product_record=None
        fresh=False
        if observation:
            try:fresh=0<=(datetime.now(timezone.utc)-datetime.fromisoformat(observation['observed_at'])).total_seconds()<=1800
            except (ValueError,TypeError):raise ValueError('listing_release_integrity_failed')from None
            for ref in observation['evidence']:
                data=self.source(r,ref)
                if data['scope']['task_id']!=observation['external_task_id']:raise ValueError('listing_release_integrity_failed')
                if data['endpoint']==IMPORT_PATH:import_record=data['projection']['record']
                elif data['endpoint']==PRODUCT_PATH:product_record=data['projection']['record']
            if product_record:
                differences=self.service.listing_reconciliation.differences(d['frozen']['payload']['fields'],{'status':'observed','matches':[product_record]})
        status='withdrawn'if s['decision']=='withdrawn'else'needs_changes'if s['decision']=='needs_changes'else'outdated'if not current else'blocked'if missing else'awaiting_execution_authority'
        with self.core.db()as db:rows=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=?AND kind=?ORDER BY created DESC,id DESC LIMIT 20',(d['target']['case_id'],self.event_kind(r['id']))).fetchall()
        history=[]
        for row in rows:
            item=self.intact(row);event=item['data'];history.append(dict(id=item['id'],sha256=item['sha256'],at=item['created_at'],action=event['action'],decision=event['state']['decision'],note=event['state']['note'],detail=event['detail']))
        return dict(id=r['id'],sha256=r['sha256'],event_sha256=h['sha256']if h else'',created_at=r['created_at'],target=d['target'],frozen=d['frozen'],note=d['note'],
            current=current,connection_current=self.binding(d['target'],d['synthetic'])==d['connection_binding'],missing=missing,status=status,decision=s['decision'],review_note=s['note'],
            external=s['external'],read=read,observation=observation,import_record=import_record,product_record=product_record,differences=differences,history=history,synthetic=d['synthetic'],
            last_observation_fresh=fresh,
            external_execution_allowed=False,platform_submission_verified=False,remote_cancel_performed=False,
            correlation_scope='external_task_offer_id_product_id_and_returned_fields_only_not_proof_of_submitted_frozen_payload')

    def get(self,case_id,platform,store_ref,market,request_id=None):
        plan=self.service.listings.get(case_id,platform,store_ref,market);target=plan['target']
        with self.core.db()as db:rows=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=?AND kind=?ORDER BY created DESC,id DESC LIMIT 10',(case_id,self.kind(target))).fetchall()
        requests=[self.intact(row)for row in rows];selected=self.request(request_id)if request_id else(requests[0]if requests else None)
        if selected and selected['data']['target']!=target:raise ValueError('listing_release_scope_mismatch')
        return dict(target=target,request=self.public(selected,plan)if selected else None,
            requests=[dict(id=r['id'],sha256=r['sha256'],created_at=r['created_at'],revision=r['data']['frozen']['revision'],current=r['data']['preview_sha256']==plan['preview_sha256'])for r in requests],
            current_preview_sha256=plan['preview_sha256'],export_formats=['json','html'],image_preview_supported=True,external_execution_allowed=False)

    def summary(self,target,plan):
        head=self.org.artifact(target['case_id'],self.kind(target))
        if not head:return None
        if not head['intact']:raise ValueError('listing_release_integrity_failed')
        r=self.request(head['id']);s=self.state(self.head(r));current=r['data']['preview_sha256']==plan['preview_sha256']
        read=s['read']['status']
        if read=='running'and(not self.current or self.current['id']!=s['read']['id']):read='interrupted'
        return dict(request_id=r['id'],current=current,decision=s['decision'],read_status=read,observation_status=s['observation']['status']if s['observation']else None,platform_submission_verified=False)

    def image(self,request_id,expected_request_sha256,index):
        from listing_review_media import read
        r=self.request(request_id)
        if r['sha256']!=expected_request_sha256:raise ValueError('listing_review_request_changed')
        return read(self,r,index)

    def export(self,request_id,expected_event_sha256,format='json'):
        if format not in ('json','html'):raise ValueError('listing_release_invalid_export_format')
        with self.live.config_lock,self.core.atomic():
            r=self.request(request_id);h=self.head(r);self.cas(h,expected_event_sha256)
            value=self.get(**r['data']['target'],request_id=request_id)
            package=dict(schema='commerce-private-listing-release-package-v1',request=value['request'],
                contains_private_business_data=True,platform_import_format=False,application_submission='not_performed_by_this_system',external_execution_allowed=False)
            if format=='html':
                from listing_review_report import render
                from listing_review_media import for_export
                return dict(filename='listing-application-'+request_id+'.html',content=render(package,for_export(self,r)),media_type='text/html')
            return dict(filename='listing-application-'+request_id+'.json',content=json.dumps(package,ensure_ascii=False,indent=2))

    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=1)
