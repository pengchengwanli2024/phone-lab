"""Versioned storefront draft handoff on original organization artifacts."""
import json,re,threading,time,uuid
from research import canonical,digest
from platform_connections import protocols
import storefront_protocol as protocol

def definitions(schema,string):
 return [
  ('commerce_storefront_draft_list','列出准确商品、店铺与市场的草稿计划以恢复回执',schema({'target':{'type':'object'}},['target'])),
  ('commerce_storefront_draft_prepare','按准确保存版本冻结Shopify/WooCommerce单商品远端草稿计划；不发送，不上线，不含库存、类目、图片或属性写入',schema({'target':{'type':'object'},'expected_preview_sha256':string,'idempotency_key':string},['target','expected_preview_sha256','idempotency_key'])),
  ('commerce_storefront_draft_get','读取准确草稿计划与实际发送/回读状态；未知不重发',schema({'plan_id':string},['plan_id'])),
  ('commerce_storefront_draft_submit','用户逐次确认准确计划后创建一次远端商品草稿；需要私有写入权限开关，不上线、不改已有商品、不写库存',schema({'plan_id':string,'expected_plan_sha256':string,'confirmed':{'type':'boolean'},'operator':string},['plan_id','expected_plan_sha256','confirmed','operator'])),
  ('commerce_storefront_draft_probe','只读复验已经收到准确产品ID的草稿；不发送创建请求',schema({'plan_id':string},['plan_id'])),
 ]

