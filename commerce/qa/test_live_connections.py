"""Synthetic read-only connector/outbox tests; no real keys, accounts or messages."""
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from live_connections import LiveConnections, now
import ozon_reader
import feishu_sender

SECRET='synthetic-key-never-used-on-network'
HOOK='https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000000'


def raw_order(posting='SYN-1',status='awaiting_packaging'):
    return {'posting_number':posting,'status':status,'products':[{'sku':123,'offer_id':'SYN-SKU','quantity':2,'name':'Synthetic item'}],
            'in_process_at':now(),'delivery_method':{'warehouse_id':42},'customer':{'name':'SYNTHETIC-CANARY-NOT-RETAINED'}}


def batch(kind, value=10, posting='SYN-1', status='awaiting_packaging'):
    records=[ozon_reader.order_projection(raw_order(posting,status),'OGL')] if kind=='orders' else [ozon_reader.stock_projection({'product_id':10,'offer_id':'SYN-SKU','stocks':[{'type':'fbs','present':value,'reserved':1,'sku':123}]})]
    return {'kind':kind,'records':records,'evidence':[{'endpoint':ozon_reader.ENDPOINTS['OGL'] if kind=='orders' else ozon_reader.ENDPOINTS['stock'],'response_sha256':'a'*64,'received_at':now(),'page':0,'count':1}],'observed_at':now(),'complete':True,'privacy':'projected_fields_only_no_buyer_identity','coverage_days':30 if kind=='orders' else None}


