"""Immutable local evidence and drafts; deliberately contains no network transport."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlsplit
from .evidence import freeze, recheck, _json

SPECS = {
    'listing':{'sku':'text','title':'text','description':'text','category_id':'text','price':'money','currency':'currency','quantity':'quantity','image_refs':'images'},
    'price':{'sku':'text','price':'money','currency':'currency'},
    'shipping':{'order_ref':'text','package_ref':'text','carrier':'text','tracking_number':'text','quantity':'positive_quantity'},
    'refund':{'order_ref':'text','amount':'money','currency':'currency','reason':'text'},
    'purchase':{'sku':'text','quantity':'positive_quantity','unit_cost':'money','currency':'currency','supplier_ref':'text'},
    'advertising':{'sku':'text','campaign_ref':'text','budget':'money','currency':'currency','market':'text','start_at':'time','end_at':'time'},
    'support':{'conversation_ref':'text','reply':'reply','policy_ref':'text'},
}
TOPICS = {
    '物流与包装':('物流','包装','快递','shipping','delivery','package','достав','упаков'),
    '尺寸与适配':('尺寸','大小','规格','size','fit','dimension','размер'),
    '耐用与质量':('耐用','质量','破损','坏','durable','quality','broken','качеств','сломан'),
    '价格与价值':('价格','贵','便宜','price','value','expensive','цен','дорог'),
    '使用体验':('使用','方便','便携','use','portable','convenient','удоб'),
}

def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value): return hashlib.sha256(encoded(value).encode()).hexdigest()

def text(value, limit=160):
    if type(value) is not str or not value.strip() or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise ValueError('business_invalid_input')
    return value

def stamp(value):
    text(value,60)
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None: raise ValueError()
        return dt.timestamp()
    except (ValueError,OverflowError): raise ValueError('business_invalid_time') from None

def validate_document(doc):
    if type(doc) is not dict or set(doc)!={'schema','kind','scope','label','origin_ref','observed_at','valid_until','synthetic','records'}:
        raise ValueError('business_invalid_document')
    if doc['schema']!='commerce-business-source-v1' or doc['kind'] not in ('reviews','conversation','facts') or type(doc['synthetic']) is not bool:
        raise ValueError('business_invalid_document')
    text(doc['label']);origin=text(doc['origin_ref'],500);scope=doc['scope']
    if origin.startswith('https://'):
        uri=urlsplit(origin)
        if not uri.hostname or uri.username or uri.password or uri.query or uri.fragment:raise ValueError('business_invalid_origin')
    elif not re.fullmatch(r'private-export:[A-Za-z0-9_.-]{1,120}',origin):raise ValueError('business_invalid_origin')
    # Reuse the reviewed strict scope contract without interpreting imported instructions.
    freeze('review',scope,[{'id':'check','version':1,'sha256':'0'*64}],{},doc['synthetic'])
    if scope['platform'] not in ('ozon','tiktok','amazon','mercado','temu','public','local'):
        raise ValueError('business_invalid_platform')
    observed,until=stamp(doc['observed_at']),stamp(doc['valid_until'])
    if observed>time.time()+300 or not observed<until<=observed+31*86400:
        raise ValueError('business_invalid_validity')
    rows=doc['records']
    if type(rows) is not list or not 1<=len(rows)<=1000: raise ValueError('business_invalid_records')
    seen=set()
    for row in rows:
        if type(row) is not dict:raise ValueError('business_invalid_record')
        if doc['kind']=='reviews':
            if set(row)!={'id','text','rating'}:raise ValueError('business_invalid_review')
            text(row['id'],80);text(row['text'],6000)
            if row['rating'] is not None and (type(row['rating']) is not int or not 1<=row['rating']<=5):raise ValueError('business_invalid_rating')
            key=row['id']
        elif doc['kind']=='conversation':
            if set(row)!={'id','role','text'} or row['role'] not in ('buyer','seller','system'):raise ValueError('business_invalid_message')
            text(row['id'],80);text(row['text'],6000);key=row['id']
        else:
            if set(row)!={'key','value'} or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}',text(row['key'],80)):raise ValueError('business_invalid_fact')
            _json(row['value']);key=row['key']
        if key in seen:raise ValueError('business_duplicate_record')
        seen.add(key)
    if len(encoded(doc).encode())>450000:raise ValueError('business_document_too_large')
    return json.loads(encoded(doc))

class BusinessWorkflows:
    def __init__(self,commerce):
        self.commerce=commerce;self.core=commerce.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS business_source_heads(id TEXT PRIMARY KEY,version INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS business_source_versions(id TEXT,version INTEGER,sha256 TEXT,document TEXT,created REAL,PRIMARY KEY(id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS business_drafts(id TEXT PRIMARY KEY,document TEXT,parent_id TEXT,created REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS business_receipts(id TEXT PRIMARY KEY,draft_id TEXT,document TEXT,created REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS business_requests(key TEXT PRIMARY KEY,sha256 TEXT,result TEXT)')

    def _once(self,db,key,payload,make):
        text(key);sha=digest(payload)
        previous=db.execute('SELECT sha256,result FROM business_requests WHERE key=?',(key,)).fetchone()
        if previous:
            if sha!=previous[0]:raise ValueError('business_idempotency_conflict')
            return json.loads(previous[1])
        result=make();db.execute('INSERT INTO business_requests VALUES (?,?,?)',(key,sha,encoded(result)))
        return result

    def source(self,source_id,version=None):
        text(source_id,80)
        if version is not None and (type(version) is not int or version<1):raise ValueError('business_invalid_version')
        with self.core.db() as db:
            head=db.execute('SELECT version FROM business_source_heads WHERE id=?',(source_id,)).fetchone()
            if not head:raise ValueError('business_source_not_found')
            row=db.execute('SELECT version,sha256,document,created FROM business_source_versions WHERE id=? AND version=?',(source_id,version or head[0])).fetchone()
        if not row:raise ValueError('business_source_not_found')
        return {'id':source_id,'version':row[0],'sha256':row[1],'document':json.loads(row[2]),'imported_at':row[3],'current':row[0]==head[0],'provenance':'operator_import_unverified','fresh':stamp(json.loads(row[2])['valid_until'])>time.time()}

    def import_source(self,document,idempotency_key,source_id=None,expected_version=None):
        doc=validate_document(document)
        if (source_id is None)!=(expected_version is None):raise ValueError('business_version_required')
        if expected_version is not None and (type(expected_version) is not int or expected_version<1):raise ValueError('business_invalid_version')
        with self.core.atomic() as db:
            def make():
                ident=source_id or uuid.uuid4().hex
                if source_id:
                    prior=self.source(source_id)
                    if prior['version']!=expected_version:raise ValueError('business_version_conflict')
                    if any(prior['document'][k]!=doc[k] for k in ('kind','scope','synthetic')):raise ValueError('business_scope_immutable')
                version=(expected_version or 0)+1
                db.execute('INSERT INTO business_source_versions VALUES (?,?,?,?,?)',(ident,version,digest(doc),encoded(doc),time.time()))
                db.execute('INSERT OR REPLACE INTO business_source_heads VALUES (?,?)',(ident,version))
                return {'source_id':ident,'version':version,'sha256':digest(doc),'external_execution_allowed':False}
            return self._once(db,idempotency_key,{'action':'import','document':doc,'source_id':source_id,'expected_version':expected_version},make)

    def _selected(self,ids):
        if type(ids) is not list or not 1<=len(ids)<=20 or any(type(x) is not str for x in ids) or len(set(ids))!=len(ids):raise ValueError('business_invalid_sources')
        sources=[self.source(x) for x in sorted(ids)];first=sources[0]['document']
        if any(s['document']['scope']!=first['scope'] or s['document']['synthetic']!=first['synthetic'] for s in sources):raise ValueError('business_scope_mismatch')
        return sources

    @staticmethod
    def _refs(sources): return [{k:s[k] for k in ('id','version','sha256')} for s in sources]

    def _save(self,db,kind,sources,content,parent_id=None):
        first=sources[0]['document']
        envelope=freeze(kind,first['scope'],self._refs(sources),content,first['synthetic'])
        if len(encoded(envelope).encode())>450000:raise ValueError('business_draft_too_large')
        if parent_id:
            parent=self.get(parent_id)['draft']
            if any(parent[k]!=envelope[k] for k in ('kind','scope','synthetic')):raise ValueError('business_scope_mismatch')
        ident=uuid.uuid4().hex
        db.execute('INSERT INTO business_drafts VALUES (?,?,?,?)',(ident,encoded(envelope),parent_id,time.time()))
        return {'draft_id':ident,'draft_sha256':envelope['draft_sha256'],'external_execution_allowed':False}

    def analyze(self,source_ids,idempotency_key):
        with self.core.atomic() as db:
            def make():
                sources=self._selected(source_ids)
                if any(s['document']['kind']!='reviews' for s in sources):raise ValueError('business_reviews_required')
                buckets={name:[] for name in TOPICS};ratings={str(n):0 for n in range(1,6)};missing=0;total=0;unmatched=0
                for s in sources:
                    for row in s['document']['records']:
                        total+=1;rating=row['rating']
                        if rating is None:missing+=1
                        else:ratings[str(rating)]+=1
                        matched=False
                        for name,words in TOPICS.items():
                            if any(w in row['text'].casefold() for w in words):
                                matched=True;buckets[name].append({'source_id':s['id'],'version':s['version'],'record_id':row['id'],'quote':row['text'][:320]})
                        if not matched:unmatched+=1
                content={'method':'keyword_topics_v1','notice':'规则命中，可重复计数；不代表情感、真实用户比例或选品结论。导入资料未独立核实。',
                         'total_records':total,'rating_counts':ratings,'missing_rating':missing,'unmatched':unmatched,
                         'topics':[{'label':name,'count':len(rows),'evidence':rows[:20],'evidence_truncated':len(rows)>20} for name,rows in buckets.items()]}
                return self._save(db,'review',sources,content)
            result=self._once(db,idempotency_key,{'action':'analyze','source_ids':source_ids},make)
        return self.get(result['draft_id'])

    def draft(self,kind,source_ids,content,idempotency_key,parent_id=None):
        if kind not in SPECS:raise ValueError('business_invalid_kind')
        if type(content) is not dict or set(content)!={'fields','citations'} or type(content['fields']) is not dict or type(content['citations']) is not dict:
            raise ValueError('business_invalid_content')
        if set(content['fields'])-set(SPECS[kind]) or set(content['citations'])-set(SPECS[kind]):raise ValueError('business_unknown_field')
        _json(content)
        for c in content['citations'].values():
            if type(c) is not dict or set(c)!={'source_id','key'}:raise ValueError('business_invalid_citation')
            text(c['source_id'],80);text(c['key'],80)
        with self.core.atomic(reuse=True) as db:
            def make():return self._save(db,kind,self._selected(source_ids),content,parent_id)
            result=self._once(db,idempotency_key,{'action':'draft','kind':kind,'source_ids':source_ids,'content':content,'parent_id':parent_id},make)
        return self.get(result['draft_id'])

    def _preflight(self,env,sources):
        by_id={s['id']:s for s in sources};missing=[];invalid=[];uncited=[]
        current=recheck(env,self._refs(sources))
        expired=[s['id'] for s in sources if not s['fresh']]
        if expired and current['status']=='current':current={'status':'stale','changed_ids':expired,'external_execution_allowed':False}
        if env['kind']=='review':
            return dict(current,missing_fields=[],invalid_fields=[],uncited_fields=[],ready_for_local_review=False,semantic_accuracy_verified=False)
        fields=env['content']['fields'];citations=env['content']['citations']
        for name,rule in SPECS[env['kind']].items():
            if name not in fields or fields[name] is None or fields[name]=='':missing.append(name);continue
            value=fields[name]
            try:
                if rule in ('text','reply'):text(value,6000 if rule=='reply' else 3000)
                elif rule=='currency':
                    if type(value) is not str or not re.fullmatch('[A-Z]{3}',value):raise ValueError()
                elif rule in ('quantity','positive_quantity'):
                    if type(value) is not int or not (0 if rule=='quantity' else 1)<=value<=10**8:raise ValueError()
                elif rule=='money':
                    if type(value) is not str or not re.fullmatch(r'\d{1,12}(\.\d{1,4})?',value) or Decimal(value)<=0:raise ValueError()
                elif rule=='time':stamp(value)
                elif rule=='images':
                    if type(value) is not list or not 1<=len(value)<=20:raise ValueError()
                    for image in value:
                        u=urlsplit(text(image,2000))
                        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError()
            except (ValueError,TypeError,InvalidOperation):invalid.append(name)
            if name=='reply':continue # Human-authored prose requires semantic review; not auto verified.
            if env['kind']=='support' and name=='conversation_ref':
                if not any(s['document']['kind']=='conversation' and value==s['document']['scope']['subject_ref'] for s in sources):invalid.append(name)
                continue
            c=citations.get(name,{})
            source=by_id.get(c.get('source_id'))
            facts={r['key']:r['value'] for r in source['document']['records']} if source and source['document']['kind']=='facts' else {}
            if c.get('key') not in facts or encoded(facts.get(c.get('key')))!=encoded(value):uncited.append(name)
        if env['kind']=='advertising' and not any(x in missing+invalid for x in ('start_at','end_at')) and stamp(fields['end_at'])<=stamp(fields['start_at']):invalid.append('end_at')
        scope_known=bool(env['scope']['store_ref']) and env['scope']['platform'] not in ('public','local')
        return dict(current,missing_fields=missing,invalid_fields=sorted(set(invalid)),uncited_fields=uncited,
                    store_scope_known=scope_known,ready_for_local_review=not(missing or invalid or uncited) and scope_known and current['status']=='current',
                    semantic_accuracy_verified=False,platform_rules_verified=False,approval_scope='local_draft_only')

    def get(self,draft_id):
        text(draft_id,80)
        with self.core.db() as db:
            row=db.execute('SELECT document,parent_id,created FROM business_drafts WHERE id=?',(draft_id,)).fetchone()
            if not row:raise ValueError('business_draft_not_found')
            receipts=[json.loads(r[0]) for r in db.execute('SELECT document FROM business_receipts WHERE draft_id=? ORDER BY created,id',(draft_id,))]
        env=json.loads(row[0]);sources=[self.source(s['id']) for s in env['sources']];check=self._preflight(env,sources)
        latest=receipts[-1] if receipts else None
        state='analysis' if env['kind']=='review' else 'ready_for_review' if check['ready_for_local_review'] else 'needs_input'
        if check['status']!='current':state=check['status']
        elif latest:
            state='rejected' if latest['decision']=='rejected' else 'review_expired' if latest['expires_at']<time.time() else 'local_review_recorded'
        return {'id':draft_id,'draft':env,'parent_id':row[1],'created_at':row[2],'status':state,'preflight':check,'receipts':receipts,'external_execution_allowed':False}

    def review(self,draft_id,expected_sha256,decision,confirmed,idempotency_key,note=''):
        if decision not in ('reviewed','rejected') or confirmed is not True:raise ValueError('business_explicit_local_review_required')
        if type(note) is not str or len(note)>1000:raise ValueError('business_invalid_note')
        with self.core.atomic() as db:
            def make():
                d=self.get(draft_id)
                if expected_sha256!=d['draft']['draft_sha256']:raise ValueError('business_draft_changed')
                if d['draft']['kind']=='review':raise ValueError('business_analysis_not_action')
                if decision=='reviewed' and not d['preflight']['ready_for_local_review']:raise ValueError('business_preflight_incomplete')
                receipt={'id':uuid.uuid4().hex,'draft_id':draft_id,'draft_sha256':expected_sha256,'decision':decision,'note':note,
                         'recorded_at':time.time(),'expires_at':time.time()+900,'approval_scope':'local_draft_only','external_execution_allowed':False}
                db.execute('INSERT INTO business_receipts VALUES (?,?,?,?)',(receipt['id'],draft_id,encoded(receipt),receipt['recorded_at']))
                return receipt
            return self._once(db,idempotency_key,{'action':'review','draft_id':draft_id,'sha256':expected_sha256,'decision':decision,'confirmed':confirmed,'note':note},make)

    def listing(self,synthetic):
        if type(synthetic) is not bool:raise ValueError('business_invalid_mode')
        with self.core.db() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM business_source_heads ORDER BY rowid DESC LIMIT 500')]
            drafts=[r[0] for r in db.execute('SELECT id FROM business_drafts ORDER BY created DESC LIMIT 500')]
        sources=[];items=[]
        for ident in ids:
            s=self.source(ident);d=s['document']
            if d['synthetic']==synthetic:sources.append({**{k:s[k] for k in ('id','version','sha256','fresh','provenance')},**{k:d[k] for k in ('kind','scope','label','origin_ref','observed_at','valid_until','synthetic')},'record_count':len(d['records'])})
        for ident in drafts:
            d=self.get(ident);env=d['draft']
            if env['synthetic']==synthetic:items.append({'id':ident,'kind':env['kind'],'scope':env['scope'],'status':d['status'],'created_at':d['created_at'],'draft_sha256':env['draft_sha256']})
        return {'sources':sources,'drafts':items,'synthetic':synthetic,'external_execution_allowed':False,'automatic_platform_intake':False,'notice':'本机导入资料未独立核实；本地审阅不会触发平台写操作。列表最多各500项。'}

    def export(self,draft_id):
        draft=self.get(draft_id)
        sources=[self.source(s['id'],s['version']) for s in draft['draft']['sources']]
        artifact={'schema':'commerce-business-private-evidence-v1','draft':draft,'sources':sources,'contains_private_business_data':True,'external_execution_allowed':False}
        return {'filename':'business-draft-'+draft_id+'.json','content':json.dumps(artifact,ensure_ascii=False,indent=2),'sha256':digest(artifact)}

    def template(self,kind):
        now=datetime.now(timezone.utc);scope={'platform':'ozon','store_ref':'synthetic-store','subject_ref':'synthetic-case'}
        doc={'schema':'commerce-business-source-v1','kind':kind if kind in ('reviews','conversation','facts') else 'facts','scope':scope,
             'label':'合成格式示例，请替换并核对来源','origin_ref':'private-export:synthetic.json','observed_at':now.isoformat(),'valid_until':(now+timedelta(days=1)).isoformat(),'synthetic':True}
        if kind=='reviews':doc['records']=[{'id':'synthetic-review-1','text':'包装完整，尺寸适合旅行。','rating':4}]
        elif kind=='conversation':doc['records']=[{'id':'synthetic-message-1','role':'buyer','text':'请核对商品尺寸是否适用。'}]
        else:
            values={'sku':'synthetic-sku','title':'合成商品','description':'合成说明，需核对规格','category_id':'synthetic-category',
                    'price':'12.50','currency':'USD','quantity':1,'image_refs':['https://example.com/synthetic.png'],
                    'order_ref':'synthetic-order','package_ref':'synthetic-package','carrier':'synthetic-carrier','tracking_number':'synthetic-tracking',
                    'amount':'12.50','reason':'合成售后原因','unit_cost':'5.00','supplier_ref':'synthetic-supplier','campaign_ref':'synthetic-campaign',
                    'budget':'10.00','market':'synthetic-market','start_at':now.isoformat(),'end_at':(now+timedelta(days=1)).isoformat(),
                    'conversation_ref':'synthetic-case','reply':'您好，我们正在核对您咨询的规格，确认后再提供说明。','policy_ref':'synthetic-policy'}
            keys=list(SPECS.get(kind,{'sku':'text','policy_ref':'text'}));doc['records']=[{'key':k,'value':values[k]} for k in keys]
        return {'document':doc,'required_fields':SPECS.get(kind,{}),'draft_content':{'fields':{},'citations':{}},'notice':'这是本项目标准格式；不是平台原始导出。使用脱敏引用，删除昵称、联系方式、地址及凭据。有效期由操作者核对，最长31天。'}

    def invoke(self,name,args):
        handlers={'template':self.template,'import':self.import_source,'list':self.listing,'source_get':self.source,'analyze':self.analyze,'draft':self.draft,'get':self.get,'review':self.review,'export':self.export}
        return handlers[name.removeprefix('commerce_business_')](**args)
