"""Pagination and expanded-result bounds; synthetic upstreams only."""
import hashlib
import json
import time
import unittest
import tempfile
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch

from test_platform_connections import config, response, synthetic
from service import Commerce
from platform_connections import PlatformConnections
from platform_connections import protocols as api


class Integrity(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
  self.pc=PlatformConnections(self.app,request=synthetic)
 def tearDown(self):self.pc.stop();self.temp.cleanup()
 def configured(self,provider,ident='a'*32):return self.pc.configure(config(provider,ident))
 def read(self,c,key,resource='orders'):
  job=self.pc.sync(c['store_id'],resource,c['revision'],key,max_pages=3)
  deadline=time.monotonic()+8
  while job['status']in ('queued','running','cancel_requested')and time.monotonic()<deadline:
   time.sleep(.01);job=self.pc.job(job['id'])
  self.assertNotIn(job['status'],('queued','running','cancel_requested'))
  return job
 def pages(self,provider,totals,batches):
  def request(req):
   path=urlparse(req.full_url).path
   if path=='/users/me':return response({'id':123})
   if provider=='mercado':
    index=int(parse_qs(urlparse(req.full_url).query)['offset'][0])
    # These test pages contain one row before any optional second row.
    page=0 if index==0 else 1
    return response({'paging':{'total':totals[page]},'results':[
      {'id':ident,'status':'paid','seller':{'id':123}} for ident in batches[page]]})
   page=json.loads(req.data)['pageNumber']-1
   return response({'success':True,'result':{'totalItemNum':totals[page],'pageItems':[
     {'parentOrderMap':{'parentOrderSn':ident,'parentOrderStatus':2}} for ident in batches[page]]}})
  return request

 def test_changed_totals_keep_previous_snapshot(self):
  for provider,totals in [('mercado',[3,2]),('mercado',[2,3]),('temu',[3,2]),('temu',[2,3])]:
   with self.subTest(provider=provider,totals=totals):
    ident=hashlib.sha256((provider+str(totals)).encode()).hexdigest()[:32]
    c=self.configured(provider,ident);self.pc.request=synthetic
    self.assertEqual(self.read(c,provider+str(totals)+'-seed')['status'],'succeeded')
    previous=self.pc.snapshot(c['store_id'],'orders')['snapshot_id']
    self.pc.request=self.pages(provider,totals,[['SYN-1'],['SYN-2']])
    job=self.read(c,provider+str(totals)+'-changed')
    self.assertEqual(job['status'],'failed');self.assertEqual(job['error'],'platform_incomplete_pagination')
    self.assertEqual(self.pc.snapshot(c['store_id'],'orders')['snapshot_id'],previous)

 def test_rows_over_reported_total_keep_previous_snapshot(self):
  for i,provider in enumerate(('mercado','temu')):
   with self.subTest(provider=provider):
    c=self.configured(provider,str(i+1)*32);self.pc.request=synthetic
    self.read(c,provider+'-seed');old=self.pc.snapshot(c['store_id'],'orders')['snapshot_id']
    self.pc.request=self.pages(provider,[1],[['SYN-1','SYN-2']])
    job=self.read(c,provider+'-overshoot')
    self.assertEqual(job['status'],'failed');self.assertEqual(job['error'],'platform_incomplete_pagination')
    self.assertEqual(self.pc.snapshot(c['store_id'],'orders')['snapshot_id'],old)

 def test_stable_totals_and_verified_empty_result_complete(self):
  for i,provider in enumerate(('mercado','temu')):
   c=self.configured(provider,str(i+1)*32)
   self.pc.request=self.pages(provider,[2,2],[['SYN-1'],['SYN-2']])
   job=self.read(c,provider+'-two-pages');self.assertEqual(job['status'],'succeeded')
   self.assertEqual(self.pc.snapshot(c['store_id'],'orders')['record_count'],2)
   self.pc.request=self.pages(provider,[0],[[]])
   job=self.read(c,provider+'-empty');self.assertEqual(job['status'],'succeeded')
   self.assertEqual(self.pc.snapshot(c['store_id'],'orders')['record_count'],0)

 def expanded(self,provider,count):
  if provider=='tiktok':return response({'code':0,'data':{'total_count':1,'products':[
   {'id':'SYN-P','skus':[{'id':'SYN-S','inventory':[{'warehouse_id':'W'+str(n),'quantity':1}for n in range(count)]}]}]}})
  if provider=='amazon':return response({'orders':[{'orderId':'SYN-'+str(n)}for n in range(count)]})
  if provider=='mercado':return response({'paging':{'total':count},'results':[
   {'id':'SYN-'+str(n),'seller':{'id':123}}for n in range(count)]})
  return response({'success':True,'result':{'totalItemNum':count,'pageItems':[
   {'parentOrderMap':{'parentOrderSn':'SYN-'+str(n)}}for n in range(count)]}})

 def test_expanded_record_limit_for_all_four_protocols_preserves_snapshot(self):
  for i,provider in enumerate(api.CATALOG):
   with self.subTest(provider=provider):
    c=self.configured(provider,str(i+1)*32);resource='products'if provider=='tiktok'else'orders'
    self.pc.request=synthetic;self.read(c,provider+'-seed',resource)
    previous=self.pc.snapshot(c['store_id'],resource)['snapshot_id']
    def read(req,p=provider):
     return response({'id':123})if urlparse(req.full_url).path=='/users/me'else self.expanded(p,4)
    self.pc.request=read
    with patch.object(api,'MAX_RECORDS',3,create=True):job=self.read(c,provider+'-limit',resource)
    self.assertEqual(job['status'],'failed');self.assertEqual(job['error'],'platform_read_budget_exceeded')
    self.assertEqual(self.pc.snapshot(c['store_id'],resource)['snapshot_id'],previous)

 def test_projection_byte_budget_counts_utf8_and_keeps_previous_snapshot(self):
  c=self.configured('amazon');self.read(c,'stock-seed','stock')
  old=self.pc.snapshot(c['store_id'],'stock')['snapshot_id']
  self.pc.request=lambda req:response({'payload':{'granularity':{'granularityId':'SYNTHETICUS'},'inventorySummaries':[
   {'asin':'SYN-ASIN','sellerSku':'SYN-SKU','productName':'合成'*100,'inventoryDetails':{'fulfillableQuantity':3}}]}})
  with patch.object(api,'LIMIT_PROJECTION_BYTES',800,create=True):job=self.read(c,'byte-limit','stock')
  self.assertEqual(job['status'],'failed');self.assertEqual(job['error'],'platform_read_budget_exceeded')
  self.assertEqual(self.pc.snapshot(c['store_id'],'stock')['snapshot_id'],old)

 def test_exact_record_boundary_is_accepted(self):
  c=self.configured('amazon');self.pc.request=lambda req:self.expanded('amazon',3)
  with patch.object(api,'MAX_RECORDS',3,create=True):job=self.read(c,'exact-boundary')
  self.assertEqual(job['status'],'succeeded');self.assertEqual(job['record_count'],3)

 def test_record_budget_accumulates_across_pages(self):
  c=self.configured('amazon');seen=[]
  def read(req):
   seen.append(req);page=len(seen)
   return response({'orders':[{'orderId':str(page)+'-'+str(n)}for n in range(2)],
                    **({'pagination':{'nextToken':'next'}}if page==1 else{})})
  self.pc.request=read
  with patch.object(api,'MAX_RECORDS',3):job=self.read(c,'cumulative-budget')
  self.assertEqual(len(seen),2);self.assertEqual(job['error'],'platform_read_budget_exceeded')
  self.assertFalse(self.pc.snapshot(c['store_id'],'orders')['available'])

 def test_actual_default_limit_bounds_sku_and_warehouse_expansion(self):
  c=self.configured('tiktok');self.read(c,'expanded-seed','products')
  old=self.pc.snapshot(c['store_id'],'products')['snapshot_id']
  self.pc.request=lambda req:response({'code':0,'data':{'total_count':1,'products':[
   {'id':'SYN-P','skus':[{'id':'SKU-'+str(n),'inventory':[
    {'warehouse_id':'W-'+str(w),'quantity':1}for w in range(501)]}for n in range(10)]}]}})
  job=self.read(c,'actual-default-budget','products')
  self.assertEqual(job['error'],'platform_read_budget_exceeded')
  self.assertEqual(self.pc.snapshot(c['store_id'],'products')['snapshot_id'],old)

 def test_catalog_discloses_projection_bounds_without_granting_business_acceptance(self):
  catalog=self.pc.catalog()
  self.assertEqual(catalog['limits']['normalized_records_per_job'],5000)
  self.assertEqual(catalog['limits']['normalized_records_json_bytes'],4*1024*1024)
  self.assertFalse(catalog['automatic_sync']);self.assertFalse(catalog['business_writes'])


if __name__=='__main__':unittest.main()
