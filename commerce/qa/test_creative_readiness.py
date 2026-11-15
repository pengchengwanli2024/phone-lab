"""Read-only, evidence-aware production preparation over actual project state."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_product_media as fixtures


class CreativeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProductMediaTests();self.fixture.setUp();self.app=self.fixture.app;self.pid=self.fixture.pid

    def tearDown(self):self.fixture.tearDown()

    def read(self,pid=None):
        self.assertTrue(callable(getattr(self.app.media,'readiness',None)),'Preparation must be available as a shared read-only method')
        return self.app.invoke('commerce_media_readiness',{'project_id':pid or self.pid})

    @staticmethod
    def checks(value):return {x['key']:x for x in value['checks']}

    def business_rows(self):
        with self.app.core.db() as db:
            names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'clients'")]
            return {n:list(db.execute('SELECT * FROM "'+n+'"')) for n in names}

    def test_empty_draft_lists_specific_inputs_without_creating_tasks_or_changing_project(self):
        p=self.app.creative.create({'product':{'name':'合成待补商品','verified_facts':[]}},'empty')
        before=self.business_rows()
        result=self.read(p['id']);checks=self.checks(result)
        self.assertEqual(checks['product_facts']['status'],'missing');self.assertEqual(checks['product_image']['status'],'missing')
        self.assertEqual(checks['reference_media']['status'],'missing');self.assertEqual(checks['design_direction']['status'],'missing')
        self.assertEqual(checks['product_source']['status'],'not_applicable')
        self.assertEqual(checks['product_facts']['action']['focus'],'creative-facts')
        self.assertFalse(result['formats']['product_main']['can_create_request']);self.assertFalse(result['generation_authorized'])
        self.assertEqual(self.business_rows(),before)

    def test_valid_direction_and_facts_allow_a_request_even_without_original_photo(self):
        self.fixture.p=self.fixture.direction();path,_,_=self.app.creative.asset(self.pid,self.fixture.asset['id']);path.unlink()
        result=self.read();self.assertEqual(self.checks(result)['product_image']['status'],'unavailable')
        self.assertTrue(result['formats']['product_main']['can_create_request'])
        self.assertFalse(result['plugin_inputs_ready'])
        actual=self.app.media.request_create(self.pid,self.fixture.p['revision'],'product_main','without-photo')
        self.assertEqual(actual['status'],'awaiting_media')

    def test_valid_original_and_direction_are_ready_as_inputs_but_never_approve_generation(self):
        self.fixture.p=self.fixture.direction();result=self.read()
        self.assertTrue(result['plugin_inputs_ready']);self.assertFalse(result['generation_authorized'])
        self.assertEqual(self.checks(result)['product_image']['asset_ids'],[self.fixture.asset['id']])
        self.assertTrue(result['formats']['ugc_video']['can_create_request'])
        self.assertEqual(result['fact_verification'],'operator_provided_not_independently_verified')

    def test_fact_change_invalidates_old_direction_and_matches_actual_creation_guard(self):
        p=self.fixture.direction();brief=p['brief'];brief['product']['verified_facts'][0]['text']='合成资料已修改'
        self.app.creative.save(self.pid,brief,p['revision'],allow_direction=True)
        result=self.read();self.assertIn(self.checks(result)['design_direction']['status'],('stale','missing'))
        self.assertFalse(result['formats']['product_main']['can_create_request'])
        with self.assertRaisesRegex(ValueError,'direction_required'):
            self.app.media.request_create(self.pid,result['project_revision'],'product_main','changed')

    def test_empty_product_name_cannot_become_an_image_or_video_request(self):
        p=self.app.creative.get(self.pid);brief=p['brief'];brief['product']['name']=''
        p=self.app.creative.save(self.pid,brief,p['revision']);self.fixture.p=p;p=self.fixture.direction()
        result=self.read();self.assertEqual(self.checks(result)['product_name']['status'],'missing')
        for kind in ('product_main','ugc_video'):
            self.assertFalse(result['formats'][kind]['can_create_request'])
            with self.assertRaisesRegex(ValueError,'creative_product_name_required'):
                self.app.media.request_create(self.pid,p['revision'],kind,'blank-'+kind)

    def test_registered_but_changed_file_is_not_reported_as_a_valid_original(self):
        self.fixture.p=self.fixture.direction();path,_,_=self.app.creative.asset(self.pid,self.fixture.asset['id']);path.write_bytes(b'changed bytes')
        result=self.read();item=self.checks(result)['product_image'];self.assertEqual(item['status'],'unavailable')
        self.assertEqual(item['asset_ids'],[]);self.assertFalse(result['plugin_inputs_ready'])
        self.assertNotIn(str(path),json.dumps(result))

    def test_file_audit_is_bounded_and_does_not_claim_unchecked_files_verified(self):
        path,_,_=self.app.creative.asset(self.pid,self.fixture.asset['id']);raw=path.read_bytes()
        for index in range(9):
            file=Path(self.fixture.tmp.name)/('synthetic-'+str(index)+'.png');file.write_bytes(raw)
            self.app.creative.register(self.pid,'product_image',file,{'source_ref':'synthetic:bounded'})
        result=self.read();item=self.checks(result)['product_image']
        self.assertLessEqual(item['checked_count'],8);self.assertEqual(item['unchecked_count'],2)
        self.assertEqual(len(item['asset_ids']),8)

    def test_overview_embeds_same_readiness_contract(self):
        self.fixture.p=self.fixture.direction();standalone=self.read();overview=self.app.invoke('commerce_media_overview',{'project_id':self.pid})
        embedded=overview['readiness'];self.assertEqual(embedded['project_revision'],standalone['project_revision'])
        self.assertEqual(embedded['formats'],standalone['formats']);self.assertEqual(embedded['checks'],standalone['checks'])

    def test_unusable_fact_entries_are_not_counted_as_evidenced_selling_points(self):
        p=self.app.creative.get(self.pid);brief=p['brief'];brief['product']['verified_facts']=[{'id':'bad id','text':'未构成有效卖点','evidence_ref':''}]
        self.app.creative.save(self.pid,brief,p['revision']);result=self.read()
        self.assertEqual(self.checks(result)['product_facts']['status'],'missing')
        self.assertEqual(self.checks(result)['product_facts']['count'],0)

    def test_updated_linked_source_is_stale_and_never_claims_planning_ready(self):
        fixture=fixtures.CatalogTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        app=fixture.app;source=app.catalog.get(fixture.cid);p=app.catalog.creative(fixture.cid,source['source_sha256'],'source-readiness')
        changed=fixture.fixture.research();changed['record']['raw_excerpt']='Synthetic revised reference material.'
        app.organization.record(fixture.cid,'research',changed,'source-revised')
        result=app.invoke('commerce_media_readiness',{'project_id':p['id']})
        self.assertEqual(self.checks(result)['product_source']['status'],'stale')
        for entry in result['formats'].values():
            self.assertFalse(entry['can_create_request']);self.assertEqual(entry['error_code'],'workspace_source_changed')

    def test_changed_or_missing_pinned_reference_blocks_readiness_like_request_creation(self):
        p=self.fixture.direction();path,_,_=self.app.creative.asset(self.pid,self.fixture.reference['id']);original=path.read_bytes()
        for missing in (False,True):
            with self.subTest(missing=missing):
                if missing:path.unlink()
                else:path.write_bytes(b'changed reference')
                result=self.read();self.assertEqual(self.checks(result)['reference_media']['status'],'unavailable')
                self.assertEqual(self.checks(result)['design_direction']['status'],'stale')
                self.assertFalse(result['formats']['product_main']['can_create_request']);self.assertFalse(result['plugin_inputs_ready'])
                with self.assertRaisesRegex(ValueError,'creative_asset_(changed|unavailable)'):
                    self.app.media.request_create(self.pid,p['revision'],'product_main','changed-reference-'+str(missing))
                path.write_bytes(original)
        self.assertTrue(self.read()['formats']['product_main']['can_create_request'])

    def test_existing_empty_or_null_section_drafts_remain_readable(self):
        for index,brief in enumerate(({}, {'product':None}, {'product':{'name':'合成草稿'},'target':None})):
            with self.subTest(brief=brief):
                p=self.app.creative.create(brief,'partial-'+str(index))
                result=self.read(p['id']);self.assertFalse(result['generation_authorized'])
                self.assertEqual(self.app.media.overview(p['id'])['readiness']['checks'],result['checks'])
        blank=self.app.creative.create({},'blank-direction')
        source,_,_=self.app.creative.asset(self.pid,self.fixture.reference['id']);copy=Path(self.fixture.tmp.name)/'blank-reference.png';copy.write_bytes(source.read_bytes())
        ref=self.app.creative.register(blank['id'],'reference_image',copy,{'source_ref':'synthetic:partial'})
        from creative_direction import DIRECTION_FIELDS
        analysis={key:'合成参考拆解' for key in DIRECTION_FIELDS}
        p=self.app.media.direction_save(blank['id'],blank['revision'],analysis,[ref['id']])
        self.assertFalse(self.read(p['id'])['formats']['product_main']['can_create_request'])
        with self.assertRaisesRegex(ValueError,'creative_product_name_required'):
            self.app.media.request_create(p['id'],p['revision'],'product_main','blank-production')

    def test_null_optional_target_does_not_prevent_valid_request_creation(self):
        p=self.app.creative.get(self.pid);brief=p['brief'];brief['target']=None
        self.fixture.p=self.app.creative.save(self.pid,brief,p['revision']);p=self.fixture.direction()
        result=self.read();self.assertTrue(result['formats']['product_main']['can_create_request'])
        self.assertEqual(self.checks(result)['target_scene']['status'],'missing')


if __name__=='__main__':unittest.main()