class Live(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=LiveConnections(Core(self.root/'db.sqlite'),self.root)

    def tearDown(self):self.temp.cleanup()

    def configure(self):return self.app.configure({'fulfillment_modes':['OGL'],'ozon_client_id':'123456','ozon_api_key':SECRET})
    def test_evidence_export_preserves_source_without_secrets_or_buyer_identity(self):
        self.configure();self.publish('orders');self.publish('stock')
        result=self.app.export_evidence();document=json.loads(result['content'])
        self.assertEqual(document['schema'],'ozon-live-evidence-v1')
        self.assertEqual(document['scope']['modes'],['OGL'])
        for item in document['snapshots'].values():self.assertEqual(hashlib.sha256(json.dumps(item['data'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),item['sha256'])
        for private in (SECRET,'SYNTHETIC-CANARY-NOT-RETAINED','123456'):self.assertNotIn(private,result['content'])
        self.assertIn('发货单号',result['content']);self.assertIn('response_sha256',result['content'])
    def publish(self, kind, **kwargs):
        config=self.app.config();self.app._publish(config['connection_id'],kind,batch(kind,**kwargs),config,self.app.snapshot(config['connection_id'],kind) is not None)
    def enable(self):
        self.configure();self.publish('orders');self.publish('stock')
        self.app.configure({'orders_scope_confirmed':True,'stock_basis':'present_minus_reserved','basis_confirmed':True,
                            'feishu_webhook':HOOK,'feishu_target_label':'Synthetic group','feishu_signing_secret':'synthetic-sign'})
        with patch('feishu_sender.send',return_value={'outcome':'confirmed','code':'0'}):self.assertEqual(self.app.test_feishu()['status'],'sent')
        self.app.configure({'feishu_received_confirmed':True,'notifications_enabled':True})

    def test_private_config_no_secret_echo_and_initial_state(self):
        self.assertFalse(self.app.status()['configured'])
        result=self.configure();self.assertTrue(result['configured']);self.assertEqual(result['fulfillment_modes'],['OGL'])
        self.assertNotIn(SECRET,json.dumps(result));self.assertNotIn('123456',json.dumps(result))
        self.assertEqual(stat.S_IMODE(self.app.path.stat().st_mode),0o600)
        self.app.configure({'ozon_api_key':''});self.assertEqual(self.app.config()['ozon_api_key'],SECRET)

    def test_baseline_review_and_feishu_receipt_gates(self):
        self.configure()
        for fields in [{'sync_enabled':True},{'orders_scope_confirmed':True},{'stock_basis':'present_minus_reserved','basis_confirmed':True},{'notifications_enabled':True}]:
            with self.assertRaises(ValueError):self.app.configure(fields)
        self.publish('orders');self.publish('stock')
        self.app.configure({'orders_scope_confirmed':True,'stock_basis':'present_minus_reserved','basis_confirmed':True})
        self.assertEqual(self.app.inventory_rows()[0]['available'],9)
        self.assertNotIn('SYNTHETIC-CANARY',json.dumps(self.app.order_rows()))

    def test_initial_sync_and_duplicate_orders_do_not_spam(self):
        self.enable()
        with self.app.core.db()as db:self.assertEqual(db.execute("SELECT count(*) FROM live_outbox WHERE event_key LIKE 'order:%'").fetchone()[0],0)
        self.publish('orders',posting='SYN-NEW');self.publish('orders',posting='SYN-NEW')
        with self.app.core.db()as db:self.assertEqual(db.execute("SELECT count(*) FROM live_outbox WHERE event_key LIKE 'order:%'").fetchone()[0],1)

    def test_unknown_delivery_never_retried_and_restart_preserves_it(self):
        self.enable();self.publish('orders',posting='SYN-NEW')
        with patch('feishu_sender.send',return_value={'outcome':'uncertain','code':'synthetic_timeout'})as send:
            self.assertEqual(self.app.dispatch()['status'],'unknown');self.app.dispatch();self.assertEqual(send.call_count,1)
        restored=LiveConnections(self.app.core,self.root)
        self.assertTrue(any(row['status']=='unknown'for row in restored.status()['outbox']))

    def test_cancelled_order_is_rechecked_before_send(self):
        self.enable();self.publish('orders',posting='SYN-NEW');self.publish('orders',posting='SYN-NEW',status='cancelled')
        with patch('feishu_sender.send')as send:
            self.assertEqual(self.app.dispatch()['code'],'order_no_longer_pending');send.assert_not_called()

    def test_stale_source_holds_pending_notification(self):
        self.enable();self.publish('orders',posting='SYN-NEW')
        config=self.app.config();snapshot=self.app.snapshot(config['connection_id'],'orders')
        with self.app.core.db()as db:db.execute('UPDATE live_snapshots SET observed=? WHERE id=?',((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),snapshot['id']))
        with patch('feishu_sender.send')as send:self.assertEqual(self.app.dispatch()['status'],'waiting_fresh_data');send.assert_not_called()

    def test_stock_low_episode_and_zero_escalation_are_deduplicated(self):
        self.enable();self.publish('stock',value=4);self.publish('stock',value=3)
        with self.app.core.db()as db:self.assertEqual(db.execute("SELECT count(*) FROM live_outbox WHERE event_key LIKE 'stock:%'").fetchone()[0],1)
        self.publish('stock',value=1)
        with self.app.core.db()as db:self.assertEqual(db.execute("SELECT count(*) FROM live_outbox WHERE event_key LIKE 'stock:%'").fetchone()[0],2)
        self.publish('stock',value=10);self.publish('stock',value=4)
        with self.app.core.db()as db:self.assertEqual(db.execute("SELECT count(*) FROM live_outbox WHERE event_key LIKE 'stock:%'").fetchone()[0],3)

    def test_unconfirmed_stock_basis_keeps_available_unknown(self):
        self.configure();self.publish('stock',value=1)
        self.assertIsNone(self.app.inventory_rows()[0]['available']);self.assertEqual(self.app.alerts()['alerts'],[])

    def test_new_channel_requires_new_receipt_and_does_not_retarget(self):
        self.enable();self.publish('orders',posting='SYN-NEW')
        self.app.configure({'feishu_target_label':'Other synthetic group'})
        self.assertFalse(self.app.status()['notifications_enabled']);self.assertFalse(self.app.status()['feishu_received_confirmed'])
        with patch('feishu_sender.send')as send:
            self.assertEqual(self.app.dispatch(allow_test=True)['code'],'channel_changed_no_retarget');send.assert_not_called()

    def test_failed_sync_retains_previous_snapshot_and_records_partial_status(self):
        self.configure();self.publish('orders');previous=self.app.snapshot(self.app.config()['connection_id'],'orders')['sha256']
        with patch('ozon_reader.fetch',side_effect=ozon_reader.ConnectionIssue('synthetic_failure')):
            ident=self.app.start_sync()['id']
            for _ in range(100):
                result=self.app.status()['last_job']
                if result['status']!='running':break
                time.sleep(.01)
        self.assertEqual(result['id'],ident);self.assertEqual(result['status'],'failed')
        self.assertEqual(self.app.snapshot(self.app.config()['connection_id'],'orders')['sha256'],previous)

    def test_tickets_are_short_lived_and_single_use(self):
        ticket=self.app.new_setup_ticket();self.assertTrue(self.app.consume_ticket(ticket));self.assertFalse(self.app.consume_ticket(ticket))
        expired=self.app.new_setup_ticket();self.app.tickets[expired]=0;self.assertFalse(self.app.consume_ticket(expired))

    def test_workbench_does_not_fabricate_revenue_or_stock(self):
        self.configure();self.publish('orders');self.publish('stock')
        self.assertIsNone(self.app.workbench('commerce_dashboard',{})['sales'])
        self.assertIsNone(self.app.workbench('commerce_products_list',{})['products'][0]['available'])
        self.assertEqual(self.app.workbench('commerce_orders_list',{'platform':'amazon'})['orders'],[])


class Reader(unittest.TestCase):
    def config(self):return {'fulfillment_modes':['OGL'],'lookback_days':30,'ozon_client_id':'123456','ozon_api_key':SECRET}
    def test_complete_cursor_chain_and_new_total_field(self):
        calls=[]
        def request(path,body,*credentials):
            calls.append((path,body))
            return ({'items':[{'product_id':1,'offer_id':'SYN','stocks':[]}],'cursor':'next','total_items':2} if not body['cursor'] else {'items':[{'product_id':2,'offer_id':'SYN2','stocks':[]}],'cursor':'','total_items':2}), 'b'*64
        result=ozon_reader.fetch(self.config(),'stock',request=request)
        self.assertEqual(len(result['records']),2);self.assertEqual(calls[1][1]['cursor'],'next')

    def test_top_level_ogl_order_projection_removes_buyer_identity(self):
        def request(path,body,*credentials):
            self.assertEqual(path,'/v4/posting/fbs/list')
            return {'postings':[raw_order()],'has_next':False,'cursor':''},'b'*64
        result=ozon_reader.fetch(self.config(),'orders',request=request)
        self.assertNotIn('SYNTHETIC-CANARY',json.dumps(result));self.assertEqual(result['records'][0]['fulfillment'],'OGL')

    def test_incomplete_or_changed_schema_is_not_empty_success(self):
        for payload in ({'result':{'postings':[]},'has_next':False},{'postings':[]},{'postings':[],'has_next':True,'cursor':''}):
            with self.assertRaises(ozon_reader.ConnectionIssue):ozon_reader.fetch(self.config(),'orders',request=lambda *args:(payload,'c'*64))

    def test_write_endpoints_and_unknown_quantities_are_rejected(self):
        with self.assertRaises(ozon_reader.ConnectionIssue):ozon_reader.post('/v2/products/stocks',{},'synthetic',SECRET)
        with self.assertRaises(ozon_reader.ConnectionIssue):ozon_reader.stock_projection({'product_id':1,'stocks':[{'type':'fbs','present':None,'reserved':0}]})


class Feishu(unittest.TestCase):
    def test_exact_signature_and_allowlisted_target(self):
        import base64,hmac
        expected=base64.b64encode(hmac.new(b'123\nsynthetic',b'',hashlib.sha256).digest()).decode()
        self.assertEqual(feishu_sender.signed_message('Synthetic','synthetic',123)['sign'],expected)
        for value in ('https://foreign.example/hook/123','http://open.feishu.cn/open-apis/bot/v2/hook/00000000000000000000',HOOK+'?x=1'):
            with self.assertRaises(ValueError):feishu_sender.validate_webhook(value)

    def test_business_code_precedes_legacy_code_and_timeout_is_unknown(self):
        for response,wanted in [({'code':0},'confirmed'),({'code':19024,'StatusCode':0},'rejected'),({'code':False},'uncertain'),({},'uncertain')]:
            stream=io.BytesIO(json.dumps(response).encode())
            with patch('urllib.request.build_opener')as opener:
                opener.return_value.open.return_value.__enter__.return_value=stream
                self.assertEqual(feishu_sender.send(HOOK,'','Synthetic')['outcome'],wanted)
        with patch('urllib.request.build_opener')as opener:
            opener.return_value.open.side_effect=TimeoutError()
            self.assertEqual(feishu_sender.send(HOOK,'','Synthetic')['outcome'],'uncertain')


if __name__=='__main__':unittest.main()
