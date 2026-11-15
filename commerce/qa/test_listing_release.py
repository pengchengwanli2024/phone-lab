"""Frozen applications and observed external receipts never authorize publishing."""
import copy,base64,hashlib
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed

IMPORT={'result':{'items':[{'offer_id':'SYN-SKU','product_id':123,'status':'imported','errors':[]}]}}
PRODUCT={'items':[{'id':123,'offer_id':'SYN-SKU','name':'Synthetic observed title','price':'249.00','currency_code':'CNY',
    'statuses':{'is_created':True,'is_failed':False,'status_name':'Synthetic moderation pending'}}]}


class ListingReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
        self.assertTrue(hasattr(self.app,'listing_releases'),'Frozen release workflow must be wired')
        self.r=self.app.listing_releases;self.target=dict(case_id=self.cid,platform='ozon',store_ref='ozon-live',market='RU')
        self.save();self.calls=[]
        def reader(path,body,client,key):
            self.calls.append((path,body));return copy.deepcopy(IMPORT if path.endswith('/import/info')else PRODUCT),'b'*64
        self.r.reader=reader

    def tearDown(self):
        if hasattr(self.app,'listing_releases'):self.app.listing_releases.stop()
        self.app.agent_runtime.stop();self.tmp.cleanup()

    def save(self,title=None):
        v=self.app.listings.get(**self.target);p=copy.deepcopy(v['payload'])
        if title:p['fields']['title']=title
        return self.app.listings.save(**self.target,payload=p,expected_revision=v['revision'],expected_source_sha256=v['source_sha256'])

    def create(self,key='release',note='Synthetic request'):
        v=self.app.listings.get(**self.target)
        return self.r.create(**self.target,expected_preview_sha256=v['preview_sha256'],note=note,confirmed=True,idempotency_key=key)

    def view(self,rid=None):return self.r.get(**self.target,request_id=rid)

    def act(self,rid,action,**args):
        v=self.view(rid)
        return self.r.review(request_id=rid,expected_event_sha256=v['request']['event_sha256'],decision=action,
            note='Synthetic local review only',confirmed=True,idempotency_key=args.pop('key',action),**args)

    def bind(self,rid,task='999',key='bind'):
        v=self.view(rid)
        return self.r.bind(request_id=rid,expected_event_sha256=v['request']['event_sha256'],task_id=task,
            source_ref='Synthetic outside-platform submission',confirmed=True,idempotency_key=key)

    def real_mode(self):
        with self.app.core.db()as db:
            scope=json.loads(db.execute('SELECT scope FROM org_cases WHERE id=?',(self.cid,)).fetchone()[0]);scope['synthetic']=False
            db.execute('UPDATE org_cases SET scope=?WHERE id=?',(json.dumps(scope),self.cid))
        self.save()

    def refresh(self,rid,key='capture'):
        v=self.view(rid);job=self.r.refresh(request_id=rid,expected_event_sha256=v['request']['event_sha256'],idempotency_key=key)
        for _ in range(150):
            v=self.view(rid)
            if v['request']['read']['status']!='running':return v
            time.sleep(.01)
        self.fail('bounded read did not finish')

    def test_local_reads_and_concurrent_create_reuse_original_artifact_without_tasks(self):
        tasks=self.app.core.invoke('commerce_task_list',{})['tasks']
        self.assertIsNone(self.view()['request']);self.assertEqual(self.calls,[])
        with ThreadPoolExecutor(4)as pool:ids=list(pool.map(lambda _:self.create()['id'],range(4)))
        self.assertEqual(len(set(ids)),1);v=self.view(ids[0]);self.assertEqual(v['request']['status'],'blocked')
        self.assertFalse(v['request']['platform_submission_verified']);self.assertIn('professional_gate',v['request']['missing'])
        self.assertEqual(tasks,self.app.core.invoke('commerce_task_list',{})['tasks'])
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.create(note='Changed same key')

    def test_request_is_frozen_source_change_invalidates_current_binding(self):
        rid=self.create()['id'];v=self.view(rid);old=v['request']['frozen']['payload']['fields']['title']
        self.save('Synthetic replacement title');v=self.view(rid)
        self.assertFalse(v['request']['current']);self.assertEqual(v['request']['frozen']['payload']['fields']['title'],old)
        newer=self.create(key='new-request');self.assertNotEqual(newer['id'],rid)
        self.assertFalse(v['request']['external_execution_allowed'])

    def test_review_cas_and_withdrawal_never_clear_professional_gate(self):
        rid=self.create()['id'];old=self.view(rid)['request']['event_sha256']
        self.act(rid,'acknowledged');v=self.view(rid)
        self.assertEqual(v['request']['decision'],'acknowledged');self.assertEqual(v['request']['status'],'blocked')
        with self.assertRaisesRegex(ValueError,'listing_release_conflict'):
            self.r.review(request_id=rid,expected_event_sha256=old,decision='needs_changes',note='Synthetic stale reviewer',confirmed=True,idempotency_key='late')
        self.bind(rid);self.act(rid,'withdrawn');v=self.view(rid)
        self.assertEqual(v['request']['status'],'withdrawn');self.assertEqual(v['request']['external']['task_id'],'999')
        self.assertFalse(v['request']['remote_cancel_performed'])

    def test_imported_without_product_id_is_not_success_and_wrong_sku_is_not_adopted(self):
        self.real_mode();rid=self.create()['id'];self.bind(rid)
        pending=copy.deepcopy(IMPORT);pending['result']['items'][0]['product_id']=0
        self.r.reader=lambda *args:(pending,'c'*64)
        v=self.refresh(rid);self.assertEqual(v['request']['observation']['status'],'awaiting_product_id');self.assertFalse(v['request']['platform_submission_verified'])
        wrong=copy.deepcopy(IMPORT);wrong['result']['items'][0]['offer_id']='OTHER-SKU'
        self.r.reader=lambda *args:(wrong,'d'*64)
        v=self.refresh(rid,key='wrong');self.assertEqual(v['request']['observation']['status'],'scope_mismatch')

    def test_exact_import_and_product_readback_persist_evidence_and_differences(self):
        self.real_mode();rid=self.create()['id'];self.bind(rid);v=self.refresh(rid)
        self.assertEqual(len(self.calls),2);self.assertEqual(v['request']['observation']['status'],'product_observed')
        self.assertTrue(v['request']['observation']['import_confirmed']);self.assertFalse(v['request']['platform_submission_verified'])
        self.assertEqual(v['request']['differences'][0]['status'],'different')
        self.assertEqual(v['request']['differences'][1]['status'],'different')
        self.assertTrue(v['request']['observation']['evidence'])
        self.assertFalse(v['request']['external_execution_allowed'])
        # A second process view reads original evidence without replaying an API call.
        from listing_release import ListingReleases
        other=ListingReleases(self.app)
        try:self.assertEqual(other.get(**self.target,request_id=rid)['request']['observation'],v['request']['observation'])
        finally:other.stop()

    def test_failed_recheck_keeps_previous_evidence_but_never_claims_current_success(self):
        self.real_mode();rid=self.create()['id'];self.bind(rid);old=self.refresh(rid)['request']['observation']
        def fail(*args):raise RuntimeError('synthetic private detail must not escape')
        self.r.reader=fail;v=self.refresh(rid,key='network-failure')
        self.assertEqual(v['request']['read']['status'],'failed');self.assertEqual(v['request']['observation'],old)
        self.assertEqual(v['request']['read']['error'],'listing_release_read_failed')

    def test_demo_does_not_query_real_platform_and_import_endpoint_stays_rejected(self):
        rid=self.create()['id'];self.bind(rid);v=self.view(rid)
        with self.assertRaisesRegex(ValueError,'listing_release_demo_no_network'):
            self.r.refresh(request_id=rid,expected_event_sha256=v['request']['event_sha256'],idempotency_key='forbidden')
        self.assertEqual(self.calls,[])
        import ozon_reader
        with self.assertRaisesRegex(ValueError,'endpoint_not_allowed'):ozon_reader.post('/v3/product/import',{},'synthetic','synthetic')

    def test_old_external_reference_cannot_be_reused_for_a_different_request(self):
        first=self.create()['id'];self.bind(first)
        self.save('Synthetic next revision');second=self.create(key='revision-two')['id']
        with self.assertRaisesRegex(ValueError,'listing_release_external_reference_in_use'):self.bind(second)

    def test_readback_rejects_mismatched_product_and_does_not_erase_withdrawal(self):
        self.real_mode();rid=self.create()['id'];self.bind(rid)
        bad=copy.deepcopy(PRODUCT);bad['items'][0]['offer_id']='WRONG-SKU'
        self.r.reader=lambda path,*args:(copy.deepcopy(IMPORT if path.endswith('/import/info')else bad),'c'*64)
        view=self.refresh(rid);self.assertEqual(view['request']['observation']['status'],'product_missing')
        self.assertFalse(view['request']['observation']['import_confirmed'])
        self.act(rid,'withdrawn');view=self.refresh(rid,key='after-withdraw')
        self.assertEqual(view['request']['status'],'withdrawn');self.assertFalse(view['request']['remote_cancel_performed'])

    def test_export_is_private_frozen_review_material_not_platform_import(self):
        rid=self.create()['id'];v=self.view(rid)
        doc=json.loads(self.r.export(rid,v['request']['event_sha256'])['content'])
        self.assertFalse(doc['platform_import_format']);self.assertFalse(doc['external_execution_allowed'])
        self.assertEqual(doc['request']['frozen'],v['request']['frozen'])

    def test_readable_export_is_escaped_frozen_and_does_not_publish_or_mutate(self):
        title='<script>alert("synthetic")</script>'
        self.save(title);rid=self.create(note='Synthetic <img src=x onerror=alert(1)>')['id'];v=self.view(rid)
        old_json=self.r.export(rid,v['request']['event_sha256'])['content']
        with self.app.core.db()as db:before=db.execute('SELECT count(*) FROM org_artifacts').fetchone()[0]
        exported=self.app.invoke('commerce_listing_release_export',{'request_id':rid,'expected_event_sha256':v['request']['event_sha256'],'format':'html'})
        self.assertTrue(exported['filename'].endswith('.html'));doc=exported['content']
        self.assertIn('&lt;script&gt;',doc);self.assertNotIn(title,doc);self.assertNotIn('<img',doc)
        self.assertIn('default-src',doc);self.assertIn('平台规则与资质专业核查',doc)
        self.assertIn('尚未通过',doc);self.assertIn(rid,doc);self.assertIn(v['request']['sha256'],doc)
        self.assertNotIn('<script',doc.lower());self.assertNotIn('javascript:',doc.lower());self.assertNotIn('<iframe',doc.lower())
        self.assertEqual(old_json,self.r.export(rid,v['request']['event_sha256'])['content'])
        with self.app.core.db()as db:self.assertEqual(before,db.execute('SELECT count(*) FROM org_artifacts').fetchone()[0])
        self.assertEqual(self.calls,[])
        self.save('Current synthetic replacement')
        old=self.r.export(rid,v['request']['event_sha256'],format='html')['content']
        self.assertIn('原方案已变化',old);self.assertIn('&lt;script&gt;',old)
        self.assertNotIn('Current synthetic replacement',old)
        with self.assertRaisesRegex(ValueError,'listing_release_invalid_export_format'):self.r.export(rid,v['request']['event_sha256'],format='pdf')
        self.act(rid,'needs_changes')
        with self.assertRaisesRegex(ValueError,'listing_release_conflict'):self.r.export(rid,v['request']['event_sha256'],format='html')

    def test_review_images_are_bound_to_the_frozen_application_and_embedded_offline(self):
        from listing_review_media import descriptor
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')
        self.real_mode();plan=self.app.listings.get(**self.target);p=copy.deepcopy(plan['payload']);p['fields']['image_refs']=['https://example.com/frozen-a.png','https://example.com/frozen-b.png']
        self.app.listings.save(**self.target,payload=p,expected_revision=plan['revision'],expected_source_sha256=plan['source_sha256'])
        rid=self.create()['id'];v=self.view(rid)['request'];args=dict(request_id=rid,expected_request_sha256=v['sha256'],index=0)
        with patch('catalog_media.fetch',return_value=png)as fetch:
            first=self.app.invoke('commerce_listing_release_image',args);self.assertEqual(first['source_sha256'],hashlib.sha256(png).hexdigest());fetch.assert_called_once_with(p['fields']['image_refs'][0])
        with patch('catalog_media.fetch',side_effect=AssertionError('offline export must never fetch')):
            doc=self.r.export(rid,v['event_sha256'],format='html')['content']
        self.assertIn('data:image/png;base64,',doc);self.assertIn('第 2 张图片尚未读取',doc);self.assertIn('产品信息',doc)
        self.assertIn('img-src data:',doc);self.assertNotIn('<img src="https:',doc)
        with self.assertRaisesRegex(ValueError,'listing_review_request_changed'):self.r.image(rid,'f'*64,0)
        with self.assertRaisesRegex(ValueError,'listing_review_image_index'):self.r.image(rid,v['sha256'],2)
        with self.assertRaisesRegex(ValueError,'listing_review_image_index'):self.r.image(rid,v['sha256'],True)
        self.save('A new listing title must not replace this frozen product')
        with patch('catalog_media.fetch',side_effect=AssertionError('cached images remain bound')):self.assertEqual(self.r.image(**args)['source_sha256'],first['source_sha256'])
        r=self.r.request(rid);_,_,path=descriptor(self.r,r,0);path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'listing_review_image_changed'):self.r.image(**args)
        self.assertEqual(self.calls,[])

    def test_review_preview_is_bounded_and_demo_never_fetches_remote_images(self):
        import random,struct,zlib
        from listing_review_media import MAX_PREVIEW
        plan=self.app.listings.get(**self.target);payload=copy.deepcopy(plan['payload']);payload['fields']['image_refs']=['https://example.com/large-source.png']
        self.app.listings.save(**self.target,payload=payload,expected_revision=plan['revision'],expected_source_sha256=plan['source_sha256'])
        rid=self.create()['id'];v=self.view(rid)['request']
        with patch('catalog_media.fetch',side_effect=AssertionError('demo never fetches')):
            with self.assertRaisesRegex(ValueError,'listing_review_demo_no_network'):self.r.image(rid,v['sha256'],0)
        self.real_mode();rid=self.create(key='real-large')['id'];v=self.view(rid)['request']
        rng=random.Random(42)
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',256,256,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(b'\0'+rng.randbytes(768)for _ in range(256))))+chunk(b'IEND',b'')
        self.assertGreater(len(raw),MAX_PREVIEW)
        with patch('catalog_media.fetch',return_value=raw):image=self.r.image(rid,v['sha256'],0)
        self.assertLessEqual(len(base64.b64decode(image['content_base64'])),MAX_PREVIEW);self.assertEqual(image['mime'],'image/jpeg')
        self.assertEqual(image['source_sha256'],hashlib.sha256(raw).hexdigest());self.assertEqual((image['width'],image['height']),(256,256))

    def test_restart_does_not_replay_a_persisted_pending_read(self):
        self.real_mode();rid=self.create()['id'];self.bind(rid)
        r=self.r.request(rid);h=self.r.head(r);s=self.r.state(h);s['read']={'id':'synthetic-abandoned-read','status':'running','error':None}
        with self.app.core.atomic():self.r._write(r,h,s,'read_started','synthetic-abandoned','a'*64)
        from listing_release import ListingReleases
        other=ListingReleases(self.app)
        try:
            v=other.get(**self.target,request_id=rid);self.assertEqual(v['request']['read']['status'],'interrupted');self.assertEqual(self.calls,[])
        finally:other.stop()

    def test_failed_catalog_flags_do_not_confirm_import_completion(self):
        self.real_mode();rid=self.create()['id'];self.bind(rid)
        bad=copy.deepcopy(PRODUCT);bad['items'][0]['statuses']['is_failed']=True
        self.r.reader=lambda path,*args:(copy.deepcopy(IMPORT if path.endswith('/import/info')else bad),'d'*64)
        v=self.refresh(rid);self.assertEqual(v['request']['observation']['status'],'product_observed')
        self.assertFalse(v['request']['observation']['import_confirmed'])

    def test_credential_rotation_between_reads_stops_the_old_second_request(self):
        self.real_mode();rid=self.create()['id'];self.bind(rid);calls=[]
        def rotate(path,*args):
            calls.append(path);self.app.live.configure({'ozon_api_key':'synthetic-rotated-key'});return copy.deepcopy(IMPORT),'e'*64
        self.r.reader=rotate;v=self.refresh(rid)
        self.assertEqual(len(calls),1);self.assertEqual(v['request']['read']['status'],'failed')
        self.assertEqual(v['request']['read']['error'],'listing_release_connection_changed');self.assertFalse(v['request']['connection_current'])


if __name__=='__main__':unittest.main()
