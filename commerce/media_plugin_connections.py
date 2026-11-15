"""Private host-plugin bindings and immutable, unsubmitted production briefs.

OAuth stays in the host. A brief is data for review and continuation in that
host; it never constitutes a remote submission or a background worker claim.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from research import canonical, digest
from media_providers import _private_free
from media_video_review import definitions as video_review_definitions,review as review_video_content

PROVIDERS={'lovart':'Lovart','heygen':'HeyGen'}
OBSERVATION_TTL=86400


def definitions(schema,string):
    return [
        ('commerce_media_plugin_plan_prepare','保存绑定商品版本与已选插件账号的制作方案，待宿主核对；不上传或消耗生成额度',schema({
            'request_id':string,'expected_revision':string,'provider':{'type':'string','enum':list(PROVIDERS)},
            'expected_connection_revision':{'type':'integer','minimum':1},'asset_ids':{'type':'array','items':string,'minItems':1,'maxItems':8},
            'idempotency_key':string,'shot_index':{'type':'integer','minimum':0,'maximum':30}},['request_id','expected_revision','provider','expected_connection_revision','asset_ids','idempotency_key'])),
        ('commerce_media_plugin_plan_get','读取插件制作方案与当前依据是否变化；方案准备不代表已生成',schema({'plan_id':string},['plan_id'])),
        ('commerce_media_plugin_plan_list','读取指定制作版本的插件方案，方便重新打开后接续',schema({'request_id':string},['request_id'])),
        ('commerce_media_plugin_plan_validate','宿主执行前重新核对方案哈希、商品、素材及账号绑定；不发起生成',schema({'plan_id':string,'expected_plan_sha256':string},['plan_id','expected_plan_sha256'])),
    ]+video_review_definitions(schema,string)


def text(value,maximum=160,empty=False):
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 for c in value) or not empty and not value.strip():
        raise ValueError('media_plugin_invalid_configuration')
    return value.strip()


class MediaPluginConnections:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.path=service.state/'media-plugin-routing.json'
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS media_plugin_plans(id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,request_id TEXT NOT NULL,document TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS media_plugin_plans_request ON media_plugin_plans(request_id)')

    def _read(self):
        if self.path.is_symlink():raise ValueError('media_plugin_unsafe_configuration')
        if not self.path.exists():return {}
        if self.path.stat().st_size>65536:raise ValueError('media_plugin_invalid_configuration')
        try:
            data=json.loads(self.path.read_text())
            if not isinstance(data,dict) or set(data)-set(PROVIDERS):raise ValueError()
            return data
        except (ValueError,OSError):raise ValueError('media_plugin_invalid_configuration') from None

    def _binding(self,provider):
        if provider not in PROVIDERS:raise ValueError('media_plugin_unsupported_provider')
        return self._read().get(provider,{'provider':provider,'revision':0,'account_label':'','link_id':'','connection_status':'unbound','observed_at':None,'model':'','model_parameters':{}})

    @staticmethod
    def _public(binding):
        status=binding['connection_status']
        if status=='available_to_host' and (binding.get('observed_at') or 0)+OBSERVATION_TTL<time.time():status='recheck_required'
        return {k:v for k,v in binding.items() if k not in ('link_id','model_parameters')} | {
            'label':PROVIDERS[binding['provider']],'account_suffix':'…'+binding['link_id'][-5:] if binding['link_id'] else '',
            'status':status,'execution_mode':'host_plugin','backend_autonomous':False,'generation_verified':False,
            'verification':'host_observation_not_backend_probe'}

    def catalog(self):
        return {'connections':[self._public(self._binding(p)) for p in PROVIDERS],
                'preferred_image':'lovart','preferred_ugc_video':'heygen','preferred_showcase_video':'heygen',
                'fallback_policy':'explicit_choice_only','oauth_shared_with_backend':False}

    def configure(self,data):
        allowed={'provider','expected_revision','account_label','link_id','connection_status','observed_at','model','model_parameters'}
        if not isinstance(data,dict) or set(data)-allowed:raise ValueError('media_plugin_unknown_field')
        provider=data.get('provider');old=self._binding(provider)
        if type(data.get('expected_revision')) is not int:raise ValueError('media_plugin_revision_conflict')
        label=text(data.get('account_label'),120);link=text(data.get('link_id',''),160,empty=provider=='heygen')
        if provider=='lovart' and not re.fullmatch(r'link_[a-zA-Z0-9_-]+',link):raise ValueError('media_plugin_invalid_account')
        status=data.get('connection_status')
        if status not in ('available_to_host','needs_reauthentication','not_verified'):raise ValueError('media_plugin_invalid_status')
        observed=data.get('observed_at')
        if type(observed) not in (float,int) or not math.isfinite(observed) or not 0<observed<=time.time()+60:raise ValueError('media_plugin_invalid_observation')
        model=text(data.get('model',''),200,empty=True);params=data.get('model_parameters',{})
        if not isinstance(params,dict) or set(params)&{'prompt','model','n','link_id','ref_images','image','referenceImages'} or len(canonical(params))>10000:raise ValueError('media_plugin_invalid_parameters')
        _private_free(params)
        lock_path=self.path.with_suffix('.lock')
        if lock_path.is_symlink():raise ValueError('media_plugin_unsafe_configuration')
        fd=os.open(lock_path,os.O_WRONLY|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX);all_bindings=self._read();old=all_bindings.get(provider,old)
            if old['revision']!=data['expected_revision']:raise ValueError('media_plugin_revision_conflict')
            binding={'provider':provider,'revision':old['revision']+1,'account_label':label,'link_id':link,
                     'connection_status':status,'observed_at':observed,'model':model,'model_parameters':params}
            all_bindings[provider]=binding;temporary=self.path.with_name(uuid.uuid4().hex+'.plugin-tmp')
            descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            try:
                with os.fdopen(descriptor,'w') as file:json.dump(all_bindings,file,ensure_ascii=False,allow_nan=False)
                if self.path.is_symlink():raise ValueError('media_plugin_unsafe_configuration')
                temporary.replace(self.path)
            finally:
                if temporary.exists():temporary.unlink()
        return self._public(binding)

    def _execution_documents(self,request_id):
        with self.core.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_plugin_executions'").fetchone():return []
            return [json.loads(row[0]) for row in db.execute('SELECT document FROM media_plugin_executions WHERE request_id=?',(request_id,))]

    def _production_guard(self,request,exclude_execution_id=None,own_result_sha256=None):
        if request.get('result_sha256') and request['result_sha256']!=own_result_sha256:raise ValueError('creative_result_immutable_create_new_version')
        with self.core.db() as db:
            jobs=[json.loads(row[0]) for row in db.execute('SELECT document FROM media_provider_jobs WHERE request_id=?',(request['id'],))]
        executions=self._execution_documents(request['id'])
        # Local cancellation is not remote terminality. Exclude only the exact
        # execution whose own frozen pins are being checked by its receiver.
        unresolved=any(e['id']!=exclude_execution_id and e.get('external_generation_submitted') and not e.get('provider_terminal') for e in executions)
        if unresolved or (request.get('external_generation_submitted') and not jobs and not executions) or any(j.get('external_generation_submitted') and self.service.media_providers._occupies_capacity(j) for j in jobs):
            raise ValueError('media_plugin_generation_already_submitted')

    def prepare(self,request_id,expected_revision,provider,asset_ids,expected_connection_revision,idempotency_key,shot_index=None):
        text(idempotency_key);binding=self._binding(provider)
        if binding['revision']!=expected_connection_revision or not binding['revision']:raise ValueError('media_plugin_connection_changed')
        request=self.service.media.request_get(request_id);project=self.service.media._current(request,expected_revision);self._production_guard(request)
        video=request['spec']['format'].endswith('_video')
        if (provider=='heygen')!=video:raise ValueError('media_plugin_format_not_supported')
        if not isinstance(asset_ids,list) or not 1<=len(asset_ids)<=8 or len(set(asset_ids))!=len(asset_ids):raise ValueError('creative_invalid_asset_selection')
        if shot_index is not None and (not video or type(shot_index) is not int or not 0<=shot_index<len(request['spec']['shots'])):raise ValueError('media_provider_invalid_shot_index')
        sources=[];blockers=[]
        for ident in asset_ids:
            path,meta,kind=self.service.creative.asset(project['id'],ident)
            if kind!='product_image':raise ValueError('creative_product_media_required')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('creative_asset_changed')
            if provider=='lovart' and (meta['size']+2)//3*4>8*1024*1024:blockers.append('upload_exceeds_plugin_inline_limit')
            sources.append({'asset_id':ident,'sha256':meta['sha256'],'kind':kind,'size':meta['size'],'filename':ident+path.suffix,
                            'read':{'name':'commerce_creative_asset_read','arguments':{'project_id':project['id'],'asset_id':ident,'offset':'0'}}})
        connection=self._public(binding)
        if connection['status']!='available_to_host':blockers.append(connection['status'])
        prompt=request['spec']['prompt'];ratio='9:16' if video else request['spec'].get('image_delivery',{}).get('aspect_ratio','1:1')
        if shot_index is not None:
            shot=request['spec']['shots'][shot_index];duration=max(5,math.ceil((shot['end_ms']-shot['start_ms'])/1000));prompt+='\n本次只制作以下镜头：'+canonical(shot)
        else:duration=30 if video else None
        if len(prompt)>(16000 if video else 32000):blockers.append('prompt_exceeds_plugin_limit')
        if provider=='lovart':
            arguments={'link_id':binding['link_id'],'prompt':prompt,'n':1,'aspect_ratio':ratio}
            if binding['model']:arguments['model']=binding['model']
            if binding['model_parameters']:arguments['params']=binding['model_parameters']
            call={'name':'lovart.generate_image','arguments':arguments,'bind_uploaded_images_to':'ref_images'}
            transfer={'name':'lovart.upload_asset','arguments':{'link_id':binding['link_id']},'input':'Read every selected asset in chunks, decode and join its bytes, verify SHA-256, then base64 encode the complete file. Upload to Lovart before using returned URLs as ref_images.'}
        else:
            blockers.append('person_script_storyboard_approval_required')
            call={'name':'heygen.reference_to_video','arguments':{'model':'heygen-video-1','prompt':prompt,'duration':duration,'aspectRatio':ratio,'resolution':'1080p','promptEnhancement':'quality'},'bind_uploaded_images_to':'referenceImages'}
            transfer={'name':'heygen.import_asset_from_chat','input':'Use a real supported host file reference or the official presigned asset-upload workflow. Never pass a local backend path as a HeyGen asset_id or public URL.'}
        frozen={'request_id':request_id,'request_sha256':request['request_sha256'],'project_revision':project['revision'],'connection_revision':binding['revision'],
                'provider':provider,'account_link_id':binding['link_id'],'sources':sources,'shot_index':shot_index,'tool_call':call,'transfer':transfer}
        fingerprint=digest(canonical(frozen));idem=digest(canonical([request_id,idempotency_key]))
        plan={**frozen,'id':'pluginplan_'+uuid.uuid4().hex[:20],'project_id':project['id'],'plan_sha256':fingerprint,'stage':'awaiting_host_review',
              'created_at':time.time(),'account_label':binding['account_label'],'blockers':sorted(set(blockers)),'generation_count':1,
              'external_generation_submitted':False,'backend_autonomous':False,'status':'prepared_not_generated','source_request':request,
              'continuation':['Revalidate this exact plan SHA immediately before execution.','Confirm the product, image count or script/storyboard, account and quota before any charged call.','Transfer selected product assets using the real plugin tools.','Persist the actual remote IDs and status; never resubmit an unknown creation.','Import actual returned files into the same project and attach them to this request for review.']}
        with self.core.atomic() as db:
            old=db.execute('SELECT document FROM media_plugin_plans WHERE idem=?',(idem,)).fetchone()
            if old:
                value=json.loads(old[0])
                if value['plan_sha256']!=fingerprint:raise ValueError('media_plugin_idempotency_conflict')
                return self.get(value['id'])
            if db.execute('SELECT count(*) FROM media_plugin_plans WHERE request_id=?',(request_id,)).fetchone()[0]>=100:raise ValueError('media_plugin_plan_limit')
            db.execute('INSERT INTO media_plugin_plans VALUES(?,?,?,?)',(plan['id'],idem,request_id,canonical(plan)))
        return self.get(plan['id'])

    def _plan(self,plan_id):
        if not isinstance(plan_id,str) or not re.fullmatch('pluginplan_[a-f0-9]{20}',plan_id):raise ValueError('media_plugin_plan_not_found')
        with self.core.db() as db:row=db.execute('SELECT document FROM media_plugin_plans WHERE id=?',(plan_id,)).fetchone()
        if not row:raise ValueError('media_plugin_plan_not_found')
        return json.loads(row[0])

    def _guard(self,plan,exclude_execution_id=None):
        request=self.service.media.request_get(plan['request_id']);self.service.media._current(request,plan['project_revision'])
        own_result=None
        if exclude_execution_id is not None:
            own=next((d for d in self._execution_documents(plan['request_id']) if d['id']==exclude_execution_id),None)
            if not own or own.get('plan_id')!=plan['id']:raise ValueError('media_plugin_execution_plan_mismatch')
            assets=own.get('assets',[])
            if assets and own.get('actual_bytes_verified'):own_result=digest(canonical([{k:a[k] for k in ('id','sha256','kind')} for a in assets]))
        self._production_guard(request,exclude_execution_id,own_result)
        if request['request_sha256']!=plan['request_sha256']:raise ValueError('creative_request_stale')
        binding=self._binding(plan['provider'])
        if binding['revision']!=plan['connection_revision'] or binding['link_id']!=plan['account_link_id']:raise ValueError('media_plugin_connection_changed')
        for source in plan['sources']:
            path,meta,_=self.service.creative.asset(plan['project_id'],source['asset_id'])
            if meta['sha256']!=source['sha256'] or hashlib.sha256(path.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('creative_asset_changed')

    def get(self,plan_id):
        plan=self._plan(plan_id);self.service.media.project(plan['project_id'])
        try:self._guard(plan);stale=False
        except ValueError:stale=True
        return {**plan,'stale':stale}

    def list(self,request_id):
        self.service.media.request_get(request_id)
        with self.core.db() as db:ids=[r[0] for r in db.execute('SELECT id FROM media_plugin_plans WHERE request_id=? ORDER BY rowid DESC LIMIT 100',(request_id,))]
        return {'plans':[self.get(ident) for ident in ids]}

    def validate(self,plan_id,expected_plan_sha256):
        plan=self._plan(plan_id)
        if plan['plan_sha256']!=expected_plan_sha256:raise ValueError('media_plugin_plan_changed')
        self._guard(plan);connection=self._public(self._binding(plan['provider']))
        if connection['status']!='available_to_host':raise ValueError('media_plugin_connection_requires_attention')
        if plan['blockers']:raise ValueError('media_plugin_plan_requires_review')
        return {'current':True,'plan_id':plan_id,'plan_sha256':plan['plan_sha256'],'external_generation_submitted':False,'next':'host_review_and_explicit_generation'}

    def review_video(self,plan_id,expected_plan_sha256,content,idempotency_key):
        return review_video_content(self,plan_id,expected_plan_sha256,content,idempotency_key)

    def invoke(self,name,args):
        actions={'commerce_media_plugin_plan_prepare':self.prepare,'commerce_media_plugin_plan_get':self.get,
                 'commerce_media_plugin_plan_list':self.list,'commerce_media_plugin_plan_validate':self.validate,
                 'commerce_media_plugin_plan_review_video':self.review_video}
        if name not in actions:raise ValueError('media_plugin_unknown_tool')
        return actions[name](**args)
