"""Scoped listing overrides inherit current product fields without rewriting legacy plans."""
from pathlib import Path
import copy,json,sys,unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_listing_workspace as fixtures

class ListingInheritanceTests(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.ListingWorkspaceTests();self.fixture.setUp();self.app=self.fixture.app;self.cid=self.fixture.cid;self.target=self.fixture.target
 def tearDown(self):self.fixture.tearDown()
 def get(self,**target):return self.fixture.get(**target)
 def save(self,view,overrides=None,**metadata):
  payload=copy.deepcopy(view['payload']);payload.update(metadata)
  return self.app.invoke('commerce_listing_save',{**view['target'],'payload':payload,'field_overrides':overrides or {},'expected_base_sha256':view['base_sha256'],'expected_revision':view['revision'],'expected_source_sha256':view['source_sha256']},'test')
 def base(self,**fields):
  p=self.app.product_workspace.get(self.cid);payload=copy.deepcopy(p['forms']['content']['payload']or {'fields':{}});payload['fields'].update(fields)
  self.app.product_workspace.save(self.cid,'content',payload,p['forms']['content']['revision'],p['source_sha256'])
 def export(self,view):return self.app.invoke('commerce_listing_export',{**view['target'],'expected_preview_sha256':view['preview_sha256']},'test')
 def test_new_plan_inherits_and_persists_only_store_differences(self):
  view=self.get();self.assertEqual(view['field_overrides'],{});self.assertEqual(view['base_fields'],view['payload']['fields']);self.assertEqual(set(view['inherited_fields']),set(view['payload']['fields']))
  saved=self.save(view,language='ru');self.assertEqual(saved['payload']['fields'],view['base_fields']);self.assertEqual(saved['revision'],1)
  _,scope=self.app.listings.scope(**self.target);stored=self.app.form_drafts.get(scope)['payload'];self.assertNotIn('fields',stored['data']);self.assertEqual(stored['field_overrides'],{});self.assertEqual(stored['data']['language'],'ru')
  self.assertEqual(json.loads(self.export(saved)['content'])['preflight']['payload'],saved['payload'])
 def test_content_checkpoint_change_without_case_source_change_is_stale_and_cas_guarded(self):
  first=self.get();saved=self.save(first);self.base(title='Updated product base')
  current=self.get();self.assertTrue(self.app.listings.saved_targets(self.cid,current['source_sha256'])[0]['stale']);self.assertEqual(current['source_sha256'],saved['source_sha256']);self.assertNotEqual(current['base_sha256'],saved['base_sha256']);self.assertTrue(current['stale']);self.assertEqual(current['payload']['fields']['title'],'Updated product base')
  with self.assertRaisesRegex(ValueError,'listing_base_fields_changed'):self.save(saved)
  with self.assertRaisesRegex(ValueError,'listing_preview_changed'):self.export(saved)
  with self.assertRaisesRegex(ValueError,'workspace_source_changed'):self.export(current)
  rebound=self.save(current);self.assertFalse(rebound['stale']);self.export(rebound)
 def test_overrides_survive_base_updates_and_clear_back_to_inheritance(self):
  saved=self.save(self.get(),{'title':'Store title','price':'88'})
  self.base(title='New base title',description='New base description',price='120')
  current=self.get();self.assertEqual(current['payload']['fields']['title'],'Store title');self.assertEqual(current['payload']['fields']['price'],'88');self.assertEqual(current['payload']['fields']['description'],'New base description')
  restored=self.save(current,{'price':'88'});self.assertEqual(restored['payload']['fields']['title'],'New base title');self.assertIn('title',restored['inherited_fields']);self.assertNotIn('price',restored['inherited_fields'])
  self.base(title='Newest base title');self.assertEqual(self.get()['payload']['fields']['title'],'Newest base title')
 def test_legacy_full_payload_keeps_exact_values_and_hash_until_explicit_migration(self):
  first=self.get();old=self.fixture.save(first,fields={**first['payload']['fields'],'title':'Legacy full value'});old_hash=old['preview_sha256'];self.base(title='New base value')
  current=self.get();self.assertEqual(current['inheritance_mode'],'legacy_explicit');self.assertEqual(current['payload'],old['payload']);self.assertEqual(current['preview_sha256'],old_hash);self.assertFalse(current['stale'])
  self.assertEqual(current['field_overrides'],old['payload']['fields']);self.export(current)
  migrated=self.save(current,{key:value for key,value in current['field_overrides'].items()if key!='title'});self.assertEqual(migrated['payload']['fields']['title'],'New base value')
 def test_other_platform_store_and_market_keep_their_own_overrides(self):
  self.save(self.get(),{'title':'One target only'})
  for target in [{'platform':'amazon'},{'market':'KZ'},{'store_ref':'another-store'}]:
   with self.subTest(target=target):
    view=self.get(**target);self.assertEqual(view['revision'],0);self.assertEqual(view['field_overrides'],{});self.assertNotEqual(view['payload']['fields']['title'],'One target only')
 def test_invalid_or_unbound_override_writes_are_rejected_without_checkpoint(self):
  view=self.get()
  for bad in [{'unknown':'x'},{'quantity':True},{'image_refs':['javascript:x']},{'currency':'ruble'}]:
   with self.subTest(overrides=bad),self.assertRaises(ValueError):self.save(view,bad)
  with self.assertRaisesRegex(ValueError,'listing_base_fields_required'):
   self.app.listings.save(**self.target,payload=view['payload'],field_overrides={},expected_revision=0,expected_source_sha256=view['source_sha256'])
  self.assertEqual(self.get()['revision'],0)
 def test_invalid_inherited_base_stays_visible_until_field_is_explicitly_overridden(self):
  self.base(price=True);view=self.get();self.assertIn('price',view['invalid_source_fields']);self.assertEqual(view['payload']['fields']['price'],'')
  overridden=self.save(view,{'price':'90'});self.assertNotIn('price',overridden['invalid_source_fields']);self.assertEqual(overridden['payload']['fields']['price'],'90')
 def test_product_scope_change_still_rejects_old_overrides(self):
  view=self.get();self.app.organization.set_currency(self.cid,'USD')
  with self.assertRaisesRegex(ValueError,'workspace_source_changed'):self.save(view,{'price':'99'})


class InheritedOwnerReviewTests(unittest.TestCase):
 def setUp(self):
  import test_owner_review as owner_fixtures
  self.fixture=owner_fixtures.OwnerReviewTests();self.fixture.setUp();self.app=self.fixture.app;self.cid=self.fixture.cid;self.target=self.fixture.target
  view=self.app.listings.get(**self.target)
  self.plan=self.app.listings.save(**self.target,payload=view['payload'],field_overrides={'category_id':view['payload']['fields']['category_id']},expected_base_sha256=view['base_sha256'],expected_revision=view['revision'],expected_source_sha256=view['source_sha256'])
 def tearDown(self):self.fixture.tearDown()
 def test_owner_review_receives_complete_resolved_product_without_board_recursion(self):
  view=self.fixture.get();self.assertEqual(view['product'],self.plan['payload']);self.assertEqual(set(view['product']['fields']),set(self.plan['base_fields']));self.assertTrue(all(row['ready']for row in view['automatic_checks']),view['automatic_checks'])
  snapshot=self.app.product_workspace.get(self.cid);self.assertTrue(snapshot['stages']);self.assertEqual(snapshot['case']['id'],self.cid)
 def test_signoff_and_local_application_freeze_resolved_fields_and_become_stale_on_base_change(self):
  signed=self.fixture.record(self.fixture.get(),key='inherited-signoff');self.assertTrue(signed['current'])
  plan=self.app.listings.get(**self.target);created=self.app.listing_releases.create(**self.target,expected_preview_sha256=plan['preview_sha256'],note='Synthetic inheritance-only local application',confirmed=True,idempotency_key='inherited-freeze')
  frozen=copy.deepcopy(self.app.listing_releases.get(**self.target)['request']['frozen']);self.assertEqual(frozen['payload'],plan['payload']);self.assertEqual(frozen['owner_review']['review_sha256'],signed['review_sha256'])
  source=self.app.product_workspace.get(self.cid);content=copy.deepcopy(source['forms']['content']['payload']);content['fields']['title']='Updated after application'
  self.app.product_workspace.save(self.cid,'content',content,source['forms']['content']['revision'],source['source_sha256'])
  current=self.fixture.get();self.assertFalse(current['current']);self.assertFalse(next(row['ready']for row in current['automatic_checks']if row['id']=='source'))
  self.assertTrue(self.app.listings.get(**self.target)['stale']);historic=self.app.listing_releases.get(**self.target)['request'];self.assertEqual(historic['frozen'],frozen);self.assertEqual(historic['id'],created['request_id']);self.assertFalse(historic['platform_submission_verified'])

if __name__=='__main__':unittest.main()
