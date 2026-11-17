"""Isolated Shopify/WooCommerce protocol checks; no real store requests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlsplit,parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from platform_connections import protocols as api


class StorefrontConnections(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name)
 def tearDown(self):self.app.platforms.stop();self.app.agent_runtime.stop();self.tmp.cleanup()
 def config(self,p):
  return {'store_id':'a'*32,'platform':p,'label':'SYNTHETIC store','market':'US','region':'global','enabled':True,'scope_reviewed':True,**({'shop_domain':'synthetic.myshopify.com','access_token':'synthetic-token'}if p=='shopify'else{'store_url':'https://synthetic.example.com','consumer_key':'synthetic-key','consumer_secret':'synthetic-secret'})}
 def test_both_storefronts_use_existing_private_configuration_and_redact_secrets(self):
  for p in ('shopify','woocommerce'):
   c=self.config(p);c['store_id']=('a'if p=='shopify'else'b')*32
   r=self.app.platforms.configure(c)
   self.assertTrue(r['configured']);self.assertNotIn('synthetic-token',json.dumps(r));self.assertNotIn('synthetic-secret',json.dumps(r))
 def test_private_or_credential_urls_are_rejected_before_network(self):
  for p,field,values in [('shopify','shop_domain',['evil.example.com','test.myshopify.com.evil.com','a.myshopify.com/path']),('woocommerce','store_url',['http://example.com','https://127.0.0.1','https://user:pass@example.com','https://example.com/?token=x'])]:
   for value in values:
    with self.subTest(value=value),self.assertRaises(ValueError):self.app.platforms.configure({**self.config(p),field:value})
 def test_shopify_reads_exact_variant_rows_without_customer_fields_or_mutation(self):
  calls=[]
  def request(req):
   calls.append(req);body=json.loads(req.data)
   self.assertNotIn('mutation',body['query']);self.assertNotIn('customer',body['query']);self.assertEqual(req.get_header('X-shopify-access-token'),'synthetic-token')
   return json.dumps({'data':{'shop':{'currencyCode':'USD'},'productVariants':{'nodes':[{'id':'gid://shopify/ProductVariant/1','sku':'SYN-A','price':'12.50','product':{'id':'gid://shopify/Product/1','title':'Synthetic product','status':'DRAFT'}}],'pageInfo':{'hasNextPage':False,'endCursor':None}}}}).encode(),None
  c=self.config('shopify');t=api.Transport(c,request=request);r=api.fetch(c,'products',{},2,t)
  self.assertTrue(r['complete']);self.assertEqual(r['records'][0]['sku'],'SYN-A');self.assertEqual(r['records'][0]['currency'],'USD');self.assertNotIn('synthetic-token',json.dumps(t.events))
  with self.assertRaises(ValueError):t.call('POST','/admin/api/2026-10/graphql.json',body={'query':'mutation { productDelete { id } }'})
 def test_woocommerce_keeps_unknown_stock_and_uses_header_auth(self):
  def request(req):
   self.assertNotIn('synthetic-secret',req.full_url);self.assertTrue(req.get_header('Authorization').startswith('Basic '))
   if '/settings/'in req.full_url:return b'{"value":"USD"}',None
   return b'[{"id":1,"type":"simple","sku":"SYN-A","name":"Synthetic","status":"draft","manage_stock":false,"stock_quantity":null,"regular_price":"8.00"}]',None
  c=self.config('woocommerce');r=api.fetch(c,'products',{},2,api.Transport(c,request=request))
  self.assertTrue(r['complete']);self.assertIsNone(r['records'][0]['quantity']);self.assertEqual(r['records'][0]['amount'],'8.00')
 def test_woocommerce_does_not_adopt_incomplete_pagination(self):
  def request(req):
   if '/settings/'in req.full_url:return b'{"value":"USD"}',None
   return json.dumps([{'id':i+1,'type':'simple','sku':str(i),'name':'Synthetic','status':'draft','manage_stock':True,'stock_quantity':0,'regular_price':'1'}for i in range(100)]).encode(),None
  c=self.config('woocommerce');r=api.fetch(c,'products',{},1,api.Transport(c,request=request))
  self.assertFalse(r['complete']);self.assertEqual(len(r['records']),100)

if __name__=='__main__':unittest.main()
