"""Exact Ozon category/type and attribute evidence, with no marketplace writes."""
import copy
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed
from listing_workspace import validate_payload

TREE={'result':[{'description_category_id':10,'category_name':'Synthetic category','disabled':False,'children':[
    {'type_id':20,'type_name':'Synthetic type','disabled':False,'children':[]}]}]}
ATTR={'result':[dict(id=101,name='Synthetic brand',description='Reference label',type='String',is_required=True,
    is_collection=False,dictionary_id=7,max_value_count=1,attribute_complex_id=0),
    dict(id=102,name='Synthetic count',description='',type='Integer',is_required=True,
    is_collection=False,dictionary_id=0,max_value_count=1,attribute_complex_id=0)]}
VALUES={'result':[{'id':8,'value':'Synthetic brand','info':'','picture':''}],'has_next':False}


class ListingSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
        self.target=dict(case_id=self.cid,platform='ozon',store_ref='ozon-live',market='RU')
        self.assertTrue(hasattr(self.app,'listing_schema'),'Ozon schema service must be wired into Commerce')
        # Isolated synthetic case exercises real-mode metadata without a live call.
        with self.app.core.db()as db:
            scope=json.loads(db.execute('SELECT scope FROM org_cases WHERE id=?',(self.cid,)).fetchone()[0]);scope['synthetic']=False
            db.execute('UPDATE org_cases SET scope=?WHERE id=?',(json.dumps(scope),self.cid))
        self.app.live.configure({'ozon_client_id':'123456','ozon_api_key':'synthetic-key-only'})
        self.calls=[]
        def reader(path,body,client,key):
            self.calls.append((path,body));return copy.deepcopy(TREE if path.endswith('/tree')else VALUES if path.endswith('/values')else ATTR),'f'*64
        self.app.listing_schema.reader=reader

    def tearDown(self):
        self.app.listing_schema.stop() if hasattr(self.app,'listing_schema')else None
        self.app.agent_runtime.stop();self.tmp.cleanup()

    def get(self,**args):return self.app.invoke('commerce_listing_schema_get',{**self.target,**args},'test')

    def refresh(self,resource,**args):
        job=self.app.invoke('commerce_listing_schema_refresh',{**self.target,'resource':resource,**args},'test')
        for _ in range(100):
            view=self.get(**{k:v for k,v in args.items()if k in ('category_id','type_id','attribute_id','last_value_id')})
            if view['refresh']and view['refresh']['id']==job['id']and view['refresh']['status']!='running':return view
            time.sleep(.01)
        self.fail('bounded metadata refresh did not finish')

    def payload(self):
        p=copy.deepcopy(self.app.listings.get(**self.target)['payload']);p['fields']['category_id']='10'
        p['ozon']={'type_id':20,'attributes':[
            {'id':101,'values':[{'dictionary_value_id':8,'value':'Synthetic brand'}],'source_ref':'Synthetic package brand'},
            {'id':102,'values':[{'dictionary_value_id':0,'value':'3'}],'source_ref':'Synthetic packaging count'}]}
        return p

    def test_read_is_local_and_original_payload_roundtrips(self):
        before=self.app.core.invoke('commerce_task_list',{})['tasks'];v=self.get()
        self.assertEqual(self.calls,[]);self.assertEqual(v['validation']['status'],'missing_category_tree')
        p=self.app.listings.get(**self.target)['payload'];self.assertEqual(validate_payload(p),p)
        for invalid in (True,-1,1.5,'20'):
            bad=self.payload();bad['ozon']['type_id']=invalid
            with self.assertRaisesRegex(ValueError,'listing_invalid_ozon'):validate_payload(bad)
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],before)

    def test_exact_type_dictionary_and_required_fields_validate_but_never_publish(self):
        v=self.refresh('tree');self.assertEqual(v['categories']['items'][0]['type_id'],20)
        self.refresh('attributes',category_id=10,type_id=20)
        p=self.payload();v=self.get(payload=p,category_id=10,type_id=20)
        self.assertNotEqual(v['validation']['status'],'limited_check_passed')
        self.refresh('values',category_id=10,type_id=20,attribute_id=101)
        v=self.get(payload=p,category_id=10,type_id=20,attribute_id=101)
        self.assertEqual(v['validation']['status'],'limited_check_passed');self.assertFalse(v['external_execution_allowed'])
        plan=self.app.listings.get(**self.target)
        saved=self.app.listings.save(**self.target,payload=p,expected_revision=plan['revision'],expected_source_sha256=plan['source_sha256'])
        self.assertEqual(saved['payload']['ozon'],p['ozon'])
        self.assertIn('platform_adapter',saved['missing']);self.assertIn('professional_gate',saved['missing'])
        self.assertNotIn('platform_schema',saved['missing'])
        p['ozon']['attributes'][0]['values'][0]['value']='Different label'
        self.assertNotEqual(self.get(payload=p,category_id=10,type_id=20)['validation']['status'],'limited_check_passed')

    def test_disabled_tree_stale_metadata_and_corrupt_cache_do_not_validate(self):
        self.refresh('tree');self.refresh('attributes',category_id=10,type_id=20)
        self.refresh('values',category_id=10,type_id=20,attribute_id=101)
        p=self.payload();self.assertEqual(self.get(payload=p)['validation']['status'],'limited_check_passed')
        with self.app.core.db()as db:db.execute("UPDATE live_snapshots SET observed='2000-01-01T00:00:00+00:00'")
        self.assertEqual(self.get(payload=p)['validation']['status'],'stale_schema')
        self.refresh('tree');bad=copy.deepcopy(TREE);bad['result'][0]['disabled']=True
        self.app.listing_schema.reader=lambda *args:(bad,'a'*64)
        self.refresh('tree');self.assertEqual(self.get(payload=p)['validation']['status'],'disabled_type')
        with self.app.core.db()as db:db.execute("UPDATE live_snapshots SET sha='invalid'")
        with self.assertRaisesRegex(ValueError,'listing_schema_integrity_failed'):self.get()

    def test_config_changed_inflight_preserves_old_snapshot_and_exposes_failure(self):
        self.refresh('tree');before=self.get()['categories']['sha256']
        def changed(*args):
            self.app.live.configure({'ozon_client_id':'654321','ozon_api_key':'synthetic-other-key'});return TREE,'e'*64
        self.app.listing_schema.reader=changed
        job=self.app.listing_schema.refresh(**self.target,resource='tree')
        for _ in range(100):
            if self.app.listing_schema.current and self.app.listing_schema.current['status']!='running':break
            time.sleep(.01)
        self.assertEqual(self.app.listing_schema.current['error'],'listing_schema_connection_changed')
        # Original organization scoping hides the old account's case entirely.
        with self.assertRaisesRegex(ValueError,'organization_case_not_found'):self.get()
        with self.app.core.db()as db:
            self.assertEqual(db.execute("SELECT sha FROM live_snapshots WHERE kind='listing-schema:tree:RU'").fetchone()[0],before)

    def test_wrong_scope_and_demo_never_send_credentials(self):
        for target in ({'platform':'amazon'},{'market':'US'},{'store_ref':'arbitrary-store'}):
            with self.assertRaisesRegex(ValueError,'listing_schema_scope_not_supported'):
                self.app.listing_schema.refresh(**{**self.target,**target},resource='tree')
        with self.app.core.db()as db:
            scope=json.loads(db.execute('SELECT scope FROM org_cases WHERE id=?',(self.cid,)).fetchone()[0]);scope['synthetic']=True
            db.execute('UPDATE org_cases SET scope=?WHERE id=?',(json.dumps(scope),self.cid))
        with self.assertRaisesRegex(ValueError,'listing_schema_demo_no_network'):self.app.listing_schema.refresh(**self.target,resource='tree')
        self.assertEqual(self.calls,[])

    def test_dictionary_pages_are_bound_to_current_parent_and_keep_required_ids(self):
        self.refresh('tree');self.refresh('attributes',category_id=10,type_id=20)
        pages=[{'result':[{'id':6,'value':'Other brand'}],'has_next':True},VALUES]
        self.app.listing_schema.reader=lambda *args:(copy.deepcopy(pages[0]if args[1]['last_value_id']==0 else pages[1]),'b'*64)
        v=self.refresh('values',category_id=10,type_id=20,attribute_id=101)
        self.assertTrue(v['values']['has_next']);self.assertEqual(v['values']['next_cursor'],6)
        v=self.refresh('values',category_id=10,type_id=20,attribute_id=101,last_value_id=6)
        self.assertFalse(v['values']['has_next'])
        p=self.payload();self.assertEqual(self.get(payload=p)['validation']['status'],'limited_check_passed')
        with self.assertRaisesRegex(ValueError,'listing_schema_invalid_cursor'):
            self.app.listing_schema.refresh(**self.target,resource='values',category_id=10,type_id=20,attribute_id=101,last_value_id=999)
        changed=copy.deepcopy(ATTR);changed['result'][0]['dictionary_id']=99
        self.app.listing_schema.reader=lambda *args:(changed,'c'*64)
        self.refresh('attributes',category_id=10,type_id=20)
        self.assertNotEqual(self.get(payload=p)['validation']['status'],'limited_check_passed')

    def test_bad_upstream_retains_success_and_import_endpoints_are_not_allowlisted(self):
        import ozon_reader
        self.refresh('tree');sha=self.get()['categories']['sha256']
        bad=copy.deepcopy(TREE);bad['result'][0]['disabled']='false'
        self.app.listing_schema.reader=lambda *args:(bad,'b'*64)
        v=self.refresh('tree');self.assertEqual(v['refresh']['status'],'failed');self.assertEqual(v['categories']['sha256'],sha)
        with self.assertRaisesRegex(ValueError,'endpoint_not_allowed'):
            ozon_reader.post('/v3/product/import',{},'synthetic-client','synthetic-secret')


if __name__=='__main__':unittest.main()
