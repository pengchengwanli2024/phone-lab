"""Isolated UI fixture: all upstream draft replies are explicitly synthetic."""
import os,json,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import server
import storefront_protocol as protocol
from fixture_product_workspace import seed
if not os.environ.get('COMMERCE_STATE'):raise SystemExit('isolated COMMERCE_STATE required')
server.Handler.secret=server.token();app=server.Commerce(server.STATE);server.Handler.service=app
marker=server.STATE/'draft-fixture.json'
if not marker.exists():marker.write_text(json.dumps({'case_id':seed(app)}))
for p,n in [('shopify','a'),('woocommerce','b')]:
 with app.platforms.configs()as values:exists=n*32 in values
 if not exists:app.platforms.configure({'store_id':n*32,'platform':p,'label':'合成验收 · '+p,'market':'US','region':'global','enabled':True,'scope_reviewed':True,'draft_create_reviewed':True,**({'shop_domain':'synthetic.myshopify.com','access_token':'synthetic-token'}if p=='shopify'else{'store_url':'https://synthetic.example.com','consumer_key':'synthetic-key','consumer_secret':'synthetic-secret'})})
# In-memory fake provider, intentionally confined to this fixture process.
created={}
def upstream(req):
 from urllib.parse import urlsplit,parse_qs
 u=urlsplit(req.full_url);body=json.loads(req.data)if req.data else{};shopify=u.hostname=='synthetic.myshopify.com'
 if shopify:
  if body['query']==protocol.SEARCH:d={'shop':{'currencyCode':'USD'},'productVariants':{'nodes':[],'pageInfo':{'hasNextPage':False}}}
  elif body['query']==protocol.CREATE:
   f=body['variables']['input'];created['shopify']={'id':'gid://shopify/Product/1','title':f['title'],'descriptionHtml':f['descriptionHtml'],'status':'DRAFT','variants':{'nodes':[{'sku':f['variants'][0]['inventoryItem']['sku'],'price':f['variants'][0]['price']}],'pageInfo':{'hasNextPage':False}}};d={'productSet':{'product':{'id':'gid://shopify/Product/1','status':'DRAFT'},'userErrors':[]}}
  else:d={'product':created.get('shopify')}
  return json.dumps({'data':d}).encode(),None
 if req.method=='POST':created['woocommerce']={'id':1,**body};d={'id':1}
 elif '/settings/'in u.path:d={'value':'USD'}
 elif u.path.endswith('/1'):d=created.get('woocommerce',{})
 else:d=[]
 return json.dumps(d).encode(),None
app.platforms.request=upstream
print(json.dumps({'synthetic':True,'port':server.PORT}),flush=True)
try:server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler).serve_forever()
finally:app.platforms.stop();app.agent_runtime.stop()
