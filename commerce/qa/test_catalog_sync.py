"""Real connector contracts exercised with isolated, explicitly synthetic responses."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed

INFO={'items':[dict(id=10,offer_id='SYN-SKU',name='Synthetic API product',price='29.90',currency_code='CNY',
    images=['https://example.com/synthetic.png'],primary_image=['https://example.com/synthetic.png'],
    description_category_id=1,type_id=2,statuses={'status_name':'Synthetic status'})]}
ATTR={'result':[dict(id=10,offer_id='SYN-SKU',height=20,width=10,depth=30,dimension_unit='mm',weight=50,weight_unit='g',
    attributes=[{'id':5,'complex_id':0,'values':[{'dictionary_value_id':0,'value':'Synthetic specification'}]}])],'last_id':'10','total':1}
DESC={'result':dict(id=10,offer_id='SYN-SKU',name='Synthetic API product',description='Synthetic product description')}

class CatalogSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
        self.assertTrue(hasattr(self.app,'catalog_sync'),'Current store details must be wired into the original product workflow')
        with self.app.core.db()as db:
            scope=json.loads(db.execute('SELECT scope FROM org_cases WHERE id=?',(self.cid,)).fetchone()[0]);scope.pop('synthetic');scope.pop('label')
            db.execute('UPDATE org_cases SET scope=? WHERE id=?',(json.dumps(scope),self.cid))
            db.execute("DELETE FROM org_artifacts WHERE case_id=?AND kind='research'",(self.cid,))
        self.calls=[]
        def read(path,body,*args):
            self.calls.append((path,body));return copy.deepcopy(DESC if path.endswith('/description')else ATTR if path.endswith('/attributes')else INFO),'a'*64
        self.app.catalog_sync.reader=read
    def tearDown(self):
        if hasattr(self.app,'catalog_sync'):self.app.catalog_sync.stop()
        self.app.agent_runtime.stop();self.tmp.cleanup()
    def sync(self,**kwargs):
        status=self.app.catalog_sync.status()
        self.app.catalog_sync.refresh(expected_stock_sha256=status['stock_sha256'],**kwargs)
        self.app.catalog_sync.thread.join(5)
        return self.app.catalog_sync.current
    def test_actual_sources_feed_original_catalog_and_content_without_verification(self):
        self.assertEqual(self.app.catalog_sync.status()['product_count'],1);self.assertEqual(self.calls,[])
        result=self.sync(case_id=self.cid);self.assertEqual(result['status'],'succeeded');self.assertEqual(result['imported_cases'],1)
        view=self.app.catalog.get(self.cid)
        self.assertEqual(view['name'],'Synthetic API product');self.assertEqual(view['price'],'29.90')
        self.assertTrue(any(f['key']=='dimensions'for f in view['fields']));self.assertTrue(view['images'])
        self.assertFalse(view['source_facts']);self.assertFalse(view['independently_verified'])
        self.assertEqual(view['store_facts'][0]['text'],'Synthetic product description')
        project=self.app.catalog.creative(self.cid,view['source_sha256'],'synthetic-project')
        self.assertEqual(project['brief']['product']['verified_facts'],[])
        self.assertEqual(self.app.organization.board(self.cid)['stages'][6]['status'],'BLOCKED')
        self.assertEqual(len(self.app.product_workspace.facts(self.app.organization.case(self.cid))),1)
    def test_no_duplicate_source_and_human_sources_or_drafts_never_overwritten(self):
        before=self.app.product_workspace.get(self.cid)['forms'];self.assertEqual(self.sync(case_id=self.cid)['status'],'succeeded')
        sources=self.app.business.listing(False)['sources'];self.assertEqual(self.sync(case_id=self.cid)['imported_cases'],0)
        self.assertEqual(sources,self.app.business.listing(False)['sources'])
        self.assertEqual(before,self.app.product_workspace.get(self.cid)['forms'])
        self.assertEqual(len(self.app.business.listing(True)['sources']),1)
        self.assertEqual(self.sync()['imported_cases'],0)
        self.assertEqual(sources,self.app.business.listing(False)['sources'])
    def test_seeded_listing_preserves_exact_typed_attribute_ids_and_unknown_quantity(self):
        self.assertEqual(self.sync(case_id=self.cid)['status'],'succeeded')
        plan=self.app.listings.get(self.cid,'ozon','ozon-live','RU')
        self.assertEqual(plan['payload']['ozon']['type_id'],2)
        self.assertEqual(plan['payload']['ozon']['attributes'][0]['id'],5)
        self.assertIsNone(plan['payload']['fields']['quantity'])
        self.assertIn('professional_gate',plan['missing']);self.assertIn('platform_adapter',plan['missing'])
    def test_listing_readback_uses_exact_fulfillment_and_actual_detail_snapshot(self):
        from test_live_connections import batch
        c=self.app.live.config();stock=batch('stock')
        stock['records'][0]['stocks'].append(dict(stock['records'][0]['stocks'][0],type='fbo'))
        self.app.live._publish(c['connection_id'],'stock',stock,c,True)
        self.assertEqual(self.sync(case_id=self.cid)['status'],'succeeded')
        target=dict(case_id=self.cid,platform='ozon',store_ref='ozon-live',market='RU')
        view=self.app.listing_reconciliation.get(**target)
        self.assertEqual(view['observation']['status'],'observed');self.assertEqual(view['observation']['match_count'],1)
        self.assertEqual(view['observation']['matches'][0]['amount'],'29.90')
        self.assertEqual(view['observation']['matches'][0]['status'],'Synthetic status')
        self.assertIsNone(view['observation']['matches'][0]['quantity'])
        self.assertTrue(view['observation']['detail_fresh'])
        with self.app.core.db()as db:db.execute("UPDATE live_snapshots SET observed='2000-01-01T00:00:00+00:00'WHERE kind LIKE 'catalog-details:%'")
        stale=self.app.listing_reconciliation.get(**target)['observation']
        self.assertFalse(stale['detail_fresh']);self.assertIsNone(stale['matches'][0]['amount'])
    def test_midflight_stock_change_never_imports_a_mixed_snapshot(self):
        from test_live_connections import batch
        def read(*args):
            c=self.app.live.config();self.app.live._publish(c['connection_id'],'stock',batch('stock',value=20),c,True)
            return INFO,'e'*64
        self.app.catalog_sync.reader=read
        self.assertEqual(self.sync()['status'],'failed')
        self.assertEqual(self.app.business.listing(False)['sources'],[])
    def test_wrong_identity_or_duplicate_response_leaves_original_sources_unchanged(self):
        for raw in ({'items':[dict(INFO['items'][0],offer_id='another-product')]},{'items':INFO['items']*2}):
            self.app.catalog_sync.reader=lambda *args:(raw,'b'*64)
            self.assertEqual(self.sync()['status'],'failed')
            self.assertEqual(self.app.business.listing(False)['sources'],[])
    def test_partial_optional_reads_preserve_missing_and_real_success_evidence(self):
        def read(path,*args):
            if not path.endswith('/list'):raise ValueError('private-key-canary')
            return INFO,'c'*64
        self.app.catalog_sync.reader=read
        result=self.sync(case_id=self.cid);self.assertEqual(result['status'],'partial')
        self.assertNotIn('private-key-canary',json.dumps(result));self.assertEqual(len(result['issues']),2)
        view=self.app.catalog.get(self.cid);self.assertFalse(view['store_facts'])
        self.assertEqual(view['name'],'Synthetic API product')
    def test_key_rotation_or_stock_change_before_commit_rejects_old_result(self):
        def read(*args):
            self.app.live.configure({'ozon_api_key':'synthetic-rotated-key'})
            return INFO,'d'*64
        self.app.catalog_sync.reader=read
        self.assertEqual(self.sync()['status'],'failed');self.assertEqual(len(self.calls),0)
        self.assertEqual(self.app.business.listing(False)['sources'],[])
    def test_demo_stale_snapshot_and_scope_never_fetch(self):
        status=self.app.catalog_sync.status()
        with self.assertRaisesRegex(ValueError,'catalog_sync_stock_changed'):
            self.app.catalog_sync.refresh(expected_stock_sha256='0'*64)
        with self.app.core.db()as db:
            scope=json.loads(db.execute('SELECT scope FROM org_cases WHERE id=?',(self.cid,)).fetchone()[0]);scope['synthetic']=True
            db.execute('UPDATE org_cases SET scope=?WHERE id=?',(json.dumps(scope),self.cid))
        with self.assertRaisesRegex(ValueError,'catalog_sync_scope'):
            self.app.catalog_sync.refresh(expected_stock_sha256=status['stock_sha256'],case_id=self.cid)
        with self.app.core.db()as db:db.execute("UPDATE live_snapshots SET observed='2000-01-01T00:00:00+00:00'WHERE kind='stock'")
        with self.assertRaisesRegex(ValueError,'catalog_sync_fresh_stock_required'):
            self.app.catalog_sync.refresh(expected_stock_sha256=status['stock_sha256'])
        self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
