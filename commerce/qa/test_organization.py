"""Synthetic organizational gates, scoped artifacts, delivery and closed-loop checks."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from live_connections import now
from test_live_connections import batch, SECRET
from research import canonical,digest,template,validate


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name);self.org=self.app.organization
        self.app.live.configure({'ozon_client_id':'123456','ozon_api_key':SECRET,'fulfillment_modes':['OGL']})
        self.config=self.app.live.config()
        for kind in ('orders','stock'):self.app.live._publish(self.config['connection_id'],kind,batch(kind),self.config,False)
        self.case=self.org.import_inventory()['cases'][0];self.cid=self.case['id']
    def tearDown(self):self.tmp.cleanup()
    def stage(self,ident):return next(s for s in self.org.board(self.cid)['stages']if s['id']==ident)
    def research(self):
        r=template('ozon')['record'];r.update(market='RU',language='en',source_url='https://example.com/item',captured_at=now(),raw_excerpt='Synthetic item.',category_rules_url='https://example.com/rules',category_rules_checked=True)
        for v in r['fields'].values():v.update(original='Synthetic item.',zh='合成商品。',reviewed=True,locator='synthetic paragraph')
        self.assertFalse(validate(r)['issues'])
        return {'record':r,'sku':self.case['scope']['sku'],'row_key':self.case['scope']['row_key']}
    def prepare_research(self):self.org.record(self.cid,'research',self.research(),'research-1')
    def prepare_cost(self):
        self.prepare_research();self.org.set_currency(self.cid,'CNY')
        self.org.record(self.cid,'supply',{'currency':'CNY','purchase_cost':30,'lead_time_days':14,'supplier':'synthetic supplier','source_ref':'synthetic:quote row 2'},'supply-1')
        data={'currency':'CNY','price':100,'purchase_cost':30,'domestic_shipping':2,'packaging':1,'fulfillment_cost':10,'electronic_fee':1,'commission_rate':.1,'payment_rate':.01,'return_rate':.02,'ad_rate':.05}
        self.org.record(self.cid,'economics',data,'economics-1');return data
    def creative(self):
        project=self.app.creative.create({'product':{'name':'Synthetic item','verified_facts':[]}},'org-test-project');path=Path(self.tmp.name)/'input.png';path.write_bytes(b'\x89PNG\r\n\x1a\nSYNTHETIC-COPY-ONLY')
        asset=self.app.creative.register(project['id'],'product_image',path,{'source_ref':'synthetic:fixture','usage_scope':'synthetic_only'})
        return project,asset

    def test_roles_dag_and_deferred_notification_are_explicit(self):
        b=self.org.board(self.cid);self.assertEqual(len(b['roles']),12);self.assertEqual(len(b['stages']),12);self.assertEqual(b['feishu'],'user_deferred');self.assertFalse(b['external_execution'])
        self.assertEqual(self.stage('S0')['status'],'PASS');self.assertEqual(self.stage('S6')['status'],'BLOCKED');self.assertEqual(self.stage('S9')['status'],'BLOCKED')
        self.assertLess([s['id']for s in b['stages']].index('S3'),[s['id']for s in b['stages']].index('S2'))
        for s in b['stages']:
            for gap in s['gaps']:self.assertTrue(all(gap[k]for k in ('reason','owner','verify')))
        self.assertNotIn(SECRET,canonical(b))

    def test_inventory_import_is_idempotent_and_currency_is_not_inferred(self):
        self.assertEqual(self.org.import_inventory()['cases'][0]['id'],self.cid);self.assertIsNone(self.case['currency'])
        self.app.live.configure({'ozon_client_id':'654321'});self.assertEqual(self.org.cases(),[])
        with self.assertRaises(ValueError):self.org.board(self.cid)

    def test_source_binding_and_changed_translations_hold(self):
        r=self.research();r['sku']='wrong'
        with self.assertRaisesRegex(ValueError,'research_scope_mismatch'):self.org.record(self.cid,'research',r,'wrong')
        self.prepare_research();self.assertEqual(self.stage('S1')['status'],'PASS');self.assertEqual(self.stage('S5')['status'],'PASS')
        r=self.research();r['record']['fields']['title']['reviewed']=False;self.org.record(self.cid,'research',r,'new-research')
        self.assertNotEqual(self.stage('S5')['status'],'PASS')

    def test_supply_before_economics_currency_and_cost_match(self):
        data=self.prepare_cost();self.assertEqual(self.stage('S2')['status'],'PASS')
        self.org.set_currency(self.cid,'RUB');self.assertEqual(self.stage('S2')['status'],'FAIL');self.assertEqual(self.stage('S3')['status'],'FAIL')
        self.org.set_currency(self.cid,'CNY');data['purchase_cost']=1;self.org.record(self.cid,'economics',data,'mismatched-cost')
        self.assertNotEqual(self.stage('S2')['status'],'PASS')

    def test_negative_contribution_is_fail_and_missing_cost_never_zero(self):
        data=self.prepare_cost();data['price']=10;self.org.record(self.cid,'economics',data,'negative');self.assertEqual(self.stage('S2')['status'],'FAIL')
        data.pop('purchase_cost');self.org.record(self.cid,'economics',data,'missing');self.assertNotEqual(self.stage('S2')['status'],'PASS')
        with self.assertRaises(ValueError):self.org.record(self.cid,'supply',{'purchase_cost':float('nan')},'nan')

    def test_artifact_tampering_cannot_pass(self):
        self.prepare_cost()
        with self.org.core.db()as db:db.execute("UPDATE org_artifacts SET sha='broken' WHERE case_id=? AND kind='supply'",(self.cid,))
        self.assertEqual(self.stage('S3')['status'],'FAIL');self.assertNotEqual(self.stage('S2')['status'],'PASS')

    def test_task_completed_flag_does_not_close_gate_and_handoff_deduplicates(self):
        a=self.org.handoff(self.cid,'S3');b=self.org.handoff(self.cid,'S3');self.assertEqual(a['task']['id'],b['task']['id'])
        with self.org.core.db()as db:db.execute("UPDATE tasks SET status='completed' WHERE id=?",(a['task']['id'],))
        self.assertNotEqual(self.stage('S3')['status'],'PASS');self.assertFalse(a['gate_closed'])
        result=self.app.invoke('commerce_task_create',{'idempotency_key':'legacy','kind':'draft','input':{'agent_role':'commerce-chief'}},'test');self.assertEqual(result['status'],'queued')

    def test_actual_image_delivery_then_missing_or_changed_files_fail(self):
        self.prepare_research();p,a=self.creative()
        result=self.org.deliver(self.cid,p['id'],[a['id']],'deliver-1');self.assertEqual(result['file_count'],1);self.assertEqual(self.stage('S4')['status'],'PASS')
        again=self.org.deliver(self.cid,p['id'],[a['id']],'deliver-1');self.assertEqual(result['id'],again['id'])
        manifest=self.org.artifact(self.cid,'images')['payload'];file=self.org.state/manifest['files'][0]['relative_path'];self.assertTrue(file.is_file());self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),a['sha256'])
        file.write_bytes(b'changed');self.assertEqual(self.stage('S4')['status'],'FAIL')
        with self.assertRaisesRegex(ValueError,'delivered_file_changed'):self.org.deliver(self.cid,p['id'],[a['id']],'deliver-1')
        file.unlink();self.assertEqual(self.stage('S4')['status'],'FAIL')

    def test_source_hash_and_project_revision_are_rechecked(self):
        self.prepare_research();p,a=self.creative();self.org.deliver(self.cid,p['id'],[a['id']],'deliver')
        self.app.creative.save(p['id'],p['brief'],'1');self.assertEqual(self.stage('S4')['status'],'FAIL')
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.org.deliver(self.cid,p['id'],[a['id']],'deliver')
        path,_,_=self.app.creative.asset(p['id'],a['id']);path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source_image_hash_mismatch'):self.org.deliver(self.cid,p['id'],[a['id']],'new')

    def test_delivered_manifest_and_current_source_are_both_verified(self):
        self.prepare_research();p,a=self.creative();self.org.deliver(self.cid,p['id'],[a['id']],'deliver')
        payload=self.org.artifact(self.cid,'images')['payload'];manifest=(self.org.state/payload['files'][0]['relative_path']).parent/'manifest.json';original=manifest.read_bytes()
        manifest.write_text('{}');self.assertEqual(self.stage('S4')['status'],'FAIL');manifest.write_bytes(original)
        source,_,_=self.app.creative.asset(p['id'],a['id']);source.write_bytes(b'tampered upstream');self.assertEqual(self.stage('S4')['status'],'FAIL')

    def test_read_only_board_does_not_recreate_missing_outbox(self):
        self.prepare_research();p,a=self.creative();self.org.deliver(self.cid,p['id'],[a['id']],'deliver')
        shutil.rmtree(self.org.state);self.assertEqual(self.stage('S4')['status'],'FAIL');self.assertFalse(self.org.state.exists())

    def test_delivery_path_scope_and_unsupported_assets_are_rejected(self):
        with self.assertRaises(ValueError):self.org._path('../outside')
        (self.org.state/'outbox').parent.mkdir(parents=True,exist_ok=True);outside=Path(self.tmp.name)/'outside';outside.mkdir();(self.org.state/'outbox').symlink_to(outside,target_is_directory=True)
        p,a=self.creative()
        with self.assertRaisesRegex(ValueError,'unsafe_delivery_path'):self.org.deliver(self.cid,p['id'],[a['id']],'unsafe')
        with self.assertRaises(ValueError):self.org.deliver(self.cid,p['id'],[{}],'bad')

    def test_snapshot_retrospective_verifies_prior_hash_and_html_escaping(self):
        result=self.org.capture(self.cid);self.assertEqual(self.stage('S11')['status'],'PASS');self.assertEqual(result['files'],['board.json','board.md','board.html'])
        with self.org.core.db()as db:db.execute("UPDATE org_boards SET sha='changed' WHERE id=?",(result['id'],))
        self.assertEqual(self.stage('S11')['status'],'FAIL')
        for f in self.org.state.rglob('board.*'):self.assertEqual(f.stat().st_mode&0o777,0o600)

    def test_fulfillment_observation_requires_review_and_freshness(self):
        self.assertNotEqual(self.stage('S8')['status'],'PASS');self.app.live.configure({'orders_scope_confirmed':True,'stock_basis':'present_minus_reserved','basis_confirmed':True});self.assertEqual(self.stage('S8')['status'],'PASS')
        stock=self.app.live.snapshot(self.config['connection_id'],'stock')
        with self.org.core.db()as db:db.execute("UPDATE live_snapshots SET observed='2020-01-01T00:00:00+00:00' WHERE id=?",(stock['id'],))
        self.assertNotEqual(self.stage('S8')['status'],'PASS')

if __name__=='__main__':unittest.main()
