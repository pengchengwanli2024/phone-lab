"""One version-bound local delivery checklist over existing drafts and artifacts."""
from pathlib import Path
import sys
import unittest
import sqlite3
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures


class DeliveryReview(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OrganizationTests();self.fixture.setUp()
        self.app,self.cid=self.fixture.app,self.fixture.cid
        self.fixture.prepare_cost()
        doc=self.app.business.template('listing')['document']
        doc.update(synthetic=False,scope={'platform':'ozon','store_ref':self.app.live.config()['connection_id'],'subject_ref':self.cid})
        for row in doc['records']:
            if row['key']=='price':row['value']='100.00'
            if row['key']=='currency':row['value']='CNY'
        self.doc=doc;self.source=self.app.business.import_source(doc,'delivery-facts')
        value=self.app.product_workspace.get(self.cid)
        saved=self.app.product_workspace.save(self.cid,'content',{'source_id':self.source['source_id'],'fields':{r['key']:r['value'] for r in doc['records']}},0,value['source_sha256'])
        self.draft=self.app.product_workspace.submit_content(self.cid,saved['revision'],value['source_sha256'])

    def tearDown(self):self.app.agent_runtime.stop();self.fixture.tearDown()

    def read(self):return self.app.invoke('commerce_workspace_delivery_get',{'case_id':self.cid},'test')

    def checks(self):
        return {key:{'status':'confirmed','source_ref':'synthetic:operator-review-'+key,'note':'Synthetic review only'} for key in ('facts','translation','media_rights','platform_rules')}

    def record(self,decision='save',checks=None,key='delivery-review'):
        view=self.read()
        return self.app.invoke('commerce_workspace_delivery_record',dict(case_id=self.cid,
            expected_package_sha256=view['package_sha256'],expected_source_sha256=view['source_sha256'],
            expected_review_sha256=view['latest']['sha256'] if view['latest'] else '',
            checks=checks if checks is not None else self.checks(),decision=decision,confirmed=True,idempotency_key=key),'test')

    def media(self):
        project,asset=self.fixture.creative()
        self.app.organization.deliver(self.cid,project['id'],[asset['id']],'delivery-images')

    def test_checklist_can_be_saved_with_pending_items_but_missing_images_blocks_review(self):
        self.assertTrue(hasattr(self.app.product_workspace,'delivery'),'unified delivery review must be connected')
        checks=self.checks();checks['media_rights']['status']='pending'
        self.record(checks=checks)
        view=self.read();self.assertEqual(view['status'],'needs_inputs')
        self.assertTrue(any(r['id']=='images' and not r['passed'] for r in view['automatic_checks']))
        with self.assertRaisesRegex(ValueError,'delivery_incomplete'):self.record('reviewed',key='blocked-review')
        self.assertEqual(self.app.business.get(self.draft['id'])['receipts'],[])

    def test_review_uses_original_business_receipt_and_preserves_professional_gate(self):
        self.media();self.record('reviewed')
        view=self.read();self.assertEqual(view['status'],'local_review_recorded')
        self.assertEqual(view['latest']['payload']['receipt_id'],self.app.business.get(self.draft['id'])['receipts'][-1]['id'])
        self.assertFalse(view['external_execution_allowed'])
        self.assertFalse(view['platform_rules_verified'])
        self.assertEqual(next(s for s in self.app.organization.board(self.cid)['stages'] if s['id']=='S6')['status'],'BLOCKED')
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_source_revision_makes_previous_checklist_stale(self):
        self.media();self.record('reviewed')
        self.doc['records'][0]['value']='changed source'
        self.app.business.import_source(self.doc,'changed-delivery-source',self.source['source_id'],self.source['version'])
        self.assertEqual(self.read()['status'],'stale')

    def test_concurrent_review_cannot_overwrite_current_checklist(self):
        self.media();view=self.read()
        args=dict(case_id=self.cid,expected_package_sha256=view['package_sha256'],expected_source_sha256=view['source_sha256'],expected_review_sha256='',checks=self.checks(),decision='save',confirmed=True,idempotency_key='initial')
        self.app.invoke('commerce_workspace_delivery_record',args,'test')
        with self.assertRaisesRegex(ValueError,'delivery_review_conflict'):
            self.app.invoke('commerce_workspace_delivery_record',{**args,'idempotency_key':'late'},'test')

    def test_failed_checklist_write_rolls_back_the_original_business_receipt(self):
        self.media()
        with self.app.core.db() as db:
            db.execute("CREATE TRIGGER reject_delivery BEFORE INSERT ON org_artifacts WHEN NEW.kind='delivery_review' BEGIN SELECT RAISE(ABORT,'synthetic-delivery-storage-failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.record('reviewed')
        self.assertEqual(self.app.business.get(self.draft['id'])['receipts'],[])


if __name__=='__main__':unittest.main()
