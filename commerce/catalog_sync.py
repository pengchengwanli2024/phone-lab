"""Explicit, bounded store reads into the existing source ledger. No store writes."""
from datetime import datetime, timezone, timedelta
import json
import re
import threading
import uuid
from decimal import Decimal, InvalidOperation
from research import canonical, digest
from product_catalog import public_url
from listing_release_reads import identifier
import ozon_reader

PATHS={'info':'/v3/product/info/list','attributes':'/v4/product/info/attributes','description':'/v1/product/info/description'}
LIMIT=100

def definitions(schema,string):
    return [
        ('commerce_catalog_store_status','读取当前Ozon库存范围和商品资料读取进度；不访问平台',schema()),
        ('commerce_catalog_store_refresh','按当前库存身份有界读取Ozon商品图文属性，保存待核实来源；不改平台、不覆盖人工来源或草稿',schema({'expected_stock_sha256':string,'case_id':string},['expected_stock_sha256'])),
    ]

def rows(raw,key):
    value=raw.get(key)if isinstance(raw,dict)else None
    if type(value)is not list or len(value)>LIMIT or any(type(r)is not dict for r in value):raise ValueError('catalog_sync_response_schema')
    return value

def exact(records,expected,id_key):
    found={}
    for row in records:
        key=identifier(row.get(id_key))
        if key not in expected or row.get('offer_id')!=expected[key]or key in found:raise ValueError('catalog_sync_response_identity')
        found[key]=row
    if set(found)!=set(expected):raise ValueError('catalog_sync_response_incomplete')
    return found

def bounded_text(value,limit):
    if type(value)is not str or len(value)>limit:raise ValueError('catalog_sync_response_schema')
    return value

def facts(info,attribute=None,description=None):
    result={'sku':bounded_text(info['offer_id'],180),'title':bounded_text(info['name'],2000)}
    price=info.get('price');currency=info.get('currency_code')
    if price is not None:
        try:
            if type(price)is not str or len(price)>40 or not Decimal(price).is_finite()or Decimal(price)<0:raise InvalidOperation()
        except InvalidOperation:raise ValueError('catalog_sync_response_schema')from None
        result['price']=price
    if currency is not None:
        if type(currency)is not str or not re.fullmatch('[A-Z]{3}',currency):raise ValueError('catalog_sync_response_schema')
        result['currency']=currency
    for name in ('description_category_id','type_id'):
        if name in info:result['category_id'if name=='description_category_id'else name]=identifier(info[name])
    links=[]
    for name in ('primary_image','images'):
        value=info.get(name,[])
        if type(value)is not list or len(value)>100:raise ValueError('catalog_sync_response_schema')
        for url in value:
            if public_url(url)and url not in links:links.append(url)
    if links:result['image_refs']=links[:20]
    flags=info.get('statuses')
    if flags is not None:
        if type(flags)is not dict:raise ValueError('catalog_sync_response_schema')
        result['platform_status']={k:bounded_text(flags[k],4000)for k in ('status_name','status_description','moderate_status','validation_status')if k in flags}
    if attribute:
        attrs=attribute.get('attributes',[])
        if type(attrs)is not list or len(attrs)>500:raise ValueError('catalog_sync_response_schema')
        result['attributes']=[]
        for a in attrs:
            if type(a)is not dict or type(a.get('values'))is not list or len(a['values'])>100:raise ValueError('catalog_sync_response_schema')
            if any(type(v)is not dict for v in a['values']):raise ValueError('catalog_sync_response_schema')
            result['attributes'].append({'id':identifier(a.get('id')),'complex_id':identifier(a.get('complex_id',0),True),'values':[
                {'dictionary_value_id':identifier(v.get('dictionary_value_id',0),True),'value':bounded_text(v.get('value'),6000)}for v in a['values']if type(v)is dict]})
        for target,keys in (('dimensions',('height','width','depth','dimension_unit')),('weight',('weight','weight_unit'))):
            values={k:attribute[k]for k in keys if k in attribute}
            if values:
                for k,v in values.items():
                    if k.endswith('_unit'):bounded_text(v,20)
                    elif type(v)not in (int,float)or not 0<=v<=10**12:raise ValueError('catalog_sync_response_schema')
                result[target]=values
    if description:result['description']=bounded_text(description.get('description'),60000)
    return result

