"""Bounded read-only API protocols. No buyer fields enter the projection.

Independent implementations; protocol references live in PLATFORMS.md.
Access tokens are supplied through the private setup page, never MCP.
"""
import hashlib
import hmac
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

CATALOG={
 'tiktok':{'name':'TikTok Shop','regions':['global'],'resources':['products','orders'],'secrets':['app_key','app_secret','access_token','shop_cipher'],'fields':[],
           'notice':'以授权店铺范围为准，商品数量仍需按店铺后台核对业务口径。'},
 'amazon':{'name':'Amazon','regions':['na','eu','fe'],'resources':['orders','stock'],'secrets':['access_token'],'fields':['marketplace_id'],
           'notice':'订单按所选市场读取；库存仅覆盖 FBA，不包含 FBM 或全部仓库数量。'},
 'mercado':{'name':'Mercado Libre','regions':['global'],'resources':['products','orders'],'secrets':['access_token'],'fields':['seller_id'],
            'notice':'商品数量可能为区间参考值，核对精确库存前不能据此采购。'},
 'temu':{'name':'Temu','regions':['global','us','eu'],'resources':['orders'],'secrets':['app_key','app_secret','access_token'],'fields':[],
         'notice':'仅接订单列表；适用地区、店铺类型与权限包须按真实授权验收。库存和金额口径尚未接入。'},
}
HOSTS={'tiktok':{'global':'open-api.tiktokglobalshop.com'},'amazon':{r:'sellingpartnerapi-'+r+'.amazon.com' for r in ('na','eu','fe')},
       'mercado':{'global':'api.mercadolibre.com'},'temu':{r:'openapi-b-'+r+'.temu.com' for r in ('global','us','eu')}}
LIMIT_BYTES=2*1024*1024
MAX_RECORDS=5000
LIMIT_PROJECTION_BYTES=4*1024*1024


class Issue(ValueError):
 def __init__(self,code):self.code=code;super().__init__(code)


def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def iso(at):return datetime.fromtimestamp(at,timezone.utc).isoformat().replace('+00:00','Z')
def require(ok,code='platform_unexpected_schema'):
 if not ok:raise Issue(code)
def text(value,limit=160):
 require(isinstance(value,(str,int)) and type(value)is not bool)
 value=str(value);require(0<len(value)<=limit and not any(ord(c)<32 for c in value));return value
def mapping(value):require(isinstance(value,dict));return value
def rows(value):require(isinstance(value,list) and len(value)<=1000 and all(isinstance(x,dict)for x in value));return value
def total(value):require(type(value)is int and value>=0);return value
def page_total(expected,reported,consumed,size):
 count=total(reported)
 require(expected is None or count==expected,'platform_incomplete_pagination')
 require(consumed+size<=count,'platform_incomplete_pagination')
 return count


class Records(list):
 """Bound expanded rows as well as upstream bytes; fail before retaining a row."""
 def __init__(self):super().__init__();self.encoded_bytes=2
 def append(self,value):
  require(len(self)<MAX_RECORDS,'platform_read_budget_exceeded')
  size=len(encoded(value).encode())+(1 if self else 0)
  require(self.encoded_bytes+size<=LIMIT_PROJECTION_BYTES,'platform_read_budget_exceeded')
  super().append(value);self.encoded_bytes+=size


def quantity(value):
 if value is None:return None
 require(type(value)is int and 0<=value<=10**12);return value
def money(value):
 if value is None:return None
 try:number=Decimal(str(value))
 except InvalidOperation:raise Issue('platform_unexpected_schema') from None
 require(type(value)is not bool and number.is_finite() and abs(number)<=10**15);return str(value)


def record(ident,**fields):
 value={'entity_id':text(ident),'sku':None,'title':None,'status':None,'quantity':None,'quantity_basis':'not_available',
        'warehouse_id':None,'amount':None,'currency':None,'created_at':None}
 for k,v in fields.items():
  if k=='quantity':v=quantity(v)
  elif k=='amount':v=money(v)
  elif v is not None:v=text(v,500 if k=='title' else 160)
  value[k]=v
 if value['currency'] is not None:require(bool(re.fullmatch('[A-Z]{3}',value['currency'])))
 value['row_id']=digest([value['entity_id'],value['sku'],value['warehouse_id']])
 return value


