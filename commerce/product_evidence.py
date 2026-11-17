"""Product-bound source dossiers and versioned local selection reviews.

Quotes, costs, creative files and executions remain in their original domains.
A local trial decision never authorizes marketplace or purchasing operations.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import ipaddress, json, math, re, time, uuid
from urllib.parse import urlsplit, parse_qsl
from research import canonical, digest
from sourcing_channels import EXTRA_PLATFORMS, Sourcing, definitions as sourcing_definitions

PLATFORMS=[
 {'id':'1688','label':'1688','hosts':['1688.com']},
 {'id':'yiwugo','label':'义乌购','hosts':['yiwugo.com']},
 {'id':'made_in_china','label':'中国制造网','hosts':['made-in-china.com']},
 {'id':'alibaba','label':'Alibaba 国际站','hosts':['alibaba.com']},
 {'id':'taobao','label':'淘宝','hosts':['taobao.com','tmall.com']},
 {'id':'jd','label':'京东','hosts':['jd.com']},
 {'id':'pdd','label':'拼多多','hosts':['pinduoduo.com','yangkeduo.com']},
 {'id':'ozon','label':'Ozon','hosts':['ozon.ru','ozon.com']},
 {'id':'amazon','label':'Amazon','hosts':['amazon.com','amazon.co.uk','amazon.de']},
 {'id':'tiktok','label':'TikTok Shop','hosts':['tiktok.com','tiktokglobalshop.com']},
 {'id':'mercado','label':'Mercado Libre','hosts':['mercadolibre.com','mercadolibre.com.mx','mercadolivre.com.br']},
 {'id':'other','label':'其他来源','hosts':[]},
]
CRITERIA={'demand':'目标市场需求','competition':'可比竞品与价格','differentiation':'可兑现的差异化','economics':'完整成本与贡献','supply':'实物、报价与履约','compliance':'资质、标识与素材权利'}
PLATFORMS += EXTRA_PLATFORMS
SOURCE_FIELDS={'kind','platform','label','url','model','variant','observed_at','valid_until','review_state','verification_note','rights_status','rights_evidence','notes','quote_ids','images','metrics','archived'}
PROPOSAL_FIELDS={'customer_need','selection_reason','differentiation','risks','currency','trial_quantity','trial_budget','max_loss','min_contribution_rate','conditions'}
METRICS={'price','currency','sales_units','window_days','searches','rating','review_count'}
ID=re.compile(r'ev_[a-f0-9]{32}\Z')
PRIVATE=re.compile(r'(?i)(?:bearer\s+[a-z0-9._-]{12,}|sk-[a-z0-9_-]{20,})')
READ_ONLY={'commerce_product_evidence_get','commerce_product_evidence_operation_get','commerce_product_evidence_source_get','commerce_product_evidence_image'}
READ_ONLY |= {'commerce_product_evidence_sourcing_channels','commerce_product_evidence_sourcing_history'}

def text(v,maximum=2000,required=False):
    if not isinstance(v,str) or len(v)>maximum or any(ord(c)<32 and c not in '\n\t'for c in v) or PRIVATE.search(v):raise ValueError('evidence_invalid_text')
    v=v.strip()
    if required and not v:raise ValueError('evidence_text_required')
    return v

def instant(v,optional=False):
    if optional and not v:return None
    try:
        d=datetime.fromisoformat(v.replace('Z','+00:00'))
        if d.utcoffset() is None:raise ValueError()
        return d.timestamp()
    except (ValueError,TypeError,AttributeError,OverflowError):raise ValueError('evidence_invalid_date')from None

def url(v,platform=None,optional=False):
    if optional and not v:return ''
    text(v,2000,True)
    try:
        p=urlsplit(v);host=p.hostname
        if p.scheme!='https' or not host or p.username or p.password or p.port not in (None,443):raise ValueError()
        if host=='localhost' or host.endswith(('.localhost','.local','.internal')):raise ValueError()
        try:address=ipaddress.ip_address(host)
        except ValueError:address=None
        if address is not None and not address.is_global:raise ValueError()
        if any(re.search(r'(?i)(token|secret|password|passwd|api.?key|authorization|session|cookie)',k)for k,_ in parse_qsl(p.query)):raise ValueError()
        if platform and platform!='other':
            hosts=next(r['hosts']for r in PLATFORMS if r['id']==platform)
            if not any(host==h or host.endswith('.'+h)for h in hosts):raise ValueError()
    except (ValueError,StopIteration):raise ValueError('evidence_invalid_url')from None
    return v

def number(v,maximum=10**12,integer=False,nullable=True):
    if v is None and nullable:return None
    if type(v)not in (int,float) or not math.isfinite(v) or not 0<=v<=maximum or integer and v!=int(v):raise ValueError('evidence_invalid_number')
    return v

def definitions(schema,string):
    case={'case_id':string}
    guard={**case,'expected_dossier_sha256':string,'idempotency_key':string,'actor':string}
    return sourcing_definitions(schema,string) + [
      ('commerce_product_evidence_get','读取同商品原始证据、报价成本、素材、评审与原执行记录；不执行外部经营动作',schema(case,['case_id'])),
      ('commerce_product_evidence_operation_get','只读核对同商品原保存请求的回执；结果未知时不新建或重放',schema({**case,'idempotency_key':string},[*case,'idempotency_key'])),
      ('commerce_product_evidence_source_get','按准确版本读取同商品原始证据；历史资料不覆盖当前记录',schema({**case,'entry_id':string,'revision':{'type':'integer','minimum':1}},[*case,'entry_id','revision'])),
      ('commerce_product_evidence_origin_open','按操作者点击请求在本机浏览器打开同商品、同来源版本的公开原始网页或图片；不携带平台凭据、不登录采购',schema({**case,'entry_id':string,'expected_entry_sha256':string,'index':{'type':'integer','minimum':-1,'maximum':11}},[*case,'entry_id','expected_entry_sha256','index'])),
      ('commerce_product_evidence_source_save','按证据版本保存货源或竞品来源；1688/义乌购等链接与图片均属待核资料，不采购',schema({**guard,'entry_id':{'type':'string','maxLength':80},'expected_revision':{'type':'integer','minimum':0},'payload':{'type':'object'}},[*guard,'entry_id','expected_revision','payload'])),
      ('commerce_product_evidence_proposal_save','按证据版本维护选品理由、风险与试销约束；不是执行授权',schema({**guard,'expected_revision':{'type':'integer','minimum':0},'payload':{'type':'object'}},[*guard,'expected_revision','payload'])),
      ('commerce_product_evidence_review_save','冻结当前证据的本地选品评审；缺项不能放行试销，不授权上架、采购或广告',schema({**guard,'payload':{'type':'object'}},[*guard,'payload'])),
    ]

class ProductEvidence:
    def __init__(self,service):
        self.service=service;self.core=service.core
        with self.core.db()as db:
            db.execute('CREATE TABLE IF NOT EXISTS product_evidence_versions(case_id TEXT NOT NULL,entry_id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,idem TEXT NOT NULL,PRIMARY KEY(case_id,entry_id,revision),UNIQUE(case_id,idem))')
            db.execute('CREATE TABLE IF NOT EXISTS product_evidence_reviews(case_id TEXT NOT NULL,id TEXT PRIMARY KEY,idem TEXT NOT NULL,document TEXT NOT NULL,UNIQUE(case_id,idem))')
        from product_evidence_media import EvidenceMedia
        self.media=EvidenceMedia(self)
        self.sourcing=Sourcing(self)

    def case(self,case_id):return self.service.organization.case(case_id)

    def _versions(self,case_id):
        self.case(case_id)
        with self.core.db()as db:rows=db.execute('SELECT document FROM product_evidence_versions WHERE case_id=? ORDER BY rowid DESC',(case_id,)).fetchall()
        groups={}
        for(raw,)in rows:
            d=json.loads(raw)
            if d['sha256']!=digest(canonical({k:v for k,v in d.items()if k!='sha256'})):raise ValueError('evidence_record_changed')
            groups.setdefault(d['id'],[]).append(d)
        return groups

    def _view(self,versions):
        d=versions[0];p=d['payload']
        fresh=not p.get('valid_until') or instant(p['valid_until'])>time.time()
        recent=not p.get('observed_at') or 0<=time.time()-instant(p['observed_at'])<=30*86400
        return {**p,'id':d['id'],'revision':d['revision'],'sha256':d['sha256'],'actor':d['actor'],'saved_at':d['at'],'fresh':fresh,'recent':recent,
            'history':[{k:r[k]for k in ('revision','payload','actor','at','sha256')}for r in versions[:20]],'history_truncated':len(versions)>20,'independently_verified':False}

    def _projection(self,case_id):
        w=self.service.product_workspace.get(case_id);groups=self._versions(case_id)
        sources=[self._view(v)for k,v in groups.items()if k!='proposal']
        proposal=self._view(groups['proposal'])if 'proposal'in groups else {'id':'proposal','revision':0,'payload':None,'customer_need':'','selection_reason':'','differentiation':'','risks':'','conditions':'','currency':w['case']['currency']or'','trial_quantity':None,'trial_budget':None,'max_loss':None,'min_contribution_rate':None}
        projects=[]
        with self.core.db()as db:
            for pid,brief,revision in db.execute('SELECT id,brief,revision FROM creative_projects ORDER BY rowid DESC'):
                b=json.loads(brief)
                if b.get('product_binding',{}).get('case_id')!=case_id:continue
                assets=[]
                for aid,kind,meta in db.execute('SELECT id,kind,metadata FROM creative_assets WHERE project=? ORDER BY rowid',(pid,)):
                    m=json.loads(meta);assets.append({'id':aid,'kind':kind,'name':m.get('display_name',kind),'sha256':m['sha256'],'source_ref':m.get('source_ref',''),'usage_scope':m.get('usage_scope','unverified'),'media':m.get('media',{})})
                projects.append({'id':pid,'name':b.get('product',{}).get('name',''),'revision':str(revision),'brief_sha256':digest(canonical(b)),'assets':assets,'source_current':b.get('product_binding',{}).get('source_sha256')==w['source_sha256']})
        quotes=w['supply_quotes']['items'];cost=w['forms']['cost']
        activity=[{'id':r['id']+'@'+str(r['revision']),'origin':'evidence','title':('保存选品理由'if r['id']=='proposal'else'归档来源'if r['payload'].get('archived')else'保存来源证据')+' · '+r['payload'].get('label',w['name']),'status':'saved','actor':r['actor'],'at':r['at']}for versions in groups.values()for r in versions]
        context={'case_id':case_id,'source_sha256':w['source_sha256'],'source_heads':[{'id':s['id'],'revision':s['revision'],'sha256':s['sha256'],'fresh':s['fresh'],'recent':s['recent']}for s in sources],
            'proposal_revision':proposal['revision'],'proposal_sha256':proposal.get('sha256'),'cost':{k:cost[k]for k in ('revision','payload','source_sha256','stale')},
            'quote_statuses':[{k:q[k]for k in ('quote_id','sha256','status','scope_current','intact')}for q in quotes],
            'projects':[{k:p[k]for k in ('id','revision','brief_sha256','assets','source_current')}for p in projects]}
        for s,head in zip(sources,context['source_heads']):
            head['images']=[{'id':i['media_id'],'sha256':self.media.asset(case_id,s['id'],i['media_id'])[1]['sha256']}for i in s['images']if i['media_id']]
        fingerprint=digest(canonical(context))
        refs=[{'id':'source:'+s['id']+'@'+str(s['revision']),'label':s['label']+' · v'+str(s['revision'])}for s in sources if not s['archived']]
        refs += [{'id':'quote:'+q['quote_id']+'@'+str(q['revision']),'label':'报价：'+q['fields'].get('supplier',q['quote_id'])+' · v'+str(q['revision'])}for q in quotes]
        if cost['revision']:refs.append({'id':'cost:'+case_id+'@'+str(cost['revision']),'label':'原成本草稿 · v'+str(cost['revision'])})
        for kind,a in w['artifacts'].items():
            if a:refs.append({'id':'artifact:'+a['id'],'label':'原产物：'+kind})
        for p in projects:
            refs.extend({'id':'asset:'+p['id']+':'+a['id'],'label':'素材：'+a['name']}for a in p['assets'])
        executions=[{'id':t['id'],'origin':'task','title':t['input'].get('title',t['kind']),'status':t['status']}for t in w['tasks']]
        with self.core.db()as db:
            for p in projects:
                for jid,raw,status,stage,created in db.execute('SELECT id,input,status,stage,created FROM creative_jobs WHERE project=? ORDER BY rowid DESC LIMIT 50',(p['id'],)):
                    j=json.loads(raw);executions.append({'id':jid,'origin':'creative','project_id':p['id'],'title':j.get('kind','媒体处理'),'status':status,'stage':stage,'created_at':created})
        return {'schema':'commerce-product-evidence-v1','case_id':case_id,'name':w['name'],'case':w['case'],'dossier_sha256':fingerprint,'source_sha256':w['source_sha256'],
            'sources':sources,'proposal':proposal,'quotes':quotes,'cost_checkpoint':cost,'economics':w['calculation'],'stages':[{'id':s['id'],'name':s['name'],'status':s['status'],'gaps':s['gaps']}for s in w['stages']],
            'projects':projects,'executions':executions,'activity':activity,'available_evidence':refs,'criteria':CRITERIA,'platforms':PLATFORMS,'external_execution_allowed':False,'_context':context}

    def get(self,case_id):
        d=self._projection(case_id)
        with self.core.db()as db:rows=db.execute('SELECT document FROM product_evidence_reviews WHERE case_id=? ORDER BY rowid DESC',(case_id,)).fetchall()
        reviews=[]
        for(raw,)in rows:
            r=json.loads(raw)
            if r['sha256']!=digest(canonical({k:v for k,v in r.items()if k!='sha256'})):raise ValueError('evidence_review_changed')
            reviews.append({**r,'current':r['dossier_sha256']==d['dossier_sha256']})
        d['reviews']=reviews[:50];d['review_history_truncated']=len(reviews)>50
        d['activity']=sorted(d['activity']+[{'id':r['id'],'origin':'selection_review','title':'保存选品评审 · '+r['decision'],'status':'saved','actor':r['actor'],'at':r['at']}for r in reviews],key=lambda r:r['at'],reverse=True)[:100]
        d['readiness']=self.readiness(d);d.pop('_context',None)
        return d

    def guard(self,case_id,expected):
        d=self._projection(case_id)
        if d['dossier_sha256']!=expected:raise ValueError('evidence_dossier_changed')
        return d

    def operation_get(self,case_id,idempotency_key):
        self.case(case_id);key=text(idempotency_key,160,True)
        with self.core.db()as db:
            version=db.execute('SELECT document FROM product_evidence_versions WHERE case_id=? AND idem=?',(case_id,key)).fetchone()
            review=db.execute('SELECT document FROM product_evidence_reviews WHERE case_id=? AND idem=?',(case_id,key)).fetchone()
        if version:
            doc=json.loads(version[0]);return {'status':'saved','kind':'proposal'if doc['id']=='proposal'else'source','id':doc['id'],'revision':doc['revision'],'sha256':doc['sha256'],'external_execution_allowed':False}
        if review:
            doc=json.loads(review[0]);return {'status':'saved','kind':'review','id':doc['id'],'sha256':doc['sha256'],'external_execution_allowed':False}
        return {'status':'not_found','external_execution_allowed':False}

    def source_get(self,case_id,entry_id,revision):
        self.case(case_id)
        versions=self._versions(case_id).get(entry_id,[])
        found=next((r for r in versions if r['revision']==revision),None)
        if not found or entry_id=='proposal':raise ValueError('evidence_source_not_found')
        return {'entry':self._view([found]),'is_current':versions[0]['revision']==revision,'external_execution_allowed':False}

    def origin_open(self,case_id,entry_id,expected_entry_sha256,index):
        # Exact recorded origin only; no caller-supplied URL or credential handoff.
        source=self.media.source(case_id,entry_id,expected_entry_sha256,allow_history=True)
        if type(index)is not int or index < -1 or index>=len(source['images']):raise ValueError('evidence_origin_not_found')
        origin=source['url']if index==-1 else source['images'][index]['url']
        origin=url(origin)
        import webbrowser
        requested=bool(webbrowser.open(origin,new=2))
        return {'status':'requested'if requested else'unavailable','url':origin,'external_execution_allowed':False}

    def validate_source(self,case_id,p,entry_id=''):
        if type(p)is not dict or set(p)!=SOURCE_FIELDS:raise ValueError('evidence_invalid_source_fields')
        p=json.loads(canonical(p))
        if p['kind']not in ('supplier','competitor','market','document'):raise ValueError('evidence_invalid_kind')
        if p['platform']not in {r['id']for r in PLATFORMS}:raise ValueError('evidence_invalid_platform')
        for k in ('label','model','variant','verification_note','rights_evidence','notes'):p[k]=text(p[k],5000 if k in ('notes','verification_note')else 1000,k=='label')
        p['url']=url(p['url'],p['platform'],p['kind']in ('market','document'))
        instant(p['observed_at']);instant(p['valid_until'],True)
        if instant(p['observed_at'])>time.time()+300:raise ValueError('evidence_future_observation')
        if p['review_state']not in ('unreviewed','checked','conflict','rejected')or p['review_state']!='unreviewed'and not p['verification_note']:raise ValueError('evidence_verification_note_required')
        if p['rights_status']not in ('unknown','reference_only','authorized','self_owned'):raise ValueError('evidence_invalid_rights')
        if p['rights_status']in ('authorized','self_owned')and not p['rights_evidence']:raise ValueError('evidence_rights_proof_required')
        if type(p['archived'])is not bool:raise ValueError('evidence_invalid_archive')
        quotes={q['quote_id']for q in self.service.product_workspace.supply.listing(case_id)['items']}
        if type(p['quote_ids'])is not list or len(p['quote_ids'])>20 or any(x not in quotes for x in p['quote_ids']):raise ValueError('evidence_quote_reference_outside_scope')
        p['quote_ids']=list(dict.fromkeys(p['quote_ids']))
        if type(p['metrics'])is not dict or set(p['metrics'])-METRICS:raise ValueError('evidence_invalid_metrics')
        for k,v in p['metrics'].items():
            if k=='currency':
                if not isinstance(v,str)or v and not re.fullmatch('[A-Z]{3}',v):raise ValueError('evidence_invalid_currency')
            else:number(v,5 if k=='rating'else 3650 if k=='window_days'else 10**12,integer=k not in ('price','rating'))
        if p['kind']=='supplier'and p['metrics']:raise ValueError('evidence_supplier_price_use_original_quote')
        if type(p['images'])is not list or len(p['images'])>12:raise ValueError('evidence_invalid_images')
        for image in p['images']:
            if type(image)is not dict or set(image)!={'url','media_id','label','role'}:raise ValueError('evidence_invalid_images')
            image['url']=url(image['url'],optional=True);image['label']=text(image['label'],300)
            if image['role']not in ('original','generated','document'):raise ValueError('evidence_invalid_image_role')
            if image['media_id']:
                _,asset=self.media.asset(case_id,entry_id,image['media_id'])
                if image['role']!=asset['role']:raise ValueError('evidence_image_role_immutable')
                if image['url']!=asset['source_url']:raise ValueError('evidence_image_origin_immutable')
            elif not image['url']:raise ValueError('evidence_image_reference_required')
        return p

    def validate_proposal(self,p):
        if type(p)is not dict or set(p)!=PROPOSAL_FIELDS:raise ValueError('evidence_invalid_proposal')
        p=json.loads(canonical(p))
        for k in ('customer_need','selection_reason','differentiation','risks','conditions'):p[k]=text(p[k],5000)
        if not isinstance(p['currency'],str)or p['currency']and not re.fullmatch('[A-Z]{3}',p['currency']):raise ValueError('evidence_invalid_currency')
        for k in ('trial_quantity','trial_budget','max_loss','min_contribution_rate'):number(p[k],1 if k=='min_contribution_rate'else 10**12,integer=k=='trial_quantity')
        return p

    def _prior(self,case_id,key,request):
        with self.core.db()as db:row=db.execute('SELECT document FROM product_evidence_versions WHERE case_id=? AND idem=?',(case_id,key)).fetchone()
        if not row:return None
        d=json.loads(row[0])
        if d['request_sha256']!=digest(canonical(request)):raise ValueError('evidence_idempotency_conflict')
        return {'entry':self._view([d]),'previous_dossier_sha256':d['previous_dossier_sha256'],'reused':True,'external_execution_allowed':False}

    def _write(self,case_id,entry_id,payload,revision,expected,key,actor,request):
        now=datetime.now(timezone.utc).isoformat()
        d={'case_id':case_id,'id':entry_id,'revision':revision+1,'payload':payload,'actor':actor,'at':now,'previous_dossier_sha256':expected,'request_sha256':digest(canonical(request))}
        d['sha256']=digest(canonical(d))
        with self.core.db()as db:
            if db.execute('SELECT count(*) FROM product_evidence_versions WHERE case_id=?',(case_id,)).fetchone()[0]>=5000:raise ValueError('evidence_capacity_reached')
            db.execute('INSERT INTO product_evidence_versions VALUES(?,?,?,?,?)',(case_id,entry_id,revision+1,canonical(d),key))
        return d

    def source_save(self,case_id,entry_id,payload,expected_revision,expected_dossier_sha256,idempotency_key,actor):
        self.case(case_id);actor=text(actor,120,True);key=text(idempotency_key,160,True)
        if entry_id and not ID.fullmatch(entry_id):raise ValueError('evidence_invalid_id')
        request={'kind':'source','entry_id':entry_id,'payload':payload,'revision':expected_revision,'actor':actor}
        with self.core.atomic():
            prior=self._prior(case_id,key,request)
            if prior:return prior
            self.guard(case_id,expected_dossier_sha256)
            groups=self._versions(case_id);versions=groups.get(entry_id,[])
            if (versions[0]['revision']if versions else 0)!=expected_revision or expected_revision and not versions:raise ValueError('evidence_revision_conflict')
            if entry_id and not versions:raise ValueError('evidence_source_not_found')
            p=self.validate_source(case_id,payload,entry_id)
            if not entry_id:
                if len(groups)>=128:raise ValueError('evidence_capacity_reached')
                entry_id='ev_'+uuid.uuid4().hex
            self._write(case_id,entry_id,p,expected_revision,expected_dossier_sha256,key,actor,request)
            return {'entry':self._view(self._versions(case_id)[entry_id]),'previous_dossier_sha256':expected_dossier_sha256,'reused':False,'external_execution_allowed':False}

    def proposal_save(self,case_id,payload,expected_revision,expected_dossier_sha256,idempotency_key,actor):
        self.case(case_id);actor=text(actor,120,True);key=text(idempotency_key,160,True)
        request={'kind':'proposal','payload':payload,'revision':expected_revision,'actor':actor}
        with self.core.atomic():
            prior=self._prior(case_id,key,request)
            if prior:return {**prior,'proposal':prior['entry']}
            self.guard(case_id,expected_dossier_sha256)
            previous=self._versions(case_id).get('proposal',[])
            if (previous[0]['revision']if previous else 0)!=expected_revision:raise ValueError('evidence_revision_conflict')
            p=self.validate_proposal(payload)
            self._write(case_id,'proposal',p,expected_revision,expected_dossier_sha256,key,actor,request)
            return {'proposal':self._view(self._versions(case_id)['proposal']),'reused':False,'external_execution_allowed':False}

    def readiness(self,d):
        active=[s for s in d['sources']if not s['archived']and s['fresh']and s['recent']and s['review_state']=='checked']
        market=[s for s in active if s['kind']in ('market','competitor')and (s['metrics'].get('window_days')or 0)>0 and ((s['metrics'].get('sales_units')or 0)or(s['metrics'].get('searches')or 0))>0]
        competitors={s['url']:s for s in active if s['kind']=='competitor'and s['metrics'].get('price')is not None and s['metrics'].get('currency')and any(i['role']=='original'for i in s['images'])}
        supply=self.service.organization.artifact(d['case_id'],'supply')or{}
        selected=supply.get('payload',{}).get('quote_ref',{})
        quote=next((q for q in d['quotes']if supply.get('intact')and q['quote_id']==selected.get('quote_id')and q['sha256']==selected.get('sha256')and q['status']=='READY_FOR_SELECTION'),None)
        p=d['proposal'];calc=d['economics']
        constraints=all(p.get(k)is not None for k in ('trial_quantity','trial_budget','max_loss','min_contribution_rate'))
        budget_ok=constraints and p['trial_quantity']>0 and p['trial_budget']>0 and p['max_loss']<=p['trial_budget']and p['currency']==d['case']['currency']
        input_cost=(d['cost_checkpoint'].get('payload')or{}).get('input')or(self.service.organization.artifact(d['case_id'],'economics')or{}).get('payload',{})
        matched_cost=bool(quote and input_cost.get('currency')==quote['fields']['currency']==calc.get('currency')==d['case']['currency']
            and input_cost.get('purchase_cost')is not None
            and Decimal(str(input_cost['purchase_cost'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)==Decimal(str(quote['fields']['purchase_cost'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
        economy=calc['status']=='CALCULATED'and not calc.get('stale')and matched_cost and calc.get('contribution',0)>0 and budget_ok and calc.get('contribution_rate',0)>=p['min_contribution_rate']
        goods_budget=bool(quote and budget_ok and calc['status']=='CALCULATED'
            and p['trial_quantity']>=quote['fields']['moq']
            and p['trial_quantity']%quote['fields']['packaging']['units_per_pack']==0
            and Decimal(str(calc['total_cost']))*p['trial_quantity']<=Decimal(str(p['trial_budget'])))
        reasons=[]
        if not market:reasons.append('缺少已核对、注明时间窗的真实需求数据')
        if len(competitors)<2:reasons.append('至少补齐两条已核对的可比竞品价格与原图')
        if not quote:reasons.append('原工作项尚未选用完整、有效且同币种的正式报价')
        if not economy:reasons.append('完整成本、目标贡献率或试销约束尚未满足')
        if not goods_budget:reasons.append('首测数量须满足报价MOQ与整包装，总投入须覆盖完整计划成本')
        return {'trial_prerequisites_met':not reasons,'gaps':reasons,'scope':'local_selection_only_not_execution_authorization'}

    def review_save(self,case_id,payload,expected_dossier_sha256,idempotency_key,actor):
        self.case(case_id);actor=text(actor,120,True);key=text(idempotency_key,160,True)
        request={'payload':payload,'actor':actor,'dossier_sha256':expected_dossier_sha256};request_sha=digest(canonical(request))
        with self.core.atomic()as db:
            old=db.execute('SELECT document FROM product_evidence_reviews WHERE case_id=? AND idem=?',(case_id,key)).fetchone()
            if old:
                r=json.loads(old[0])
                if r['request_sha256']!=request_sha:raise ValueError('evidence_idempotency_conflict')
                return {'review':{**r,'current':r['dossier_sha256']==self._projection(case_id)['dossier_sha256']},'reused':True}
            d=self.guard(case_id,expected_dossier_sha256)
            if type(payload)is not dict or set(payload)!={'decision','reason','checks'}or payload['decision']not in ('hold','reject','trial'):raise ValueError('evidence_invalid_review')
            reason=text(payload['reason'],5000,True);checks=payload['checks']
            if type(checks)is not dict or set(checks)!=set(CRITERIA):raise ValueError('evidence_invalid_review_checks')
            refs={r['id']for r in d['available_evidence']}
            for row in checks.values():
                if type(row)is not dict or set(row)!={'status','note','evidence_refs'}or row['status']not in ('pending','pass','fail'):raise ValueError('evidence_invalid_review_checks')
                text(row['note'],2000,True)
                if type(row['evidence_refs'])is not list or len(row['evidence_refs'])>30 or any(x not in refs for x in row['evidence_refs']):raise ValueError('evidence_reference_outside_scope')
                if row['status']=='pass'and not row['evidence_refs']:raise ValueError('evidence_reference_required')
            ready=self.readiness(d)
            if payload['decision']=='trial'and(not ready['trial_prerequisites_met']or any(r['status']!='pass'for r in checks.values())):raise ValueError('evidence_trial_not_ready')
            r={'id':'sel_'+uuid.uuid4().hex,'case_id':case_id,'decision':payload['decision'],'reason':reason,'checks':checks,'actor':actor,'at':datetime.now(timezone.utc).isoformat(),'dossier_sha256':expected_dossier_sha256,
                'snapshot':d['_context'],'readiness':ready,'request_sha256':request_sha,'external_execution_allowed':False,'independently_verified':False}
            r['sha256']=digest(canonical(r))
            db.execute('INSERT INTO product_evidence_reviews VALUES(?,?,?,?)',(case_id,r['id'],key,canonical(r)))
            return {'review':{**r,'current':True},'reused':False,'external_execution_allowed':False}

    def invoke(self,name,args):
        operation=name.removeprefix('commerce_product_evidence_')
        if operation.startswith('sourcing_'):return {'channels':self.sourcing.channels,'search':self.sourcing.search,'preview':self.sourcing.preview,'history':self.sourcing.history}[operation.removeprefix('sourcing_')](**args)
        if operation.startswith(('image','upload')):return self.media.invoke(operation,args)
        return {'get':self.get,'operation_get':self.operation_get,'source_get':self.source_get,'origin_open':self.origin_open,'source_save':self.source_save,'proposal_save':self.proposal_save,'review_save':self.review_save}[operation](**args)