class StorefrontDrafts:
 def __init__(self,service):
  self.service=service;self.core=service.core;self.org=service.organization;self.platforms=service.platforms;self.threads={}
 def invoke(self,name,args):return getattr(self,name.removeprefix('commerce_storefront_draft_'))(**args)
 def list(self,target):
  target,_=self.service.listings.scope(**target)
  with self.core.db()as db:rows=db.execute("SELECT id FROM org_artifacts WHERE case_id=?AND kind='storefront_draft_plan'ORDER BY created DESC,id DESC LIMIT 100",(target['case_id'],)).fetchall()
  return {'plans':[self.get(r[0])for r in rows if self.load(r[0])['target']==target]}
 def event(self,p,status,**details):
  d={'status':status,'at':time.time(),**details};self.org._store(p['target']['case_id'],'storefront_event_'+p['id'],d,uuid.uuid4().hex);return d
 def load(self,plan_id):
  with self.core.db()as db:r=db.execute("SELECT case_id,payload,sha FROM org_artifacts WHERE id=?AND kind='storefront_draft_plan'",(plan_id,)).fetchone()
  if not r:raise ValueError('storefront_plan_not_found')
  self.org.case(r[0]);d=json.loads(r[1])
  if digest(canonical(d))!=r[2]:raise ValueError('storefront_plan_changed')
  return {'id':plan_id,'plan_sha256':r[2],**d}
 def state(self,p):
  event=self.org.artifact(p['target']['case_id'],'storefront_event_'+p['id'])
  if event and not event['intact']:raise ValueError('storefront_receipt_changed')
  d=event['payload']if event else{'status':'prepared'}
  if d['status']in ('checking','submitting','accepted')and time.time()-d['at']>120:return {'status':'unknown','error':'storefront_interrupted_unknown','remote_id':d.get('remote_id')}
  return d
 def get(self,plan_id):
  p=self.load(plan_id);return {**p,'state':self.state(p),'online_publication_executed':False,'stock_written':False}
 def current(self,p,write=False):
  v=self.service.listings.get(**p['target'])
  if v['preview_sha256']!=p['preview_sha256']or v['stale']:raise ValueError('listing_preview_changed')
  c=self.platforms.config(p['target']['store_ref']);m=self.platforms.metadata(c)
  if c['revision']!=p['connection_revision']or c['platform']!=p['target']['platform']or c['market']!=p['target']['market']:raise ValueError('platform_configuration_changed')
  if not(m['configured']and c['enabled']and c['scope_reviewed']):raise ValueError('platform_connection_not_ready')
  if write and not c.get('draft_create_reviewed'):raise ValueError('storefront_write_permission_required')
  return c
 def prepare(self,target,expected_preview_sha256,idempotency_key):
  with self.core.atomic():
   v=self.service.listings.get(**target)
   if v['target']['platform']not in ('shopify','woocommerce'):raise ValueError('storefront_unsupported')
   if not v['revision']or v['stale']or v['preview_sha256']!=expected_preview_sha256:raise ValueError('listing_preview_changed')
   c=self.platforms.config(v['target']['store_ref'])
   f=v['payload']['fields']
   if not all(f.get(k)for k in ('sku','title','description','price','currency'))or len(f['title'])>255 or len(f['sku'])>100:raise ValueError('storefront_fields_required')
   data={'schema':'commerce-storefront-draft-v1','target':v['target'],'preview_sha256':v['preview_sha256'],'connection_revision':c['revision'],'fields':{k:f[k]for k in ('sku','title','description','price','currency')},'excluded_fields':['quantity','image_refs','category_id','attributes','tax','fulfillment'],'wire':protocol.wire(c['platform'],f),'draft_only':True,'synthetic':v['synthetic']}
   self.current(data)
   a=self.org._store(target['case_id'],'storefront_draft_plan',data,idempotency_key)
   return self.get(a['id'])
 def submit(self,plan_id,expected_plan_sha256,confirmed,operator):
  if confirmed is not True or not isinstance(operator,str)or not operator.strip()or len(operator)>160:raise ValueError('storefront_explicit_confirmation_required')
  with self.core.atomic()as db:
   p=self.load(plan_id)
   if p['plan_sha256']!=expected_plan_sha256:raise ValueError('storefront_plan_changed')
   state=self.state(p)
   if state['status']!='prepared':return self.get(plan_id)
   c=self.current(p,write=True)
   # A different plan cannot create the same SKU again after a dispatch intent.
   rows=db.execute("SELECT id FROM org_artifacts WHERE kind='storefront_draft_plan'AND json_extract(payload,'$.target.store_ref')=?AND json_extract(payload,'$.fields.sku')=?",(p['target']['store_ref'],p['fields']['sku'])).fetchall()
   for (other,)in rows:
    if other!=plan_id and self.state(self.load(other))['status']not in ('prepared','failed_preflight'):raise ValueError('storefront_duplicate_or_unknown')
   self.event(p,'checking',operator=operator.strip())
  worker=threading.Thread(target=self.run,args=(p,c),daemon=True,name='commerce-storefront-draft');self.threads[plan_id]=worker;worker.start();return self.get(plan_id)
 def run(self,p,c):
  dispatched=False;ident=None
  try:
   protocol.before(c,p['fields'],self.platforms.request)
   with self.core.atomic():
    self.current(p,write=True);self.event(p,'submitting',operator=self.state(p).get('operator'),dispatch_started=True)
   dispatched=True;ident=protocol.create(c,p['fields'],self.platforms.request)
   with self.core.atomic():self.event(p,'accepted',remote_id=ident,dispatch_started=True)
   result=protocol.verify(c,p['fields'],ident,self.platforms.request)
   with self.core.atomic():self.event(p,'succeeded'if not result['description_requires_review']else'needs_review',remote_id=ident,readback=result,dispatch_started=True)
  except Exception as error:
   code=str(error)if isinstance(error,(ValueError,protocols.Issue))and re.fullmatch('[a-z_]{1,100}',str(error))else'storefront_network_unknown'
   with self.core.atomic():self.event(p,'unknown'if dispatched else'failed_preflight',remote_id=ident,error=code,dispatch_started=dispatched)
 def probe(self,plan_id):
  p=self.load(plan_id);state=self.state(p)
  if not state.get('remote_id'):raise ValueError('storefront_exact_receipt_required')
  c=self.platforms.config(p['target']['store_ref'])
  if c['revision']!=p['connection_revision']:raise ValueError('platform_configuration_changed')
  result=protocol.verify(c,p['fields'],state['remote_id'],self.platforms.request)
  with self.core.atomic():self.event(p,'succeeded'if not result['description_requires_review']else'needs_review',remote_id=state['remote_id'],readback=result,dispatch_started=True)
  return self.get(plan_id)
