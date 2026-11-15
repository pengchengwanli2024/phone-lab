"""Ozon metadata and limited structural checks over original private ledgers.

Only explicit refresh performs an upstream read. No import, offer, price or
inventory write endpoint belongs to this module.
"""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
import json
import re
import threading
import time
import uuid
from research import canonical,digest
import ozon_reader
from ozon_listing_schema import PATHS,ident,project

TTL=6*3600


def definitions(schema,string):
    target={'case_id':string,'platform':string,'store_ref':{'type':'string','maxLength':100},'market':{'type':'string','maxLength':2}}
    ids={k:{'type':'integer','minimum':0,'maximum':2**53-1}for k in ('category_id','type_id','attribute_id','last_value_id')}
    return [
        ('commerce_listing_schema_get','只读原店铺类目/类型与属性字典快照，检查所填结构；不证明平台规则、资质或发布成功',schema({**target,**ids,'query':{'type':'string','maxLength':100},'offset':{'type':'integer','minimum':0},'payload':{'type':'object'}},list(target))),
        ('commerce_listing_schema_refresh','明确读取Ozon类目、属性或单页字典并留存原快照；不修改平台商品',schema({**target,**ids,'resource':{'type':'string','enum':list(PATHS)}},[*target,'resource'])),
    ]


class ListingSchema:
    def __init__(self,service):
        self.service=service;self.core=service.core;self.live=service.live
        self.reader=ozon_reader.post;self.lock=threading.Lock();self.current=None
        self.stopping=threading.Event();self.thread=None

    def invoke(self,name,args):
        return {'commerce_listing_schema_get':self.get,'commerce_listing_schema_refresh':self.refresh}[name](**args)

    @staticmethod
    def connection(config):
        return 'ozon-schema:'+digest(canonical([config.get('connection_id'),config.get('ozon_client_id'),config.get('ozon_api_key')]))[:32]

    def context(self,target,synthetic):
        if target['platform']!='ozon'or target['store_ref']!='ozon-live'or target['market']!='RU':return None,'scope_not_supported'
        if synthetic:return 'synthetic-listing-schema',None
        c=self.live.config()
        if not c.get('ozon_client_id')or not c.get('ozon_api_key'):return None,'missing_connection'
        return self.connection(c),None

    @staticmethod
    def kind(resource,category=0,typ=0,attribute=0,cursor=0):
        if resource=='tree':return 'listing-schema:tree:RU'
        return ':'.join(map(str,['listing-schema',resource,'RU',category,typ,*([attribute,cursor]if resource=='values'else[])]))

    def cache(self,connection,resource,category=0,typ=0,attribute=0,cursor=0):
        if not connection:return None
        cached=self.live.snapshot(connection,self.kind(resource,category,typ,attribute,cursor))
        if not cached:return None
        if digest(canonical(cached['data']))!=cached['sha256']:raise ValueError('listing_schema_integrity_failed')
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(cached['observed_at'])).total_seconds()
            cached['fresh']=0<=age<=TTL
        except (TypeError,ValueError):raise ValueError('listing_schema_integrity_failed')from None
        return cached

    def dictionary(self,connection,category,typ,attribute):
        prefix=self.kind('values',category,typ,attribute,0).rsplit(':',1)[0]+':'
        with self.core.db()as db:
            kinds=[r[0]for r in db.execute('SELECT kind FROM live_latest WHERE connection=?AND kind LIKE ?',(connection,prefix+'%'))]
        return [self.cache(connection,'values',category,typ,attribute,int(k.rsplit(':',1)[1]))for k in kinds]

    def evaluate(self,target,payload,synthetic):
        try:return self._evaluate(target,payload,synthetic)
        except ValueError as exc:
            if str(exc)!='listing_schema_integrity_failed':raise
            return dict(status='invalid_schema',issues=[],references=[],scope='category_and_simple_attributes_only',professional_approval=False,platform_submission_verified=False)

    def _evaluate(self,target,payload,synthetic):
        connection,error=self.context(target,synthetic)
        result=dict(status=error or 'missing_category_tree',issues=[],references=[],scope='category_and_simple_attributes_only',
                    professional_approval=False,platform_submission_verified=False)
        if error:return result
        tree=self.cache(connection,'tree')
        if not tree:return result
        result['references'].append(tree['sha256'])
        if not tree['fresh']:result['status']='stale_schema';return result
        raw=payload['fields']['category_id'];category=int(raw)if re.fullmatch('[1-9][0-9]{0,15}',raw or '')else 0
        typ=payload.get('ozon',{}).get('type_id',0)
        if not category or not typ:result['status']='missing_type';return result
        choice=next((r for r in tree['data']['records']if r['category_id']==category and r['type_id']==typ),None)
        if not choice:result['status']='invalid_type';return result
        if choice['disabled']:result['status']='disabled_type';return result
        attributes=self.cache(connection,'attributes',category,typ)
        if not attributes:result['status']='missing_attributes';return result
        result['references'].append(attributes['sha256'])
        tree_kind=self.kind('tree')
        if not attributes['fresh']or attributes['data']['parent_references'].get(tree_kind)!=tree['sha256']:result['status']='stale_schema';return result
        supplied={r['id']:r for r in payload.get('ozon',{}).get('attributes',[])}
        schemas={r['id']:r for r in attributes['data']['records']};issues=[]
        def issue(key,code):issues.append(dict(attribute_id=key,code=code,name=schemas.get(key,{}).get('name',str(key))))
        for key,s in schemas.items():
            row=supplied.get(key)
            if not row:
                if s['is_required']:issue(key,'required')
                continue
            if s['complex_id']:issue(key,'complex_not_assessed')
            if not row['source_ref'].strip():issue(key,'source_required')
            if (not s['is_collection']and len(row['values'])>1)or(s['max_value_count']and len(row['values'])>s['max_value_count']):issue(key,'too_many_values')
            if s['dictionary_id']:
                pages=self.dictionary(connection,category,typ,key)
                pages=[p for p in pages if p['fresh']and p['data']['parent_references'].get(self.kind('attributes',category,typ))==attributes['sha256']]
                known={v['id']:v['value']for page in pages for v in page['data']['records']}
                result['references'].extend(page['sha256']for page in pages)
                for v in row['values']:
                    if not v['dictionary_value_id']or known.get(v['dictionary_value_id'])!=v['value']:issue(key,'dictionary_value_not_current')
            else:
                for v in row['values']:
                    if v['dictionary_value_id']:issue(key,'unexpected_dictionary_id')
                    text=v['value'].strip()
                    if not text:issue(key,'empty_value');continue
                    kind=s['type'].lower()
                    if kind in ('integer','int')and not re.fullmatch(r'[+-]?[0-9]+',text):issue(key,'invalid_integer')
                    elif kind in ('decimal','number','float'):
                        try:
                            if not Decimal(text).is_finite():raise InvalidOperation()
                        except InvalidOperation:issue(key,'invalid_number')
                    elif kind in ('boolean','bool')and text.lower()not in ('true','false'):issue(key,'invalid_boolean')
                    elif kind not in ('string','integer','int','decimal','number','float','boolean','bool'):issue(key,'type_not_assessed')
        for key in supplied.keys()-schemas.keys():issue(key,'unknown_attribute')
        result.update(status='incomplete'if issues else'limited_check_passed',issues=issues,references=sorted(set(result['references'])))
        return result

    @staticmethod
    def summary(cached):
        return dict(sha256=cached['sha256'],observed_at=cached['observed_at'],fresh=cached['fresh'])if cached else dict(sha256=None,observed_at=None,fresh=False)

    def get(self,case_id,platform,store_ref,market,query='',offset=0,category_id=0,type_id=0,attribute_id=0,last_value_id=0,payload=None):
        from listing_workspace import validate_payload
        if not isinstance(query,str)or len(query)>100 or type(offset)is not int or not 0<=offset<=50000:raise ValueError('listing_schema_invalid_query')
        for value in (category_id,type_id,attribute_id,last_value_id):ident(value,True)
        plan=self.service.listings.get(case_id,platform,store_ref,market);target=plan['target']
        payload=validate_payload(payload)if payload is not None else plan['payload']
        raw=payload['fields']['category_id'];category_id=category_id or(int(raw)if re.fullmatch('[1-9][0-9]{0,15}',raw or '')else 0)
        type_id=type_id or payload.get('ozon',{}).get('type_id',0)
        connection,_=self.context(target,plan['synthetic']);tree=self.cache(connection,'tree')
        categories=[r for r in tree['data']['records']if query.casefold()in r['path'].casefold()or query in str(r['category_id'])or query in str(r['type_id'])]if tree else[]
        attrs=self.cache(connection,'attributes',category_id,type_id)if category_id and type_id else None
        values=self.cache(connection,'values',category_id,type_id,attribute_id,last_value_id)if attribute_id and category_id and type_id else None
        refresh=self.current
        refresh={k:v for k,v in refresh.items()if k!='connection'}if refresh and refresh['connection']==connection else None
        return dict(target=target,categories={**self.summary(tree),'items':categories[offset:offset+50],'total':len(categories),'offset':offset,'next_offset':offset+50 if offset+50<len(categories)else None},
            attributes={**self.summary(attrs),'items':attrs['data']['records']if attrs else[]},
            values={**self.summary(values),'items':values['data']['records']if values else[],'has_next':values['data']['has_next']if values else False,'next_cursor':values['data']['next_cursor']if values else None},
            validation=self.evaluate(target,payload,plan['synthetic']),refresh=refresh,synthetic=plan['synthetic'],external_execution_allowed=False)

    def refresh(self,case_id,platform,store_ref,market,resource,category_id=0,type_id=0,attribute_id=0,last_value_id=0):
        if resource not in PATHS:raise ValueError('listing_schema_invalid_resource')
        for value in (category_id,type_id,attribute_id,last_value_id):ident(value,True)
        plan=self.service.listings.get(case_id,platform,store_ref,market);target=plan['target']
        connection,error=self.context(target,plan['synthetic'])
        if error:raise ValueError('listing_schema_'+error if error=='scope_not_supported'else'configure_ozon_first')
        if plan['synthetic']:raise ValueError('listing_schema_demo_no_network')
        body={'language':'RU'};parents={}
        if resource!='tree':
            ident(category_id);ident(type_id);tree=self.cache(connection,'tree')
            if not tree or not tree['fresh']:raise ValueError('listing_schema_refresh_tree_first')
            match=next((r for r in tree['data']['records']if r['category_id']==category_id and r['type_id']==type_id and not r['disabled']),None)
            if not match:raise ValueError('listing_schema_invalid_type')
            parents[self.kind('tree')]=tree['sha256']
            body.update(description_category_id=category_id,type_id=type_id)
        if resource=='values':
            ident(attribute_id);attrs=self.cache(connection,'attributes',category_id,type_id)
            if not attrs or not attrs['fresh']or attrs['data']['parent_references']!=parents or not any(r['id']==attribute_id and r['dictionary_id']for r in attrs['data']['records']):raise ValueError('listing_schema_dictionary_unavailable')
            parents[self.kind('attributes',category_id,type_id)]=attrs['sha256']
            if last_value_id and not any(p['data']['next_cursor']==last_value_id for p in self.dictionary(connection,category_id,type_id,attribute_id)if p['fresh']and p['data']['parent_references']==parents):raise ValueError('listing_schema_invalid_cursor')
            body.update(attribute_id=attribute_id,last_value_id=last_value_id,limit=100)
        if self.stopping.is_set():raise ValueError('listing_schema_stopped')
        if not self.lock.acquire(blocking=False):raise ValueError('listing_schema_refresh_busy')
        self.current=dict(id=uuid.uuid4().hex,status='running',resource=resource,category_id=category_id,type_id=type_id,attribute_id=attribute_id,last_value_id=last_value_id,connection=connection,error=None)
        config=self.live.config();job=self.current.copy()
        if self.connection(config)!=connection:
            self.current={**job,'status':'failed','error':'listing_schema_connection_changed'};self.lock.release()
            raise ValueError('listing_schema_connection_changed')
        self.thread=threading.Thread(target=self.run,args=(job,config,body,parents),daemon=True,name='ozon-listing-schema')
        try:self.thread.start()
        except Exception:self.lock.release();raise
        return {k:v for k,v in job.items()if k!='connection'}

    def run(self,job,config,body,parents):
        path=PATHS[job['resource']];response_sha=None;error=None
        try:
            payload,response_sha=self.reader(path,body,config['ozon_client_id'],config['ozon_api_key'])
            normalized=project(job['resource'],payload)
            if job['resource']=='values'and normalized['has_next']and normalized['next_cursor']<=job['last_value_id']:raise ValueError('listing_schema_invalid_cursor')
            normalized.update(endpoint=path,parameters=body,response_sha256=response_sha,parent_references=parents)
            with self.live.config_lock,self.core.atomic()as db:
                if self.stopping.is_set():raise ValueError('listing_schema_interrupted')
                if self.connection(self.live.config())!=job['connection']:raise ValueError('listing_schema_connection_changed')
                for kind,expected in parents.items():
                    row=db.execute('SELECT s.sha FROM live_latest l JOIN live_snapshots s ON s.id=l.snapshot WHERE l.connection=?AND l.kind=?',(job['connection'],kind)).fetchone()
                    if not row or row[0]!=expected:raise ValueError('listing_schema_parent_changed')
                encoded=canonical(normalized);sha=digest(encoded);stamp=datetime.now(timezone.utc).isoformat();snapshot=uuid.uuid4().hex
                kind=self.kind(job['resource'],job['category_id'],job['type_id'],job['attribute_id'],job['last_value_id'])
                db.execute('INSERT INTO live_snapshots VALUES (?,?,?,?,?,?)',(snapshot,job['connection'],kind,encoded,sha,stamp))
                db.execute('INSERT OR REPLACE INTO live_latest VALUES (?,?,?)',(job['connection'],kind,snapshot))
            self.current={**job,'status':'succeeded','count':len(normalized['records']),'snapshot_sha256':sha}
        except Exception as exc:
            allowed=('listing_schema_','ozon_','unexpected_response_schema','response_too_large')
            code=exc.code if isinstance(exc,ozon_reader.ConnectionIssue)else str(exc)
            error=code if isinstance(exc,(ValueError,ozon_reader.ConnectionIssue))and code.startswith(allowed)else'listing_schema_read_failed'
            self.current={**job,'status':'failed','error':error}
        finally:
            try:
                with self.core.db()as db:db.execute('INSERT INTO live_http(job,endpoint,request_sha,response_sha,error,at)VALUES(?,?,?,?,?,?)',(job['id'],path,digest(canonical(body)),response_sha,error,datetime.now(timezone.utc).isoformat()))
            finally:self.lock.release()

    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=1)
