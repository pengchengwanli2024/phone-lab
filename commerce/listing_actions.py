"""Scoped owner-reviewed image actions on original artifacts/snapshots.

An owner attestation is not independent compliance. It can authorize only this
frozen gallery change, never a whole listing, price, stock or other operation.
"""
from datetime import datetime,timezone
import json
import re
import threading
import time
import uuid
from research import canonical,digest
from listing_action_protocol import CHECKS,READ_PATH,WRITE_PATH,images,gallery,checklist,text
from ozon_image_writer import post_once
import ozon_reader

ACTIVE={'checking','submitting','awaiting_readback','unknown','verifying'}

def definitions(schema,string):
    selected={'case_id':string};event={'action_id':string,'expected_event_sha256':{'type':'string'},'idempotency_key':string}
    return [
        ('commerce_listing_action_get','只读准确现有商品图库、人工图片变更审核和一次执行状态；可指定历史动作，不批准或提交',schema({**selected,'action_id':string},['case_id'])),
        ('commerce_listing_action_directory','只读当前店铺的图片动作与恢复入口；分页保留未知和历史状态，不回读或重放提交',schema({'demo':{'type':'boolean'},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':50}})),
        ('commerce_listing_action_refresh','明确只读获取当前商品图库；不改店铺',schema(selected,['case_id'])),
        ('commerce_listing_action_prepare','固定现有商品标准图库前后数组与来源版本，生成待核对动作；不改价库存或创建商品',schema({**selected,'expected_source_sha256':string,'expected_gallery_sha256':string,'image_urls':{'type':'array','items':string,'minItems':1,'maxItems':20},'idempotency_key':string},[*selected,'expected_source_sha256','expected_gallery_sha256','image_urls','idempotency_key'])),
        ('commerce_listing_action_review','按准确图片变更版本记录操作者核对/退回；owner_manual仅是本人本次声明，不是独立专业认证，批准必须来自用户明确核对',schema({**event,'checks':{'type':'object'},'decision':{'type':'string','enum':['save','approved','rejected']},'reviewer':{'type':'string','maxLength':160},'review_mode':{'type':'string','enum':['','owner_manual']},'confirmed':{'type':'boolean'}},[*event,'checks','decision','reviewer','review_mode','confirmed'])),
        ('commerce_listing_action_submit','只在用户明确批准准确商品和整组图片后执行一次Ozon图库替换；会修改真实店铺，未知不重发，不更改价库存或原S6',schema({**event,'expected_action_sha256':string,'confirmed':{'type':'boolean'}},[*event,'expected_action_sha256','confirmed'])),
        ('commerce_listing_action_readback','明确只读核对已尝试图片动作的实际图库；不重发提交',schema(event,list(event))),
        ('commerce_listing_action_image','只读预览该动作已回读的准确图库图片，绑定观测哈希；不接受任意网址',schema({'action_id':string,'expected_observation_sha256':string,'index':{'type':'integer','minimum':0,'maximum':19}},['action_id','expected_observation_sha256','index'])),
        ('commerce_listing_action_finish','仅在用户逐图核对平台转存后的图片及顺序后记录人工完成声明；不冒充地址精确匹配、独立合规或整卡发布',schema({**event,'expected_observation_sha256':string,'note':{'type':'string','maxLength':1000},'confirmed':{'type':'boolean'}},[*event,'expected_observation_sha256','note','confirmed'])),
        ('commerce_listing_action_cancel','仅撤销尚未提交的本地图片动作；提交后不宣称取消远端',schema(event,list(event))),
    ]

class ListingActions:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.org=service.organization;self.live=service.live
        self.reader=ozon_reader.post;self.writer=post_once;self.lock=threading.Lock();self.thread=None;self.current=None;self.stopping=threading.Event()
    def invoke(self,name,args):return getattr(self,name.removeprefix('commerce_listing_action_'))(**args)
    @staticmethod
    def binding(c):return digest(canonical([c.get('connection_id'),c.get('ozon_client_id'),c.get('ozon_api_key')]))
    @staticmethod
    def store_identity(c):return digest(canonical(['ozon',c.get('ozon_client_id')]))
    def context(self,case_id):
        case=self.org.case(case_id);s=case['scope'];c=self.live.config()
        if s.get('synthetic')or s.get('platform')!='ozon'or s.get('market')!='RU'or not s.get('product_id')or s.get('origin')!='inventory_scope_not_independently_verified':raise ValueError('listing_action_real_existing_product_required')
        if not c.get('ozon_client_id')or not c.get('ozon_api_key'):raise ValueError('configure_ozon_first')
        return case,c
    def owned_inventory(self,case,c):
        snap=self.live.snapshot(c.get('connection_id',''),'stock')
        if not snap or not self.live._fresh(snap,c):raise ValueError('listing_action_fresh_inventory_required')
        if digest(canonical(snap['data']))!=snap['sha256']:raise ValueError('listing_action_integrity')
        scope=case['scope'];rows=[r for r in snap['data']['records']if r['product_id']==scope['product_id']and r['offer_id']==scope['sku']]
        if len(rows)!=1 or not any(s['type']==scope.get('inventory_type')for s in rows[0]['stocks']):raise ValueError('listing_action_inventory_scope_changed')
    def snapshot(self,case_id):
        case,c=self.context(case_id);value=self.live.snapshot('image-action:'+self.binding(c),'gallery:'+case['scope']['product_id'])
        if value:
            if digest(canonical(value['data']))!=value['sha256']:raise ValueError('listing_action_integrity')
            value['fresh']=self.live._fresh(value,c)
        return value
    def _read(self,case_id,config,job):
        case=self.org.case(case_id);pid=case['scope']['product_id'];body={'product_id':[int(pid)]};sha=None;error=None
        try:
            if self.binding(self.live.config())!=self.binding(config):raise ValueError('listing_action_connection_changed')
            raw,sha=self.reader(READ_PATH,body,config['ozon_client_id'],config['ozon_api_key']);value=gallery(raw,pid)
            if type(sha)is not str or not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('listing_action_response_schema')
            value['evidence']=dict(endpoint=READ_PATH,request_sha256=digest(canonical(body)),response_sha256=sha)
            with self.live.config_lock,self.core.atomic():
                if self.binding(self.live.config())!=self.binding(config):raise ValueError('listing_action_connection_changed')
                self.org.case(case_id);encoded=canonical(value);now=datetime.now(timezone.utc).isoformat();ident=uuid.uuid4().hex;connection='image-action:'+self.binding(config);kind='gallery:'+pid
                with self.core.db()as db:
                    db.execute('INSERT INTO live_snapshots VALUES (?,?,?,?,?,?)',(ident,connection,kind,encoded,digest(encoded),now))
                    db.execute('INSERT OR REPLACE INTO live_latest VALUES (?,?,?)',(connection,kind,ident))
            return self.snapshot(case_id)
        except Exception as exc:error=self.safe(exc);raise ValueError(error)from None
        finally:
            with self.core.db()as db:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at)VALUES(?,?,?,?,?,?)',(job,READ_PATH,digest(canonical(body)),sha,error,datetime.now(timezone.utc).isoformat()))
    @staticmethod
    def safe(exc):
        code=exc.code if isinstance(exc,ozon_reader.ConnectionIssue)else str(exc)
        return code if isinstance(exc,ValueError)and code.startswith(('listing_action_','ozon_'))else'listing_action_failed'
    def _launch(self,case_id,kind,run):
        if self.stopping.is_set():raise ValueError('listing_action_stopped')
        if not self.lock.acquire(False):raise ValueError('listing_action_busy')
        self.current={'id':uuid.uuid4().hex,'case_id':case_id,'kind':kind,'status':'running'}
        def worker():
            try:run(self.current['id']);self.current['status']='succeeded'
            except Exception as exc:self.current.update(status='failed',error=self.safe(exc))
            finally:self.lock.release()
        self.thread=threading.Thread(target=worker,daemon=True,name='ozon-image-action')
        try:self.thread.start()
        except Exception:self.lock.release();raise
        return dict(self.current)
    def refresh(self,case_id):
        _,c=self.context(case_id)
        return self._launch(case_id,'read',lambda job:self._read(case_id,c,job))
    def action(self,ident):
        if type(ident)is not str or len(ident)!=32:raise ValueError('listing_action_not_found')
        with self.core.db()as db:row=db.execute("SELECT case_id,payload,sha,created FROM org_artifacts WHERE id=?AND kind='listing_image_action'",(ident,)).fetchone()
        if not row:raise ValueError('listing_action_not_found')
        self.org.case(row[0]);d=json.loads(row[1])
        if digest(canonical(d))!=row[2]:raise ValueError('listing_action_integrity')
        return dict(id=ident,case_id=row[0],data=d,sha256=row[2],created_at=row[3])
    def head(self,a):return self.org.artifact(a['case_id'],'listing_image_event_'+a['id'])
    def state(self,a,h=None):
        h=h or self.head(a)
        if h and(not h['intact']or h['payload']['action_sha256']!=a['sha256']):raise ValueError('listing_action_integrity')
        state=h['payload']['state']if h else dict(status='draft',checks={k:dict(status='pending',source_ref='',note='')for k in CHECKS},reviewer='',review_mode='',approved_at=None,dispatch_started=False,observation=None)
        state=json.loads(canonical(state))
        if state['status']in ('checking','verifying','submitting')and(not self.current or self.current.get('action_id')!=a['id']or self.current['status']!='running'):
            state['status']='unknown'if state['dispatch_started']else'approved'if state['approved_at']else'draft'
        return state
    def _event(self,a,expected,key,operation,update):
        h=self.head(a)
        if(h['sha256']if h else'')!=expected:raise ValueError('listing_action_conflict')
        state=self.state(a,h);state.update(update)
        d=dict(action_sha256=a['sha256'],previous_sha256=expected,operation=operation,state=state)
        return self.org._store(a['case_id'],'listing_image_event_'+a['id'],d,key,_expected_head=h['id']if h else None)
    def _once(self,a,key,sig):
        with self.core.db()as db:row=db.execute("SELECT id,payload,sha FROM org_artifacts WHERE case_id=?AND kind=?AND idem=?",(a['case_id'],'listing_image_event_'+a['id'],key)).fetchone()
        if not row:return False
        if digest(row[1])!=row[2]:raise ValueError('listing_action_integrity')
        if json.loads(row[1])['operation']!=sig:raise ValueError('listing_action_idempotency_conflict')
        return True
    def _current(self,a,require_inventory=False):
        case,c=self.context(a['case_id']);d=a['data']
        if self.binding(c)!=d['connection_binding']:raise ValueError('listing_action_connection_changed')
        self.service.product_workspace.guard(a['case_id'],d['source_sha256'])
        if case['scope']['product_id']!=d['product_id']or case['scope']['sku']!=d['sku']:raise ValueError('listing_action_scope_changed')
        if require_inventory:self.owned_inventory(case,c)
        return c
    def item(self,a):
        h=self.head(a);state=self.state(a,h)
        try:self._current(a);current=True
        except ValueError:current=False
        return dict(id=a['id'],sha256=a['sha256'],event_sha256=h['sha256']if h else'',created_at=a['created_at'],**a['data'],state=state,current=current,approval_fresh=bool(state['approved_at']and 0<=time.time()-state['approved_at']<1800))
    def directory(self,demo=False,offset=0,limit=25):
        if type(demo)is not bool or type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=50:raise ValueError('listing_action_invalid_page')
        c=self.live.config();configured=bool(c.get('ozon_client_id')and c.get('ozon_api_key'))
        if demo or not configured:return dict(items=[],total=0,offset=offset,next_offset=None,complete=demo,configured=configured if not demo else False,status='demo_no_shop_read'if demo else'not_configured',external_execution_allowed=False)
        query=" FROM org_artifacts a JOIN org_cases c ON c.id=a.case_id WHERE a.kind='listing_image_action'AND json_extract(a.payload,'$.store_identity')=?AND c.connection=?AND COALESCE(json_extract(c.scope,'$.synthetic'),0)=0"
        params=(self.store_identity(c),c.get('connection_id',''))
        with self.core.db()as db:
            total=db.execute('SELECT count(*)'+query,params).fetchone()[0]
            ids=[r[0]for r in db.execute('SELECT a.id'+query+' ORDER BY a.created DESC,a.id DESC LIMIT ? OFFSET ?',(*params,limit,offset))]
        items=[]
        for ident in ids:
            a=self.action(ident);case,_=self.context(a['case_id']);v=self.item(a)
            items.append(dict(id=ident,target=dict(case_id=a['case_id'],platform='ozon',store_ref='ozon-live',market='RU'),name=case['scope'].get('label')or a['data']['sku'],sku=a['data']['sku'],created_at=a['created_at'],status=v['state']['status'],current=v['current'],approval_fresh=v['approval_fresh'],requires_readback=v['state']['status']in ACTIVE))
        return dict(items=items,total=total,offset=offset,next_offset=offset+limit if offset+limit<total else None,complete=offset==0 and len(items)==total,configured=True,status='available',external_execution_allowed=False)
    def get(self,case_id,action_id=None):
        case,c=self.context(case_id);snap=self.snapshot(case_id);items=[]
        selected=self.action(action_id)if action_id is not None else None
        if selected and(selected['case_id']!=case_id or selected['data']['store_identity']!=self.store_identity(c)):raise ValueError('listing_action_scope_changed')
        try:self.owned_inventory(case,c);inventory_current=True
        except ValueError:inventory_current=False
        with self.core.db()as db:ids=[r[0]for r in db.execute("SELECT id FROM org_artifacts WHERE case_id=?AND kind='listing_image_action'ORDER BY created DESC,id DESC LIMIT 10",(case_id,))]
        if selected and action_id not in ids:ids.append(action_id)
        for ident in ids:items.append(self.item(selected if selected and ident==action_id else self.action(ident)))
        return dict(case_id=case_id,source_sha256=self.service.product_workspace.sources(case_id)[3],inventory_current=inventory_current,gallery=dict(sha256=snap['sha256'],observed_at=snap['observed_at'],fresh=snap['fresh'],**snap['data'])if snap else None,
            requirements=CHECKS,items=items,selected_action_id=action_id or(ids[0]if ids else''),refresh=self.current if self.current and self.current['case_id']==case_id else None,
            scope='existing_standard_gallery_only',independent_professional_approval=False,whole_listing_submission=False)
    def prepare(self,case_id,expected_source_sha256,expected_gallery_sha256,image_urls,idempotency_key):
        new=images(image_urls);key='prepare:'+text(idempotency_key);case,c=self.context(case_id)
        with self.live.config_lock,self.core.atomic():
            self.owned_inventory(case,c)
            self.service.product_workspace.guard(case_id,expected_source_sha256);snap=self.snapshot(case_id)
            if not snap or not snap['fresh']or not snap['data'].get('evidence'):raise ValueError('listing_action_read_gallery_first')
            if snap['sha256']!=expected_gallery_sha256:raise ValueError('listing_action_gallery_changed')
            if snap['data']['special_images']or snap['data']['errors_present']:raise ValueError('listing_action_nonstandard_gallery')
            if new==snap['data']['images']:raise ValueError('listing_action_no_change')
            d=dict(schema='commerce-image-action-v1',product_id=case['scope']['product_id'],sku=case['scope']['sku'],before_images=snap['data']['images'],after_images=new,
                source_sha256=expected_source_sha256,gallery_sha256=expected_gallery_sha256,connection_binding=self.binding(c),store_identity=self.store_identity(c))
            return self.org._store(case_id,'listing_image_action',d,key)
    def review(self,action_id,expected_event_sha256,idempotency_key,checks,decision,reviewer,review_mode,confirmed):
        checked=checklist(checks);a=self.action(action_id);key='review:'+text(idempotency_key)
        if decision not in ('save','approved','rejected')or review_mode not in ('','owner_manual'):raise ValueError('listing_action_review_mode')
        if type(reviewer)is not str or len(reviewer)>160:raise ValueError('listing_action_invalid_input')
        sig=digest(canonical([checked,decision,reviewer,review_mode,confirmed]))
        with self.live.config_lock,self.core.atomic():
            if self._once(a,key,sig):return self.get(a['case_id'])
            state=self.state(a)
            if state['dispatch_started']or state['status']in ('checking','cancelled'):raise ValueError('listing_action_review_closed')
            self._current(a)
            if decision!='save'and confirmed is not True:raise ValueError('listing_action_confirmation_required')
            if decision=='approved'and(review_mode!='owner_manual'or not text(reviewer)or any(v['status']!='confirmed'for v in checked.values())):raise ValueError('listing_action_review_incomplete')
            self._event(a,expected_event_sha256,key,sig,dict(status='approved'if decision=='approved'else'rejected'if decision=='rejected'else'draft',checks=checked,reviewer=reviewer,review_mode=review_mode,approved_at=time.time()if decision=='approved'else None,error=None))
        return self.get(a['case_id'])
    def occupied(self,a):
        with self.core.db()as db:ids=[r[0]for r in db.execute("SELECT id FROM org_artifacts WHERE kind='listing_image_action'AND json_extract(payload,'$.product_id')=?AND json_extract(payload,'$.store_identity')=?",(a['data']['product_id'],a['data']['store_identity']))]
        return any(i!=a['id']and self.state(self.action(i))['status']in ACTIVE for i in ids)
    def submit(self,action_id,expected_event_sha256,idempotency_key,expected_action_sha256,confirmed):
        a=self.action(action_id);key='submit:'+text(idempotency_key);sig=digest(canonical([expected_action_sha256,confirmed]))
        with self.live.config_lock,self.core.atomic():
            if self._once(a,key,sig):return self.get(a['case_id'])
            c=self._current(a,True);state=self.state(a)
            if confirmed is not True or a['sha256']!=expected_action_sha256:raise ValueError('listing_action_confirmation_required')
            if state['status']!='approved'or state['dispatch_started']or not state['approved_at']or not 0<=time.time()-state['approved_at']<1800:raise ValueError('listing_action_approval_required')
            if self.occupied(a):raise ValueError('listing_action_other_outcome_unresolved')
            if self.service.listing_submissions.occupied_sku(c,a['data']['sku'],product_id=a['data']['product_id']):raise ValueError('listing_action_other_outcome_unresolved')
            if self.lock.locked():raise ValueError('listing_action_busy')
            event=self._event(a,expected_event_sha256,key,sig,dict(status='checking',error=None))
        try:
            job=self._launch(a['case_id'],'submit',lambda job:self._submit(a,c,event['sha256'],job))
            self.current['action_id']=a['id']
        except Exception:
            # No dispatch was attempted; an approved record remains explicitly resumable.
            raise
        return self.get(a['case_id'])
    def _submit(self,a,c,expected,job):
        self.current['action_id']=a['id'];started=False;receipt_sha=None;error=None
        try:
            snap=self._read(a['case_id'],c,job)
            if snap['data']['images']!=a['data']['before_images']or snap['data']['special_images']or snap['data']['errors_present']:raise ValueError('listing_action_gallery_changed')
            with self.live.config_lock,self.core.atomic():
                self._current(a,True)
                if self.stopping.is_set():raise ValueError('listing_action_stopped')
                state=self.state(a)
                if not state['approved_at']or not 0<=time.time()-state['approved_at']<1800:raise ValueError('listing_action_approval_required')
                # The whole-card worker may have started after submit's first check.
                if self.service.listing_submissions.occupied_sku(c,a['data']['sku'],exclude_image_action=a['id'],product_id=a['data']['product_id']):raise ValueError('listing_action_other_outcome_unresolved')
                intent=self._event(a,expected,'intent:'+job,'dispatch_intent',dict(status='submitting',dispatch_started=True))
            started=True
            raw,receipt_sha=self.writer({'product_id':int(a['data']['product_id']),'images':a['data']['after_images']},c['ozon_client_id'],c['ozon_api_key'])
            if type(raw)is not dict or type(receipt_sha)is not str or not re.fullmatch('[a-f0-9]{64}',receipt_sha):raise ValueError('listing_action_response_schema')
            with self.core.atomic():self._event(a,intent['sha256'],'returned:'+job,'http_response_not_completion',dict(status='awaiting_readback',receipt_sha256=receipt_sha))
        except Exception as exc:
            error=self.safe(exc)
            with self.core.atomic():
                h=self.head(a)
                if not started and self.state(a,h)['status']=='cancelled':return
                self._event(a,h['sha256']if h else'','failed:'+job,'dispatch_unknown'if started else'preflight_failed',dict(status='unknown'if started else'conflict',error=error))
            raise
        finally:
            if started:
                with self.core.db()as db:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at)VALUES(?,?,?,?,?,?)',(job,WRITE_PATH,digest(canonical({'product_id':a['data']['product_id'],'images':a['data']['after_images']})),receipt_sha,error,datetime.now(timezone.utc).isoformat()))
    def readback(self,action_id,expected_event_sha256,idempotency_key):
        a=self.action(action_id);key='readback:'+text(idempotency_key);sig='readback'
        with self.live.config_lock,self.core.atomic():
            if self._once(a,key,sig):return self.get(a['case_id'])
            # Preserve outcome visibility if product facts change after dispatch.
            case,c=self.context(a['case_id'])
            if case['scope']['product_id']!=a['data']['product_id']:raise ValueError('listing_action_scope_changed')
            if self.store_identity(c)!=a['data']['store_identity']:raise ValueError('listing_action_connection_changed')
            s=self.state(a)
            if not s['dispatch_started']:raise ValueError('listing_action_not_submitted')
            if s['status']in ('observed','owner_confirmed'):raise ValueError('listing_action_terminal_use_current_gallery')
            if self.lock.locked():raise ValueError('listing_action_busy')
            event=self._event(a,expected_event_sha256,key,sig,dict(status='verifying',error=None))
        def read(job):
            self.current['action_id']=a['id']
            try:
                snap=self._read(a['case_id'],c,job);data=snap['data'];exact=data['images']==a['data']['after_images']and not data['errors_present']and not data['special_images']
                update=dict(status='observed'if exact else'unknown',error=None,observation=dict(sha256=snap['sha256'],observed_at=snap['observed_at'],images=data['images'],exact_images=exact,errors_present=data['errors_present']))
            except Exception as exc:update=dict(status='unknown',error=self.safe(exc))
            with self.core.atomic():self._event(a,event['sha256'],'read-result:'+job,'readback_observed',update)
            if update.get('error'):raise ValueError(update['error'])
        self._launch(a['case_id'],'readback',read);self.current['action_id']=a['id'];return self.get(a['case_id'])
    def cancel(self,action_id,expected_event_sha256,idempotency_key):
        a=self.action(action_id);key='cancel:'+text(idempotency_key)
        with self.core.atomic():
            if self._once(a,key,'cancel'):return self.get(a['case_id'])
            if self.state(a)['dispatch_started']:raise ValueError('listing_action_cannot_cancel_remote')
            self._event(a,expected_event_sha256,key,'cancel',dict(status='cancelled'))
        return self.get(a['case_id'])
    def image(self,action_id,expected_observation_sha256,index):
        from catalog_media import preview
        a=self.action(action_id);state=self.state(a);observed=state.get('observation')
        if not observed or observed['sha256']!=expected_observation_sha256:raise ValueError('listing_action_observation_changed')
        if type(index)is not int or not 0<=index<len(observed['images']):raise ValueError('listing_action_invalid_image_index')
        return preview(self.service,{'url':observed['images'][index],'source_ref':'image-action:'+action_id},observed['sha256'])
    def finish(self,action_id,expected_event_sha256,idempotency_key,expected_observation_sha256,note,confirmed):
        a=self.action(action_id);key='finish:'+text(idempotency_key)
        if confirmed is not True or type(note)is not str or not note.strip()or len(note)>1000:raise ValueError('listing_action_confirmation_required')
        sig=digest(canonical([expected_observation_sha256,note,confirmed]))
        with self.live.config_lock,self.core.atomic():
            if self._once(a,key,sig):return self.get(a['case_id'])
            case,c=self.context(a['case_id']);state=self.state(a);obs=state.get('observation')
            if state['status']!='unknown':raise ValueError('listing_action_result_review_closed')
            if self.store_identity(c)!=a['data']['store_identity']or case['scope']['product_id']!=a['data']['product_id']:raise ValueError('listing_action_connection_changed')
            if self.lock.locked():raise ValueError('listing_action_busy')
            snap=self.snapshot(a['case_id'])
            if not state['dispatch_started']or not obs or obs['sha256']!=expected_observation_sha256 or not snap or not snap['fresh']or snap['sha256']!=obs['sha256']:raise ValueError('listing_action_fresh_observation_required')
            if obs['errors_present']or obs['images']==a['data']['before_images']or len(obs['images'])!=len(a['data']['after_images']):raise ValueError('listing_action_result_not_ready')
            self._event(a,expected_event_sha256,key,sig,dict(status='owner_confirmed',completion_basis='owner_visual_attestation_not_exact_url_proof',result_review_note=note.strip(),result_reviewed_at=time.time()))
        return self.get(a['case_id'])
    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=1)
