"""Synthetic protocol, persistence and scope checks. No public requests."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from platform_connections import PlatformConnections
from platform_connections import protocols as api


def config(provider='amazon',ident='a'*32):
 value={'store_id':ident,'platform':provider,'label':'Synthetic store','region':api.CATALOG[provider]['regions'][0],
        'market':'US','enabled':True,'scope_reviewed':True}
 value.update({k:'synthetic-'+k for k in api.CATALOG[provider]['secrets']})
 value.update({'marketplace_id':'SYNTHETICUS'}if provider=='amazon'else {'seller_id':'123'}if provider=='mercado'else{})
 return value


def response(value):return api.encoded(value).encode(),None


def synthetic(request):
 path=urlparse(request.full_url).path;q=parse_qs(urlparse(request.full_url).query)
 if path=='/users/me':return response({'id':123,'email':'PRIVATE_BUYER_SENTINEL'})
 if path.endswith('/items/search'):return response({'results':['SYN1'],'paging':{'total':1}})
 if path=='/items':return response([{'code':200,'body':{'id':'SYN1','seller_id':123,'title':'Synthetic','available_quantity':50,'currency_id':'USD','price':'12.34'}}])
 if path=='/orders/search':return response({'paging':{'total':1},'results':[{'id':123,'status':'paid','seller':{'id':123},'buyer':{'email':'PRIVATE_BUYER_SENTINEL'},'total_amount':12.34,'currency_id':'USD'}]})
 if path=='/orders/2026-01-01/orders':return response({'orders':[{'orderId':'SYN-ORDER','salesChannel':{'marketplaceId':'SYNTHETICUS'},'fulfillment':{'fulfillmentStatus':'UNSHIPPED'},'buyer':{'email':'PRIVATE_BUYER_SENTINEL'}}]})
 if path=='/fba/inventory/v1/summaries':return response({'payload':{'granularity':{'granularityId':'SYNTHETICUS'},'inventorySummaries':[{'asin':'SYN-ASIN','sellerSku':'SYN-SKU','totalQuantity':99,'inventoryDetails':{'fulfillableQuantity':3}}]}})
 if path=='/product/202309/products/search':return response({'code':0,'data':{'total_count':1,'products':[{'id':'SYN-PRODUCT','title':'Synthetic','skus':[{'id':'SYN-SKU','seller_sku':'SYN-SKU','price':{'sale_price':'12.34','currency':'USD'},'inventory':[{'warehouse_id':'SYN-WAREHOUSE','quantity':3}]}]}]}})
 if path=='/order/202309/orders/search':return response({'code':0,'data':{'total_count':1,'orders':[{'id':'SYN-ORDER','status':'AWAITING_SHIPMENT','buyer_email':'PRIVATE_BUYER_SENTINEL'}]}})
 if path=='/openapi/router':return response({'success':True,'result':{'totalItemNum':1,'pageItems':[{'parentOrderMap':{'parentOrderSn':'SYN-ORDER','parentOrderStatus':2,'buyerName':'PRIVATE_BUYER_SENTINEL'}}]}})
 raise AssertionError('unexpected fixture route')


class Connections(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name);self.pc=PlatformConnections(self.app,request=synthetic)
 def tearDown(self):self.pc.stop();self.temp.cleanup()
 def configured(self,p='amazon',ident='a'*32):return self.pc.configure(config(p,ident))
 def read(self,c,resource='orders',key='read',pages=3):return self.pc.sync(c['store_id'],resource,c['revision'],key,max_pages=pages)
 def wait(self,j):
  end=time.monotonic()+8
  while time.monotonic()<end:
   result=self.pc.job(j['id'])
   if result['status']not in ('queued','running','cancel_requested'):return result
   time.sleep(.01)
  self.fail('synthetic read did not finish')

 def test_all_provider_resources_use_explicit_projection_and_keep_unknown_finance(self):
  for i,(provider,spec)in enumerate(api.CATALOG.items()):
   c=self.configured(provider,str(i+1)*32)
   for resource in spec['resources']:
    with self.subTest(provider=provider,resource=resource):
     j=self.wait(self.read(c,resource,provider+resource));self.assertEqual(j['status'],'succeeded',j.get('error'))
     s=self.pc.snapshot(c['store_id'],resource);self.assertTrue(s['fresh']);self.assertFalse(s['business_accepted'])
     d=s['document'];self.assertFalse(d['financial_ledger']);self.assertEqual(len(d['records']),1)
     self.assertNotIn('PRIVATE_BUYER_SENTINEL',json.dumps(d));self.assertTrue(d['evidence'][0]['response_sha256'])
     if provider=='amazon'and resource=='stock':self.assertEqual(d['records'][0]['quantity'],3)
     if provider=='mercado'and resource=='products':self.assertIn('reference',d['records'][0]['quantity_basis'])
     if provider=='temu':self.assertIsNone(d['records'][0]['amount'])

 def test_private_fields_not_in_status_jobs_or_export_and_private_permissions(self):
  c=self.configured('tiktok');j=self.wait(self.read(c));public=json.dumps([self.pc.listing(),j,self.pc.export(c['store_id'],'orders')])
  for secret in api.CATALOG['tiktok']['secrets']:self.assertNotIn('synthetic-'+secret,public)
  self.assertEqual(self.pc.path.stat().st_mode&0o777,0o600);self.assertEqual(self.pc.directory.stat().st_mode&0o777,0o700)
  with self.app.core.db()as db:
   contents=''.join(r[0]for r in db.execute('SELECT document FROM platform_snapshots'))+''.join(r[0]for r in db.execute('SELECT document FROM platform_jobs'))
  self.assertNotIn('PRIVATE_BUYER_SENTINEL',contents)

 def test_config_cas_and_blank_credentials_preserve_existing_private_values(self):
  c=self.configured();change={**config(), 'expected_revision':c['revision'],'label':'Updated','access_token':''};new=self.pc.configure(change)
  self.assertNotEqual(c['revision'],new['revision']);self.assertEqual(self.pc.config(c['store_id'])['access_token'],'synthetic-access_token')
  with self.assertRaisesRegex(ValueError,'platform_configuration_changed'):self.pc.configure(change)
  with self.assertRaisesRegex(ValueError,'platform_configuration_changed'):self.read(c)

 def test_configuration_change_hides_old_store_snapshot(self):
  c=self.configured();self.wait(self.read(c));change={**config(),'expected_revision':c['revision'],'marketplace_id':'DIFFERENT'}
  new=self.pc.configure(change);s=self.pc.snapshot(new['store_id'],'orders');self.assertTrue(s['retained_previous']);self.assertFalse(s['available']);self.assertIsNone(s['document'])

 def test_local_disabled_unreviewed_or_missing_credentials_never_contact_provider(self):
  for field,value in [('enabled',False),('scope_reviewed',False),('access_token','')]:
   data=config(ident=hashlib.md5(field.encode()).hexdigest());data[field]=value;c=self.pc.configure(data)
   with patch.object(self.pc,'request',side_effect=AssertionError('must not call')):
    with self.assertRaises(ValueError):self.read(c,key=field)

 def test_unsupported_endpoint_and_resource_rejected_before_network(self):
  c=self.configured();t=api.Transport(self.pc.config(c['store_id']),request=lambda r:self.fail('network'))
  with self.assertRaisesRegex(ValueError,'endpoint_not_allowed'):t.call('POST','/orders/2026-01-01/orders')
  with self.assertRaisesRegex(ValueError,'resource_unsupported'):self.read(c,'products')
  with self.assertRaisesRegex(ValueError,'endpoint_not_allowed'):t.call('GET','https://example.org')

 def test_atomic_idempotency_single_shared_job_and_conflicts(self):
  c=self.configured()
  with ThreadPoolExecutor(4)as pool:jobs=list(pool.map(lambda _:self.read(c),range(4)))
  self.assertEqual(len({x['id']for x in jobs}),1);self.assertEqual(self.wait(jobs[0])['status'],'succeeded')
  with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.pc.sync(c['store_id'],'orders',c['revision'],'read',window_days=3)

 def test_failed_unknown_and_partial_reads_preserve_last_success(self):
  c=self.configured();first=self.wait(self.read(c));old=self.pc.snapshot(c['store_id'],'orders')['snapshot_id']
  for code,status in [('platform_rate_limited','failed'),('platform_network_unknown_no_retry','unknown')]:
   def fail(req):raise api.Issue(code)
   self.pc.request=fail;j=self.wait(self.read(c,key=code));self.assertEqual(j['status'],status);self.assertEqual(self.pc.snapshot(c['store_id'],'orders')['snapshot_id'],old)
   self.assertEqual(self.read(c,key=code)['id'],j['id'])
  self.pc.request=lambda req:response({'orders':[{'orderId':'SYN-ORDER'}],'pagination':{'nextToken':'next'}})
  j=self.wait(self.read(c,key='partial',pages=1));self.assertEqual(j['status'],'partial');self.assertEqual(self.pc.snapshot(c['store_id'],'orders')['snapshot_id'],old)

 def test_store_change_during_read_cannot_publish(self):
  c=self.configured();started=threading.Event();release=threading.Event()
  def slow(req):started.set();release.wait(5);return synthetic(req)
  self.pc.request=slow;j=self.read(c);self.assertTrue(started.wait(3));self.pc.configure({**config(),'expected_revision':c['revision'],'label':'Changed'})
  release.set();self.assertEqual(self.wait(j)['status'],'superseded');self.assertFalse(self.pc.snapshot(c['store_id'],'orders')['available'])

 def test_cancel_only_own_read_and_no_publication(self):
  c=self.configured();started=threading.Event();release=threading.Event()
  def slow(req):started.set();release.wait(5);return synthetic(req)
  self.pc.request=slow;j=self.read(c);self.assertTrue(started.wait(3));self.pc.cancel(j['id']);release.set()
  self.assertEqual(self.wait(j)['status'],'cancelled');self.assertFalse(self.pc.snapshot(c['store_id'],'orders')['available'])

 def test_expired_interruption_is_unknown_and_never_replayed(self):
  c=self.configured();j=self.wait(self.read(c))
  with self.app.core.db()as db:
   value={**j,'status':'running'};db.execute('UPDATE platform_jobs SET status=?,expires=?,document=? WHERE id=?',('running',time.time()-1,api.encoded(value),j['id']))
  other=PlatformConnections(self.app,request=lambda r:self.fail('no replay'))
  try:self.assertEqual(other.job(j['id'])['status'],'unknown');self.assertEqual(other.listing()['stores'][0]['store_id'],c['store_id'])
  finally:other.stop()

 def test_scope_mismatch_retains_old_snapshot(self):
  c=self.configured('mercado');self.wait(self.read(c));self.pc.request=lambda req:response({'id':456})
  j=self.wait(self.read(c,key='wrong-owner'));self.assertEqual(j['error'],'platform_scope_mismatch');self.assertTrue(self.pc.snapshot(c['store_id'],'orders')['available'])

 def test_snapshot_tampering_rejected(self):
  c=self.configured();self.wait(self.read(c))
  with self.app.core.db()as db:
   ident,value=db.execute('SELECT id,document FROM platform_snapshots').fetchone();d=json.loads(value);d['records'][0]['status']='forged';db.execute('UPDATE platform_snapshots SET document=?WHERE id=?',(api.encoded(d),ident))
  with self.assertRaisesRegex(ValueError,'integrity_failed'):self.pc.snapshot(c['store_id'],'orders')

 def test_schema_missing_empty_and_duplicate_or_repeated_pages(self):
  c=self.configured()
  for i,value in enumerate(({}, {'orders':{}}, {'orders':[{'orderId':'same'},{'orderId':'same'}]}, {'orders':[],'pagination':{'nextToken':'x'}})):
   self.pc.request=lambda req,v=value:response(v);j=self.wait(self.read(c,key=str(i)));self.assertEqual(j['status'],'failed')
  self.pc.request=lambda req:response({'orders':[]});self.assertEqual(self.wait(self.read(c,key='valid-empty'))['status'],'succeeded');self.assertEqual(self.pc.snapshot(c['store_id'],'orders')['record_count'],0)

 def test_read_window_explicit_fixed_and_no_pii_included_data_requested(self):
  c=self.configured();requests=[]
  def capture(req):requests.append(req);return synthetic(req)
  self.pc.request=capture;j=self.wait(self.read(c));q=parse_qs(urlparse(requests[0].full_url).query)
  self.assertEqual(q['createdAfter'][0],j['window']['from']);self.assertEqual(q['createdBefore'][0],j['window']['to']);self.assertNotIn('includedData',q)
  self.assertGreaterEqual(j['requested_at']-j['window']['to_epoch'],180)

 def test_token_route_prefix_control_and_body_signature_not_in_evidence(self):
  c=self.configured('temu');requests=[]
  def capture(req):requests.append(req);return synthetic(req)
  self.pc.request=capture;j=self.wait(self.read(c));body=json.loads(requests[0].data)
  self.assertEqual(body['type'],'bg.order.list.v2.get');self.assertEqual(body['pageNumber'],1);self.assertEqual(body['sign'],api.temu_signature(body,'synthetic-app_secret'))
  self.assertNotIn(body['sign'],json.dumps(j));self.assertNotIn(body['access_token'],json.dumps(j))

 def test_invalid_config_and_size_budget_before_projection(self):
  for change in ({'region':'https://example.org'},{'market':'AUTO'},{'access_token':'bad\nheader'},{'enabled':'true'},{'store_id':'../escape'},{'marketplace_id':'../escape'}):
   with self.assertRaises(ValueError):self.pc.configure({**config(),**change})
  t=api.Transport({**config(),'revision':'x'},request=lambda req:(b' '* (api.LIMIT_BYTES+1),None))
  with self.assertRaisesRegex(ValueError,'response_too_large'):t.call('GET','/orders/2026-01-01/orders')

 def test_tiktok_count_mismatch_does_not_publish(self):
  c=self.configured('tiktok');self.pc.request=lambda req:response({'code':0,'data':{'orders':[{'id':'SYN'}],'total_count':2}})
  j=self.wait(self.read(c));self.assertEqual(j['error'],'platform_incomplete_pagination')

 def test_configuration_and_provider_jobs_never_change_ozon_state(self):
  before=self.app.live.config();c=self.configured();self.wait(self.read(c));self.assertEqual(self.app.live.config(),before)

 def test_summary_distinguishes_configured_partial_and_all_supported_reads(self):
  c=self.configured();self.assertEqual(self.pc.summary()['amazon']['status'],'configured_pending_read')
  self.wait(self.read(c));self.assertEqual(self.pc.summary()['amazon']['status'],'partial_or_stale')
  self.wait(self.read(c,'stock','stock'));self.assertEqual(self.pc.summary()['amazon']['status'],'readonly_connected');self.assertFalse(self.pc.summary()['amazon']['business_accepted'])


class ThreeEntries(unittest.TestCase):
 def test_private_setup_then_three_mcp_clients_share_one_read_receipt(self):
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory()as temp:
   state=Path(temp);(state/'auth.token').write_text('synthetic-platform-transport')
   with socket.socket()as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
   env=dict(os.environ,COMMERCE_STATE=str(state),COMMERCE_PORT=str(port));server=subprocess.Popen([sys.executable,str(root/'qa/fixture_platforms.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   def rpc(client,name,args):
    messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':args}}]
    done=subprocess.run([sys.executable,str(root/'mcp_server.py'),client],env=env,input=''.join(json.dumps(m)+'\n'for m in messages),capture_output=True,text=True,timeout=12)
    result=json.loads(done.stdout.splitlines()[-1])['result'];self.assertFalse(result.get('isError'),name);return result['structuredContent']
   try:
    for _ in range(100):
     with socket.socket()as sock:
      if sock.connect_ex(('127.0.0.1',port))==0:break
     time.sleep(.05)
    request=urllib.request.Request(f'http://127.0.0.1:{port}/v1/platforms/configure',data=api.encoded(config()).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer synthetic-platform-transport'},method='POST')
    with urllib.request.urlopen(request,timeout=5)as response:c=json.load(response)
    stores=rpc('codex','commerce_platform_list',{})['stores'];self.assertEqual(len(stores),1);self.assertNotIn('synthetic-access_token',json.dumps(stores))
    args={'store_id':c['store_id'],'resource':'orders','expected_revision':c['revision'],'idempotency_key':'transport-read'}
    job=rpc('hermes','commerce_platform_sync',args)
    for _ in range(30):
     result=rpc('harness','commerce_platform_job',{'job_id':job['id']})
     if result['status']not in ('queued','running'):break
     time.sleep(.05)
    self.assertEqual(result['status'],'succeeded');self.assertEqual(rpc('codex','commerce_platform_sync',args)['id'],job['id'])
    doc=json.loads(rpc('hermes','commerce_platform_export',{'store_id':c['store_id'],'resource':'orders'})['content']);self.assertEqual(doc['document']['records'][0]['entity_id'],'SYN-ORDER');self.assertFalse(doc['business_accepted'])
   finally:server.terminate();server.wait(timeout=8)


if __name__=='__main__':unittest.main()
