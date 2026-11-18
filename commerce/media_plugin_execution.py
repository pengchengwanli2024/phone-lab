"""Durable host-plugin handoff. Only a claimed host may submit the frozen call.

This module never invokes generation tools. A persisted submitting intent is an
at-most-once grant, not proof that a provider accepted or completed generation.
"""
from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
import uuid
from urllib.parse import urlsplit

from research import canonical, digest

PREFIX='commerce_media_plugin_execution_'
LEASE_SECONDS=900


def definitions(schema,string):
    ref={'execution_id':string};token={**ref,'claim_token':string}
    receipt=schema({'status':{'type':'string','enum':['pending','completed','failed','cancelled']},
        'task_ids':{'type':'array','items':string,'minItems':1,'maxItems':8},'project_id':string,
        'outputs':{'type':'array','items':schema({'url':{'type':'string','minLength':1,'maxLength':4000},'artifact_id':string},['url']),'minItems':1,'maxItems':8},'error_code':string},['status'])
    items=[('start',{'plan_id':string,'expected_plan_sha256':string,'idempotency_key':string},None),
        ('approve',{**ref,'expected_plan_sha256':string,'decision':{'type':'string','enum':['approve','reject']}},None),
        ('claim',{**ref,'host_id':{'type':'string','enum':['codex','hermes','harness']},'idempotency_key':string},None),
        ('record_transfer',{**token,'asset_id':string,'remote_reference':schema({'type':{'type':'string','enum':['url','asset_id']},'url':{'type':'string','minLength':1,'maxLength':4000},'asset_id':string},['type']),'idempotency_key':string},None),
        ('begin',token,None),('receipt',{**token,'receipt':receipt,'idempotency_key':string},None),
        ('get',ref,None),('list',{'request_id':string,'project_id':string},[]),('poll_packet',ref,None),('cancel',ref,None),('retry_download',ref,None)]
    descriptions={'start':'保存精确插件方案的执行审批记录；不生成', 'approve':'批准当前哈希与商品素材账号；不生成',
        'claim':'宿主独占领取一次性控制凭证；凭证仅返回一次','record_transfer':'登记真实插件上传回执与原始素材关联',
        'begin':'先持久化提交意图，再返回一次精确生成调用；不可重复生成','receipt':'登记宿主真实回执，完成报告不代表文件验证',
        'get':'读取安全执行摘要与实际验证状态','list':'读取制作版本或项目的执行记录','poll_packet':'读取已有任务的状态查询调用；不生成',
        'cancel':'停止本地结果采用；不声称远程取消','retry_download':'仅重试已有结果下载与校验；不重新生成'}
    return [(PREFIX+name,descriptions[name],schema(props,list(props) if required is None else required)) for name,props,required in items]


def _text(value,maximum=200):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or any(ord(c)<32 for c in value):raise ValueError('media_plugin_execution_invalid_value')
    return value


def _https(value,lovart=False):
    _text(value,4000)
    try:
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username is not None or p.password is not None or p.fragment or p.port not in (None,443):raise ValueError()
        if lovart and not (p.hostname=='lovart.ai' or p.hostname.endswith('.lovart.ai')):raise ValueError()
    except ValueError:raise ValueError('media_plugin_execution_invalid_remote_reference') from None
    return value


