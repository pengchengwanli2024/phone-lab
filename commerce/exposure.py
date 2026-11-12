"""Explicit business coverage and conservative public-signal relationships.

Relations are geometric/country-field checks, never disruption predictions.
No source capture, platform writes, notification, map CDN or geocoding service.
"""
import hashlib
import json
import math
import re
import time
import uuid
from datetime import datetime, timezone

VERSION='exposure-v1'
KINDS=('market','warehouse','route')
EARTH_KM=6371.0  # Spherical approximation, not a transport/risk model.
ITEM_FIELDS=('id','source','source_key','title','url','published','category','country','country_code','location','publisher_alert','collected_at','record_sha256','source_payload_sha256','verification')


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def stamp():return datetime.now(timezone.utc).isoformat()


def point(value):
    if not isinstance(value,dict) or set(value)!={'lat','lon'}:raise ValueError('exposure_invalid_point')
    if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) for k in ('lat','lon')):raise ValueError('exposure_invalid_point')
    if not -90<=value['lat']<=90 or not -180<=value['lon']<=180:raise ValueError('exposure_invalid_point')
    return {k:float(value[k]) for k in ('lat','lon')}


def unit(p):
    lat,lon=math.radians(p['lat']),math.radians(p['lon'])
    return (math.cos(lat)*math.cos(lon),math.cos(lat)*math.sin(lon),math.sin(lat))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def norm(v):return math.sqrt(dot(v,v))
def angle(a,b):return math.atan2(norm(cross(a,b)),dot(a,b))
def distance(a,b):return EARTH_KM*angle(unit(a),unit(b))


def segment_distance(p,a,b):
    p,a,b=unit(p),unit(a),unit(b)
    arc=angle(a,b);normal=cross(a,b);length=norm(normal)
    best=min(angle(p,a),angle(p,b))
    if length<1e-10:return best*EARTH_KM
    normal=tuple(x/length for x in normal)
    projection=tuple(p[i]-dot(p,normal)*normal[i] for i in range(3));length=norm(projection)
    if length>1e-10:
        for sign in (1,-1):
            q=tuple(sign*x/length for x in projection)
            if angle(a,q)+angle(q,b)<=arc+1e-8:best=min(best,angle(p,q))
    return best*EARTH_KM


def normalize(data):
    allowed={'label','kind','country_codes','point','path','radius_km','source_ref','active'}
    if not isinstance(data,dict) or set(data)-allowed:raise ValueError('exposure_invalid_target')
    for key,limit in (('label',60),('source_ref',240)):
        if not isinstance(data.get(key),str) or not 1<=len(data[key].strip())<=limit:raise ValueError('exposure_'+key+'_required')
    kind=data.get('kind')
    if kind not in KINDS:raise ValueError('exposure_invalid_kind')
    active=data.get('active',True)
    if type(active) is not bool:raise ValueError('exposure_invalid_active')
    countries=data.get('country_codes',[])
    if not isinstance(countries,list) or len(countries)>10 or any(not isinstance(c,str) or not re.fullmatch('[A-Za-z]{3}',c) for c in countries):raise ValueError('exposure_invalid_country_codes')
    countries=sorted({c.upper() for c in countries})
    p=data.get('point');path=data.get('path');radius=data.get('radius_km')
    if kind=='market' and (p is not None or path is not None or radius is not None):raise ValueError('exposure_market_uses_country_fields')
    if kind=='warehouse' and path is not None:raise ValueError('exposure_warehouse_uses_point')
    if kind=='route' and p is not None:raise ValueError('exposure_route_uses_path')
    p=point(p) if p is not None else None
    if path is not None:
        if not isinstance(path,list) or not 2<=len(path)<=20:raise ValueError('exposure_invalid_path')
        path=[point(v) for v in path]
        for a,b in zip(path,path[1:]):
            arc=angle(unit(a),unit(b))
            if arc<1e-9 or arc>=math.pi-1e-5:raise ValueError('exposure_ambiguous_path_segment')
    if p is not None or path is not None:
        if type(radius) not in (int,float) or not math.isfinite(radius) or not .1<=radius<=1000:raise ValueError('exposure_radius_required')
        radius=float(radius)
    elif radius is not None:raise ValueError('exposure_geometry_required_for_radius')
    if not countries and p is None and path is None:raise ValueError('exposure_coverage_required')
    return dict(label=data['label'].strip(),kind=kind,country_codes=countries,point=p,path=path,radius_km=radius,source_ref=data['source_ref'].strip(),active=active)


