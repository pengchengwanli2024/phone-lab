"""No-network action review, one-shot transport and outcome recovery contracts."""
import copy,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed
from listing_actions import ListingActions
from listing_action_protocol import CHECKS,gallery,images,WRITE_PATH
from ozon_image_writer import post_once

OLD='https://example.com/old-product.jpg';NEW='https://example.com/new-product.jpg'
RAW={'items':[dict(product_id=10,primary_photo=[OLD],photo=[],color_photo=[],photo_360=[],errors=[])]}

class ListingActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
        with self.app.core.db()as db:
            scope=json.loads(db.execute('SELECT scope FROM org_cases WHERE id=?',(self.cid,)).fetchone()[0]);scope['synthetic']=False
            db.execute('UPDATE org_cases SET scope=?WHERE id=?',(json.dumps(scope),self.cid))
        self.actions=ListingActions(self.app);self.app.listing_actions=self.actions;self.calls=[];self.raw=copy.deepcopy(RAW)
        self.actions.reader=lambda *args:(copy.deepcopy(self.raw),'a'*64)
        def write(body,*args):self.calls.append(body);return {'result':{'pictures':[]} },'b'*64
        self.actions.writer=write
    def tearDown(self):self.actions.stop();self.app.agent_runtime.stop();self.tmp.cleanup()
    def wait(self):
        self.actions.thread.join(5);self.assertFalse(self.actions.thread.is_alive())
    def latest(self):return self.actions.get(self.cid)['items'][0]
    def prepare(self,key='first'):
        self.actions.refresh(self.cid);self.wait();v=self.actions.get(self.cid)
        self.actions.prepare(self.cid,v['source_sha256'],v['gallery']['sha256'],[NEW],key)
        return self.latest()
    def review(self,a,decision='approved',**changes):
        args=dict(action_id=a['id'],expected_event_sha256=a['event_sha256'],idempotency_key='review-'+str(time.time_ns()),checks={k:dict(status='confirmed',source_ref='synthetic:'+k,note='Synthetic owner check, not independent certification')for k in CHECKS},decision=decision,reviewer='Synthetic owner',review_mode='owner_manual',confirmed=True);args.update(changes)
        self.actions.review(**args);return self.latest()
    def submit(self,a,key='submit'):
        return self.actions.submit(a['id'],a['event_sha256'],key,a['sha256'],True)
    def test_prepare_is_local_frozen_and_noop_or_invalid_urls_reject(self):
        self.assertEqual(self.app.invoke('commerce_listing_action_get',{'case_id':self.cid})['case_id'],self.cid)
        a=self.prepare();self.assertEqual(a['state']['status'],'draft');self.assertEqual(self.calls,[])
        evidence=self.actions.snapshot(self.cid)['data']['evidence']
        with self.app.core.db()as db:row=db.execute('SELECT request_sha,response_sha FROM live_http ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual((evidence['request_sha256'],evidence['response_sha256']),tuple(row))
        self.assertFalse(self.actions.get(self.cid)['independent_professional_approval'])
        v=self.actions.get(self.cid)
        with self.assertRaisesRegex(ValueError,'listing_action_no_change'):self.actions.prepare(self.cid,v['source_sha256'],v['gallery']['sha256'],[OLD],'noop')
        for value in (['http://example.com/p.jpg'],['https://127.0.0.1/a'],['https://169.254.169.254/a'],['https://host.internal/a'],['https://example.com/a\r\nX-Test:1'],[NEW,NEW]):
            with self.assertRaises(ValueError):images(value)
    def test_recovery_directory_and_exact_old_action_are_readonly_and_scoped(self):
        first=self.prepare('oldest-recovery')
        stored=self.actions.action(first['id'])
        with self.app.core.atomic():self.actions._event(stored,first['event_sha256'],'synthetic-unknown','dispatch_intent',dict(status='submitting',dispatch_started=True))
        for i in range(11):self.prepare('newer-'+str(i))
        with self.app.core.db()as db:before=db.execute('SELECT count(*) FROM org_artifacts').fetchone()[0]
        page=self.app.invoke('commerce_listing_action_directory',{'demo':False,'offset':0,'limit':5})
        self.assertEqual(page['total'],12);self.assertEqual(page['next_offset'],5)
        old_page=self.app.invoke('commerce_listing_action_directory',{'demo':False,'offset':10,'limit':5})
        row=next(r for r in old_page['items']if r['id']==first['id'])
        self.assertEqual(row['status'],'unknown');self.assertTrue(row['requires_readback']);self.assertEqual(row['target']['case_id'],self.cid)
        self.assertEqual(self.actions.get(self.cid,action_id=first['id'])['selected_action_id'],first['id'])
        self.assertIn(first['id'],[r['id']for r in self.actions.get(self.cid,action_id=first['id'])['items']])
        empty=self.app.invoke('commerce_listing_action_directory',{'demo':True});self.assertEqual(empty['items'],[]);self.assertTrue(empty['complete'])
        with self.assertRaisesRegex(ValueError,'listing_action_not_found'):self.actions.get(self.cid,action_id='f'*32)
        with self.assertRaisesRegex(ValueError,'listing_action_invalid_page'):self.actions.directory(limit=True)
        self.app.live.configure({'ozon_api_key':'synthetic-replacement-key'})
        rotated=self.actions.directory();self.assertEqual(rotated['total'],12)
        self.assertFalse(next(r for r in rotated['items']if r['id']==first['id'])['current'])
        self.app.live.configure({'ozon_client_id':'654321'})
        self.assertEqual(self.actions.directory()['total'],0)
        with self.assertRaisesRegex(ValueError,'listing_action_scope_changed|organization_case_not_found'):self.actions.get(self.cid,action_id=first['id'])
        with self.app.core.db()as db:self.assertEqual(db.execute('SELECT count(*) FROM org_artifacts').fetchone()[0],before)
        self.assertFalse(self.calls)
    def test_actual_approval_required_and_old_s6_never_changes(self):
        a=self.prepare()
        self.app.invoke('commerce_listing_action_review',dict(action_id=a['id'],expected_event_sha256=a['event_sha256'],idempotency_key='incomplete-api-draft',checks=a['state']['checks'],decision='save',reviewer='',review_mode='',confirmed=False))
        a=self.latest()
        with self.assertRaisesRegex(ValueError,'listing_action_approval_required'):self.submit(a)
        bad={k:dict(status='pending',source_ref='',note='')for k in CHECKS}
        with self.assertRaisesRegex(ValueError,'listing_action_review_incomplete'):self.review(a,checks=bad)
        with self.assertRaisesRegex(ValueError,'listing_action_confirmation_required'):self.review(a,confirmed=False)
        a=self.review(a);self.assertEqual(a['state']['status'],'approved')
        self.assertEqual(next(s for s in self.app.organization.board(self.cid)['stages']if s['id']=='S6')['status'],'BLOCKED')
        self.assertEqual(self.calls,[])
    def test_submit_once_and_exact_readback_are_distinct_states(self):
        a=self.review(self.prepare());self.submit(a);self.wait()
        after=self.latest();self.assertEqual(after['state']['status'],'awaiting_readback');self.assertEqual(len(self.calls),1)
        self.submit(a);self.assertEqual(len(self.calls),1)
        with self.assertRaisesRegex(ValueError,'listing_action_approval_required'):self.submit(after,'another')
        self.raw['items'][0]['primary_photo']=[NEW]
        self.actions.readback(a['id'],after['event_sha256'],'read-1');self.wait()
        observed=self.latest();self.assertEqual(observed['state']['status'],'observed');self.assertTrue(observed['state']['observation']['exact_images'])
        self.assertEqual(len(self.calls),1)
        with self.assertRaisesRegex(ValueError,'listing_action_terminal_use_current_gallery'):self.actions.readback(a['id'],observed['event_sha256'],'do-not-reopen-history')
        self.assertEqual(self.latest()['state']['observation'],observed['state']['observation'])
    def test_changed_gallery_or_credentials_before_intent_never_dispatch(self):
        a=self.review(self.prepare());self.raw['items'][0]['primary_photo']=['https://example.com/another-edit.jpg']
        self.submit(a);self.wait();self.assertEqual(self.latest()['state']['status'],'conflict');self.assertFalse(self.calls)
        self.actions.refresh(self.cid);self.wait();a=self.review(self.prepare('new-plan'))
        def rotated(*args):self.app.live.configure({'ozon_api_key':'synthetic-rotated-key'});return RAW,'c'*64
        self.actions.reader=rotated;self.submit(a,'rotate');self.wait();self.assertEqual(self.latest()['state']['status'],'conflict');self.assertFalse(self.calls)
    def test_timeout_is_unknown_and_another_action_cannot_duplicate_it(self):
        a=self.review(self.prepare())
        def unknown(*args):self.calls.append('attempt');raise TimeoutError('private-key-canary')
        self.actions.writer=unknown;self.submit(a);self.wait();after=self.latest()
        self.assertEqual(after['state']['status'],'unknown');self.assertNotIn('private-key-canary',json.dumps(after))
        other=self.review(self.prepare('other-action'))
        with self.assertRaisesRegex(ValueError,'listing_action_other_outcome_unresolved'):self.submit(other,'other-submit')
        restarted=ListingActions(self.app);self.assertEqual(restarted.state(restarted.action(a['id']))['status'],'unknown');self.assertEqual(len(self.calls),1)
        self.app.live.configure({'ozon_api_key':'synthetic-replacement-key'})
        other=self.review(self.prepare('new-key-action'))
        with self.assertRaisesRegex(ValueError,'listing_action_other_outcome_unresolved'):self.submit(other,'new-key-submit')
        self.raw['items'][0]['primary_photo']=[NEW]
        old=next(x for x in self.actions.get(self.cid)['items']if x['id']==a['id'])
        self.actions.readback(a['id'],old['event_sha256'],'new-key-readback');self.wait()
        old=next(x for x in self.actions.get(self.cid)['items']if x['id']==a['id'])
        self.assertEqual(old['state']['status'],'observed');self.assertEqual(len(self.calls),1)
    def test_pending_after_restart_is_unknown_and_never_replayed(self):
        a=self.review(self.prepare());stored=self.actions.action(a['id'])
        with self.app.core.atomic():self.actions._event(stored,a['event_sha256'],'synthetic-crash-intent','dispatch_intent',dict(status='submitting',dispatch_started=True))
        restarted=ListingActions(self.app);view=restarted.get(self.cid)['items'][0]
        self.assertEqual(view['state']['status'],'unknown');self.assertFalse(self.calls)
        with self.assertRaisesRegex(ValueError,'listing_action_approval_required'):restarted.submit(a['id'],view['event_sha256'],'no-replay',a['sha256'],True)
    def test_cancel_while_preflight_is_running_prevents_writer(self):
        a=self.review(self.prepare());entered=threading.Event();proceed=threading.Event()
        def read(*args):entered.set();proceed.wait(3);return RAW,'d'*64
        self.actions.reader=read;self.submit(a);self.assertTrue(entered.wait(2))
        view=self.latest();self.actions.cancel(a['id'],view['event_sha256'],'cancel-before-dispatch');proceed.set();self.wait()
        self.assertEqual(self.latest()['state']['status'],'cancelled');self.assertFalse(self.calls)
    def test_rejected_or_stale_approval_cannot_execute_and_receipts_preserve_ambiguity(self):
        a=self.review(self.prepare(),decision='rejected')
        with self.assertRaisesRegex(ValueError,'listing_action_approval_required'):self.submit(a)
        a=self.review(a)
        with patch('listing_actions.time.time',return_value=time.time()+1801):
            with self.assertRaisesRegex(ValueError,'listing_action_approval_required'):self.submit(a)
        self.submit(a,'valid');self.wait();view=self.latest();self.actions.readback(a['id'],view['event_sha256'],'unchanged');self.wait()
        self.assertEqual(self.latest()['state']['status'],'unknown')
        with self.assertRaisesRegex(ValueError,'listing_action_cannot_cancel_remote'):self.actions.cancel(a['id'],self.latest()['event_sha256'],'remote-cancel')
    def test_special_images_or_duplicate_product_response_never_prepare(self):
        bad=copy.deepcopy(RAW);bad['items'].append(bad['items'][0])
        with self.assertRaisesRegex(ValueError,'listing_action_response_scope'):gallery(bad,'10')
        self.raw['items'][0]['color_photo']=[OLD];self.actions.refresh(self.cid);self.wait();v=self.actions.get(self.cid)
        with self.assertRaisesRegex(ValueError,'listing_action_nonstandard_gallery'):self.actions.prepare(self.cid,v['source_sha256'],v['gallery']['sha256'],[NEW],'special')
    def test_inventory_ownership_is_checked_on_prepare_and_submit(self):
        a=self.review(self.prepare())
        with self.app.core.db()as db:db.execute("UPDATE live_snapshots SET observed='2000-01-01T00:00:00+00:00'WHERE kind='stock'")
        self.assertFalse(self.actions.get(self.cid)['inventory_current'])
        with self.assertRaisesRegex(ValueError,'listing_action_fresh_inventory_required'):self.submit(a)
        view=self.actions.get(self.cid)
        with self.assertRaisesRegex(ValueError,'listing_action_fresh_inventory_required'):self.actions.prepare(self.cid,view['source_sha256'],view['gallery']['sha256'],[NEW],'stale')
        self.assertFalse(self.calls)
    def test_transformed_urls_need_fresh_explicit_visual_attestation(self):
        a=self.review(self.prepare());self.submit(a);self.wait();state=self.latest()
        self.actions.readback(a['id'],state['event_sha256'],'old-gallery');self.wait();state=self.latest();obs=state['state']['observation']
        with self.assertRaisesRegex(ValueError,'listing_action_result_not_ready'):
            self.actions.finish(a['id'],state['event_sha256'],'not-changed',obs['sha256'],'Synthetic visual statement',True)
        self.raw['items'][0]['primary_photo']=['https://example.com/platform-transformed.jpg']
        self.actions.readback(a['id'],state['event_sha256'],'transformed-gallery');self.wait();state=self.latest();obs=state['state']['observation'];self.assertFalse(obs['exact_images'])
        with self.assertRaisesRegex(ValueError,'listing_action_confirmation_required'):
            self.actions.finish(a['id'],state['event_sha256'],'no-confirm',obs['sha256'],'Synthetic visual statement',False)
        self.actions.finish(a['id'],state['event_sha256'],'human-finish',obs['sha256'],'Synthetic owner compared every image and sequence',True)
        final=self.latest();self.assertEqual(final['state']['status'],'owner_confirmed');self.assertFalse(final['state']['observation']['exact_images']);self.assertEqual(len(self.calls),1)

class ImageWriterTests(unittest.TestCase):
    def test_connect_selection_never_retries_an_http_body(self):
        bad,good=MagicMock(),MagicMock();bad.connect.side_effect=OSError('synthetic no route')
        good.getresponse.return_value.status=200;good.getresponse.return_value.read.return_value=b'{}'
        with patch('ozon_image_writer.pinned_hosts',return_value=['1.1.1.1']),patch('ozon_image_writer.source_addresses',return_value=[None,'192.0.2.1']),patch('ozon_image_writer.DirectConnection',side_effect=[bad,good]):
            self.assertEqual(post_once({'product_id':10,'images':[NEW]},'synthetic-client','synthetic-key')[0],{})
        bad.request.assert_not_called();self.assertEqual(good.request.call_count,1);bad.close.assert_called_once();good.close.assert_called_once()
    def test_write_transport_uses_only_one_connection_attempt_and_fixed_payload(self):
        connection=MagicMock();connection.request.side_effect=OSError('synthetic timeout')
        with patch('ozon_image_writer.pinned_hosts',return_value=['1.1.1.1','8.8.8.8']),patch('ozon_image_writer.source_addresses',return_value=[None,'192.0.2.1']),patch('ozon_image_writer.DirectConnection',return_value=connection)as make:
            with self.assertRaisesRegex(ValueError,'ozon_write_outcome_unknown'):post_once({'product_id':10,'images':[NEW]},'synthetic-client','synthetic-key')
        self.assertEqual(make.call_count,1);self.assertEqual(connection.request.call_count,1);self.assertEqual(connection.request.call_args.args[1],WRITE_PATH)
        self.assertEqual(connection.close.call_count,1)
    def test_redirect_or_unknown_reply_never_claim_success(self):
        for status,data in ((302,b'{}'),(200,b'not-json'),(200,b'[]')):
            connection=MagicMock();connection.getresponse.return_value.status=status;connection.getresponse.return_value.read.return_value=data
            with patch('ozon_image_writer.pinned_hosts',return_value=[]),patch('ozon_image_writer.http.client.HTTPSConnection',return_value=connection):
                with self.assertRaisesRegex(ValueError,'ozon_write_outcome_unknown'):post_once({'product_id':10,'images':[NEW]},'synthetic-client','synthetic-key')

if __name__=='__main__':unittest.main()
