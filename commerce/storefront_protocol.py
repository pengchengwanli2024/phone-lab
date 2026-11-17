"""Fixed single-product DRAFT operations; no active publication or stock writes."""
import html,json,urllib.request
from urllib.parse import urlencode
from platform_connections.storefronts import SHOPIFY_PATH,field
from platform_connections.protocols import Issue,encoded

SEARCH='''query CommerceDraftSearch($query: String!) { shop { currencyCode } productVariants(first: 2, query: $query) { nodes { id sku product { id } } pageInfo { hasNextPage } } }'''
CREATE='''mutation CommerceCreateDraft($input: ProductSetInput!) { productSet(input: $input, synchronous: true) { product { id status } userErrors { field message code } } }'''
READ='''query CommerceDraftRead($id: ID!) { product(id: $id) { id title descriptionHtml status variants(first: 2) { nodes { sku price } pageInfo { hasNextPage } } } }'''

def wire(platform,fields):
 desc='<p>'+html.escape(fields['description']).replace('\n','<br>')+'</p>'
 if platform=='shopify':return {'query':CREATE,'variables':{'input':{'title':fields['title'],'descriptionHtml':desc,'status':'DRAFT','productOptions':[{'name':'Title','values':[{'name':'Default Title'}]}],'variants':[{'optionValues':[{'optionName':'Title','name':'Default Title'}],'price':fields['price'],'inventoryItem':{'sku':fields['sku']}}]}}}
 if platform=='woocommerce':return {'name':fields['title'],'description':desc,'type':'simple','status':'draft','sku':fields['sku'],'regular_price':fields['price']}
 raise ValueError('storefront_unsupported')

def call(config,operation,values,request):
 import base64
 platform=config['platform'];write=operation=='create'
 if platform=='shopify':
  base='https://'+field('shop_domain',config['shop_domain']);path=SHOPIFY_PATH;method='POST';headers={'X-Shopify-Access-Token':config['access_token']}
  body=wire(platform,values)if write else {'query':SEARCH,'variables':{'query':'sku:"'+values['sku'].replace('\\','\\\\').replace('"','\\"')+'"'}}if operation=='search'else {'query':READ,'variables':{'id':values['id']}}
 else:
  base=field('store_url',config['store_url']);method='POST'if write else'GET';path='/wp-json/wc/v3/products';headers={'Authorization':'Basic '+base64.b64encode((config['consumer_key']+':'+config['consumer_secret']).encode()).decode()};body=wire(platform,values)if write else None
  if operation=='search':path+='?'+urlencode({'sku':values['sku'],'per_page':2,'_fields':'id,sku,status'})
  elif operation=='currency':path='/wp-json/wc/v3/settings/general/woocommerce_currency'
  elif operation=='read':
   if not str(values['id']).isdigit():raise ValueError('storefront_invalid_receipt')
   path+='/'+str(values['id'])+'?'+urlencode({'_fields':'id,name,description,status,sku,regular_price'})
 headers.update({'Accept':'application/json','Content-Type':'application/json'})
 req=urllib.request.Request(base+path,data=encoded(body).encode()if body else None,headers=headers,method=method);req._commerce_pin_public=True;req._commerce_expected_status=(200,201)if write else(200,)
 raw,_=request(req)
 try:r=json.loads(raw)
 except(ValueError,UnicodeError):raise Issue('storefront_unexpected_schema')from None
 if platform=='shopify':
  if r.get('errors')or not isinstance(r.get('data'),dict):raise Issue('storefront_provider_rejected')
  return r['data']
 return r

def before(c,f,request):
 r=call(c,'search',f,request)
 if c['platform']=='shopify':
  group=r.get('productVariants',{});rows=group.get('nodes');currency=r.get('shop',{}).get('currencyCode')
  if not isinstance(rows,list)or group.get('pageInfo',{}).get('hasNextPage')is not False:raise Issue('storefront_incomplete_search')
 else:rows=r;currency=call(c,'currency',{},request).get('value')
 if not isinstance(rows,list)or rows:raise Issue('storefront_sku_exists_or_unresolved')
 if currency!=f['currency']:raise Issue('storefront_currency_mismatch')
 return {'sku_absent':True,'currency':currency}

def create(c,f,request):
 r=call(c,'create',f,request)
 if c['platform']=='shopify':
  result=r.get('productSet',{})
  if result.get('userErrors'):raise Issue('storefront_provider_rejected')
  r=result.get('product')or{}
 ident=r.get('id')
 if not ident:raise Issue('storefront_missing_receipt_unknown')
 return str(ident)

def verify(c,f,ident,request):
 from decimal import Decimal,InvalidOperation
 r=call(c,'read',{'id':ident},request)
 if c['platform']=='shopify':
  r=r.get('product')or{};v=r.get('variants',{});rows=v.get('nodes')or[]
  if len(rows)!=1 or v.get('pageInfo',{}).get('hasNextPage')is not False:raise Issue('storefront_readback_mismatch')
  projection={'id':str(r.get('id')),'title':r.get('title'),'description':r.get('descriptionHtml'),'status':r.get('status'),'sku':rows[0].get('sku'),'price':rows[0].get('price')};expected_status='DRAFT'
 else:projection={'id':str(r.get('id')),'title':r.get('name'),'description':r.get('description'),'status':r.get('status'),'sku':r.get('sku'),'price':r.get('regular_price')};expected_status='draft'
 try:valid=projection['id']==ident and projection['title']==f['title']and projection['sku']==f['sku']and projection['status']==expected_status and Decimal(projection['price'])==Decimal(f['price'])
 except(InvalidOperation,TypeError):valid=False
 if not valid:raise Issue('storefront_readback_mismatch')
 # HTML may be normalized by the provider. Preserve it in the receipt for review.
 return {**projection,'description_requires_review':projection['description']!=('<p>'+html.escape(f['description']).replace('\n','<br>')+'</p>'),'online_publication_executed':False,'stock_written':False}