def relation(item,target):
    data=target['data'];code=item.get('country_code')
    code=code.upper() if isinstance(code,str) and re.fullmatch('[A-Za-z]{3}',code) else None
    country='unknown' if not code or not data['country_codes'] else 'match' if code in data['country_codes'] else 'different'
    geometry='unknown';km=None
    try:p=point(item.get('location'))
    except ValueError:p=None
    if p and (data['point'] is not None or data['path'] is not None):
        km=distance(p,data['point']) if data['point'] is not None else min(segment_distance(p,a,b) for a,b in zip(data['path'],data['path'][1:]))
        geometry='inside' if km<=data['radius_km'] else 'outside'
    signal='potential_relation' if country=='match' or geometry=='inside' else 'no_match_in_available_checks' if country=='different' or geometry=='outside' else 'insufficient_data'
    return {'target_id':target['id'],'target_version':target['version'],'target_sha256':target['sha256'],
            'label':data['label'],'kind':data['kind'],'relation':signal,
            'country_check':country,'publisher_country_code':code,'configured_country_codes':data['country_codes'],
            'geometry_check':geometry,'approx_distance_km':round(km,3) if km is not None else None,
            'selected_radius_km':data['radius_km'],'business_impact':'unknown',
            'basis':'explicit_country_field_and_spherical_interest_geometry_not_disruption_model'}


def definitions(schema,string):
    return [
        ('commerce_exposure_targets','读取明确工作项的经营范围；不会自动配置国家或坐标',schema({'case_id':string},['case_id'])),
        ('commerce_exposure_save','保存明确国家/仓库点位/路线兴趣范围，按版本防覆盖；不执行店铺操作',schema({'case_id':string,'data':{'type':'object'},'idempotency_key':string,'target_id':string,'expected_sha256':string},['case_id','data','idempotency_key'])),
        ('commerce_exposure_assess','对选定公开记录和明确工作项计算关联线索并留存凭据；不是风险判断',schema({'case_id':string,'item_id':string,'record_sha256':string},['case_id','item_id'])),
        ('commerce_exposure_get','读取冻结关联凭据及是否已失效；不标为已核实',schema({'assessment_id':string},['assessment_id'])),
        ('commerce_exposure_history','列出当前明确工作项最近20份关联凭据，不触发采集或模型',schema({'case_id':string},['case_id'])),
        ('commerce_exposure_review','按已展示的关联版本创建去重本地复核待办；依据变化拒绝首次派单',schema({'assessment_id':string},['assessment_id'])),
        ('commerce_exposure_export','导出冻结关联凭据与当前有效性；不发送通知',schema({'assessment_id':string},['assessment_id'])),
    ]


