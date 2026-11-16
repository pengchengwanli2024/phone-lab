"""Exact single-item publishing plans over original artifacts, release events and reads."""
from datetime import datetime,timezone
import json,re,threading,time,uuid
from decimal import Decimal
from research import canonical,digest
import ozon_reader
from listing_action_protocol import READ_PATH,gallery
from listing_release_reads import PRODUCT_PATH,identifier
from listing_submission_protocol import WRITE_PATH,ATTR_PATH,publication_issues,materialize,project_before
from ozon_product_writer import post_once,validate_wire

UNRESOLVED = ('checking','submitting','unknown','accepted')

def definitions(schema,string):
    event={'plan_id':string,'expected_event_sha256':{'type':'string'},'idempotency_key':string}
    return [
        ('commerce_listing_submission_get','只读准确申请的整卡提交准备、差异、未知结果和平台处理状态；不执行',schema({'request_id':string,'plan_id':string},['request_id'])),
        ('commerce_listing_submission_probe','明确只读核对准确SKU的当前商品/简单属性/图库并留存证据；不发布',schema({'request_id':string},['request_id'])),
        ('commerce_listing_submission_prepare','当前S6负责人核查通过后，冻结准确单商品导入/更新请求及平台前值；不提交',schema({'request_id':string,'expected_request_sha256':string,'expected_before_sha256':string,'idempotency_key':string},['request_id','expected_request_sha256','expected_before_sha256','idempotency_key'])),
        ('commerce_listing_submission_submit','仅在用户明确确认准确整卡请求后执行一次Ozon商品导入/更新（含价格和图片，不写库存）；未知不重发，必须另有用户授权',schema({**event,'expected_plan_sha256':string,'operator':{'type':'string','maxLength':160},'confirmed':{'type':'boolean'}},[*event,'expected_plan_sha256','operator','confirmed'])),
        ('commerce_listing_submission_finish','仅在用户于Ozon后台逐项核对未知提交的任务、商品、图片、属性、包装和税率后记录本人完成声明；不是传输回执、独立认证或再次执行',schema({**event,'expected_before_sha256':string,'expected_release_event_sha256':string,'operator':string,'source_ref':string,'note':string,'confirmed':{'type':'boolean'}},[*event,'expected_before_sha256','expected_release_event_sha256','operator','source_ref','note','confirmed'])),
        ('commerce_listing_submission_cancel','仅撤销尚未提交的本地整卡计划；不取消平台处理',schema(event,list(event))),
    ]

