"""Service-level read contracts over temporary multi-scope inventory and assets."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce,TOOLS
import test_catalog_store_identity as catalog_fixtures

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII=')


class CatalogMediaIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.app=Commerce(self.tmp.name)
        self.app.ozon_accounts.configure(dict(ozon_client_id='111111',ozon_api_key='synthetic-integration-account-A',store_label='Integration shop A'))
        self.stock=catalog_fixtures.CatalogStoreIdentityTests.inventory();self.publish()
        self.cases=self.app.organization.cases();self.cid=next(c['id']for c in self.cases if c['scope']['product_id']=='100')

    def tearDown(self):
        self.app.catalog_sync.stop();self.app.agent_runtime.stop();self.app.autonomy.stop();self.tmp.cleanup()

    def call(self,name,**args):return self.app.invoke(name,args,'test')

    def publish(self):
        config=self.app.live.config();self.app.live._publish(config['connection_id'],'stock',self.stock,config,False)
        self.app.organization.import_inventory()

    def asset(self,kind='product_image',source='https://example.com/original.png',name='Original source'):
        detail=self.call('commerce_catalog_get',case_id=self.cid)
        project=self.call('commerce_catalog_creative',case_id=self.cid,expected_source_sha256=detail['source_sha256'],idempotency_key='integration-project')
        path=self.root/'synthetic.png';path.write_bytes(PNG)
        asset=self.app.creative.register(project['id'],kind,path,dict(source_ref=source,display_name=name,media=dict(width=1,height=1,duration_seconds=0)))
        return project,asset

    def test_service_tools_are_registered_once_and_validate_public_read_arguments(self):
        for name in ('commerce_catalog_list','commerce_catalog_get','commerce_media_library_list'):
            self.assertEqual(sum(row[0]==name for row in TOOLS),1,name)
        cards=self.call('commerce_catalog_list')['items'];self.assertEqual(len(cards),8)
        self.assertEqual(self.call('commerce_catalog_get',case_id=cards[0]['id'])['id'],cards[0]['id'])
        self.assertEqual(self.call('commerce_media_library_list',synthetic=False)['items'],[])
        for name,args in [('commerce_catalog_get',dict(case_id=self.cid,_catalog_context={})),
                          ('commerce_catalog_get',dict(case_id=self.cid,_fact_sources=[])),
                          ('commerce_media_library_list',{}),('commerce_media_library_list',dict(synthetic=False,limit=51))]:
            with self.subTest(name=name,args=args),self.assertRaisesRegex(ValueError,'invalid_arguments|media_library_invalid_filter'):
                self.app.invoke(name,args,'test')

    def test_catalog_workspace_card_is_projection_only_and_preserves_source_sha(self):
        before=self.app.product_workspace.sources(self.cid)[3]
        workspace=self.call('commerce_workspace_get',case_id=self.cid)
        detail=self.call('commerce_catalog_get',case_id=self.cid)
        self.assertEqual(workspace['source_sha256'],before);self.assertEqual(detail['source_sha256'],before)
        card=workspace['product_card'];self.assertEqual(len(card['case_ids']),3)
        self.assertEqual(card['store_identity'],detail['store_identity'])
        self.assertEqual(card['product_key'],detail['product_key'])
        self.assertFalse(workspace['external_execution_allowed'])
        self.assertFalse(card['store_identity']['identity_verified'])
        self.call('commerce_catalog_list');self.call('commerce_media_library_list',synthetic=False)
        self.assertEqual(self.app.product_workspace.sources(self.cid)[3],before)

    def test_eight_cards_retain_seventeen_individual_cases_without_merging_assets(self):
        self.asset();cards=self.call('commerce_catalog_list')['items']
        self.assertEqual(len(cards),8);self.assertEqual(sum(len(c['case_ids'])for c in cards),17)
        siblings=[c for c in self.cases if c['scope']['product_id']=='100']
        for case in siblings:
            detail=self.call('commerce_catalog_get',case_id=case['id'])
            self.assertEqual(detail['id'],case['id']);self.assertIn(case['id'],detail['case_ids'])
            self.assertEqual(bool(detail['images']),case['id']==self.cid)
        self.assertEqual(len(self.app.organization.cases()),17)

    def test_display_group_changes_do_not_invalidate_original_object_source(self):
        before=self.app.product_workspace.sources(self.cid)[3]
        row=self.stock['records'][0];row['stocks'].append(dict(row['stocks'][0],type='additional_scope'))
        self.publish();workspace=self.call('commerce_workspace_get',case_id=self.cid)
        self.assertEqual(workspace['source_sha256'],before)
        self.assertEqual(len(workspace['product_card']['case_ids']),4)
        self.assertEqual(len(self.call('commerce_catalog_list')['items']),8)

    def test_same_sku_between_accounts_keeps_asset_owner_and_current_case_permissions(self):
        project,asset=self.asset();old=self.call('commerce_catalog_get',case_id=self.cid)
        self.app.ozon_accounts.configure(dict(ozon_client_id='222222',ozon_api_key='synthetic-integration-account-B',store_label='Integration shop B'))
        self.publish();cards=self.call('commerce_catalog_list')['items'];self.assertEqual(len(cards),8)
        current=next(c for c in cards if c['product_id']=='100')
        self.assertEqual(current['sku'],old['sku']);self.assertNotEqual(current['product_key'],old['product_key'])
        self.assertNotEqual(current['store_identity']['account_id'],old['store_identity']['account_id'])
        for name in ('commerce_catalog_get','commerce_workspace_get'):
            with self.assertRaisesRegex(ValueError,'case_not_found'):self.call(name,case_id=self.cid)
        media=self.call('commerce_media_library_list',synthetic=False)['items'][0]
        self.assertEqual(media['asset_id'],asset['id']);self.assertEqual(media['store_identity']['label'],'Integration shop A')
        self.assertFalse(media['store_identity']['active']);self.assertFalse(media['product_readable'])
        self.assertTrue(media['preview']['available'])
        self.assertEqual(self.call('commerce_media_library_list',synthetic=False,store_ref=current['store_identity']['account_id'])['items'],[])

    def test_generated_candidates_and_local_preview_do_not_grant_approval(self):
        project,asset=self.asset(kind='generated_image',name='APPROVED FINAL HIGH-DEFINITION')
        library=self.call('commerce_media_library_list',synthetic=False,kind='generated_image');self.assertEqual(library['total'],1)
        media=library['items'][0];self.assertEqual(media['review_status'],'unreviewed')
        self.assertFalse(media['publication_approved']);self.assertFalse(media['quality_verified'])
        self.assertTrue(media['product_readable']);self.assertFalse(library['external_execution_allowed'])
        read=self.app.invoke(media['preview']['tool'],media['preview']['arguments'],'test')
        self.assertEqual(base64.b64decode(read['content_base64']),PNG)
        self.assertEqual(read['sha256'],media['sha256'])

    def test_catalog_and_library_do_not_echo_local_paths_or_secret_query_refs(self):
        self.asset(source='file:///private/synthetic-private-origin.png',name='/private/synthetic-private-name.png')
        self.asset(source='https://example.com/image.png?api_key=synthetic-query-canary',name='Public title')
        result=[self.call('commerce_catalog_get',case_id=self.cid),self.call('commerce_catalog_list'),
                self.call('commerce_media_library_list',synthetic=False)]
        serialized=json.dumps(result)
        for hidden in ('file:///private/','/private/synthetic-private-','synthetic-query-canary','api_key='):
            self.assertFalse(hidden in serialized,'Private source reference leaked through a read projection')
        self.assertNotIn('111111',serialized);self.assertNotIn('synthetic-integration-account-A',serialized)

    def test_service_reads_do_not_mutate_original_domain_state(self):
        self.asset();tables=('org_cases','org_artifacts','form_drafts','tasks','creative_projects','creative_assets','creative_requests','product_evidence_versions','product_evidence_reviews')
        def state():
            with self.app.core.db()as db:return {t:list(db.execute('SELECT * FROM '+t+' ORDER BY rowid'))for t in tables}
        before=state()
        self.call('commerce_catalog_list');self.call('commerce_catalog_get',case_id=self.cid)
        self.call('commerce_workspace_get',case_id=self.cid);self.call('commerce_media_library_list',synthetic=False)
        self.assertEqual(state(),before)


if __name__=='__main__':unittest.main()
