import sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from unittest.mock import patch
from fixture_product_workspace import seed
VALUES=dict(currency='CNY',price=100,purchase_cost=20,domestic_shipping=2,packaging=1,fulfillment_cost=10,electronic_fee=1,commission_rate=.1,payment_rate=.02,return_rate=.03,ad_rate=.05)

class CostScenariosTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.cid=seed(self.app)
    def tearDown(self):self.app.agent_runtime.stop();self.tmp.cleanup()
    def test_saved_alternatives_compare_without_mutating_current_cost(self):
        self.assertTrue(hasattr(self.app,'cost_scenarios'))
        w=self.app.product_workspace;s=w.get(self.cid)
        saved=w.save(self.cid,'cost',{'input':VALUES},0,s['source_sha256'])
        before=w.get(self.cid)
        args=dict(case_id=self.cid,label='Synthetic base',expected_source_sha256=before['source_sha256'],expected_revision=before['forms']['cost']['revision'],idempotency_key='synthetic-base')
        self.assertEqual(len(self.app.cost_scenarios.save(**args)['items']),1)
        self.assertEqual(len(self.app.cost_scenarios.save(**args)['items']),1)
        self.assertEqual(w.get(self.cid),before)
        alternative=dict(VALUES,price=VALUES['price']+10)
        w.save(self.cid,'cost',{'input':alternative},before['forms']['cost']['revision'],before['source_sha256'])
        self.app.cost_scenarios.save(**{**args,'label':'Synthetic alternative','expected_revision':before['forms']['cost']['revision']+1,'idempotency_key':'synthetic-alternative'})
        rows=self.app.cost_scenarios.get(self.cid)['items'];self.assertEqual(len(rows),2)
        self.assertNotEqual(rows[0]['result']['contribution'],rows[1]['result']['contribution'])
        self.assertFalse(any(r['stale']for r in rows))
        with patch('supply_quotes.selection_issues',return_value=['expired']):
            self.assertTrue(all(r['stale']for r in self.app.cost_scenarios.get(self.cid)['items']))
            with self.assertRaisesRegex(ValueError,'workspace_quote_not_ready'):
                self.app.cost_scenarios.save(**{**args,'expected_revision':before['forms']['cost']['revision']+1,'idempotency_key':'expired-quote'})
    def test_unconfirmed_currency_stale_input_and_unknown_scope_are_rejected(self):
        self.assertTrue(hasattr(self.app,'cost_scenarios'))
        w=self.app.product_workspace;s=w.get(self.cid)
        w.save(self.cid,'cost',{'input':VALUES},0,s['source_sha256'])
        args=dict(case_id=self.cid,label='Synthetic base',expected_source_sha256=s['source_sha256'],expected_revision=1,idempotency_key='synthetic-base')
        with self.assertRaisesRegex(ValueError,'form_draft_conflict'):self.app.cost_scenarios.save(**{**args,'expected_revision':2})
        self.app.organization.set_currency(self.cid,'USD')
        with self.assertRaisesRegex(ValueError,'workspace_source_changed'):self.app.cost_scenarios.save(**args)
        with self.assertRaisesRegex(ValueError,'organization_case_not_found'):self.app.cost_scenarios.get('unknown')

if __name__=='__main__':unittest.main()
