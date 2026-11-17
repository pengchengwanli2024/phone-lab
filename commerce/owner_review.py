"""Responsible-owner signoff on existing, scoped evidence; never independent certification."""
import json
import time
from research import canonical,digest

POLICY='owner_attested_not_independently_verified'
REQUIREMENTS={'identity':'产品身份、规格与实物对应','claims':'标题、描述、翻译与卖点依据','rights':'图片、视频与品牌使用权','rules':'店铺、市场及类目规则','qualifications':'资质、标签与必要证明'}

def definitions(schema,string):
    target={k:string for k in ('case_id','platform','store_ref','market')}
    return [
        ('commerce_owner_review_get','只读经营负责人核查包、缺项和签收历史；不是独立认证或平台执行授权',schema(target,list(target))),
        ('commerce_owner_review_record','仅在用户逐项核对准确版本后记录负责人签收/退回/撤销；不由智能体自行签收，不授予平台写入',schema({**target,'expected_binding_sha256':string,'expected_review_sha256':{'type':'string'},'checks':{'type':'object'},'decision':{'type':'string','enum':['save','owner_confirmed','rejected','withdrawn']},'reviewer':{'type':'string','maxLength':160},'confirmed':{'type':'boolean'},'idempotency_key':string},[*target,'expected_binding_sha256','expected_review_sha256','checks','decision','reviewer','confirmed','idempotency_key'])),
        ('commerce_owner_review_image','只读负责人核查包准确保存方案的产品图片；版本/索引受控，不采用其他候选',schema({**target,'expected_binding_sha256':string,'index':{'type':'integer','minimum':0,'maximum':19}},[*target,'expected_binding_sha256','index'])),
    ]

def checklist(value):
    if type(value)is not dict or set(value)!=set(REQUIREMENTS):raise ValueError('owner_review_invalid_checks')
    out={}
    for key,row in value.items():
        if type(row)is not dict or set(row)!={'status','source_ref','note'}or row['status']not in ('pending','confirmed','not_applicable','rejected'):raise ValueError('owner_review_invalid_checks')
        if any(type(row[k])is not str or len(row[k])>1500 for k in ('source_ref','note')):raise ValueError('owner_review_invalid_checks')
        if row['status']=='not_applicable'and(key!='qualifications'or not row['note'].strip()):raise ValueError('owner_review_not_applicable_requires_reason')
        if row['status']in ('confirmed','not_applicable')and not row['source_ref'].strip():raise ValueError('owner_review_evidence_required')
        out[key]=dict(row)
    return out