class CatalogSync:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.live=service.live
        self.reader=ozon_reader.post;self.lock=threading.Lock();self.stopping=threading.Event();self.thread=None;self.current=None

    @staticmethod
    def connection(config):return digest(canonical([config.get('connection_id'),config.get('ozon_client_id'),config.get('ozon_api_key')]))

    def context(self):
        config=self.live.config();snapshot=self.live.snapshot(config.get('connection_id',''),'stock')
        return config,snapshot

    def status(self):
        config,snapshot=self.context();job=self.current
        return dict(configured=bool(config.get('ozon_client_id')and config.get('ozon_api_key')),stock_sha256=snapshot['sha256']if snapshot else None,
            stock_fresh=bool(snapshot and self.live._fresh(snapshot,config)),product_count=len(snapshot['data']['records'])if snapshot else 0,max_products=LIMIT,
            refresh={k:v for k,v in job.items()if k!='connection'}if job and job['connection']==self.connection(config)else None,external_execution_allowed=False)

    def detail(self,case_id):
        """Read actual API evidence, never imported/operator-supplied fact documents."""
        case=self.service.organization.case(case_id);scope=case['scope'];config=self.live.config()
        if scope.get('synthetic')or scope.get('platform')!='ozon':return None
        found=[]
        for kind in ('catalog-details:'+case_id,'catalog-details:inventory'):
            snapshot=self.live.snapshot(config.get('connection_id',''),kind)
            if not snapshot:continue
            if digest(canonical(snapshot['data']))!=snapshot['sha256']:raise ValueError('catalog_sync_snapshot_integrity')
            row=snapshot['data'].get('records',{}).get(scope.get('product_id'))
            if row and row.get('sku')==scope.get('sku'):found.append((snapshot,row))
        if not found:return None
        snapshot,row=max(found,key=lambda pair:pair[0]['observed_at'])
        return dict(record=row,snapshot_id=snapshot['id'],sha256=snapshot['sha256'],observed_at=snapshot['observed_at'],fresh=self.live._fresh(snapshot,config))

    def check(self,config,stock_sha):
        current,snapshot=self.context()
        if self.stopping.is_set():raise ValueError('catalog_sync_interrupted')
        if self.connection(current)!=self.connection(config):raise ValueError('catalog_sync_connection_changed')
        if not snapshot or not self.live._fresh(snapshot,current):raise ValueError('catalog_sync_fresh_stock_required')
        if snapshot['sha256']!=stock_sha:raise ValueError('catalog_sync_stock_changed')
        if digest(canonical(snapshot['data']))!=stock_sha:raise ValueError('catalog_sync_stock_integrity')
        return snapshot

    def refresh(self,expected_stock_sha256,case_id=None):
        config,snapshot=self.context()
        if not config.get('ozon_client_id')or not config.get('ozon_api_key'):raise ValueError('configure_ozon_first')
        snapshot=self.check(config,expected_stock_sha256)
        expected={identifier(r['product_id']):r['offer_id']for r in snapshot['data']['records']if r.get('offer_id')}
        if case_id:
            case=self.service.organization.case(case_id);scope=case['scope']
            if scope.get('synthetic')or scope.get('platform')!='ozon'or expected.get(scope.get('product_id'))!=scope.get('sku'):raise ValueError('catalog_sync_scope')
            expected={scope['product_id']:scope['sku']}
        if not expected or len(expected)>LIMIT:raise ValueError('catalog_sync_inventory_limit')
        if not self.lock.acquire(False):raise ValueError('catalog_sync_busy')
        self.current=dict(id=uuid.uuid4().hex,status='running',connection=self.connection(config),case_id=case_id,product_count=len(expected),imported_cases=0,issues=[])
        self.thread=threading.Thread(target=self.run,args=(self.current.copy(),config,expected_stock_sha256,expected),daemon=True,name='ozon-catalog-read')
        try:self.thread.start()
        except Exception:self.lock.release();raise
        return self.status()['refresh']

    def read(self,job,config,stock_sha,resource,body):
        self.check(config,stock_sha);sha=None;error=None
        try:
            raw,sha=self.reader(PATHS[resource],body,config['ozon_client_id'],config['ozon_api_key'])
            return raw,sha
        except Exception as exc:
            error=exc.code if isinstance(exc,ozon_reader.ConnectionIssue)else'catalog_sync_read_failed'
            raise ValueError(error)from None
        finally:
            with self.core.db()as db:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at)VALUES(?,?,?,?,?,?)',
                (job['id'],PATHS[resource],digest(canonical(body)),sha,error,datetime.now(timezone.utc).isoformat()))

    def run(self,job,config,stock_sha,expected):
        try:
            raw,sha=self.read(job,config,stock_sha,'info',{'product_id':[int(x)for x in expected]})
            info=exact(rows(raw,'items'),expected,'id');attributes={};descriptions={};evidence={'info':sha};issues=[]
            for resource in ('attributes',*(['description']if job['case_id']else[])):
                try:
                    body={'filter':{'product_id':list(expected),'visibility':'ALL'},'limit':LIMIT}if resource=='attributes'else{'product_id':int(next(iter(expected)))}
                    raw,sha=self.read(job,config,stock_sha,resource,body)
                    projected=exact(rows(raw,'result')if resource=='attributes'else[raw.get('result')],expected,'id')
                    if resource=='attributes':attributes=projected
                    else:descriptions=projected
                    evidence[resource]=sha
                except ValueError as exc:
                    if str(exc).startswith(('catalog_sync_connection_','catalog_sync_stock_','catalog_sync_fresh_','catalog_sync_interrupted')):raise
                    issues.append({'resource':resource,'error':str(exc)if str(exc).startswith(('catalog_sync_','ozon_'))else'catalog_sync_response_schema'})
            records={key:facts(row,attributes.get(key),descriptions.get(key))for key,row in info.items()}
            count=0;now=datetime.now(timezone.utc)
            with self.live.config_lock,self.core.atomic():
                self.check(config,stock_sha)
                if not job['case_id']:self.service.organization.import_inventory()
                cases=[c for c in self.service.organization.cases()if c['scope'].get('product_id')in expected and not c['scope'].get('synthetic')and c['scope'].get('sku')==expected[c['scope']['product_id']]]
                if job['case_id']:cases=[c for c in cases if c['id']==job['case_id']]
                for case in cases:
                    key=case['scope']['product_id'];values=dict(records[key]);origin='private-export:ozon-'+case['id']
                    existing=[s for s in self.service.business.listing(False)['sources']if s['scope']['subject_ref']==case['id']and self.service.business.source(s['id'])['document']['origin_ref']==origin]
                    if len(existing)>1:raise ValueError('catalog_sync_source_ambiguous')
                    prior=self.service.business.source(existing[0]['id'])if existing else None
                    # A list refresh must not erase a previously collected description.
                    until=now+timedelta(hours=6)
                    if 'description'not in values and prior and prior['fresh']:
                        old={r['key']:r['value']for r in prior['document']['records']}
                        if old.get('description'):
                            values['description']=old['description']
                            values['retained_description_ref']={k:prior[k]for k in ('id','version','sha256')}
                            until=min(until,datetime.fromisoformat(prior['document']['valid_until']))
                    values['ozon_api_evidence']={'product_id':key,'response_sha256':evidence,'independently_verified':False}
                    doc=dict(schema='commerce-business-source-v1',kind='facts',scope={'platform':'ozon','store_ref':'ozon-live','subject_ref':case['id']},
                        label='Ozon 商品资料 · 平台返回待核实',origin_ref=origin,observed_at=now.isoformat(),valid_until=until.isoformat(),synthetic=False,
                        records=[{'key':k,'value':v}for k,v in sorted(values.items())])
                    # Observation hashes changing alone must not invalidate edited drafts.
                    previous={r['key']:r['value']for r in prior['document']['records']}if prior else None
                    if prior and prior['fresh']and {k:v for k,v in previous.items()if k not in ('ozon_api_evidence','retained_description_ref')}=={k:v for k,v in values.items()if k not in ('ozon_api_evidence','retained_description_ref')}:continue
                    self.service.business.import_source(doc,'catalog:'+digest(canonical(doc)),source_id=prior['id']if prior else None,expected_version=prior['version']if prior else None,_reuse=True)
                    count+=1
                snapshot=dict(records=records,issues=issues,evidence=evidence,case_id=job['case_id'],stock_sha256=stock_sha)
                with self.core.db()as db:
                    kind='catalog-details:'+ (job['case_id']or'inventory');encoded=canonical(snapshot);ident=uuid.uuid4().hex
                    db.execute('INSERT INTO live_snapshots VALUES (?,?,?,?,?,?)',(ident,config['connection_id'],kind,encoded,digest(encoded),now.isoformat()))
                    db.execute('INSERT OR REPLACE INTO live_latest VALUES (?,?,?)',(config['connection_id'],kind,ident))
            self.current={**job,'status':'partial'if issues else'succeeded','imported_cases':count,'issues':issues,'finished_at':now.isoformat()}
        except Exception as exc:
            code=str(exc)
            self.current={**job,'status':'failed','error':code if isinstance(exc,ValueError)and code.startswith(('catalog_sync_','ozon_'))else'catalog_sync_failed'}
        finally:self.lock.release()

    def invoke(self,name,args):return (self.status if name.endswith('_status')else self.refresh)(**args)
    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=1)