def tiktok_signature(path,query,body,secret):
 base=path+''.join(k+str(query[k])for k in sorted(query)if k not in ('sign','access_token'))+body
 return hmac.new(secret.encode(),(secret+base+secret).encode(),hashlib.sha256).hexdigest()


def temu_signature(body,secret):
 def string(v):return v if isinstance(v,str)else encoded(v)
 base=''.join(k+string(body[k])for k in sorted(body)if k!='sign')
 return hashlib.md5((secret+base+secret).encode(),usedforsecurity=False).hexdigest().upper()


def allowed(provider,method,path,body):
 if provider=='tiktok':return method=='POST' and path in ('/product/202309/products/search','/order/202309/orders/search')
 if provider=='amazon':return method=='GET' and path in ('/orders/2026-01-01/orders','/fba/inventory/v1/summaries')
 if provider=='mercado':return method=='GET' and (path in ('/users/me','/items','/orders/search')or bool(re.fullmatch(r'/users/[1-9][0-9]{0,19}/items/search',path)))
 return provider=='temu' and method=='POST' and path=='/openapi/router' and body.get('type')=='bg.order.list.v2.get'


class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None


def network(request):
 try:
  with urllib.request.build_opener(NoRedirect).open(request,timeout=15)as response:
   data=response.read(LIMIT_BYTES+1);headers=response.headers
 except urllib.error.HTTPError as exc:
  code=exc.code;exc.close()
  raise Issue('platform_permission_or_expired' if code in (401,403)else 'platform_rate_limited' if code==429 else 'platform_http_failed') from None
 except Exception:raise Issue('platform_network_unknown_no_retry') from None
 require(len(data)<=LIMIT_BYTES,'platform_response_too_large')
 return data,headers.get('x-amzn-RequestId')


class Transport:
 def __init__(self,config,cancelled=lambda:False,request=network,clock=time.time):
  self.config=config;self.provider=config['platform'];self.cancelled=cancelled;self.request=request;self.clock=clock
  self.events=[];self.bytes=0;self.end=time.monotonic()+75

 def call(self,method,path,query=None,body=None):
  require(not self.cancelled(),'platform_cancelled')
  require(time.monotonic()<self.end and len(self.events)<24,'platform_read_budget_exceeded')
  query=dict(query or {});body=dict(body or {});c=self.config;p=self.provider
  require(allowed(p,method,path,body),'platform_endpoint_not_allowed')
  safe={'method':method,'path':path,'query':{k:v for k,v in query.items()if 'token' not in k.lower()},'body':body}
  request_sha=digest(safe)
  headers={'Accept':'application/json','User-Agent':'PhoneLab-Commerce/0.1 read-only'}
  if p=='tiktok':
   query.update(app_key=c['app_key'],timestamp=int(self.clock()),shop_cipher=c['shop_cipher'])
   query['sign']=tiktok_signature(path,query,encoded(body),c['app_secret']);headers['x-tts-access-token']=c['access_token']
  elif p in ('amazon','mercado'):
   headers['x-amz-access-token' if p=='amazon' else 'Authorization']=c['access_token']if p=='amazon'else 'Bearer '+c['access_token']
  else:
   body.update(type='bg.order.list.v2.get',app_key=c['app_key'],access_token=c['access_token'],timestamp=str(int(self.clock())),data_type='JSON')
   body['sign']=temu_signature(body,c['app_secret'])
  payload=None if method=='GET'else encoded(body).encode()
  if payload is not None:headers['Content-Type']='application/json'
  url='https://'+HOSTS[p][c['region']]+path+('?' +urllib.parse.urlencode(query)if query else '')
  event={'method':method,'endpoint':path,'request_projection_sha256':request_sha,'observed_at':iso(self.clock())};self.events.append(event)
  try:
   raw,request_id=self.request(urllib.request.Request(url,data=payload,headers=headers,method=method))
   self.bytes+=len(raw);require(len(raw)<=LIMIT_BYTES and self.bytes<=8*LIMIT_BYTES,'platform_response_too_large')
   event['response_sha256']=hashlib.sha256(raw).hexdigest()
   if request_id and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',request_id):event['request_id']=request_id
   try:value=json.loads(raw)
   except (ValueError,UnicodeError):raise Issue('platform_unexpected_schema')from None
   require(not self.cancelled(),'platform_cancelled')
   return value
  except Issue as error:event['error']=error.code;raise