class Exposure:
    def __init__(self,service):
        self.service=service;self.core=service.core
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS exposure_targets(id TEXT PRIMARY KEY,case_id TEXT,document TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS exposure_versions(id TEXT,version INTEGER,document TEXT,PRIMARY KEY(id,version))')
            db.execute('CREATE TABLE IF NOT EXISTS exposure_mutations(idem TEXT PRIMARY KEY,request_sha TEXT,result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS exposure_assessments(id TEXT PRIMARY KEY,case_id TEXT,item_id TEXT,document TEXT,created REAL)')

    def invoke(self,name,args):
        methods={'commerce_exposure_targets':self.targets,'commerce_exposure_save':self.save,'commerce_exposure_assess':self.assess,
                 'commerce_exposure_get':self.get,'commerce_exposure_history':self.history,'commerce_exposure_review':self.review,'commerce_exposure_export':self.export}
        return methods[name](**args)

    def case(self,cid):
        try:case=self.service.organization.case(cid)
        except ValueError:raise ValueError('exposure_case_unavailable') from None
        # Currency is unrelated to geographic coverage. Full business identity
        # remains bound, including product/fulfillment and import provenance.
        return {'id':case['id'],'scope':case['scope']}

    def model_case(self,case):
        return {'id':case['id'],'scope':{k:case['scope'].get(k) for k in ('platform','market','fulfillment','sku','inventory_type')},'binding_sha256':digest(case)}

    def rows(self,cid):
        with self.core.db() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT document FROM exposure_targets WHERE case_id=? ORDER BY id',(cid,))]
        for row in rows:
            if row.get('case_id')!=cid or digest({k:v for k,v in row.items() if k!='sha256'})!=row.get('sha256'):
                raise ValueError('exposure_target_integrity_failed')
        return rows

    def history(self,case_id):
        self.case(case_id)
        with self.core.db() as db:rows=db.execute('SELECT id,document,created FROM exposure_assessments WHERE case_id=? ORDER BY created DESC,id LIMIT 20',(case_id,)).fetchall()
        return {'assessments':[{'id':r[0],'title':json.loads(r[1])['source']['title'],'created_at':r[2]} for r in rows]}

    def targets(self,case_id):
        case=self.case(case_id);rows=self.rows(case_id)
        return {'case':self.model_case(case),'targets':[dict(r,scope_current=r['case_binding']==digest(case)) for r in rows],
                'limit_active':12,'automatic_configuration':False}

    def save(self,case_id,data,idempotency_key,target_id=None,expected_sha256=None):
        data=normalize(data)
        if not isinstance(idempotency_key,str) or not idempotency_key.strip() or len(idempotency_key)>160:raise ValueError('invalid_idempotency_key')
        request_sha=digest(dict(case_id=case_id,data=data,target_id=target_id,expected_sha256=expected_sha256))
        with self.service.live.config_lock,self.core.atomic() as db:
            old=db.execute('SELECT request_sha,result FROM exposure_mutations WHERE idem=?',(idempotency_key,)).fetchone()
            if old:
                if old[0]!=request_sha:raise ValueError('idempotency_conflict')
                return {'target':json.loads(old[1]),'reused':True}
            case=self.case(case_id);rows=self.rows(case_id)
            current=next((r for r in rows if r['id']==target_id),None) if target_id else None
            if target_id and not current:raise ValueError('exposure_target_not_found')
            if current and current['sha256']!=expected_sha256:raise ValueError('exposure_target_changed')
            if not current and expected_sha256 is not None:raise ValueError('exposure_invalid_expected_version')
            if not current and len(rows)>=24:raise ValueError('exposure_target_limit')
            active=sum(r['data']['active'] for r in rows if not current or r['id']!=current['id'])
            if data['active'] and active>=12:raise ValueError('exposure_active_target_limit')
            document={'id':target_id or uuid.uuid4().hex,'case_id':case_id,'version':current['version']+1 if current else 1,
                      'case_binding':digest(case),'data':data}
            document['sha256']=digest(document)
            encoded=canonical(document)
            db.execute('INSERT INTO exposure_targets VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',(document['id'],case_id,encoded))
            db.execute('INSERT INTO exposure_versions VALUES (?,?,?)',(document['id'],document['version'],encoded))
            db.execute('INSERT INTO exposure_mutations VALUES (?,?,?)',(idempotency_key,request_sha,encoded))
            return {'target':document,'reused':False}

    def compute(self,case_id,item_id,record_sha256=None):
        case=self.case(case_id);item=self.service.intelligence.store.item(item_id)
        if record_sha256 and item['record_sha256']!=record_sha256:raise ValueError('exposure_source_changed')
        rows=self.rows(case_id);valid=[r for r in rows if r['data']['active'] and r['case_binding']==digest(case)]
        source=next((s for s in self.service.intelligence.sources()['sources'] if s['id']==item['source']),{})
        try:
            when=datetime.fromisoformat(item['collected_at'].replace('Z','+00:00'))
            collected=when.timestamp() if when.tzinfo is not None else None
        except (KeyError,ValueError,TypeError,AttributeError):collected=None
        age=time.time()-collected if collected is not None else None
        source_state={'last_collection':item.get('collected_at'),'collection_stale':age is None or age< -300 or age>21600,
                      'latest_snapshot':bool(item.get('in_latest_snapshot')),'last_attempt_status':source.get('status','unknown')}
        document={'schema':VERSION,'case':self.model_case(case),'source':{k:item.get(k) for k in ITEM_FIELDS},
                  'source_state':source_state,'target_set_sha256':digest([(r['id'],r['sha256']) for r in rows]),
                  'targets':rows,'relations':[relation(item,r) for r in valid],
                  'coverage':{'active_current':len(valid),'inactive':sum(not r['data']['active'] for r in rows),
                              'scope_changed':sum(r['case_binding']!=digest(case) for r in rows)},
                  'business_impact':'unknown','independently_verified':False,
                  'limits':['Country equality is a broad context only; proximity is to the configured interest radius, not a hazard boundary.',
                            'No match in available fields does not establish absence of business impact.',
                            'Route segments use shortest great-circle arcs, not actual roads, shipping lanes, delays or capacity.']}
        return document

    def assess(self,case_id,item_id,record_sha256=None):
        with self.service.live.config_lock,self.core.atomic() as db:
            document=self.compute(case_id,item_id,record_sha256);ident=digest(document)
            db.execute('INSERT OR IGNORE INTO exposure_assessments VALUES (?,?,?,?,?)',(ident,case_id,item_id,canonical(document),time.time()))
        return self.get(ident)

    def frozen(self,ident):
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{64}',ident):raise ValueError('exposure_invalid_assessment_id')
        with self.core.db() as db:row=db.execute('SELECT case_id,item_id,document,created FROM exposure_assessments WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('exposure_assessment_not_found')
        document=json.loads(row[2])
        if digest(document)!=ident or document['case']['id']!=row[0] or document['source']['id']!=row[1]:raise ValueError('exposure_assessment_integrity_failed')
        return row,document

    def current(self,ident):
        row,document=self.frozen(ident)
        try:value=self.compute(row[0],row[1]);return 'current' if digest(value)==ident else 'changed'
        except ValueError:return 'unavailable'

    def get(self,assessment_id):
        row,document=self.frozen(assessment_id)
        with self.core.db() as db:task=db.execute('SELECT * FROM tasks WHERE idempotency_key=?',('exposure-review:'+assessment_id,)).fetchone()
        return {'id':assessment_id,'document':document,'created_at':row[3],'current_status':self.current(assessment_id),
                'checked_at':time.time(),'review_task':self.core.present(task) if task else None,'business_impact':'unknown'}

    @staticmethod
    def projection(result):
        doc=result['document']
        return {'id':result['id'],'case':doc['case'],'source':doc['source'],'source_state':doc['source_state'],
                'coverage':doc['coverage'],'relations':doc['relations'],'current_status':result['current_status'],
                'business_impact':'unknown','independently_verified':False,'limits':doc['limits']}

    def review(self,assessment_id):
        with self.service.live.config_lock,self.core.atomic():return self.review_in_transaction(assessment_id)

    def review_in_transaction(self,assessment_id):
        with self.core.db() as db:
            row,document=self.frozen(assessment_id)
            old=db.execute('SELECT * FROM tasks WHERE idempotency_key=?',('exposure-review:'+assessment_id,)).fetchone()
            if old:return {'task':self.core.present(old),'reused':True,'current_status':self.current(assessment_id),'external_operations_executed':False}
            if self.current(assessment_id)!='current':raise ValueError('exposure_evidence_changed')
            projected=self.projection({'id':assessment_id,'document':document,'current_status':'current'})
            task=self.service.core.invoke('commerce_task_create',{'kind':'analysis','idempotency_key':'exposure-review:'+assessment_id,
                  'input':{'title':'经营关联复核 · '+document['source']['title'][:90],'agent_role':'conductor',
                           'exposure_assessment':assessment_id,'exposure_case':row[0],'evidence':projected,
                           'execution':'not_requested','business_impact':'unknown'}})
            return {'task':task,'reused':False,'current_status':'current','external_operations_executed':False}

    def apply_agent(self,run,proposal):
        ident=proposal['input']['assessment']['id']
        if ident!=run['parameters']['assessment_id']:raise ValueError('agent_exposure_outside_scope')
        with self.service.live.config_lock,self.core.atomic() as db:
            result=self.review_in_transaction(ident)
            db.execute('INSERT OR IGNORE INTO agent_actions VALUES (?,?,?,?)',(run['id'],proposal['id'],result['task']['id'],time.time()))
            return dict(result,execution=None,approval_scope='single_exposure_review')

    def export(self,assessment_id):
        result=self.get(assessment_id)
        document={'assessment_id':assessment_id,'frozen_document':result['document'],'current_status_at_export':result['current_status'],
                  'exported_at':stamp(),'business_impact':'unknown'}
        document['export_sha256']=digest(document)
        return {'filename':'business-association-'+assessment_id[:12]+'.json','content':json.dumps(document,ensure_ascii=False,indent=2),
                'privacy':'contains_explicit_local_business_mapping_not_a_public_release_attachment'}
