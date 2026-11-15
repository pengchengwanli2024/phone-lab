"""Snapshot reconciliation and local review never act as platform approval."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed
from platform_connections import protocols as api
from test_platform_connections import config
from research import canonical


class ListingReconciliation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
        with self.app.core.db()as db:
            row=json.loads(db.execute('SELECT scope FROM org_cases WHERE id=?',(self.cid,)).fetchone()[0]);row['synthetic']=False
            db.execute('UPDATE org_cases SET scope=?WHERE id=?',(canonical(row),self.cid))
        self.store=self.app.platforms.configure(config('tiktok'))
        self.target=dict(case_id=self.cid,platform='tiktok',store_ref=self.store['store_id'],market='US')
        v=self.app.listings.get(**self.target);payload=v['payload'];payload['fields'].update(sku='SYNTHETIC-SKU',title='Prepared title',price='25.00',currency='USD',quantity=4)
        self.app.listings.save(**self.target,payload=payload,expected_revision=v['revision'],expected_source_sha256=v['source_sha256'])

    def tearDown(self):self.app.agent_runtime.stop();self.tmp.cleanup()
    def snapshot(self,records=None,age=0):
        c=self.app.platforms.config(self.store['store_id']);doc=dict(store={k:c[k]for k in ('store_id','platform','market','revision')},resource='products',observed_at=time.time()-age,complete=True,
            records=records if records is not None else[api.record('synthetic-id',sku='SYNTHETIC-SKU',title='Observed title',amount='26',currency='USD',quantity=7,quantity_basis='tiktok_reported_inventory_not_reviewed')],evidence=[])
        doc['sha256']=api.digest(doc);ident='c'*32
        with self.app.core.db()as db:
            db.execute('INSERT OR REPLACE INTO platform_snapshots VALUES (?,?,?,?,?,?)',(ident,c['store_id'],'products',c['revision'],api.encoded(doc),doc['observed_at']))
            db.execute('INSERT OR REPLACE INTO platform_latest VALUES (?,?,?)',(c['store_id'],'products',ident))
    def get(self,**target):return self.app.invoke('commerce_listing_reconcile',{**self.target,**target})
    def record(self,v,decision='reviewed',key='synthetic-review'):
        return self.app.invoke('commerce_listing_review',{**self.target,'expected_comparison_sha256':v['comparison_sha256'],'expected_review_sha256':v['review']['sha256'] if v['review']else'','decision':decision,'note':'Synthetic local review','confirmed':True,'idempotency_key':key})

    def test_exact_store_sku_and_currency_comparison_preserves_quantity_uncertainty(self):
        self.snapshot()
        with patch.object(self.app.platforms,'request',side_effect=AssertionError('reconciliation must not sync')):view=self.get()
        self.assertEqual(view['observation']['status'],'observed')
        self.assertEqual({r['field']:r['status']for r in view['differences']},{'title':'different','price':'different','currency':'same','quantity':'not_comparable'})
        self.assertFalse(view['external_execution_allowed']);self.assertFalse(view['platform_submission_verified'])

    def test_duplicate_sku_stale_market_and_missing_store_fail_closed(self):
        row=api.record('a',sku='SYNTHETIC-SKU');self.snapshot([row,dict(row,entity_id='b',row_id='b')])
        self.assertEqual(self.get()['observation']['status'],'sku_ambiguous')
        self.snapshot(age=4000);self.assertEqual(self.get()['observation']['status'],'snapshot_stale')
        self.assertEqual(self.get(market='RU')['observation']['status'],'scope_mismatch')
        self.assertEqual(self.get(store_ref='unlinked')['observation']['status'],'store_unlinked')

    def test_review_is_original_artifact_idempotent_and_invalidated_by_snapshot_or_plan(self):
        self.snapshot();v=self.get();receipt=self.record(v)
        self.assertEqual(receipt['id'],self.record(v)['id'])
        current=self.get();self.assertTrue(current['review']['current'])
        self.assertEqual(current['review']['decision'],'reviewed')
        self.snapshot(age=5);self.assertFalse(self.get()['review']['current'])
        with self.assertRaisesRegex(ValueError,'listing_comparison_changed'):self.record(v,key='old-view')
        with self.app.core.db()as db:self.assertEqual(db.execute("SELECT count(*)FROM org_artifacts WHERE kind LIKE 'listing_check_%'").fetchone()[0],1)

    def test_missing_snapshot_cannot_be_reviewed_as_observed_and_directory_keeps_target(self):
        v=self.get()
        with self.assertRaisesRegex(ValueError,'listing_observation_required'):self.record(v)
        self.record(v,'needs_changes')
        rows=self.app.invoke('commerce_listing_directory',{'demo':False})['items']
        self.assertEqual(rows[0]['target'],self.target);self.assertEqual(rows[0]['review_status'],'needs_changes')
        self.assertEqual(self.app.invoke('commerce_listing_directory',{'demo':True})['items'],[])
        self.assertEqual(self.get(store_ref='')['observation']['status'],'store_unlinked')

    def test_concurrent_review_is_idempotent_and_corrupt_receipt_is_rejected(self):
        self.snapshot();v=self.get()
        with ThreadPoolExecutor(max_workers=2)as pool:receipts=list(pool.map(lambda _:self.record(v),range(2)))
        self.assertEqual(receipts[0]['id'],receipts[1]['id'])
        with self.app.core.db()as db:
            row=json.loads(db.execute('SELECT payload FROM org_artifacts WHERE id=?',(receipts[0]['id'],)).fetchone()[0]);row['note']='Tampered'
            db.execute('UPDATE org_artifacts SET payload=?WHERE id=?',(canonical(row),receipts[0]['id']))
        with self.assertRaisesRegex(ValueError,'listing_review_integrity_failed'):self.record(v)

    def test_snapshot_must_bind_the_current_configuration_revision(self):
        self.snapshot()
        with self.app.core.db()as db:
            doc=json.loads(db.execute('SELECT document FROM platform_snapshots WHERE id=?',('c'*32,)).fetchone()[0]);doc['store']['revision']='incorrect-revision'
            doc['sha256']=api.digest({k:v for k,v in doc.items()if k!='sha256'})
            db.execute('UPDATE platform_snapshots SET document=?WHERE id=?',(api.encoded(doc),'c'*32))
        with self.assertRaisesRegex(ValueError,'listing_snapshot_scope_invalid'):self.get()


if __name__=='__main__':unittest.main()
