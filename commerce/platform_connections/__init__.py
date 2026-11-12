"""Private multi-store configuration and explicit, bounded read jobs.

No periodic sync, business writes, notification or automatic OAuth renewal.
The existing Ozon adapter and its configuration are not modified.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import fcntl
import json
import os
import re
import tempfile
import threading
import time
import uuid
import webbrowser
from . import protocols as api

VERSION='platform-read-v1'
ACTIVE=('queued','running','cancel_requested')


def definitions(schema,string):
 return [
  ('commerce_platform_catalog','四个平台只读范围与接入要求；不代表已授权或已验收',schema()),
  ('commerce_platform_list','读取多店铺接入与快照状态，不返回凭据或触发同步',schema()),
  ('commerce_platform_status','读取指定店铺缺项、版本与快照状态，不调用平台',schema({'store_id':string},['store_id'])),
  ('commerce_platform_sync','明确请求一次有界平台读取；不改店铺，分页不全不覆盖旧快照',schema({'store_id':string,'resource':{'type':'string','enum':['orders','products','stock']},'expected_revision':string,'idempotency_key':string,'window_days':{'type':'integer','minimum':1,'maximum':30},'max_pages':{'type':'integer','minimum':1,'maximum':5}},['store_id','resource','expected_revision','idempotency_key'])),
  ('commerce_platform_job','读取只读作业回执；结果未知不自动重发',schema({'job_id':string},['job_id'])),
  ('commerce_platform_cancel','取消尚未结束的本地读取；已发请求可能已被平台处理',schema({'job_id':string},['job_id'])),
  ('commerce_platform_snapshot','读取所选店铺和资源的当前版本快照；旧版或陈旧不视为有效',schema({'store_id':string,'resource':{'type':'string','enum':['orders','products','stock']}},['store_id','resource'])),
  ('commerce_platform_export','导出所选私有业务快照与读取证据，不作为公开附件',schema({'store_id':string,'resource':{'type':'string','enum':['orders','products','stock']}},['store_id','resource'])),
  ('commerce_platform_open_setup','在本机浏览器打开多平台私有接入向导，凭据不经聊天或MCP',schema()),
 ]


class PlatformConnections:
 def __init__(self,service,request=api.network):
  self.service=service;self.core=service.core;self.request=request;self.owner=uuid.uuid4().hex
  self.directory=service.state/'platform-connections';self.directory.mkdir(mode=0o700,exist_ok=True);self.directory.chmod(0o700)
  self.path=self.directory/'config.json';self.lock=threading.RLock();self.threads={};self.stopping=threading.Event()
  with self.core.db()as db:
   db.execute('CREATE TABLE IF NOT EXISTS platform_jobs(id TEXT PRIMARY KEY,idem TEXT UNIQUE,request TEXT,store_id TEXT,resource TEXT,revision TEXT,status TEXT,document TEXT,expires REAL)')
   db.execute('CREATE TABLE IF NOT EXISTS platform_snapshots(id TEXT PRIMARY KEY,store_id TEXT,resource TEXT,revision TEXT,document TEXT,created REAL)')
   db.execute('CREATE TABLE IF NOT EXISTS platform_latest(store_id TEXT,resource TEXT,snapshot_id TEXT,PRIMARY KEY(store_id,resource))')
  self.recover()

 def recover(self):
  with self.core.db()as db:
   for ident,encoded in db.execute("SELECT id,document FROM platform_jobs WHERE status IN ('queued','running','cancel_requested')AND expires<?",(time.time(),)).fetchall():
    job=json.loads(encoded);job.update(status='unknown',error='platform_interrupted_outcome_unknown',finished_at=time.time())
    db.execute('UPDATE platform_jobs SET status=?,document=? WHERE id=?',('unknown',api.encoded(job),ident))

 @contextmanager
 def configs(self,write=False):
  with self.lock:
   lock_path=self.directory/'config.lock';fd=os.open(lock_path,os.O_CREAT|os.O_RDWR,0o600)
   with os.fdopen(fd,'a+')as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    values=json.loads(self.path.read_text())if self.path.exists()else{}
    yield values
    if write:
     fd,name=tempfile.mkstemp(prefix='config-',dir=self.directory)
     try:
      with os.fdopen(fd,'w')as out:json.dump(values,out,ensure_ascii=False);out.flush();os.fsync(out.fileno())
      os.replace(name,self.path)
     finally:
      if os.path.exists(name):os.unlink(name)

 def config(self,store_id):
  with self.configs()as values:
   if store_id not in values:raise api.Issue('platform_connection_not_found')
   return deepcopy(values[store_id])

 def configure(self,data):
  """Private HTTP only. This method is deliberately absent from MCP."""
  api.require(isinstance(data,dict),'platform_invalid_configuration')
  p=data.get('platform');api.require(p in api.CATALOG,'platform_invalid_provider');spec=api.CATALOG[p]
  allowed={'store_id','expected_revision','platform','label','market','region','enabled','scope_reviewed',*spec['secrets'],*spec['fields']}
  api.require(not set(data)-allowed,'platform_invalid_configuration');ident=data.get('store_id')
  api.require(isinstance(ident,str)and bool(re.fullmatch('[a-f0-9]{32}',ident)),'platform_invalid_connection_id')
  with self.configs(write=True)as values:
   old=values.get(ident)
   api.require(not old or old['platform']==p,'platform_provider_immutable')
   expected=data.get('expected_revision')
   api.require((old and old['revision']==expected)or(not old and expected is None),'platform_configuration_changed')
   api.require(old or len(values)<20,'platform_connection_limit')
   result={k:data.get(k)for k in ('platform','label','market','region','enabled','scope_reviewed')}
   api.require(isinstance(result['label'],str)and 1<=len(result['label'].strip())<=60,'platform_label_required');result['label']=result['label'].strip()
   api.require(not any(ord(c)<32 for c in result['label']),'platform_invalid_configuration')
   api.require(isinstance(result['market'],str)and bool(re.fullmatch('[A-Z]{2}',result['market'])),'platform_market_required')
   api.require(result['region']in spec['regions'],'platform_invalid_region')
   api.require(type(result['enabled'])is bool and type(result['scope_reviewed'])is bool,'platform_invalid_configuration')
   for field in spec['fields']:
    value=data.get(field);pattern=r'[A-Z0-9]{5,24}'if field=='marketplace_id'else r'[1-9][0-9]{0,19}'
    api.require(isinstance(value,str)and bool(re.fullmatch(pattern,value)),'platform_scope_field_required');result[field]=value
   for field in spec['secrets']:
    value=data.get(field)or(old or{}).get(field,'')
    api.require(isinstance(value,str)and len(value)<=4096 and (not value or value.isascii()and all(32<ord(c)<127 for c in value)),'platform_invalid_credential')
    result[field]=value
   result.update(store_id=ident,revision=uuid.uuid4().hex,updated_at=time.time())
   values[ident]=result
  return self.status(ident)

 @staticmethod
 def catalog():return {'schema':VERSION,'providers':[dict(id=k,**v)for k,v in api.CATALOG.items()],
                       'ozon':'existing_independent_read_connector','automatic_sync':False,'automatic_token_renewal':False,'business_writes':False,
                       'limits':{'normalized_records_per_job':api.MAX_RECORDS,'normalized_records_json_bytes':api.LIMIT_PROJECTION_BYTES}}

 def invoke(self,name,args):
  names={'commerce_platform_catalog':self.catalog,'commerce_platform_list':self.listing,'commerce_platform_status':self.status,
         'commerce_platform_sync':self.sync,'commerce_platform_job':self.job,'commerce_platform_cancel':self.cancel,
         'commerce_platform_snapshot':self.snapshot,'commerce_platform_export':self.export,'commerce_platform_open_setup':self.open_setup}
  return names[name](**args)

 def metadata(self,c):
  missing=[k for k in api.CATALOG[c['platform']]['secrets']if not c.get(k)]
  return {**{k:c[k]for k in ('store_id','revision','platform','label','market','region','enabled','scope_reviewed','updated_at')},
          **{k:c[k]for k in api.CATALOG[c['platform']]['fields']},'configured':not missing,'missing_fields':missing,
          'credential_presence':{k:bool(c.get(k))for k in api.CATALOG[c['platform']]['secrets']},
          'resources':api.CATALOG[c['platform']]['resources'],'scope_authority':'operator_provided_not_independently_verified',
          'automatic_sync':False,'automatic_token_renewal':False,'business_accepted':False}

 def listing(self):
  self.recover()
  with self.configs()as values:ids=list(values)
  return {'stores':[self.status(i)for i in ids],'schema':VERSION,'automatic_sync':False,'business_writes':False}

 def summary(self):
  stores=self.listing()['stores'];result={}
  for provider in api.CATALOG:
   group=[s for s in stores if s['platform']==provider];enabled=[s for s in group if s['enabled']and s['configured']]
   fresh=sum(v['fresh']for s in enabled for v in s['snapshots'].values())
   ready=bool(enabled)and all(s['scope_reviewed']and all(v['fresh']for v in s['snapshots'].values())for s in enabled)
   result[provider]={'status':'readonly_connected'if ready else 'partial_or_stale'if fresh else 'configured_pending_read'if enabled else 'not_authorized',
                     'store_count':len(group),'fresh_resources':fresh,'business_accepted':False}
  return result

 def status(self,store_id):
  c=self.config(store_id);result=self.metadata(c)
  result['snapshots']={r:{k:v for k,v in self.snapshot(store_id,r).items()if k not in ('document',)}for r in api.CATALOG[c['platform']]['resources']}
  with self.core.db()as db:row=db.execute('SELECT id FROM platform_jobs WHERE store_id=? ORDER BY rowid DESC LIMIT 1',(store_id,)).fetchone()
  result['last_job']=self.job(row[0])if row else None
  return result

 def job(self,job_id):
  self.recover()
  with self.core.db()as db:row=db.execute('SELECT document FROM platform_jobs WHERE id=?',(job_id,)).fetchone()
  if not row:raise api.Issue('platform_job_not_found')
  job=json.loads(row[0]);c=self.config(job['store_id']);job['configuration_current']=c['revision']==job['revision'];return job

 def sync(self,store_id,resource,expected_revision,idempotency_key,window_days=7,max_pages=3):
  api.require(isinstance(idempotency_key,str)and 1<=len(idempotency_key)<=160,'invalid_idempotency_key')
  api.require(type(window_days)is int and 1<=window_days<=30 and type(max_pages)is int and 1<=max_pages<=5,'platform_invalid_read_limit')
  request=dict(store_id=store_id,resource=resource,expected_revision=expected_revision,window_days=window_days,max_pages=max_pages);encoded=api.encoded(request)
  with self.configs()as values,self.core.atomic()as db:
   old=db.execute('SELECT id,request,document FROM platform_jobs WHERE idem=?',(idempotency_key,)).fetchone()
   if old:
    api.require(old[1]==encoded,'idempotency_conflict');job=json.loads(old[2]);job['configuration_current']=values.get(store_id,{}).get('revision')==job['revision'];return job
   c=deepcopy(values.get(store_id));api.require(bool(c),'platform_connection_not_found')
   api.require(c['revision']==expected_revision,'platform_configuration_changed')
   api.require(c['enabled'],'platform_connection_disabled');api.require(c['scope_reviewed'],'platform_scope_review_required')
   api.require(not self.metadata(c)['missing_fields'],'platform_credentials_missing')
   api.require(resource in api.CATALOG[c['platform']]['resources'],'platform_resource_unsupported')
   api.require(not db.execute("SELECT 1 FROM platform_jobs WHERE store_id=? AND status IN ('queued','running','cancel_requested')AND expires>?",(store_id,time.time())).fetchone(),'platform_connection_busy')
   api.require(db.execute("SELECT count(*)FROM platform_jobs WHERE status IN ('queued','running','cancel_requested')AND expires>?",(time.time(),)).fetchone()[0]<8,'platform_queue_full')
   at=time.time();end=int(at)-180;window={'from_epoch':end-window_days*86400,'to_epoch':end,'from':api.iso(end-window_days*86400),'to':api.iso(end)}
   ident=uuid.uuid4().hex;job=dict(id=ident,store_id=store_id,platform=c['platform'],resource=resource,revision=c['revision'],status='queued',
                               requested_at=at,started_at=None,finished_at=None,window=window if resource=='orders'else None,
                               error=None,record_count=None,complete=False,snapshot_id=None,evidence=[],business_writes=False)
   db.execute('INSERT INTO platform_jobs VALUES (?,?,?,?,?,?,?,?,?)',(ident,idempotency_key,encoded,store_id,resource,c['revision'],'queued',api.encoded(job),at+180))
  thread=threading.Thread(target=self.execute,args=(ident,c,resource,window,max_pages),daemon=True,name='commerce-platform-read')
  with self.lock:
   self.threads={k:t for k,t in self.threads.items()if t.is_alive()};self.threads[ident]=thread;thread.start()
  return self.job(ident)

 def save_job(self,db,job):db.execute('UPDATE platform_jobs SET status=?,document=? WHERE id=?',(job['status'],api.encoded(job),job['id']))

 def cancelled(self,ident):
  if self.stopping.is_set():return True
  with self.core.db()as db:row=db.execute('SELECT status FROM platform_jobs WHERE id=?',(ident,)).fetchone()
  return not row or row[0]not in ('queued','running')

 def execute(self,ident,config,resource,window,pages):
  transport=api.Transport(config,lambda:self.cancelled(ident),self.request);start=time.monotonic();job=None
  try:
   while not self.cancelled(ident):
    with self.core.atomic()as db:
     row=db.execute('SELECT document FROM platform_jobs WHERE id=?',(ident,)).fetchone();job=json.loads(row[0])
     if db.execute("SELECT count(*)FROM platform_jobs WHERE status='running'AND expires>?",(time.time(),)).fetchone()[0]<2:
      job.update(status='running',started_at=time.time());self.save_job(db,job);break
    api.require(time.monotonic()-start<30,'platform_busy_timeout');self.stopping.wait(.1)
   api.require(not self.cancelled(ident),'platform_cancelled')
   result=api.fetch(config,resource,window,pages,transport)
   with self.configs()as values,self.core.atomic()as db:
    current=json.loads(db.execute('SELECT document FROM platform_jobs WHERE id=?',(ident,)).fetchone()[0])
    if current['status']not in ('running','cancel_requested'):return
    job=current;job.update(evidence=transport.events,finished_at=time.time(),record_count=len(result['records']),complete=result['complete'])
    if self.stopping.is_set()or current['status']=='cancel_requested':job.update(status='cancelled',error='platform_cancelled')
    elif values.get(config['store_id'],{}).get('revision')!=config['revision']:job.update(status='superseded',error='platform_configuration_changed')
    elif not result['complete']:job.update(status='partial',error='platform_page_limit_old_snapshot_retained')
    else:
     document=dict(schema=VERSION,store={k:config[k]for k in ('store_id','platform','label','market','region','revision')},resource=resource,window=job['window'],observed_at=time.time(),evidence=transport.events,**result)
     document['sha256']=api.digest(document);snapshot=uuid.uuid4().hex
     db.execute('INSERT INTO platform_snapshots VALUES (?,?,?,?,?,?)',(snapshot,config['store_id'],resource,config['revision'],api.encoded(document),document['observed_at']))
     db.execute('INSERT INTO platform_latest VALUES (?,?,?)ON CONFLICT(store_id,resource)DO UPDATE SET snapshot_id=excluded.snapshot_id',(config['store_id'],resource,snapshot))
     job.update(status='succeeded',snapshot_id=snapshot)
    self.save_job(db,job)
  except Exception as error:
   with self.core.atomic()as db:
    row=db.execute('SELECT document FROM platform_jobs WHERE id=?',(ident,)).fetchone()
    if not row:return
    job=json.loads(row[0])
    if job['status']not in ACTIVE:return
    code=error.code if isinstance(error,api.Issue)else 'platform_read_failed'
    job.update(status='cancelled'if code=='platform_cancelled'or job['status']=='cancel_requested'else 'unknown'if code=='platform_network_unknown_no_retry'else 'failed',error=code,evidence=transport.events,finished_at=time.time());self.save_job(db,job)

 def cancel(self,job_id):
  with self.core.atomic()as db:
   row=db.execute('SELECT document FROM platform_jobs WHERE id=?',(job_id,)).fetchone()
   if not row:raise api.Issue('platform_job_not_found')
   job=json.loads(row[0])
   if job['status']in ('queued','running'):job['status']='cancelled'if job['status']=='queued'else 'cancel_requested';self.save_job(db,job)
  return self.job(job_id)

 def snapshot(self,store_id,resource):
  with self.configs()as values:
   c=values.get(store_id);api.require(bool(c),'platform_connection_not_found');api.require(resource in api.CATALOG[c['platform']]['resources'],'platform_resource_unsupported')
   with self.core.db()as db:row=db.execute('SELECT s.id,s.revision,s.document FROM platform_latest l JOIN platform_snapshots s ON s.id=l.snapshot_id WHERE l.store_id=?AND l.resource=?',(store_id,resource)).fetchone()
   current=bool(row and row[1]==c['revision']);document=json.loads(row[2])if current else None
   if document:api.require(api.digest({k:v for k,v in document.items()if k!='sha256'})==document['sha256'],'platform_snapshot_integrity_failed')
   age=time.time()-document['observed_at']if document else None
   return {'available':bool(document),'enabled':c['enabled'],'configuration_current':current,'fresh':bool(document and c['enabled']and -300<=age<=1800),
           'retained_previous':bool(row),'snapshot_id':row[0]if current else None,'record_count':len(document['records'])if document else None,
           'observed_at':document['observed_at']if document else None,'document':document,'business_accepted':False,'business_writes':False}

 def export(self,store_id,resource):
  result=self.snapshot(store_id,resource);api.require(result['available'],'platform_current_snapshot_missing')
  return {'filename':'platform-'+self.config(store_id)['platform']+'-'+resource+'-evidence.json','content':json.dumps(result,ensure_ascii=False,indent=2),'privacy':'private_business_data_not_public_release_attachment'}

 def open_setup(self):
  from runtime import PORT
  ticket=self.service.live.new_setup_ticket();webbrowser.open('http://127.0.0.1:'+str(PORT)+'/platform-setup?ticket='+ticket)
  return {'status':'opened_local_private_setup','credentials_in_mcp':False}

 def stop(self):
  self.stopping.set()
  for thread in list(self.threads.values()):thread.join(timeout=16)