class MediaPluginExecution:
    def __init__(self,service):
        self.service=service;self.core=service.core;self._lock=threading.RLock();self._stopped=False
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS media_plugin_executions(id TEXT PRIMARY KEY,plan_id TEXT UNIQUE,request_id TEXT,task_id TEXT UNIQUE,status TEXT,document TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS media_plugin_executions_request ON media_plugin_executions(request_id)')

    def _load(self,ident):
        if not isinstance(ident,str) or not re.fullmatch(r'pluginexec_[a-f0-9]{20}',ident):raise ValueError('media_plugin_execution_not_found')
        with self.core.db() as db:row=db.execute('SELECT document FROM media_plugin_executions WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('media_plugin_execution_not_found')
        return json.loads(row[0])

    def _save(self,d):
        d['updated_at']=time.time()
        with self.core.db() as db:
            db.execute('UPDATE media_plugin_executions SET status=?,document=? WHERE id=?',(d['status'],canonical(d),d['id']))
            statuses={'awaiting_approval':'blocked','result_held':'blocked','awaiting_host':'queued','claimed':'running','submitting':'running',
                'submitted':'running','retrieving':'running','awaiting_review':'completed','unknown':'unknown','cancelled':'cancelled','rejected':'cancelled',
                'download_failed':'failed','failed':'failed'}
            db.execute('UPDATE tasks SET status=? WHERE id=?',(statuses[d['status']],d['task_id']))

    @staticmethod
    def _public(d):
        allowed=('id','plan_id','plan_sha256','request_id','project_id','task_id','provider','status','created_at','updated_at','approved_at','host_id',
            'lease_until','external_generation_submitted','provider_status','provider_terminal','cancel_requested','cancel_scope','actual_bytes_verified',
            'review_status','result_sha256','assets','error_code','attached_request_id','shot_index')
        return {k:deepcopy(d[k]) for k in allowed if k in d} | {'backend_autonomous':False,'remote_cancel_supported':False,'stage':d['status'],
            'product_identity_preserved':'not_independently_verified','provider_reported_complete':d.get('provider_status')=='completed'}

    def get(self,execution_id):
        d=self._load(execution_id);self.service.media.project(d['project_id']);return self._public(d)

    def list(self,request_id=None,project_id=None):
        if request_id:self.service.media.request_get(request_id)
        elif project_id:self.service.media.project(project_id)
        else:raise ValueError('media_plugin_execution_scope_required')
        with self.core.db() as db:
            rows=db.execute('SELECT document FROM media_plugin_executions WHERE '+('request_id=?' if request_id else "json_extract(document,'$.project_id')=?")+' ORDER BY rowid DESC LIMIT 100',(request_id or project_id,)).fetchall()
        return {'executions':[self._public(json.loads(r[0])) for r in rows]}

    @staticmethod
    def _occupies_capacity(d):return bool(d.get('external_generation_submitted') and not d.get('provider_terminal'))

    def summary(self,request_id):
        entries=self.list(request_id=request_id)['executions']
        return entries

    def _guard(self,d,approved=True):
        plan=self.service.media_plugins._plan(d['plan_id'])
        if plan['plan_sha256']!=d['plan_sha256']:raise ValueError('media_plugin_plan_changed')
        self.service.media_plugins._guard(plan,exclude_execution_id=d['id'])
        if approved:
            connection=self.service.media_plugins._public(self.service.media_plugins._binding(plan['provider']))
            if connection['status']!='available_to_host':raise ValueError('media_plugin_connection_requires_attention')
            if plan['blockers']:raise ValueError('media_plugin_plan_requires_review')
        return plan

    def start(self,plan_id,expected_plan_sha256,idempotency_key):
        key=digest(_text(idempotency_key))
        plan=self.service.media_plugins._plan(plan_id)
        if plan['plan_sha256']!=expected_plan_sha256:raise ValueError('media_plugin_plan_changed')
        with self.core.atomic() as db:
            row=db.execute('SELECT id,document FROM media_plugin_executions WHERE plan_id=?',(plan_id,)).fetchone()
            if row:
                d=json.loads(row[1])
                if d['start_key']!=key:raise ValueError('media_plugin_execution_idempotency_conflict')
                return self._public(d)
            self.service.media_plugins._guard(plan)
            ident='pluginexec_'+uuid.uuid4().hex[:20]
            product=self.service.media.project(plan['project_id'])['brief']['product']['name']
            task=self.core.invoke('commerce_task_create',{'kind':'draft','input':{'media_plugin_execution_id':ident,'title':('Lovart 商品图片生成' if plan['provider']=='lovart' else 'HeyGen 商品视频生成')+' · '+product,'project_id':plan['project_id'],'request_id':plan['request_id'],'plan_id':plan_id},'idempotency_key':'plugin-execution:'+ident})
            d={'id':ident,'plan_id':plan_id,'plan_sha256':expected_plan_sha256,'request_id':plan['request_id'],'project_id':plan['project_id'],
               'task_id':task['id'],'provider':plan['provider'],'shot_index':plan['shot_index'],'start_key':key,'status':'awaiting_approval',
               'created_at':time.time(),'external_generation_submitted':False,'provider_terminal':False,'provider_status':None,
               'actual_bytes_verified':False,'cancel_requested':False,'review_status':'not_adopted','transfers':{},'receipt_keys':{}}
            db.execute('INSERT INTO media_plugin_executions VALUES(?,?,?,?,?,?)',(ident,plan_id,d['request_id'],task['id'],d['status'],canonical(d)));self._save(d)
        return self._public(d)

    def approve(self,execution_id,expected_plan_sha256,decision):
        if decision not in ('approve','reject'):raise ValueError('media_plugin_execution_invalid_decision')
        with self.core.atomic():
            d=self._load(execution_id)
            if d['plan_sha256']!=expected_plan_sha256:raise ValueError('media_plugin_plan_changed')
            if d['status']!='awaiting_approval':raise ValueError('media_plugin_execution_approval_closed')
            if decision=='reject':d.update(status='rejected',review_status='not_adopted')
            else:self._guard(d);d.update(status='awaiting_host',approved_at=time.time())
            self._save(d)
        return self._public(d)

    def _token(self,d,token,late=False):
        if not isinstance(token,str) or not hmac.compare_digest(d.get('claim_token_sha256',''),digest(token)):raise ValueError('media_plugin_execution_invalid_claim_token')
        if not late and (d.get('lease_until',0)<=time.time() or d.get('cancel_requested')):raise ValueError('media_plugin_execution_claim_expired_or_cancelled')

    def claim(self,execution_id,host_id,idempotency_key):
        if host_id not in ('codex','hermes','harness'):raise ValueError('media_plugin_execution_invalid_host')
        key=digest(_text(idempotency_key));token=secrets.token_urlsafe(32)
        with self.core.atomic():
            d=self._load(execution_id)
            if d['status']=='claimed' and d.get('lease_until',0)<=time.time():d.update(status='awaiting_host',transfers={});d.pop('claim_token_sha256',None)
            if d['status']!='awaiting_host':raise ValueError('media_plugin_execution_already_claimed' if d.get('host_id') else 'media_plugin_execution_approval_required')
            self._guard(d);d.update(status='claimed',host_id=host_id,claim_key=key,claim_token_sha256=digest(token),lease_until=time.time()+LEASE_SECONDS);self._save(d)
        return {**self._public(d),'claim_token':token}

    def record_transfer(self,execution_id,claim_token,asset_id,remote_reference,idempotency_key):
        key=digest(_text(idempotency_key))
        with self.core.atomic():
            d=self._load(execution_id);self._token(d,claim_token)
            if d['status']!='claimed':raise ValueError('media_plugin_execution_transfer_closed')
            plan=self._guard(d);source=next((s for s in plan['sources'] if s['asset_id']==asset_id),None)
            if not source:raise ValueError('media_plugin_execution_source_not_pinned')
            if d['provider']=='lovart':
                if not isinstance(remote_reference,dict) or set(remote_reference)!={'type','url'} or remote_reference['type']!='url':raise ValueError('media_plugin_execution_invalid_remote_reference')
                _https(remote_reference['url'],lovart=True)
            elif not isinstance(remote_reference,dict) or set(remote_reference)!= {'type','asset_id'} or remote_reference['type']!='asset_id':raise ValueError('media_plugin_execution_invalid_remote_reference')
            else:_text(remote_reference['asset_id'])
            value={'asset_id':asset_id,'source_sha256':source['sha256'],'remote_reference':remote_reference,'key':key}
            old=d['transfers'].get(asset_id)
            if old and old!=value:raise ValueError('media_plugin_execution_idempotency_conflict')
            if any(t['key']==key and t!=value for t in d['transfers'].values()):raise ValueError('media_plugin_execution_idempotency_conflict')
            d['transfers'][asset_id]=value;self._save(d)
        return self._public(d)

    def begin(self,execution_id,claim_token):
        with self.core.atomic():
            d=self._load(execution_id);self._token(d,claim_token)
            if d['external_generation_submitted']:raise ValueError('media_plugin_execution_already_begun')
            if d['status']!='claimed':raise ValueError('media_plugin_execution_claim_required')
            plan=self._guard(d)
            if set(d['transfers'])!={s['asset_id'] for s in plan['sources']} or any(d['transfers'][s['asset_id']]['source_sha256']!=s['sha256'] for s in plan['sources']):raise ValueError('media_plugin_execution_transfers_required')
            call=deepcopy(plan['tool_call']);bind=call.pop('bind_uploaded_images_to')
            references=[d['transfers'][s['asset_id']]['remote_reference'] for s in plan['sources']]
            call['arguments'][bind]=[r['url'] for r in references] if d['provider']=='lovart' else references
            d.update(status='submitting',external_generation_submitted=True,begun_at=time.time(),submitted_call_sha256=digest(canonical(call)));self._save(d)
        return {'execution_id':execution_id,'plan_sha256':d['plan_sha256'],'tool_call':call,'submission_grant':'once_only','must_record_receipt':True}

    @staticmethod
    def _receipt(value):
        if not isinstance(value,dict) or set(value)-{'status','task_ids','project_id','outputs','error_code'} or value.get('status') not in ('pending','completed','failed','cancelled'):raise ValueError('media_plugin_execution_invalid_receipt')
        try:
            if 'task_ids' in value and (not isinstance(value['task_ids'],list) or not 1<=len(value['task_ids'])<=8 or len(set(value['task_ids']))!=len(value['task_ids'])):raise ValueError()
            for ident in value.get('task_ids',[]):_text(ident)
            for field in ('project_id','error_code'):
                if field in value:_text(value[field])
            if 'error_code' in value and not re.fullmatch('[A-Za-z0-9_.:-]{1,160}',value['error_code']):raise ValueError()
            if 'outputs' in value:
                if not isinstance(value['outputs'],list) or not 1<=len(value['outputs'])<=8:raise ValueError()
                for output in value['outputs']:
                    if not isinstance(output,dict) or set(output)-{'url','artifact_id'}:raise ValueError()
                    _https(output.get('url'))
                    if 'artifact_id' in output:_text(output['artifact_id'])
            if value['status']=='completed' and not value.get('outputs'):raise ValueError()
            if value['status']!='completed' and value.get('outputs'):raise ValueError()
        except (ValueError,TypeError,KeyError):raise ValueError('media_plugin_execution_invalid_receipt') from None
        return deepcopy(value)

    def receipt(self,execution_id,claim_token,receipt,idempotency_key):
        receipt=self._receipt(receipt);key=digest(_text(idempotency_key));sha=digest(canonical(receipt))
        with self.core.atomic():
            d=self._load(execution_id);self._token(d,claim_token,late=True)
            if not d['external_generation_submitted']:raise ValueError('media_plugin_execution_not_begun')
            if key in d['receipt_keys']:
                if d['receipt_keys'][key]!=sha:raise ValueError('media_plugin_execution_idempotency_conflict')
                return self._public(d)
            if len(d['receipt_keys'])>=100:raise ValueError('media_plugin_execution_receipt_limit')
            for field in ('task_ids','project_id'):
                if field in receipt and d.get('remote_'+field) and d['remote_'+field]!=receipt[field]:raise ValueError('media_plugin_execution_remote_identity_changed')
            if d.get('provider_terminal'):
                if d['provider_status']!=receipt['status'] or receipt.get('outputs',d.get('outputs'))!=d.get('outputs'):raise ValueError('media_plugin_execution_terminal_receipt_conflict')
            for field in ('task_ids','project_id'):
                if field in receipt:d['remote_'+field]=receipt[field]
            d['receipt_keys'][key]=sha
            if d.get('provider_terminal'):
                # Terminal provider truth may be replayed under a fresh host key.
                # Keep verified/adopted/download-failure state; only an explicit
                # download retry may restart retrieval after that first receipt.
                self._save(d)
                return self._public(d)
            d.update(provider_status=receipt['status'],provider_terminal=receipt['status']!='pending')
            if receipt['status']=='completed':d.update(status='retrieving',outputs=receipt['outputs'],error_code=None)
            elif receipt['status']=='pending':d['status']='unknown' if d['cancel_requested'] else 'submitted'
            else:d.update(status='cancelled' if d['cancel_requested'] or receipt['status']=='cancelled' else 'failed',error_code=receipt.get('error_code'))
            self._save(d)
        return self._public(d)

    def poll_packet(self,execution_id):
        d=self._load(execution_id);plan=self.service.media_plugins._plan(d['plan_id'])
        ids=d.get('remote_task_ids')
        if not ids:raise ValueError('media_plugin_execution_remote_ids_required')
        if d['provider']=='lovart':
            if not d.get('remote_project_id'):raise ValueError('media_plugin_execution_remote_project_required')
            call={'name':'lovart.get_task_status','arguments':{'link_id':plan['account_link_id'],'project_id':d['remote_project_id'],'task_ids':ids}}
        else:call={'name':'heygen.get_model_video','arguments':{'videoId':ids[0]}}
        return {'execution_id':execution_id,'tool_call':call,'generation':False}

    def cancel(self,execution_id):
        with self.core.atomic():
            d=self._load(execution_id)
            if d.get('attached_request_id'):raise ValueError('media_plugin_execution_not_cancellable')
            d.update(cancel_requested=True,cancel_scope='local_result_adoption',review_status='not_adopted')
            if d['status']!='retrieving':d['status']='unknown' if self._occupies_capacity(d) else 'cancelled'
            self._save(d)
        return self._public(d)

    def _folder(self,d):
        root=self.service.state/'plugin-results';folder=root/d['id']
        if root.is_symlink() or folder.is_symlink():raise ValueError('media_plugin_execution_unsafe_result_folder')
        root.mkdir(mode=0o700,exist_ok=True);folder.mkdir(mode=0o700,exist_ok=True)
        if not folder.is_dir():raise ValueError('media_plugin_execution_unsafe_result_folder')
        return folder

    def _retrieve(self,ident,owner):
        from media_outputs import retrieve
        d=self._load(ident);plan=self.service.media_plugins._plan(d['plan_id']);folder=self._folder(d)
        duration=plan['tool_call']['arguments'].get('duration');kind='video' if d['provider']=='heygen' else 'image'
        result=retrieve(self.service.creative,folder,kind,d['outputs'],config={'provider':d['provider'],'base_url':'https://lovart.ai' if kind=='image' else 'https://api.heygen.com'},duration_seconds=duration,cancelled=lambda:self._stopped)
        with self.core.atomic():
            d=self._load(ident)
            if d.get('download_owner')!=owner:raise ValueError('media_plugin_execution_download_lease_lost')
            assets=[]
            for artifact in result['artifacts']:
                existing=next((a for a in self.service.creative.get(d['project_id'])['assets'] if a.get('media_plugin_execution_id')==ident and a.get('provider_output_index')==artifact['index'] and a['sha256']==artifact['sha256']),None)
                if existing:
                    path,_,_=self.service.creative.asset(d['project_id'],existing['id'])
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:raise ValueError('creative_asset_changed')
                    assets.append(existing);continue
                path=folder/artifact['filename']
                if path.parent!=folder or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=artifact['sha256']:raise ValueError('creative_asset_changed')
                copy=folder/('register-'+uuid.uuid4().hex+path.suffix);shutil.copyfile(path,copy);os.chmod(copy,0o600)
                try:
                    asset=self.service.creative.register(d['project_id'],'generated_'+kind,copy,{'origin':'host_plugin','provider':d['provider'],
                        'media_plugin_execution_id':ident,'provider_output_index':artifact['index'],'creative_request_id':d['request_id'],
                        'creative_request_sha256':plan['request_sha256'],'source_assets':{s['asset_id']:s['sha256'] for s in plan['sources']},
                        'media':artifact['media'],'shot_index':d['shot_index'],'complete_request_output':d['shot_index'] is None,
                        'generation_verified':'actual_media_bytes_and_probe_only','product_identity_preserved':'not_independently_verified'})
                finally:
                    if copy.exists():copy.unlink()
                assets.append(asset)
            d.update(assets=assets,result_sha256=result['result_sha256'],actual_bytes_verified=True,status='result_held',review_status='not_adopted',error_code=None,download_owner=None,download_until=0)
            self._save(d)
        with self.core.atomic():
            d=self._load(ident)
            try:
                if self._stopped or d['cancel_requested']:raise ValueError('media_plugin_execution_not_adopted')
                self._guard(d)
                if d['shot_index'] is None:
                    self.service.media.request_attach(d['request_id'],plan['project_revision'],[a['id'] for a in assets],_reuse=True)
                    d['attached_request_id']=d['request_id']
                d.update(status='awaiting_review',review_status='awaiting_review')
            except ValueError as error:d['error_code']=self._error(error)
            self._save(d)

    @staticmethod
    def _error(error):
        code=str(error)
        return code if re.fullmatch('[a-z][a-z0-9_]{1,150}',code) else 'media_plugin_execution_retrieval_failed'

    def retry_download(self,execution_id):
        with self.core.atomic():
            d=self._load(execution_id)
            if d.get('provider_status')!='completed' or not d.get('outputs') or d.get('actual_bytes_verified'):raise ValueError('media_plugin_execution_download_retry_not_available')
            d.update(status='retrieving',error_code=None);self._save(d)
        return self._public(d)

    def tick(self,at=None):
        if self._stopped:return []
        at=time.time() if at is None else at
        with self._lock:
            with self.core.atomic() as db:
                rows=[json.loads(r[0]) for r in db.execute('SELECT document FROM media_plugin_executions')]
                for d in rows:
                    if d['status']=='claimed' and d.get('lease_until',0)<=at:
                        d.update(status='awaiting_host',transfers={});d.pop('claim_token_sha256',None);self._save(d)
                    elif d['status']=='submitting' and d.get('lease_until',0)<=at:d['status']='unknown';self._save(d)
            for d in rows:
                if d['status']=='retrieving':
                    owner=uuid.uuid4().hex
                    with self.core.atomic():
                        current=self._load(d['id'])
                        if current['status']!='retrieving' or current.get('download_until',0)>time.time():continue
                        current.update(download_owner=owner,download_until=time.time()+LEASE_SECONDS);self._save(current)
                    try:self._retrieve(d['id'],owner)
                    except (ValueError,OSError) as error:
                        with self.core.atomic():
                            fresh=self._load(d['id'])
                            if fresh.get('download_owner')==owner:
                                fresh.update(status='download_failed',error_code=self._error(error),download_owner=None,download_until=0);self._save(fresh)
            # Maintenance above is scope independent. A record whose project is no
            # longer readable (e.g. its case belongs to a previous store connection)
            # is omitted from this view; explicit get() still rejects it.
            views=[]
            for d in rows:
                try:views.append(self.get(d['id']))
                except ValueError:continue
            return views

    def recover(self):
        with self._lock,self.core.atomic() as db:
            for row in db.execute('SELECT document FROM media_plugin_executions').fetchall():
                d=json.loads(row[0])
                if d['status']=='submitting':d['status']='unknown';self._save(d)
                elif d['status']=='claimed':d.update(status='awaiting_host',transfers={});d.pop('claim_token_sha256',None);self._save(d)
                elif d['status']=='retrieving':d.update(download_owner=None,download_until=0);self._save(d)
        return True

    def stop(self):self._stopped=True

    def invoke(self,name,args):
        action=name.removeprefix(PREFIX)
        if not name.startswith(PREFIX) or action not in ('start','approve','claim','record_transfer','begin','receipt','poll_packet','get','list','cancel','retry_download'):raise ValueError('media_plugin_execution_unknown_tool')
        return getattr(self,action)(**args)
