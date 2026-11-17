"""Bounded storefront reads. Fixed operations, public HTTPS, no redirects."""
import base64
import hashlib
import http.client
import json
import re
import time
from urllib.parse import urlsplit,urlencode
import urllib.request

CATALOG={
 'shopify':{'name':'Shopify','regions':['global'],'resources':['products'],'secrets':['access_token'],'fields':['shop_domain'],
            'notice':'Admin GraphQL 2026-10 商品变体读取；需 read_products。账号登录与店铺授权分别配置，不读取买家资料。'},
 'woocommerce':{'name':'WooCommerce','regions':['global'],'resources':['products','orders'],'secrets':['consumer_key','consumer_secret'],'fields':['store_url'],
                'notice':'REST wc/v3；使用已取得的店铺只读密钥。变体展开受作业预算限制，分页不全保留旧快照。'}
}
SHOPIFY_PATH='/admin/api/2026-10/graphql.json'
PRODUCTS_QUERY='''query CommerceProducts($after: String) {
 shop { currencyCode }
 productVariants(first: 100, after: $after) {
  nodes { id sku price product { id title status } }
  pageInfo { hasNextPage endCursor }
 }
}'''

def field(name,value):
 from .protocols import require
 if name=='shop_domain':
  require(isinstance(value,str)and bool(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,61}\.myshopify\.com',value)),'platform_invalid_store_domain')
  return value
 from public_web import public_url
 try:
  clean=public_url(value);p=urlsplit(clean)
  require(p.scheme=='https'and p.path in ('','/')and not p.query and not p.fragment,'platform_invalid_store_domain')
  return clean.rstrip('/')
 except ValueError:raise ValueError('platform_invalid_store_domain')from None

def secure_network(request):
 from .protocols import Issue,LIMIT_BYTES,require
 from public_web_transport import PublicConnection,addresses
 host=urlsplit(request.full_url);connection=None
 try:
  connection=PublicConnection(host.hostname,addresses(host.hostname)[0]);connection.timeout=15
  connection.request(request.method,(host.path or '/')+('?' +host.query if host.query else ''),body=request.data,headers=dict(request.header_items()))
  response=connection.getresponse()
  if response.status not in getattr(request,'_commerce_expected_status',(200,)):raise Issue('platform_permission_or_expired'if response.status in (401,403)else'platform_rate_limited'if response.status==429 else'platform_http_failed')
  raw=response.read(LIMIT_BYTES+1);require(len(raw)<=LIMIT_BYTES,'platform_response_too_large')
  return raw,None
 except Issue:raise
 except (OSError,ValueError,http.client.HTTPException):raise Issue('platform_network_unknown_no_retry')from None
 finally:
  if connection:connection.close()

def call(t,method,path,query,body):
 from .protocols import Issue,require,digest,iso,encoded,LIMIT_BYTES
 c=t.config;p=c['platform'];query=dict(query or{});body=dict(body or{})
 require(not t.cancelled(),'platform_cancelled');require(time.monotonic()<t.end and len(t.events)<24,'platform_read_budget_exceeded')
 if p=='shopify':
  require(method=='POST'and path==SHOPIFY_PATH and body.get('query')==PRODUCTS_QUERY and set(body)<= {'query','variables'},'platform_endpoint_not_allowed')
  base='https://'+field('shop_domain',c['shop_domain']);headers={'X-Shopify-Access-Token':c['access_token']}
 else:
  require(method=='GET'and bool(re.fullmatch(r'/wp-json/wc/v3/(?:products(?:/[1-9][0-9]*/variations)?|orders|settings/general/woocommerce_currency)',path)),'platform_endpoint_not_allowed')
  base=field('store_url',c['store_url']);headers={'Authorization':'Basic '+base64.b64encode((c['consumer_key']+':'+c['consumer_secret']).encode()).decode()}
 headers.update({'Accept':'application/json','Content-Type':'application/json','User-Agent':'PhoneLab-Commerce/0.1 read-only'})
 event={'method':method,'endpoint':path,'request_projection_sha256':digest({'path':path,'query':query,'body':body}),'observed_at':iso(t.clock())};t.events.append(event)
 request=urllib.request.Request(base+path+('?' +urlencode(query)if query else''),data=encoded(body).encode()if method=='POST'else None,headers=headers,method=method)
 request._commerce_pin_public=True
 try:
  raw,_=t.request(request);t.bytes+=len(raw);require(len(raw)<=LIMIT_BYTES and t.bytes<=8*LIMIT_BYTES,'platform_response_too_large')
  event['response_sha256']=hashlib.sha256(raw).hexdigest();require(not t.cancelled(),'platform_cancelled')
  try:return json.loads(raw)
  except (ValueError,UnicodeError):raise Issue('platform_unexpected_schema')from None
 except Issue as error:event['error']=error.code;raise

def shopify(c,resource,window,pages,t):
 from .protocols import Records,mapping,rows,record,require,text
 result=Records();cursor=None;seen=set()
 for _ in range(pages):
  raw=mapping(t.call('POST',SHOPIFY_PATH,body={'query':PRODUCTS_QUERY,'variables':{'after':cursor}}))
  require(not raw.get('errors'),'platform_provider_rejected');data=mapping(raw.get('data'));currency=text(mapping(data.get('shop')).get('currencyCode'))
  connection=mapping(data.get('productVariants'));batch=rows(connection.get('nodes'));page=mapping(connection.get('pageInfo'))
  for row in batch:
   product=mapping(row.get('product'));result.append(record(row.get('id'),sku=row.get('sku')or None,title=product.get('title'),status=product.get('status'),amount=row.get('price'),currency=currency))
  require(type(page.get('hasNextPage'))is bool)
  if not page['hasNextPage']:return result,True,None
  cursor=page.get('endCursor');require(bool(batch)and isinstance(cursor,str)and cursor and cursor not in seen,'platform_incomplete_pagination');seen.add(cursor)
 return result,False,None

def woocommerce(c,resource,window,pages,t):
 from .protocols import Records,mapping,rows,record,require,text
 result=Records();currency=None;seen=set()
 if resource=='products':currency=text(mapping(t.call('GET','/wp-json/wc/v3/settings/general/woocommerce_currency')).get('value'))
 for page in range(1,pages+1):
  query={'per_page':100,'page':page,'orderby':'id','order':'asc'}
  if resource=='orders':query.update(after=window['from'].replace('+00:00','').rstrip('Z'),before=window['to'].replace('+00:00','').rstrip('Z'),dates_are_gmt='true',_fields='id,status,currency,date_created_gmt,total')
  batch=rows(t.call('GET','/wp-json/wc/v3/'+resource,query))
  for row in batch:
   ident=text(row.get('id'));require(ident not in seen,'platform_pagination_repeated');seen.add(ident)
   if resource=='orders':result.append(record(ident,status=row.get('status'),currency=row.get('currency'),amount=row.get('total'),created_at=row.get('date_created_gmt')));continue
   if row.get('type')=='variable':
    expected=row.get('variations');require(isinstance(expected,list),'platform_unexpected_schema');variants=[]
    for index in range(1,pages+1):
     part=rows(t.call('GET','/wp-json/wc/v3/products/'+ident+'/variations',{'per_page':100,'page':index}));variants+=part
     if len(part)<100:break
    require(sorted(str(r.get('id'))for r in variants)==sorted(str(i)for i in expected),'platform_incomplete_pagination')
   else:variants=[row]
   for variant in variants:result.append(record(variant.get('id'),sku=variant.get('sku')or None,title=row.get('name'),status=variant.get('status',row.get('status')),quantity=variant.get('stock_quantity')if variant.get('manage_stock')is True else None,quantity_basis='woocommerce_managed_stock'if variant.get('manage_stock')is True else'not_tracked',amount=variant.get('regular_price')or None,currency=currency))
  if len(batch)<100:return result,True,None
 return result,False,None