def tiktok(c,resource,window,pages,t):
 path='/product/202309/products/search'if resource=='products'else '/order/202309/orders/search';field='products'if resource=='products'else 'orders'
 result=Records();token=None;seen=set();expected=None;entity_count=0
 for page in range(pages):
  q={'page_size':100};body={}
  if token:q['page_token']=token
  if resource=='orders':body={'create_time_ge':window['from_epoch'],'create_time_lt':window['to_epoch']}
  raw=mapping(t.call('POST',path,q,body));require(type(raw.get('code'))is int)
  require(raw['code']==0,'platform_provider_rejected')
  data=mapping(raw.get('data'));batch=rows(data.get(field))
  expected=page_total(expected,data.get('total_count'),entity_count,len(batch));entity_count+=len(batch)
  for item in batch:
   if resource=='orders':result.append(record(item.get('id'),status=item.get('status'),created_at=item.get('create_time')))
   else:
    ident=text(item.get('id'));title=item.get('title');status=item.get('status');skus=rows(item.get('skus',[]))
    if not skus:result.append(record(ident,title=title,status=status))
    for sku in skus:
     sku_id=text(sku.get('id'));price=mapping(sku.get('price',{}));inv=rows(sku.get('inventory',[]))or[{}]
     for stock in inv:result.append(record(ident,sku=sku.get('seller_sku')or sku_id,title=title,status=status,warehouse_id=stock.get('warehouse_id'),quantity=stock.get('quantity'),quantity_basis='tiktok_reported_inventory_not_reviewed',amount=price.get('sale_price'),currency=price.get('currency')))
  token=data.get('next_page_token');require(token is None or isinstance(token,str))
  if not token:
   require(expected==entity_count,'platform_incomplete_pagination');return result,True,expected
  require(bool(batch)and token not in seen,'platform_pagination_repeated');seen.add(token)
 return result,False,expected


def amazon(c,resource,window,pages,t):
 orders=resource=='orders';path='/orders/2026-01-01/orders'if orders else '/fba/inventory/v1/summaries'
 q={'marketplaceIds':c['marketplace_id']}
 if orders:q.update(createdAfter=window['from'],createdBefore=window['to'],maxResultsPerPage=100)
 else:q.update(details='true',granularityType='Marketplace',granularityId=c['marketplace_id'])
 result=Records();seen=set()
 for _ in range(pages):
  data=mapping(t.call('GET',path,q))
  if data.get('errors'):raise Issue('platform_provider_rejected')
  if orders:batch=rows(data.get('orders'))
  else:
   payload=mapping(data.get('payload'));granularity=mapping(payload.get('granularity'))
   require(granularity.get('granularityId')==c['marketplace_id'],'platform_scope_mismatch');batch=rows(payload.get('inventorySummaries'))
  for item in batch:
   if orders:
    channel=mapping(item.get('salesChannel',{}));require(not channel.get('marketplaceId')or channel['marketplaceId']==c['marketplace_id'],'platform_scope_mismatch')
    result.append(record(item.get('orderId'),status=mapping(item.get('fulfillment',{})).get('fulfillmentStatus'),created_at=item.get('createdTime')))
   else:
    details=mapping(item.get('inventoryDetails',{}));result.append(record(item.get('asin'),sku=item.get('sellerSku'),title=item.get('productName'),quantity=details.get('fulfillableQuantity'),quantity_basis='amazon_fba_reported_fulfillable_not_all_inventory'))
  pagination=data.get('pagination')or{};token=mapping(pagination).get('nextToken');require(token is None or isinstance(token,str))
  if not token:return result,True,None
  require(bool(batch)and token not in seen,'platform_pagination_repeated');seen.add(token)
  q['paginationToken'if orders else 'nextToken']=token
 return result,False,None


