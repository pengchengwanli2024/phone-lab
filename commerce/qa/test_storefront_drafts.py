"""Synthetic network exercises actual persistence, single dispatch and readback."""
import sys,tempfile,time,unittest,json
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed
import storefront_protocol as wire

class Drafts(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app);self.calls=[];self.fail=False;self.currency='USD'
 def tearDown(self):self.app.autonomy.stop();self.app.agent_runtime.stop();self.app.platforms.stop();self.tmp.cleanup()
 def prepare(self,p='woocommerce',permission=True):
  self.platform=p;self.sid=('a'if p=='shopify'else'b')*32
  self.app.platforms.configure({'store_id':self.sid,'platform':p,'label':'SYNTHETIC','market':'US','region':'global','enabled':True,'scope_reviewed':True,'draft_create_reviewed':permission,**({'shop_domain':'synthetic.myshopify.com','access_token':'synthetic-token'}if p=='shopify'else{'store_url':'https://synthetic.example.com','consumer_key':'synthetic-key','consumer_secret':'synthetic-secret'})})
  target={'case_id':self.cid,'platform':p,'store_ref':self.sid,'market':'US'};v=self.app.listings.get(**target);payload=v['payload'];payload['fields']['currency']='USD'
  v=self.app.listings.save(**target,payload=payload,expected_revision=v['revision'],expected_source_sha256=v['source_sha256']);self.fields=v['payload']['fields']
  self.app.platforms.request=self.request
  return self.app.invoke('commerce_storefront_draft_prepare',{'target':target,'expected_preview_sha256':v['preview_sha256'],'idempotency_key':'p'+p})
 def request(self,r):
  self.calls.append(r);body=json.loads(r.data)if r.data else{}
  if self.platform=='shopify':
   if body['query']==wire.SEARCH:d={'shop':{'currencyCode':self.currency},'productVariants':{'nodes':[],'pageInfo':{'hasNextPage':False}}}
   elif body['query']==wire.CREATE:
    if self.fail:raise OSError('SYNTHETIC private network text')
    d={'productSet':{'product':{'id':'gid://shopify/Product/1','status':'DRAFT'},'userErrors':[]}}
   else:d={'product':{'id':'gid://shopify/Product/1','title':self.fields['title'],'descriptionHtml':wire.wire(self.platform,self.fields)['variables']['input']['descriptionHtml'],'status':'DRAFT','variants':{'nodes':[{'sku':self.fields['sku'],'price':self.fields['price']}],'pageInfo':{'hasNextPage':False}}}}
   return json.dumps({'data':d}).encode(),None
  if r.method=='POST':
   if self.fail:raise OSError('SYNTHETIC private network text')
   d={'id':1}
  elif '/settings/'in r.full_url:d={'value':self.currency}
  elif '/products/1?'in r.full_url:d={'id':1,**wire.wire(self.platform,self.fields)}
  else:d=[]
  return json.dumps(d).encode(),None
 def submit(self,p):
  out=self.app.storefront_drafts.submit(p['id'],p['plan_sha256'],True,'synthetic operator');deadline=time.monotonic()+3
  while out['state']['status']in ('checking','submitting','accepted')and time.monotonic()<deadline:
   time.sleep(.01);out=self.app.storefront_drafts.get(p['id'])
  return out
 def writes(self):return [r for r in self.calls if r.method=='POST'and (self.platform!='shopify'or json.loads(r.data)['query']==wire.CREATE)]
 def test_both_protocols_reach_exact_draft_readback_and_never_repeat(self):
  for platform in ('woocommerce','shopify'):
   p=self.prepare(platform);self.assertEqual(self.calls,[]);r=self.submit(p);self.assertEqual(r['state']['status'],'succeeded',r);self.assertFalse(r['online_publication_executed']);self.assertEqual(len(self.writes()),1);self.submit(p);self.assertEqual(len(self.writes()),1);self.calls=[]
 def test_write_scope_and_explicit_confirmation_enforced_server_side(self):
  p=self.prepare(permission=False)
  with self.assertRaisesRegex(ValueError,'write_permission'):self.submit(p)
  with self.assertRaisesRegex(ValueError,'explicit_confirmation'):self.app.storefront_drafts.submit(p['id'],p['plan_sha256'],False,'test')
  self.assertFalse(self.calls)
 def test_currency_mismatch_fails_before_mutation(self):
  p=self.prepare();self.currency='EUR';r=self.submit(p);self.assertEqual(r['state']['status'],'failed_preflight');self.assertEqual(self.writes(),[])
 def test_transport_failure_after_dispatch_stays_unknown_and_does_not_resend(self):
  p=self.prepare();self.fail=True;r=self.submit(p);self.assertEqual(r['state']['status'],'unknown');self.assertNotIn('private network',json.dumps(r));self.submit(p);self.assertEqual(len(self.writes()),1)

if __name__=='__main__':unittest.main()
