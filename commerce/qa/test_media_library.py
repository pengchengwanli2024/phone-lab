"""Read-only media index over temporary original domain records."""
import base64
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from test_live_connections import batch

if importlib.util.find_spec('media_library'):
    from media_library import MediaLibrary
else:MediaLibrary=None

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')


class MediaLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.app=Commerce(self.temp.name)
        self.app.ozon_accounts.configure(dict(ozon_client_id='111111',ozon_api_key='synthetic-media-account-A',store_label='Test shop A'))
        config=self.app.live.config();self.app.live._publish(config['connection_id'],'stock',batch('stock'),config,False)
        self.cid=self.app.organization.import_inventory()['cases'][0]['id']
        detail=self.app.catalog.get(self.cid);self.project=self.app.catalog.creative(self.cid,detail['source_sha256'],'library-project')
        self.asset=self.register(self.project['id'],'product_image','Original product')

    def tearDown(self):
        self.app.catalog_sync.stop();self.app.agent_runtime.stop();self.app.autonomy.stop();self.temp.cleanup()

    def library(self):
        self.assertIsNotNone(MediaLibrary,'A source-preserving local media index is missing')
        return MediaLibrary(self.app)

    def register(self,project,kind,name,source='https://example.com/original.png'):
        path=self.root/('synthetic-'+kind+('.mp4'if'video'in kind else'.png'));path.write_bytes(PNG)
        return self.app.creative.register(project,kind,path,dict(display_name=name,source_ref=source,media=dict(width=1,height=1,duration_seconds=0)))

    def source(self,kind='supplier',role='original',archived=False):
        dossier=self.app.product_evidence;value=dict(kind=kind,platform='other',label='Evidence '+kind,url='https://example.com/'+kind,model='',variant='',
            observed_at=datetime.now(timezone.utc).isoformat(),valid_until='',review_state='unreviewed',verification_note='',rights_status='reference_only',rights_evidence='',notes='',quote_ids=[],images=[],metrics={},archived=archived)
        source=dossier.source_save(self.cid,'',value,0,dossier.get(self.cid)['dossier_sha256'],'source-'+kind+'-'+role,'synthetic')['entry']
        media=dossier.media;begin=media.upload_begin(self.cid,source['id'],source['sha256'],'source.png',len(PNG),hashlib.sha256(PNG).hexdigest(),'https://example.com/'+kind+'.png',role,'synthetic')
        media.upload_chunk(self.cid,begin['upload_id'],0,base64.b64encode(PNG).decode());media.upload_finish(self.cid,begin['upload_id'])
        return dossier.source_get(self.cid,source['id'],2)['entry']

    def test_registered_creative_asset_is_indexed_with_existing_preview_packet(self):
        rows=self.library().listing(False)['items'];self.assertEqual(len(rows),1);row=rows[0]
        self.assertEqual(row['asset_id'],self.asset['id']);self.assertEqual(row['case_id'],self.cid)
        self.assertEqual(row['sku'],'SYN-SKU');self.assertEqual(row['store_identity']['label'],'Test shop A')
        self.assertEqual(row['preview']['tool'],'commerce_creative_asset_read')
        self.assertEqual(base64.b64decode(self.app.invoke(row['preview']['tool'],row['preview']['arguments'])['content_base64']),PNG)

    def test_synthetic_mode_is_explicit_and_separate(self):
        project=self.app.creative.create(dict(synthetic=True,product=dict(name='Demo',verified_facts=[]),target={},reference={}),'demo-project')
        asset=self.register(project['id'],'reference_image','Synthetic only')
        self.assertNotIn(asset['id'],[r.get('asset_id')for r in self.library().listing(False)['items']])
        self.assertEqual([r['asset_id']for r in self.library().listing(True)['items']],[asset['id']])
        with self.assertRaisesRegex(ValueError,'media_library_invalid_filter'):self.library().listing('false')

    def test_unbound_projects_are_not_assigned_by_matching_sku_or_name(self):
        project=self.app.creative.create(dict(synthetic=False,product=dict(name='SYN-SKU',verified_facts=[]),target={},reference={}),'unbound')
        asset=self.register(project['id'],'generated_image','Approved FINAL product')
        row=next(r for r in self.library().listing(False)['items']if r.get('asset_id')==asset['id'])
        self.assertEqual(row['store_identity']['kind'],'unassigned')
        self.assertIsNone(row['store_identity']['account_id']);self.assertIsNone(row['case_id'])
        self.assertEqual(row['review_status'],'unreviewed');self.assertFalse(row['publication_approved'])
        filtered=self.library().listing(False,connection_id=self.app.live.config()['connection_id'])['items']
        self.assertNotIn(asset['id'],[r.get('asset_id')for r in filtered])

    def test_supplier_and_competitor_archive_preserve_exact_role_and_preview(self):
        supplier=self.source();competitor=self.source('competitor')
        rows=self.library().listing(False)['items']
        evidence=[r for r in rows if r['origin']=='product_evidence'];self.assertEqual(len(evidence),2)
        self.assertEqual({r['kind']for r in evidence},{'supplier_image','competitor_image'})
        row=next(r for r in evidence if r['entry_id']==supplier['id'])
        self.assertEqual(row['preview']['tool'],'commerce_product_evidence_image')
        self.assertEqual(row['preview']['arguments']['expected_entry_sha256'],supplier['sha256'])
        result=self.app.invoke(row['preview']['tool'],row['preview']['arguments']);self.assertEqual(base64.b64decode(result['content_base64']),PNG)
        self.assertFalse(row['independently_verified']);self.assertFalse(row['publication_approved'])

    def test_generated_supplier_image_is_not_presented_as_original_supplier_photo(self):
        self.source(role='generated');rows=[r for r in self.library().listing(False)['items']if r['origin']=='product_evidence']
        self.assertEqual(rows[0]['kind'],'generated_image');self.assertEqual(rows[0]['source_kind'],'supplier')
        self.assertEqual(rows[0]['role'],'generated');self.assertEqual(rows[0]['review_status'],'unreviewed')

    def test_current_evidence_only_no_history_duplicates_or_inactive_preview(self):
        source=self.source();dossier=self.app.product_evidence
        payload={k:source[k]for k in __import__('product_evidence').SOURCE_FIELDS};payload['notes']='Updated source'
        dossier.source_save(self.cid,source['id'],payload,2,dossier.get(self.cid)['dossier_sha256'],'new-version','synthetic')
        rows=[r for r in self.library().listing(False)['items']if r['origin']=='product_evidence'];self.assertEqual(len(rows),1)
        self.app.ozon_accounts.configure(dict(ozon_client_id='222222',ozon_api_key='synthetic-media-account-B',store_label='Test shop B'))
        rows=self.library().listing(False)['items'];self.assertFalse(any(r['origin']=='product_evidence'for r in rows))
        creative=next(r for r in rows if r.get('asset_id')==self.asset['id'])
        self.assertEqual(creative['store_identity']['label'],'Test shop A');self.assertFalse(creative['store_identity']['active'])
        self.assertTrue(creative['preview']['available'])
        self.assertFalse(creative['product_readable'])

    def test_missing_local_file_is_unavailable_and_never_a_remote_fetch(self):
        path,_,_=self.app.creative.asset(self.project['id'],self.asset['id']);path.unlink()
        row=self.library().listing(False)['items'][0];self.assertFalse(row['preview']['available'])
        self.assertIsNone(row['preview']['tool']);self.assertEqual(row['storage_status'],'missing_local_file')

    def test_paths_and_credential_like_references_are_not_returned(self):
        self.register(self.project['id'],'reference_image','/Users/private-owner/secret.png',source='https://example.com/image.png?api_key=private-key')
        self.register(self.project['id'],'reference_image','/private/synthetic-hidden.png',source='/Volumes/private/synthetic-local.png')
        encoded=json.dumps(self.library().listing(False))
        for private in ('/Users/','/private/','/Volumes/','private-owner','private-key','api_key=','111111','synthetic-media-account-A'):
            self.assertNotIn(private,encoded)

    def test_filters_pagination_and_bounds(self):
        for n in range(3):self.register(self.project['id'],'generated_image','Generated '+str(n))
        library=self.library();allrows=library.listing(False)['items']
        pages=library.listing(False,limit=2)['items']+library.listing(False,limit=2,offset=2)['items']
        self.assertEqual([r['id']for r in pages],[r['id']for r in allrows])
        self.assertEqual(len(library.listing(False,kind='generated_image')['items']),3)
        self.assertEqual(len(library.listing(False,query='SYN-SKU')['items']),4)
        self.assertEqual(library.listing(False,connection_id='another-connection')['items'],[])
        for kwargs in ({'limit':51},{'limit':0},{'limit':True},{'offset':-1},{'query':'x'*201},{'kind':'invented'}):
            with self.assertRaisesRegex(ValueError,'media_library_invalid_filter'):library.listing(False,**kwargs)

    def test_video_classification_does_not_claim_genuine_ugc_or_publication(self):
        self.register(self.project['id'],'generated_video','UGC approved final')
        row=self.library().listing(False,kind='video')['items'][0]
        self.assertEqual(row['asset_kind'],'generated_video');self.assertEqual(row['review_status'],'unreviewed')
        self.assertFalse(row['publication_approved']);self.assertFalse(row['quality_verified'])

    def test_archived_evidence_is_marked_unavailable(self):
        self.source(archived=True)
        row=next(r for r in self.library().listing(False)['items']if r['origin']=='product_evidence')
        self.assertFalse(row['preview']['available']);self.assertEqual(row['storage_status'],'source_archived')

    def test_index_does_not_create_or_update_domain_rows(self):
        tables=['creative_projects','creative_assets','creative_requests','product_evidence_versions','tasks','org_cases']
        def state():
            with self.app.core.db()as db:return {t:list(db.execute('SELECT * FROM '+t+' ORDER BY rowid'))for t in tables}
        before=state();self.library().listing(False);self.assertEqual(before,state())

    def test_current_product_navigation_and_store_facets_are_complete_before_paging(self):
        row=self.library().listing(False)['items'][0];self.assertIn('product_readable',row);self.assertTrue(row['product_readable'])
        project=self.app.creative.create(dict(synthetic=False,product=dict(name='Unassigned',verified_facts=[]),target={},reference={}),'facet-unassigned')
        self.register(project['id'],'reference_image','Unassigned picture')
        result=self.library().listing(False,limit=1)
        self.assertEqual(len(result['items']),1)
        self.assertEqual(sum(s['count']for s in result['stores']),2)
        self.assertEqual(len(result['stores']),2)


if __name__=='__main__':unittest.main()
