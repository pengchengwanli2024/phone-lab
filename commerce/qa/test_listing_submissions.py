"""Exact human-confirmed submission, durable one-shot intent and real synthetic readback."""
import copy,json,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_owner_review as owner_fixtures
from fixture_listing_submission import metadata
from listing_submission_protocol import ATTR_PATH,WRITE_PATH
from listing_release_reads import PRODUCT_PATH,IMPORT_PATH
from listing_action_protocol import READ_PATH

class ListingSubmissions(unittest.TestCase):
 def setUp(self):
  self.fixture=owner_fixtures.OwnerReviewTests();self.fixture.setUp();self.app=self.fixture.app;self.target=self.fixture.target;self.cid=self.fixture.cid;metadata(self.app)
  v=self.app.listings.get(**self.target);p=copy.deepcopy(v['payload']);p.update(language='ru',fulfillment='OGL synthetic',rules_ref='synthetic:current-rules');p['ozon']['attributes'] += [dict(id=8229,values=[dict(dictionary_value_id=20,value='Synthetic type')],source_ref='synthetic:type'),dict(id=4191,values=[dict(dictionary_value_id=0,value=p['fields']['description'])],source_ref='synthetic:description')]
  p['fields']['sku']=self.app.organization.case(self.cid)['scope']['sku']
  p['ozon']['publication']=dict(depth=100,width=80,height=50,dimension_unit='mm',weight=200,weight_unit='g',vat='0.22',source_ref='synthetic:package',vat_source_ref='synthetic:tax',description_attribute_id=4191)
  self.app.listings.save(**self.target,payload=p,expected_revision=v['revision'],expected_source_sha256=v['source_sha256']);self.fixture.record(self.fixture.get())
  v=self.app.listings.get(**self.target);self.assertFalse(v['missing'],v['checks']);r=self.app.listing_releases.create(**self.target,expected_preview_sha256=v['preview_sha256'],note='Synthetic publication request',confirmed=True,idempotency_key='request');self.rid=r['id']
  self.app.listing_releases.review(self.rid,'','acknowledged','Synthetic exact application read',True,'ack')
  self.s=self.app.listing_submissions;self.writes=[];self.reads=[];self.pid=self.app.organization.case(self.cid)['scope']['product_id'];self.sku=p['fields']['sku']
  self.remote=dict(id=int(self.pid),offer_id=self.sku,name='Original synthetic title',price='90.00',currency_code='CNY',old_price='0',statuses=dict(is_created=True,is_failed=False))
  self.attrs=dict(id=int(self.pid),offer_id=self.sku,description_category_id=10,type_id=20,barcode='SYN-BAR',attributes=[dict(attribute_id=999,complex_id=0,values=[dict(dictionary_value_id=0,value='Original optional data')])],complex_attributes=[])
  self.urls=['https://example.com/original-synthetic.jpg']
  def reader(path,body,*args):
   self.reads.append((path,body))
   if path==PRODUCT_PATH:raw=dict(items=[copy.deepcopy(self.remote)])
   elif path==ATTR_PATH:raw=dict(result=[copy.deepcopy(self.attrs)])
   elif path==READ_PATH:raw=dict(items=[dict(product_id=int(self.pid),primary_photo=self.urls[:1],photo=self.urls[1:],color_photo=[],photo_360=[],errors=[])])
   elif path==IMPORT_PATH:raw=dict(result=dict(items=[dict(offer_id=self.sku,product_id=int(self.pid),status='imported',errors=[])]))
   else:raise AssertionError('unlisted endpoint')
   return raw,'b'*64
  self.s.reader=reader;self.app.listing_releases.reader=reader
  def write(body,*args):
   self.writes.append(copy.deepcopy(body));item=body['items'][0];self.remote.update(name=item['name'],price=item['price'],currency_code=item['currency_code']);self.urls=item['images'];return dict(result=dict(task_id=999)),'c'*64
  self.s.writer=write
 def tearDown(self):self.s.stop();self.fixture.tearDown()
 def wait(self):self.s.thread.join(5);self.assertFalse(self.s.thread.is_alive())
 def prepare(self,key='prepare'):
  self.s.probe(self.rid);self.wait();v=self.s.get(self.rid);self.assertTrue(v['ready_to_prepare'],v)
  return self.s.prepare(self.rid,v['request_sha256'],v['before']['sha256'],key)['plan']
 def submit(self,p,key='submit',**extra):
  args=dict(plan_id=p['id'],expected_event_sha256=p['event_sha256'],idempotency_key=key,expected_plan_sha256=p['sha256'],operator='Synthetic responsible operator',confirmed=True);args.update(extra);return self.app.invoke('commerce_listing_submission_submit',args)
 def test_exact_plan_requires_confirmation_and_import_is_not_sellable_receipt(self):
  p=self.prepare();self.assertTrue(p['can_submit']);self.assertEqual(p['body']['items'][0]['attributes'][0]['id'],101)
  self.assertTrue(any(r['id']==999 for r in p['body']['items'][0]['attributes']));self.assertEqual(self.writes,[])
  with self.assertRaisesRegex(ValueError,'confirmation_required'):self.submit(p,confirmed=False)
  self.submit(p);self.wait();v=self.s.get(self.rid);self.assertEqual(len(self.writes),1);self.assertEqual(v['plan']['state']['status'],'accepted')
  self.submit(p);self.assertEqual(len(self.writes),1)
  r=self.app.listing_releases.get(**self.target)['request'];self.assertEqual(r['external']['task_id'],'999');self.assertFalse(r['platform_submission_verified'])
  self.app.listing_releases.refresh(self.rid,r['event_sha256'],'readback');self.app.listing_releases.thread.join(5)
  self.assertEqual(self.s.get(self.rid)['plan']['state']['status'],'imported_needs_review')
  self.assertFalse(self.app.listing_releases.get(**self.target)['request']['platform_submission_verified'])
  with self.assertRaisesRegex(ValueError,'reference_locked'):self.app.listing_releases.bind(self.rid,self.app.listing_releases.get(**self.target)['request']['event_sha256'],'998','Synthetic replacement',True,'replace-task')
 def test_changed_remote_before_write_refuses_and_unknown_never_replays(self):
  p=self.prepare();self.remote['price']='91.00';self.submit(p);self.wait();self.assertEqual(self.writes,[])
  v=self.s.get(self.rid);self.assertFalse(v['plan']['can_submit']);self.assertEqual(v['plan']['state']['error'],'listing_submission_before_changed')
  p=self.prepare('current-before')
  def unknown(*args):self.writes.append(args[0]);raise ValueError('ozon_write_outcome_unknown')
  self.s.writer=unknown;self.submit(p,key='unknown');self.wait();v=self.s.get(self.rid);self.assertEqual(v['plan']['state']['status'],'unknown')
  with self.assertRaises(ValueError):self.submit(v['plan'],key='no-replay')
  from listing_submissions import ListingSubmissions
  other=ListingSubmissions(self.app);self.assertEqual(other.get(self.rid)['plan']['state']['status'],'unknown');self.assertEqual(len(self.writes),1)
 def test_saved_change_or_revoked_owner_signoff_cannot_execute(self):
  p=self.prepare();review=self.fixture.get();self.fixture.record(review,decision='withdrawn',key='withdraw-owner')
  with self.assertRaises(ValueError):self.submit(p)
  self.assertEqual(self.writes,[])
 def test_cancel_before_dispatch_and_corrupt_plan_fail_closed(self):
  p=self.prepare();self.s.cancel(p['id'],'','cancel');self.assertEqual(self.s.get(self.rid)['plan']['state']['status'],'cancelled')
  with self.assertRaises(ValueError):self.submit(p)
  with self.app.core.db()as db:db.execute("UPDATE org_artifacts SET sha='broken' WHERE id=?",(p['id'],))
  with self.assertRaisesRegex(ValueError,'integrity'):self.s.get(self.rid)
 def test_runtime_tracks_worker_and_transport_never_retries_http_body(self):
  import threading
  gate=threading.Event();original=self.s.reader
  self.s.reader=lambda *a:(gate.wait(3),original(*a))[1]
  self.s.probe(self.rid)
  self.assertGreater(self.app.invoke('commerce_runtime_status',{})['requested_local_work'],0);gate.set();self.wait()
  from ozon_product_writer import post_once
  from unittest.mock import MagicMock
  c=MagicMock();c.getresponse.side_effect=TimeoutError()
  p=self.prepare()
  with patch('ozon_product_writer.connection',return_value=c):
   with self.assertRaises(ValueError):post_once(p['body'],'123456','synthetic-key')
  self.assertEqual(c.request.call_count,1);self.assertEqual(c.request.call_args.args[:2],('POST',WRITE_PATH))
 def test_unknown_can_be_closed_only_by_fresh_remote_proof_and_explicit_owner_statement(self):
  p=self.prepare();original=self.s.writer
  def applied_but_reply_lost(body,*args):
   original(body,*args);item=body['items'][0];self.attrs.update(attributes=copy.deepcopy(item['attributes']),**{k:item[k]for k in ('depth','width','height','weight','dimension_unit','weight_unit')});raise ValueError('ozon_write_outcome_unknown')
  self.s.writer=applied_but_reply_lost;self.submit(p);self.wait();v=self.s.get(self.rid);self.assertEqual(v['plan']['state']['status'],'unknown')
  self.app.live.configure({'ozon_api_key':'synthetic-rotated-read-key'})
  # The original account may read with its rotated key; it cannot submit the old plan.
  r=self.app.listing_releases.get(**self.target)['request'];self.app.listing_releases.bind(self.rid,r['event_sha256'],'999','Synthetic operator matched the Ozon task',True,'recover-reference')
  r=self.app.listing_releases.get(**self.target)['request'];self.app.listing_releases.refresh(self.rid,r['event_sha256'],'recover-read');self.app.listing_releases.thread.join(5)
  self.s.probe(self.rid);self.wait();v=self.s.get(self.rid)
  args=dict(plan_id=p['id'],expected_event_sha256=v['plan']['event_sha256'],idempotency_key='resolve',expected_before_sha256=v['before']['sha256'],expected_release_event_sha256=v['release_event_sha256'],operator='Synthetic owner',source_ref='synthetic:platform-review',note='Synthetic owner checked gallery, complete attributes, packaging and tax in the platform',confirmed=False)
  with self.assertRaisesRegex(ValueError,'confirmation_required'):self.s.finish(**args)
  result=self.s.finish(**{**args,'confirmed':True});self.assertEqual(result['plan']['state']['status'],'owner_confirmed')
  self.assertEqual(result['plan']['state']['completion_basis'],'owner_platform_attestation_not_transport_proof');self.assertEqual(len(self.writes),1)
  exported=json.loads(self.app.listing_releases.export(self.rid,self.app.listing_releases.get(**self.target)['request']['event_sha256'])['content'])
  self.assertFalse(exported['request']['platform_submission_verified']);self.assertEqual(exported['application_submission'],'operator_attested_after_unknown_dispatch')
  html=self.app.listing_releases.export(self.rid,self.app.listing_releases.get(**self.target)['request']['event_sha256'],format='html')['content'];self.assertIn('未知提交后由负责人核对声明，非传输证明',html);self.assertIn('整卡发布包装与税率',html)
 def test_concurrent_confirmation_is_single_body_and_expired_plan_cannot_run(self):
  from concurrent.futures import ThreadPoolExecutor
  p=self.prepare()
  with patch('listing_submissions.time.time',return_value=time.time()+1900):
   with self.assertRaises(ValueError):self.submit(p,key='expired')
  with ThreadPoolExecutor(2)as pool:
   results=list(pool.map(lambda _:self.submit(p),range(2)))
  self.wait();self.assertEqual(len(self.writes),1)
 def test_inventory_product_missing_does_not_silently_create_new_sku(self):
  original=self.s.reader
  self.s.reader=lambda path,body,*a:({'items':[]},'a'*64)if path==PRODUCT_PATH else original(path,body,*a)
  self.s.probe(self.rid);self.wait();v=self.s.get(self.rid)
  self.assertFalse(v['ready_to_prepare']);self.assertEqual(v['worker']['error'],'listing_submission_existing_product_missing');self.assertEqual(self.writes,[])
 def test_packaging_drift_and_known_preconnection_failure_never_send_body(self):
  p=self.prepare();self.attrs['width']=999;self.submit(p);self.wait();v=self.s.get(self.rid)
  self.assertEqual(v['plan']['state']['status'],'failed_before_dispatch');self.assertEqual(self.writes,[])
  p=self.prepare('prepare-current');from ozon_reader import ConnectionIssue
  self.s.writer=lambda *args:(_ for _ in ()).throw(ConnectionIssue('ozon_connect_failed_before_write'))
  self.submit(p,key='before-connect');self.wait();v=self.s.get(self.rid)
  self.assertFalse(v['plan']['state']['dispatch_started']);self.assertEqual(v['plan']['state']['status'],'failed_before_dispatch');self.assertEqual(self.writes,[])
 def test_unknown_blocks_another_plan_and_cannot_be_falsely_resolved(self):
  p=self.prepare();other=self.prepare('parallel-plan');self.s.writer=lambda *args:(_ for _ in ()).throw(ValueError('ozon_write_outcome_unknown'));self.submit(p);self.wait()
  other=self.s.get(self.rid,other['id'])['plan'];self.assertFalse(other['can_submit'])
  with self.assertRaises(ValueError):self.submit(other,key='second-submit')
  v=self.s.get(self.rid,p['id'])
  with self.assertRaisesRegex(ValueError,'fresh_import_proof_required'):
   self.s.finish(p['id'],v['plan']['event_sha256'],'false-complete',v['before']['sha256'],v['release_event_sha256'],'Synthetic owner','synthetic:unconfirmed','Synthetic statement without actual fresh proof',True)
  self.assertEqual(self.writes,[])

 def test_old_unknown_plan_stays_reachable_and_blocks_new_preparations(self):
  p=self.prepare('old-recovery')
  for i in range(10):self.prepare('later-draft-'+str(i))
  self.s.writer=lambda *args:(_ for _ in ()).throw(ValueError('ozon_write_outcome_unknown'))
  self.submit(p);self.wait()
  from listing_submissions import ListingSubmissions
  restarted=ListingSubmissions(self.app);v=restarted.get(self.rid)
  self.assertEqual(v['plan']['id'],p['id']);self.assertIn(p['id'],[r['id']for r in v['history']])
  self.assertFalse(v['ready_to_prepare'])
  with self.assertRaisesRegex(ValueError,'other_outcome_unresolved'):
   restarted.prepare(self.rid,v['request_sha256'],v['before']['sha256'],'blocked-new-draft')

 def test_same_product_remains_reserved_when_a_stale_record_has_another_sku(self):
  p=self.prepare();self.s.writer=lambda *args:(_ for _ in ()).throw(ValueError('ozon_write_outcome_unknown'))
  self.submit(p);self.wait();c=self.app.live.config()
  self.assertTrue(self.s.occupied_sku(c,'different-synthetic-sku',product_id=self.pid))
  self.assertFalse(self.s.occupied_sku(c,'different-synthetic-sku',product_id='999999'))
  self.assertFalse(self.s.occupied_sku({**c,'ozon_client_id':'654321'},'different-synthetic-sku',product_id=self.pid))

 def test_image_dispatch_rechecks_whole_card_after_worker_launch_gap(self):
  import threading
  from concurrent.futures import ThreadPoolExecutor
  from listing_action_protocol import CHECKS
  p=self.prepare();actions=self.app.listing_actions;actions.reader=self.s.reader;image_writes=[]
  self.assertEqual(p['sku'],self.app.organization.case(self.cid)['scope']['sku'])
  actions.writer=lambda *args:(image_writes.append(args[0])or{'result':{'pictures':[]}},'d'*64)
  actions.refresh(self.cid);actions.thread.join(5);v=actions.get(self.cid)
  actions.prepare(self.cid,v['source_sha256'],v['gallery']['sha256'],['https://example.com/synthetic-race.jpg'],'race-image')
  a=actions.get(self.cid)['items'][0]
  actions.review(a['id'],a['event_sha256'],'race-review',{k:dict(status='confirmed',source_ref='synthetic:'+k,note='Synthetic check')for k in CHECKS},'approved','Synthetic owner','owner_manual',True)
  a=actions.get(self.cid)['items'][0];paused=threading.Event();resume=threading.Event();launch=actions._launch
  def delayed_launch(*args):
   paused.set()
   if not resume.wait(5):raise AssertionError('Synthetic race did not resume')
   return launch(*args)
  def unknown(body,*args):self.writes.append(body);raise ValueError('ozon_write_outcome_unknown')
  self.s.writer=unknown
  with patch.object(actions,'_launch',side_effect=delayed_launch),ThreadPoolExecutor(1)as pool:
   pending=pool.submit(actions.submit,a['id'],a['event_sha256'],'race-submit',a['sha256'],True)
   self.assertTrue(paused.wait(2))
   try:
    self.submit(p);self.wait();self.assertEqual(self.s.get(self.rid)['plan']['state']['status'],'unknown')
   finally:resume.set()
   pending.result(5)
  actions.thread.join(5);self.assertFalse(actions.thread.is_alive())
  self.assertEqual(len(self.writes),1);self.assertEqual(image_writes,[])
  self.assertEqual(actions.get(self.cid)['items'][0]['state']['error'],'listing_action_other_outcome_unresolved')