class OwnerReviews:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.org=service.organization;self.workspace=service.product_workspace
    def invoke(self,name,args):return {'commerce_owner_review_get':self.get,'commerce_owner_review_record':self.record,'commerce_owner_review_image':self.image}[name](**args)
    @staticmethod
    def kind(target):return 'compliance_owner_'+digest(canonical(target))[:24]
    def snapshot(self,target):
        target,scope=self.service.listings.scope(**target);case,_,facts,source=self.workspace.sources(target['case_id']);config=self.service.live.config()
        saved=self.service.form_drafts.get(scope);envelope=saved['payload']or{};payload,base_current=self.service.listings.saved_payload(target,envelope,source,facts=facts)
        supported=target['platform']=='ozon'and target['store_ref']=='ozon-live'and target['market']=='RU'and case['scope'].get('platform')=='ozon'and case['scope'].get('market')=='RU'
        head=self.org.artifact(target['case_id'],'delivery_review');content=self.workspace.content_for_case(case);draft=content[0]if content else None
        receipt=None
        if draft and head and head['intact']:
            receipt=next((r for r in draft['receipts']if r['id']==head['payload'].get('receipt_id')),None)
        delivery=bool(head and head['intact']and head['payload'].get('decision')=='reviewed'and head['payload'].get('binding_source_sha256')==source and draft and head['payload'].get('draft_id')==draft['id']and receipt and receipt['expires_at']>time.time()and draft['receipts'][-1]['id']==receipt['id']and draft['preflight']['ready_for_local_review'])
        checkpoints={name:self.service.form_drafts.get(self.workspace.form_scope(target['case_id'],name))for name in ('cost','content')}
        schema=self.service.listing_schema.evaluate(target,payload,case['scope'].get('synthetic')is True)if payload else None
        binding=dict(platform_schema_sha256=digest(canonical(schema)),policy=POLICY,target=target,source_sha256=source,listing_revision=saved['revision'],saved_source_sha256=envelope.get('source_sha256'),payload_sha256=digest(canonical(payload)),connection_binding=digest(canonical([config.get('connection_id'),config.get('ozon_client_id'),config.get('ozon_api_key')])),delivery_sha256=head['sha256']if head else None,content_draft_id=draft['id']if draft else None,content_draft_sha256=draft['draft']['draft_sha256']if draft else None,checkpoints={k:dict(revision=v['revision'],sha256=digest(canonical(v['payload'])))for k,v in checkpoints.items()})
        checks=[dict(id='scope',label='当前 Ozon 店铺、市场与商品范围',ready=supported),dict(id='saved',label='店铺方案已保存',ready=bool(saved['revision']and payload)),dict(id='source',label='保存方案与当前商品来源一致',ready=envelope.get('source_sha256')==source and base_current),dict(id='delivery',label='当前本地交付审阅与有效回执',ready=delivery)]
        return dict(target=target,binding=binding,binding_sha256=digest(canonical(binding)),product=payload,synthetic=case['scope'].get('synthetic')is True,supported=supported,automatic_checks=checks)
    def state(self,target):
        value=self.snapshot(target);head=self.org.artifact(value['target']['case_id'],self.kind(value['target']))
        if head and(not head['intact']or head['payload'].get('target')!=value['target']or head['payload'].get('policy')!=POLICY):raise ValueError('owner_review_integrity')
        data=head['payload']if head else{};decision=data.get('decision','pending');matches=bool(head and data['binding_sha256']==value['binding_sha256'])
        checks=data.get('checks')if matches else{k:dict(status='pending',source_ref='',note='')for k in REQUIREMENTS}
        current=bool(matches and decision=='owner_confirmed'and all(c['ready']for c in value['automatic_checks'])and all(c['status']in ('confirmed','not_applicable')for c in checks.values()))
        status='owner_confirmed'if current else'stale'if head and not matches else'prerequisites_missing'if decision=='owner_confirmed'else decision
        return dict(**value,policy=POLICY,requirements=REQUIREMENTS,checks=checks,review_sha256=head['sha256']if head else'',review_id=head['id']if head else None,reviewer=data.get('reviewer',''),reviewed_at=head['created_at']if head else None,decision=decision,recorded_checks=data.get('checks'),recorded_binding_sha256=data.get('binding_sha256'),current=current,status=status,independent_certification=False,external_execution_allowed=False)
    def prerequisites(self,target):
        snapshot=self.workspace.get(target['case_id']);stages={s['id']:s for s in snapshot['stages']}
        rows=[dict(id=key,label=stages[key]['name'],ready=stages[key]['status']=='PASS')for key in ('S2','S4','S5')]
        rows.append(dict(id='delivery',label='本地交付审阅',ready=snapshot['delivery_review']['status']=='local_review_recorded'))
        value=self.snapshot(target)
        schema=self.service.listing_schema.evaluate(target,value['product'],value['synthetic'])if value['product']else None
        rows.append(dict(id='platform_schema',label='平台类目与属性结构',ready=bool(schema and schema['status']=='limited_check_passed')))
        return rows
    def get(self,**target):
        value=self.state(target);rows=self.prerequisites(value['target']);value['automatic_checks']+=rows
        if value['current']and not all(c['ready']for c in rows):value.update(current=False,status='prerequisites_missing')
        with self.core.db()as db:history=db.execute('SELECT id,payload,sha,created FROM org_artifacts WHERE case_id=?AND kind=?ORDER BY created DESC,id DESC LIMIT 10',(target['case_id'],self.kind(value['target']))).fetchall()
        value['history']=[]
        for ident,raw,sha,created in history:
            if digest(raw)!=sha:raise ValueError('owner_review_integrity')
            row=json.loads(raw);value['history'].append(dict(id=ident,sha256=sha,decision=row['decision'],reviewer=row['reviewer'],at=created,binding_sha256=row['binding_sha256']))
        return value
    def case_gate(self,case_id):
        target=dict(case_id=case_id,platform='ozon',store_ref='ozon-live',market='RU')
        try:value=self.state(target)
        except ValueError:return dict(status='FAIL',detail='负责人核查范围或证据完整性异常',evidence=[])
        status='PASS'if value['current']else'FAIL'if value['decision']=='rejected'else'HOLD'if value['review_id']else'BLOCKED'
        return dict(status=status,detail='经营负责人已逐项签收当前版本；不属于独立认证'if value['current']else'需要经营负责人核查并签收当前版本，旧签收不自动沿用',evidence=[dict(ref='artifact:'+value['review_id'],sha256=value['review_sha256'])]if value['review_id']else[])
    def record(self,case_id,platform,store_ref,market,expected_binding_sha256,expected_review_sha256,checks,decision,reviewer,confirmed,idempotency_key):
        target,_=self.service.listings.scope(case_id,platform,store_ref,market);checks=checklist(checks)
        if decision not in ('save','owner_confirmed','rejected','withdrawn')or type(reviewer)is not str or len(reviewer)>160 or type(idempotency_key)is not str or not 1<=len(idempotency_key)<=160:raise ValueError('owner_review_invalid_input')
        if decision!='save'and(confirmed is not True or not reviewer.strip()):raise ValueError('owner_review_confirmation_required')
        if decision=='owner_confirmed'and any(v['status']not in ('confirmed','not_applicable')for v in checks.values()):raise ValueError('owner_review_incomplete')
        sig=digest(canonical([target,expected_binding_sha256,expected_review_sha256,checks,decision,reviewer,confirmed]));kind=self.kind(target)
        with self.service.live.config_lock,self.core.atomic()as db:
            self.org.case(case_id)
            prior=db.execute('SELECT payload,sha FROM org_artifacts WHERE case_id=?AND kind=?AND idem=?',(case_id,kind,idempotency_key)).fetchone()
            if prior:
                if digest(prior[0])!=prior[1]:raise ValueError('owner_review_integrity')
                if json.loads(prior[0])['operation_sha256']!=sig:raise ValueError('owner_review_idempotency_conflict')
                return self.get(**target)
            value=self.get(**target)
            if not value['supported']:raise ValueError('owner_review_scope_not_supported')
            if value['binding_sha256']!=expected_binding_sha256:raise ValueError('owner_review_binding_changed')
            if value['review_sha256']!=expected_review_sha256:raise ValueError('owner_review_conflict')
            if decision=='owner_confirmed'and not all(c['ready']for c in value['automatic_checks']):raise ValueError('owner_review_prerequisites_missing')
            payload=dict(policy=POLICY,target=target,binding_sha256=value['binding_sha256'],binding=value['binding'],checks=checks,decision=decision,reviewer=reviewer,operator_identity='owner_supplied_not_independently_verified',independent_certification=False,external_execution_allowed=False,operation_sha256=sig)
            head=self.org.artifact(case_id,kind);self.org._store(case_id,kind,payload,idempotency_key,_expected_head=head['id']if head else None)
        return self.get(**target)
    def image(self,case_id,platform,store_ref,market,expected_binding_sha256,index):
        from listing_review_media import read
        value=self.snapshot(dict(case_id=case_id,platform=platform,store_ref=store_ref,market=market))
        if not value['supported']or value['binding_sha256']!=expected_binding_sha256:raise ValueError('owner_review_binding_changed')
        if not value['product']:raise ValueError('owner_review_save_required')
        r=dict(id='owner-review:'+value['binding_sha256'],sha256=value['binding_sha256'],data=dict(synthetic=value['synthetic'],frozen=dict(payload=value['product'])))
        return read(self,r,index)
