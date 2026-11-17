"""Per-store listing preparation reuses product evidence; it never publishes."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from fixture_product_workspace import seed


class ListingWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
        self.target=dict(case_id=self.cid,platform='ozon',store_ref='synthetic-store',market='RU')

    def tearDown(self):
        self.app.agent_runtime.stop();self.tmp.cleanup()

    def get(self,**target):return self.app.invoke('commerce_listing_get',{**self.target,**target},'test')

    def save(self,view,**changes):
        payload={**view['payload'],**changes}
        return self.app.invoke('commerce_listing_save',{**view['target'],'payload':payload,
            'expected_revision':view['revision'],'expected_source_sha256':view['source_sha256']},'test')

    def test_read_does_not_create_drafts_tasks_or_publish(self):
        with self.app.core.db() as db:before=list(db.execute('SELECT * FROM form_drafts'))
        count=len(self.app.core.invoke('commerce_task_list',{})['tasks'])
        value=self.get()
        self.assertEqual(value['revision'],0);self.assertFalse(value['external_execution_allowed'])
        self.assertEqual(value['payload']['fields']['title'],'合成示例 · 便携式榨汁机')
        self.assertIn('platform_adapter', {c['id'] for c in value['checks'] if c['status']=='blocked'})
        with self.app.core.db() as db:self.assertEqual(before,list(db.execute('SELECT * FROM form_drafts')))
        self.assertEqual(count,len(self.app.core.invoke('commerce_task_list',{})['tasks']))

    def test_product_draft_identity_tracks_saved_and_stale_editor_revision(self):
        workspace=self.app.product_workspace.get(self.cid)
        initial=self.get()['product_draft']
        self.assertEqual(initial['revision'],workspace['forms']['content']['revision'])
        self.app.product_workspace.save(self.cid,'content',{'fields':{'title':'待核对的优化标题'}},
            workspace['forms']['content']['revision'],workspace['source_sha256'])
        current=self.get()
        self.assertEqual(current['payload']['fields']['title'],'待核对的优化标题')
        self.assertEqual(current['product_draft']['revision'],initial['revision']+1)
        self.assertTrue(current['product_draft']['has_payload'])
        self.assertFalse(current['product_draft']['stale'])
        self.assertEqual(current['product_draft']['source_sha256'],current['source_sha256'])
        self.app.organization.set_currency(self.cid,'USD')
        changed=self.get()
        self.assertTrue(changed['product_draft']['stale'])
        self.assertNotEqual(changed['product_draft']['source_sha256'],changed['source_sha256'])
        self.assertFalse(changed['external_execution_allowed'])

    def test_store_market_and_platform_drafts_never_overwrite_one_another(self):
        first=self.get();fields={**first['payload']['fields'],'title':'Synthetic Ozon version'}
        saved=self.save(first,fields=fields)
        self.assertEqual(saved['revision'],1);self.assertEqual(self.get()['payload']['fields']['title'],fields['title'])
        for target in ({'platform':'amazon'},{'store_ref':'other-store'},{'market':'KZ'}):
            other=self.get(**target);self.assertEqual(other['revision'],0)
            self.assertNotEqual(other['target'],saved['target'])

    def test_parallel_and_changed_product_versions_reject_writes(self):
        first=self.get();self.save(first)
        with self.assertRaisesRegex(ValueError,'form_draft_conflict'):self.save(first)
        current=self.get();self.app.organization.set_currency(self.cid,'USD')
        self.assertTrue(self.get()['stale'])
        with self.assertRaisesRegex(ValueError,'workspace_source_changed'):self.save(current)

    def test_export_keeps_missing_checks_and_is_never_a_platform_receipt(self):
        view=self.save(self.get())
        result=self.app.invoke('commerce_listing_export',{**view['target'],'expected_preview_sha256':view['preview_sha256']},'test')
        doc=json.loads(result['content'])
        self.assertEqual(doc['platform_submission'],'not_performed');self.assertFalse(doc['external_execution_allowed'])
        self.assertTrue(doc['contains_private_business_data']);self.assertTrue(doc['preflight']['missing'])
        self.save(view,fields={**view['payload']['fields'],'title':'Changed'})
        with self.assertRaisesRegex(ValueError,'listing_preview_changed'):
            self.app.invoke('commerce_listing_export',{**view['target'],'expected_preview_sha256':view['preview_sha256']},'test')

    def test_invalid_values_and_unsupported_platform_are_rejected(self):
        for target in ({'platform':'arbitrary'},{'market':'Russia'},{'store_ref':'https://user:secret@example.com'}):
            with self.subTest(target=target),self.assertRaises(ValueError):self.get(**target)
        value=self.get()
        for key,bad in [('quantity',True),('price','NaN'),('image_refs',['javascript:alert(1)']),('currency','RUBLE')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.save(value,fields={**value['payload']['fields'],key:bad})

    def test_malformed_original_editor_fields_are_visible_missing_inputs(self):
        source=self.app.product_workspace.get(self.cid)
        self.app.product_workspace.save(self.cid,'content',{'fields':{'image_refs':'not-an-image-list','price':True}},
            source['forms']['content']['revision'],source['source_sha256'])
        value=self.get()
        self.assertEqual(value['payload']['fields']['image_refs'],[])
        self.assertEqual(value['payload']['fields']['price'],'')
        self.assertEqual(set(value['invalid_source_fields']),{'image_refs','price'})
        self.assertIn('source_fields',value['missing'])

    def test_both_independent_store_plans_are_kept_separately(self):
        for platform in ('shopify','woocommerce'):
            value=self.get(platform=platform);self.save(value,language='en')
            self.assertEqual(self.get(platform=platform)['revision'],1)
        self.assertEqual(self.get()['revision'],0)

    def test_saved_store_plans_can_be_found_again_without_guessing_store_ids(self):
        self.save(self.get())
        self.save(self.get(store_ref='second-store'))
        targets=self.get()['saved_targets']
        self.assertEqual({t['store_ref'] for t in targets},{'synthetic-store','second-store'})
        self.assertTrue(all(t['case_id']==self.cid and t['revision']==1 for t in targets))

    def test_store_workbench_keeps_partial_errors_and_no_remote_success(self):
        with patch.object(self.app.operations,'list',side_effect=RuntimeError('private exception')):
            result=self.app.invoke('commerce_store_workbench',{'demo':True},'test')
        self.assertIn('imported_alerts',result['unavailable'])
        self.assertNotIn('private exception',json.dumps(result))
        self.assertFalse(result['access']['remote_access_enabled'])
        self.assertFalse(result['access']['platform_writes_enabled'])
        self.assertTrue(all(x['synthetic'] for x in result['products']))


if __name__=='__main__':unittest.main()
