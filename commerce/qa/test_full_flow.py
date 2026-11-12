"""One synthetic case crosses source intake, roles, economics, delivery and recheck."""
import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from database_recovery import verify_recovery
import test_organization as fixtures

class FullFlow(unittest.TestCase):
    setUp=fixtures.OrganizationTests.setUp
    tearDown=fixtures.OrganizationTests.tearDown
    research=fixtures.OrganizationTests.research
    creative=fixtures.OrganizationTests.creative
    def call(self,name,client='harness',**args):return self.app.invoke('commerce_'+name,args,client)
    def test_scoped_case_from_evidence_to_recheck_and_offline_restore(self):
        case=self.call('organization_board',case_id=self.cid)['case']
        self.assertIsNone(case['currency'])
        self.call('organization_currency',case_id=self.cid,currency='CNY')
        context=self.call('organization_exchange_status',client='codex',case_id=self.cid)['context']
        record=self.research()['record']
        checked=self.call('organization_exchange_produce',context=context,source_tool='commerce_collection_check',source_arguments={'record':record})
        self.assertEqual(checked['artifact_handoff']['status'],'saved')
        self.call('organization_record',case_id=self.cid,kind='supply',payload={'currency':'CNY','purchase_cost':30,'lead_time_days':14,'supplier':'Synthetic supplier','source_ref':'synthetic:quote'},idempotency_key='flow-supply')
        values={'currency':'CNY','price':100,'purchase_cost':30,'domestic_shipping':2,'packaging':1,'fulfillment_cost':10,'electronic_fee':1,'commission_rate':.1,'payment_rate':.01,'return_rate':.02,'ad_rate':.05}
        economics=self.call('organization_exchange_produce',client='hermes',context=context,source_tool='commerce_unit_economics',source_arguments={'input':values})
        self.assertEqual(economics['contribution'],38)
        task=self.call('organization_handoff',case_id=self.cid,stage_id='S4')['task']
        repeated=self.call('organization_handoff',client='codex',case_id=self.cid,stage_id='S4')['task']
        self.assertEqual(task['id'],repeated['id'])
        project,asset=self.creative()
        delivery=self.call('organization_deliver',case_id=self.cid,project_id=project['id'],asset_ids=[asset['id']],idempotency_key='flow-delivery')
        self.assertFalse(delivery.get('marketplace_writes',False))
        scope={'module':'operations','form':'cost','case_id':self.cid}
        self.call('form_draft_save',scope=scope,payload={'values':values,'origin':'manual'},expected_revision=0)
        fresh=Commerce(self.tmp.name)
        self.assertEqual(fresh.invoke('commerce_form_draft_get',{'scope':scope})['payload']['values']['purchase_cost'],30)
        self.assertEqual(fresh.organization.board(self.cid)['case']['id'],self.cid)
        self.assertEqual(verify_recovery(Path(self.tmp.name))['status'],'passed')
        self.call('organization_currency',case_id=self.cid,currency='RUB')
        with self.assertRaisesRegex(ValueError,'scope_changed'):
            self.call('organization_exchange_produce',context=context,source_tool='commerce_unit_economics',source_arguments={'input':values})
        board=self.call('organization_board',case_id=self.cid)
        self.assertFalse(board['external_execution'])
        self.assertNotEqual(next(s for s in board['stages']if s['id']=='S2')['status'],'PASS')

if __name__=='__main__':unittest.main()