class ListingSubmissions:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.org=service.organization;self.live=service.live;self.releases=service.listing_releases
        self.reader=ozon_reader.post;self.writer=post_once;self.lock=threading.Lock();self.current=None;self.thread=None;self.stopping=threading.Event()
    def invoke(self,name,args):return getattr(self,name.removeprefix('commerce_listing_submission_'))(**args)
    @staticmethod
    def store(c):return digest(canonical(['ozon',c.get('ozon_client_id')]))
    def metadata(self,target,payload,synthetic):
        connection,error=self.service.listing_schema.context(target,synthetic)
        if error:return []
        category=payload['fields']['category_id'];typ=payload.get('ozon',{}).get('type_id',0)
        if not re.fullmatch('[1-9][0-9]{0,15}',category or '')or not typ:return []
        row=self.service.listing_schema.cache(connection,'attributes',int(category),typ)
        return row['data']['records']if row and row['fresh']else[]
    def check_payload(self,target,payload,synthetic):
        return publication_issues(payload,self.metadata(target,payload,synthetic))
    def context(self,r,ready=False,historical_read=False):
        c=self.releases.read_credentials(r)if historical_read else self.releases.credentials(r);plan=self.service.listings.get(**r['data']['target']);case=self.org.case(r['data']['target']['case_id'])
        if not historical_read and plan['preview_sha256']!=r['data']['preview_sha256']:raise ValueError('listing_release_request_outdated')
        if case['scope'].get('platform')!='ozon'or case['scope'].get('market')!='RU':raise ValueError('listing_submission_scope_mismatch')
        release_state=self.releases.state(self.releases.head(r));decision=release_state['decision']
        if ready and release_state['external']:raise ValueError('listing_submission_reference_present')
        if decision=='withdrawn'and not historical_read:raise ValueError('listing_release_withdrawn')
        if ready and decision!='acknowledged':raise ValueError('listing_submission_application_review_required')
        if ready:
            if plan['missing']:raise ValueError('listing_submission_checks_incomplete')
            owner=self.service.owner_reviews.get(**r['data']['target'])
            if not owner['current']or not all(v['ready']for v in owner['automatic_checks']):raise ValueError('listing_submission_owner_review_required')
        return c,plan,case
    @staticmethod
    def safe(exc):
        code=exc.code if isinstance(exc,ozon_reader.ConnectionIssue)else str(exc)
        return code if isinstance(exc,ValueError)and code.startswith(('listing_submission_','listing_release_','workspace_source_','ozon_'))else'listing_submission_failed'
    def snapshot(self,r):
        v=self.live.snapshot('submission:'+r['data']['connection_binding'],'before:'+r['id'])
        if v:
            if digest(canonical(v['data']))!=v['sha256']:raise ValueError('listing_submission_integrity')
            v['fresh']=self.live._fresh(v,self.live.config())
        return v
    def fetch(self,path,body,c,job):
        sha=None;error=None
        try:
            if self.service.listing_schema.connection(self.live.config())!=self.service.listing_schema.connection(c):raise ValueError('listing_release_connection_changed')
            raw,sha=self.reader(path,body,c['ozon_client_id'],c['ozon_api_key'])
            if type(sha)is not str or not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('listing_submission_response_schema')
            return raw,dict(endpoint=path,request_sha256=digest(canonical(body)),response_sha256=sha)
        except Exception as exc:error=self.safe(exc);raise
        finally:
            with self.core.db()as db:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at)VALUES(?,?,?,?,?,?)',(job,path,digest(canonical(body)),sha,error,datetime.now(timezone.utc).isoformat()))
    def capture(self,r,c,job):
        historical=self.has_dispatched(r['id']);_,_,case=self.context(r,historical_read=historical);sku=r['data']['frozen']['payload']['fields']['sku'];evidence=[]
        raw,e=self.fetch(PRODUCT_PATH,{'offer_id':[sku]},c,job);evidence.append(e)
        attrs=None;photos=None
        rows=raw.get('items')if type(raw)is dict else None
        if type(rows)is not list or len(rows)>1:raise ValueError('listing_submission_scope_mismatch')
        if rows:
            if rows[0].get('offer_id')!=sku:raise ValueError('listing_submission_scope_mismatch')
            pid=int(identifier(rows[0].get('id')))
            attrs,e=self.fetch(ATTR_PATH,{'filter':{'product_id':[str(pid)]},'limit':1},c,job);evidence.append(e)
            pictures,e=self.fetch(READ_PATH,{'product_id':[pid]},c,job);evidence.append(e);photos=gallery(pictures,str(pid))
        before=project_before(raw,attrs,sku,case['scope'].get('product_id'),photos)
        with self.live.config_lock,self.core.atomic()as db:
            self.context(r,historical_read=historical)
            if self.service.listing_schema.connection(self.live.config())!=self.service.listing_schema.connection(c):raise ValueError('listing_release_connection_changed')
            value=dict(capture_connection_binding=self.service.listing_schema.connection(c),before=before,before_sha256=digest(canonical(before)),evidence=evidence);encoded=canonical(value);ident=uuid.uuid4().hex;stamp=datetime.now(timezone.utc).isoformat();connection='submission:'+r['data']['connection_binding'];kind='before:'+r['id']
            db.execute('INSERT INTO live_snapshots VALUES(?,?,?,?,?,?)',(ident,connection,kind,encoded,digest(encoded),stamp));db.execute('INSERT OR REPLACE INTO live_latest VALUES(?,?,?)',(connection,kind,ident))
        return self.snapshot(r)
    def launch(self,r,kind,run,plan_id=None):
        if self.stopping.is_set():raise ValueError('listing_submission_stopped')
        if not self.lock.acquire(False):raise ValueError('listing_submission_busy')
        job=dict(id=uuid.uuid4().hex,request_id=r['id'],plan_id=plan_id,kind=kind,status='running');self.current=job
        def worker():
            try:run(job['id']);job['status']='succeeded'
            except Exception as exc:job.update(status='failed',error=self.safe(exc))
            finally:self.lock.release()
        self.thread=threading.Thread(target=worker,daemon=True,name='ozon-product-submission')
        try:self.thread.start()
        except Exception:self.lock.release();raise
        return dict(job)
    def probe(self,request_id):
        r=self.releases.request(request_id);c,_,_=self.context(r,historical_read=self.has_dispatched(request_id))
        return self.launch(r,'probe',lambda job:self.capture(r,c,job))
    def plan(self,ident):
        if type(ident)is not str or not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('listing_submission_not_found')
        with self.core.db()as db:row=db.execute("SELECT case_id,payload,sha,created FROM org_artifacts WHERE id=?AND kind='listing_submit_plan'",(ident,)).fetchone()
        if not row:raise ValueError('listing_submission_not_found')
        self.org.case(row[0]);data=json.loads(row[1])
        if digest(row[1])!=row[2]:raise ValueError('listing_submission_integrity')
        return dict(id=ident,case_id=row[0],data=data,sha256=row[2],created_at=row[3])
    def head(self,p):return self.org.artifact(p['case_id'],'listing_submit_event_'+p['id'])
    def state(self,p):
        h=self.head(p)
        if h and(not h['intact']or h['payload']['plan_sha256']!=p['sha256']):raise ValueError('listing_submission_integrity')
        state=json.loads(canonical(h['payload']['state']))if h else dict(status='draft',dispatch_started=False,operator='',task_id=None,error=None)
        if state['status']=='checking'and(not self.current or self.current.get('plan_id')!=p['id']or self.current['status']!='running'):state.update(status='interrupted_before_dispatch',error='listing_submission_interrupted_before_dispatch')
        if state['status']=='submitting'and(not self.current or self.current.get('plan_id')!=p['id']or self.current['status']!='running'):state.update(status='unknown',error='listing_submission_outcome_unknown')
        if state['status']=='accepted':
            r=self.releases.request(p['data']['request_id']);s=self.releases.state(self.releases.head(r));obs=s['observation']
            if obs and obs['external_task_id']==state['task_id']and s['read']['status']=='succeeded':
                if obs['import_confirmed']:state['status']='imported_needs_review'
                elif obs['status']=='import_rejected':state['status']='import_rejected'
        return state
    def event(self,p,expected,key,operation,updates):
        h=self.head(p)
        if(h['sha256']if h else'')!=expected:raise ValueError('listing_submission_conflict')
        state=self.state(p);state.update(updates);data=dict(plan_sha256=p['sha256'],previous_sha256=expected,operation=operation,state=state)
        return self.org._store(p['case_id'],'listing_submit_event_'+p['id'],data,key,_expected_head=h['id']if h else None)
    def duplicate(self,p,key,sig):
        with self.core.db()as db:row=db.execute('SELECT payload,sha FROM org_artifacts WHERE case_id=?AND kind=?AND idem=?',(p['case_id'],'listing_submit_event_'+p['id'],key)).fetchone()
        if not row:return False
        if digest(row[0])!=row[1]:raise ValueError('listing_submission_integrity')
        if json.loads(row[0])['operation']!=sig:raise ValueError('listing_submission_idempotency_conflict')
        return True
    def occupied_sku(self,c,sku,exclude=None,exclude_image_action=None,product_id=None):
        # A stale SKU label must not permit two writes to the same platform product.
        pid=str(product_id)if product_id is not None else''
        with self.core.db()as db:rows=db.execute("SELECT id FROM org_artifacts WHERE kind='listing_submit_plan'AND json_extract(payload,'$.store_identity')=?AND (json_extract(payload,'$.sku')=?OR (?!=''AND CAST(json_extract(payload,'$.before.product_id')AS TEXT)=?))",(self.store(c),sku,pid,pid)).fetchall()
        for(ident,)in rows:
            if ident==exclude:continue
            try:p=self.plan(ident)
            except ValueError as exc:
                if str(exc)=='organization_case_not_found':return True
                raise
            if self.state(p)['status']in UNRESOLVED:return True
        # A product import also changes the gallery. Do not race an unresolved gallery action.
        with self.core.db()as db:rows=db.execute("SELECT id FROM org_artifacts WHERE kind='listing_image_action'AND json_extract(payload,'$.store_identity')=?AND (json_extract(payload,'$.sku')=?OR (?!=''AND CAST(json_extract(payload,'$.product_id')AS TEXT)=?))",(self.store(c),sku,pid,pid)).fetchall()
        return any(ident!=exclude_image_action and self.service.listing_actions.state(self.service.listing_actions.action(ident))['status']in ('checking','submitting','awaiting_readback','unknown','verifying')for(ident,)in rows)
    def get(self,request_id,plan_id=None):
        r=self.releases.request(request_id);plan=self.service.listings.get(**r['data']['target']);issues=self.check_payload(r['data']['target'],r['data']['frozen']['payload'],r['data']['synthetic'])
        try:self.context(r,True);ready=True;blocked=None
        except ValueError as exc:ready=False;blocked=self.safe(exc)
        snap=self.snapshot(r);worker=self.current if self.current and self.current['request_id']==request_id else None
        if worker and worker['status']=='failed':ready=False;blocked=worker['error']
        if worker and worker['status']=='running':ready=False;blocked='listing_submission_busy'
        if not snap or not snap['fresh']:ready=False;blocked=blocked or'listing_submission_read_before_prepare'
        if issues:ready=False;blocked=blocked or'listing_submission_inputs_incomplete'
        if self.occupied_sku(self.live.config(),r['data']['frozen']['payload']['fields']['sku'],product_id=snap['data']['before'].get('product_id')if snap else None):ready=False;blocked=blocked or'listing_submission_other_outcome_unresolved'
        with self.core.db()as db:rows=db.execute("SELECT id FROM org_artifacts WHERE case_id=?AND kind='listing_submit_plan'AND json_extract(payload,'$.request_id')=?ORDER BY created DESC,id DESC",(r['data']['target']['case_id'],request_id)).fetchall()
        plans=[self.plan(ident)for(ident,)in rows]
        unresolved=[p for p in plans if self.state(p)['status']in UNRESOLVED]
        selected=self.plan(plan_id)if plan_id else unresolved[0]if unresolved else plans[0]if plans else None
        if selected and selected['data']['request_id']!=request_id:raise ValueError('listing_submission_scope_mismatch')
        # Recent drafts must never displace a plan that still needs recovery.
        history=[p['id']for p in plans[:10]]
        for p in [*unresolved,*([selected]if selected else[])]:
            if p['id']not in history:history.append(p['id'])
        item=None
        if selected:
            state=self.state(selected);head=self.head(selected);fresh=0<=time.time()-datetime.fromisoformat(selected['created_at']).timestamp()<=1800
            item=dict(id=selected['id'],sha256=selected['sha256'],event_sha256=head['sha256']if head else'',**selected['data'],state=state,fresh=fresh,can_submit=ready and fresh and snap['data']['before_sha256']==selected['data']['before_sha256']and state['status']in ('draft','interrupted_before_dispatch','failed_before_dispatch')and not self.occupied_sku(self.live.config(),selected['data']['sku'],selected['id'],product_id=selected['data']['before'].get('product_id')))
        release_head=self.releases.head(r);release_state=self.releases.state(release_head);obs=release_state['observation']
        readback_ready=bool(obs and obs['import_confirmed']and release_state['read']['status']=='succeeded'and 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(obs['observed_at'])).total_seconds()<=1800)
        return dict(release_event_sha256=release_head['sha256']if release_head else'',import_readback_confirmed=readback_ready,request_id=request_id,request_sha256=r['sha256'],current=plan['preview_sha256']==r['data']['preview_sha256'],issues=issues,blocked_reason=blocked,ready_to_prepare=ready,before=dict(sha256=snap['sha256'],observed_at=snap['observed_at'],fresh=snap['fresh'],**snap['data'])if snap else None,plan=item,history=[dict(id=ident)for ident in history],worker=worker,external_execution_allowed=False,scope='single_item_product_import_no_stock_write',independent_certification=False)
    def prepare(self,request_id,expected_request_sha256,expected_before_sha256,idempotency_key):
        key='prepare:'+self.releases.key('submit-plan',idempotency_key);r=self.releases.request(request_id)
        with self.live.config_lock,self.core.atomic()as db:
            c,_,_=self.context(r,True)
            if r['sha256']!=expected_request_sha256:raise ValueError('listing_submission_request_changed')
            view=self.get(request_id)
            if not view['ready_to_prepare']:raise ValueError(view['blocked_reason']or'listing_submission_not_ready')
            snap=self.snapshot(r)
            if snap['sha256']!=expected_before_sha256:raise ValueError('listing_submission_before_changed')
            payload=r['data']['frozen']['payload'];body=materialize(payload,self.metadata(r['data']['target'],payload,False),snap['data']['before'])
            data=dict(request_id=r['id'],request_sha256=r['sha256'],sku=payload['fields']['sku'],store_identity=self.store(c),connection_binding=r['data']['connection_binding'],body=body,body_sha256=digest(canonical(body)),before=snap['data']['before'],before_sha256=snap['data']['before_sha256'],before_snapshot_sha256=snap['sha256'])
            validate_wire(body)
            prior=db.execute("SELECT id,payload FROM org_artifacts WHERE case_id=?AND kind='listing_submit_plan'AND idem=?",(r['data']['target']['case_id'],key)).fetchone()
            if prior:
                if json.loads(prior[1])!=data:raise ValueError('listing_submission_idempotency_conflict')
                return self.get(request_id,prior[0])
            value=self.org._store(r['data']['target']['case_id'],'listing_submit_plan',data,key)
        return self.get(request_id,value['id'])
    def submit(self,plan_id,expected_event_sha256,idempotency_key,expected_plan_sha256,operator,confirmed):
        if confirmed is not True or type(operator)is not str or not operator.strip()or len(operator)>160:raise ValueError('listing_submission_confirmation_required')
        p=self.plan(plan_id);key='submit:'+self.releases.key('submit',idempotency_key);sig=digest(canonical([expected_plan_sha256,operator,confirmed]))
        with self.live.config_lock,self.core.atomic():
            if self.duplicate(p,key,sig):return self.get(p['data']['request_id'],plan_id)
            r=self.releases.request(p['data']['request_id']);c,_,_=self.context(r,True);view=self.get(r['id'],plan_id)
            if p['sha256']!=expected_plan_sha256:raise ValueError('listing_submission_plan_changed')
            if not view['plan']['can_submit']:raise ValueError('listing_submission_not_ready')
            if self.lock.locked()or self.releases.lock.locked()or self.releases.state(self.releases.head(r))['external']:raise ValueError('listing_submission_busy_or_reference_present')
            self.event(p,expected_event_sha256,key,sig,dict(status='checking',operator=operator.strip(),error=None))
        self.launch(r,'submit',lambda job:self.dispatch(p,r,c,job),p['id'])
        return self.get(r['id'],p['id'])
    def dispatch(self,p,r,c,job):
        response_sha=None;error=None;started=False;task=None
        try:
            snap=self.capture(r,c,job)
            if snap['data']['before_sha256']!=p['data']['before_sha256']:raise ValueError('listing_submission_before_changed')
            with self.live.config_lock,self.core.atomic():
                self.context(r,True);head=self.head(p);state=self.state(p)
                if not 0<=time.time()-datetime.fromisoformat(p['created_at']).timestamp()<=1800:raise ValueError('listing_submission_plan_expired')
                if state['status']!='checking'or self.stopping.is_set():raise ValueError('listing_submission_cancelled_before_dispatch')
                if self.occupied_sku(c,p['data']['sku'],p['id'],product_id=p['data']['before'].get('product_id')):raise ValueError('listing_submission_other_outcome_unresolved')
                if self.releases.state(self.releases.head(r))['external']:raise ValueError('listing_submission_reference_present')
                self.event(p,head['sha256'],'dispatch:'+job,'dispatch_intent',dict(status='submitting',dispatch_started=True));started=True
            with self.live.config_lock:
                self.releases.credentials(r)
                raw,response_sha=self.writer(p['data']['body'],c['ozon_client_id'],c['ozon_api_key'])
            if type(response_sha)is not str or not re.fullmatch('[a-f0-9]{64}',response_sha):raise ValueError('listing_submission_response_schema')
            task=identifier(raw.get('result',{}).get('task_id'))
        except Exception as exc:error=self.safe(exc)
        with self.live.config_lock,self.core.atomic()as db:
            head=self.head(p);state=self.state(p)
            if state['status']=='cancelled':return
            before_write=error=='ozon_connect_failed_before_write'
            status='failed_before_dispatch'if before_write or not started else'unknown'if error else'accepted'
            self.event(p,head['sha256'],'result:'+job,'submission_result',dict(status=status,dispatch_started=started and not before_write,task_id=task,error=error,response_sha256=response_sha))
            if started:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at)VALUES(?,?,?,?,?,?)',(job,WRITE_PATH,p['data']['body_sha256'],response_sha,error,datetime.now(timezone.utc).isoformat()))
            if task and not error:
                h=self.releases.head(r);s=self.releases.state(h);s['external']=dict(task_id=task,source_ref='submission-plan:'+p['id'],origin='system_explicit_single_submission',body_sha256=p['data']['body_sha256']);s['observation']=None;s['read']=dict(status='not_requested',error=None)
                self.releases._write(r,h,s,'system_submission_received','system-submit:'+p['id'],p['sha256'],dict(plan_id=p['id'],body_sha256=p['data']['body_sha256'],response_sha256=response_sha))
        if error:raise ValueError(error)
    def cancel(self,plan_id,expected_event_sha256,idempotency_key):
        p=self.plan(plan_id);key='cancel:'+self.releases.key('cancel',idempotency_key)
        with self.core.atomic():
            if self.duplicate(p,key,'cancel'):return self.get(p['data']['request_id'],plan_id)
            if self.state(p)['dispatch_started']:raise ValueError('listing_submission_cannot_cancel_remote')
            self.event(p,expected_event_sha256,key,'cancel',dict(status='cancelled'))
        return self.get(p['data']['request_id'],plan_id)
    def finish(self,plan_id,expected_event_sha256,idempotency_key,expected_before_sha256,expected_release_event_sha256,operator,source_ref,note,confirmed):
        if confirmed is not True or type(operator)is not str or len(operator)>160 or any(type(v)is not str or not v.strip()or len(v)>1500 for v in (operator,source_ref,note)):raise ValueError('listing_submission_confirmation_required')
        p=self.plan(plan_id);r=self.releases.request(p['data']['request_id']);key='finish:'+self.releases.key('finish',idempotency_key);sig=digest(canonical([expected_before_sha256,expected_release_event_sha256,operator,source_ref,note,confirmed]))
        with self.live.config_lock,self.core.atomic():
            if self.duplicate(p,key,sig):return self.get(r['id'],p['id'])
            c=self.releases.read_credentials(r);state=self.state(p);snap=self.snapshot(r);h=self.releases.head(r)
            if self.store(c)!=p['data']['store_identity']or state['status']!='unknown'or not state['dispatch_started']:raise ValueError('listing_submission_resolution_closed')
            if self.lock.locked()or self.releases.lock.locked():raise ValueError('listing_submission_busy')
            if not snap or not snap['fresh']or snap['sha256']!=expected_before_sha256:raise ValueError('listing_submission_before_changed')
            if(h['sha256']if h else'')!=expected_release_event_sha256:raise ValueError('listing_submission_conflict')
            observed=self.releases.get(**r['data']['target'],request_id=r['id'])['request'];current=snap['data']['before'];item=p['data']['body']['items'][0]
            if not observed['observation']or not observed['observation']['import_confirmed']or not observed['last_observation_fresh']or observed['read']['status']!='succeeded'or current['kind']!='existing':raise ValueError('listing_submission_fresh_import_proof_required')
            if not observed['product_record']or observed['product_record']['entity_id']!=current['product_id']:raise ValueError('listing_submission_scope_mismatch')
            if p['data']['before'].get('product_id')and current['product_id']!=p['data']['before']['product_id']:raise ValueError('listing_submission_scope_mismatch')
            if current['name']!=item['name']or current['currency_code']!=item['currency_code']or Decimal(current['price']or'-1')!=Decimal(item['price']):raise ValueError('listing_submission_result_differs')
            if current['category_id']!=item['description_category_id']or current['type_id']!=r['data']['frozen']['payload']['ozon']['type_id']or current['special_media']or len(current['images'])!=len(item['images']):raise ValueError('listing_submission_result_differs')
            for k in ('depth','width','height','weight','dimension_unit','weight_unit'):
                if current.get(k)!=item[k]:raise ValueError('listing_submission_result_differs')
            def values(rows):return {a['id']:[v['dictionary_value_id']if v['dictionary_value_id']else v['value']for v in a['values']]for a in rows}
            if values(current['attributes'])!=values(item['attributes']):raise ValueError('listing_submission_result_differs')
            self.event(p,expected_event_sha256,key,sig,dict(status='owner_confirmed',operator=operator.strip(),task_id=observed['external']['task_id'],completion_basis='owner_platform_attestation_not_transport_proof',source_ref=source_ref.strip(),note=note.strip(),observation_sha256=snap['sha256']))
        return self.get(r['id'],p['id'])
    def summary(self,request_id):
        with self.core.db()as db:ids=[r[0]for r in db.execute("SELECT id FROM org_artifacts WHERE kind='listing_submit_plan'AND json_extract(payload,'$.request_id')=?ORDER BY created DESC,id DESC",(request_id,))]
        if not ids:return None
        plans=[self.plan(ident)for ident in ids];chosen=next((p for p in plans if self.state(p)['dispatch_started']),plans[0]);h=self.head(chosen)
        return dict(plan_id=chosen['id'],plan_sha256=chosen['sha256'],event_sha256=h['sha256']if h else'',state=self.state(chosen),**chosen['data'])
    def has_dispatched(self,request_id):
        with self.core.db()as db:ids=[r[0]for r in db.execute("SELECT id FROM org_artifacts WHERE kind='listing_submit_plan'AND json_extract(payload,'$.request_id')=?",(request_id,))]
        return any(self.state(self.plan(ident))['dispatch_started']for ident in ids)
    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=1)