def mercado(c,resource,window,pages,t):
 owner=mapping(t.call('GET','/users/me'));require(text(owner.get('id'))==c['seller_id'],'platform_scope_mismatch')
 result=Records();offset=0;expected=None
 for _ in range(pages):
  if resource=='orders':
   path='/orders/search';q={'seller':c['seller_id'],'limit':50,'offset':offset,'order.date_created.from':window['from'],'order.date_created.to':window['to']}
  else:path='/users/'+c['seller_id']+'/items/search';q={'limit':50,'offset':offset}
  data=mapping(t.call('GET',path,q));paging=mapping(data.get('paging'));batch=data.get('results');require(isinstance(batch,list)and len(batch)<=100)
  expected=page_total(expected,paging.get('total'),offset,len(batch))
  if resource=='products':
   ids=[text(x)for x in batch];items=[]
   for start in range(0,len(ids),20):
    raw=t.call('GET','/items',{'ids':','.join(ids[start:start+20]),'attributes':'id,seller_id,title,status,available_quantity,price,currency_id,seller_custom_field'})
    for wrapper in rows(raw):
     require(wrapper.get('code')==200,'platform_item_read_failed');item=mapping(wrapper.get('body'));require(text(item.get('id'))in ids,'platform_scope_mismatch');require(text(item.get('seller_id'))==c['seller_id'],'platform_scope_mismatch');items.append(item)
   require(len(items)==len(ids),'platform_incomplete_pagination')
   for item in items:result.append(record(item['id'],sku=item.get('seller_custom_field'),title=item.get('title'),status=item.get('status'),quantity=item.get('available_quantity'),quantity_basis='mercado_reference_quantity_not_verified_stock',amount=item.get('price'),currency=item.get('currency_id')))
  else:
   for item in rows(batch):
    require(text(mapping(item.get('seller')).get('id'))==c['seller_id'],'platform_scope_mismatch')
    result.append(record(item.get('id'),status=item.get('status'),amount=item.get('total_amount'),currency=item.get('currency_id'),created_at=item.get('date_created')))
  offset+=len(batch)
  if offset==expected:return result,True,expected
  require(bool(batch),'platform_incomplete_pagination')
  if offset>=1000:return result,False,expected
 return result,False,expected


def temu(c,resource,window,pages,t):
 result=Records();expected=None
 for page in range(1,pages+1):
  raw=mapping(t.call('POST','/openapi/router',body={'type':'bg.order.list.v2.get','pageNumber':page,'pageSize':100,'createAfter':window['from_epoch'],'createBefore':window['to_epoch']}))
  require(raw.get('success')is True,'platform_provider_rejected');data=mapping(raw.get('result'));batch=rows(data.get('pageItems'))
  expected=page_total(expected,data.get('totalItemNum'),len(result),len(batch))
  for row in batch:
   item=mapping(row.get('parentOrderMap'));result.append(record(item.get('parentOrderSn'),status=item.get('parentOrderStatus'),created_at=item.get('parentOrderTime')))
  if len(result)==expected:return result,True,expected
  require(bool(batch),'platform_incomplete_pagination')
 return result,False,expected


def fetch(config,resource,window,pages,transport):
 require(resource in CATALOG[config['platform']]['resources'],'platform_resource_unsupported')
 records,complete,expected=globals()[config['platform']](config,resource,window,pages,transport)
 ids=[r['row_id']for r in records];require(len(ids)==len(set(ids)),'platform_duplicate_records')
 return {'records':records,'complete':complete,'expected_entities':expected,'scope':'selected_store_resource_and_requested_window_only',
         'business_scope_reviewed':False,'stock_basis_reviewed':False,'financial_ledger':False,'buyer_fields_retained':False,'notice':CATALOG[config['platform']]['notice']}
