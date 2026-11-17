"""Product-bound evidence and local selection decisions; no marketplace writes."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import base64, copy, hashlib, sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from service import TOOLS

def stamp(days=0):
    return (datetime.now(timezone.utc)+timedelta(days=days)).isoformat()

class ProductEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OrganizationTests();self.fixture.setUp()
        self.app,self.cid=self.fixture.app,self.fixture.cid
        self.observed=stamp()
    def tearDown(self):self.fixture.tearDown()
    def call(self,op,**args):
        return self.app.invoke('commerce_product_evidence_'+op,{'case_id':self.cid,**args},'test')
    def get(self):return self.call('get')
    def source(self,**extra):
        return {'kind':'supplier','platform':'1688','label':'合成供货源','url':'https://detail.1688.com/offer/123456.html','model':'A1','variant':'银色单篮','observed_at':self.observed,'valid_until':'','review_state':'unreviewed','verification_note':'待样品核对','rights_status':'reference_only','rights_evidence':'','notes':'仅合成测试来源','quote_ids':[],'images':[],'metrics':{},'archived':False,**extra}
    def save(self,payload=None,entry_id='',revision=0,key=None,snapshot=None):
        return self.call('source_save',entry_id=entry_id,payload=payload or self.source(),expected_revision=revision,expected_dossier_sha256=snapshot or self.get()['dossier_sha256'],idempotency_key=key or 'save-'+str(revision)+'-'+entry_id,actor='合成操作者')
    def proposal(self):
        return {'customer_need':'水槽收纳','selection_reason':'合成评估，尚未验证','differentiation':'待比较','risks':'待样品与实价','currency':'RUB','trial_quantity':None,'trial_budget':None,'max_loss':None,'min_contribution_rate':None,'conditions':'先补证'}
    def test_execution_projection_includes_exact_nested_case_and_preserves_original_status(self):
        own=self.app.core.invoke('commerce_task_create',{'idempotency_key':'nested-own','kind':'analysis','input':{'scope':{'case_id':self.cid},'title':'原扩展执行'}})
        self.app.core.invoke('commerce_task_create',{'idempotency_key':'nested-other','kind':'analysis','input':{'scope':{'case_id':'other-case'},'title':'别的商品'}})
        rows=self.get()['executions']
        self.assertTrue(any(r['id']==own['id'] and r['status']=='queued'for r in rows))
        self.assertFalse(any(r['title']=='别的商品'for r in rows))
    def test_origin_open_uses_only_saved_version_bound_public_url(self):
        from unittest.mock import patch
        entry=self.save(key='origin')['entry']
        with patch('webbrowser.open',return_value=True)as opened:
            result=self.call('origin_open',entry_id=entry['id'],expected_entry_sha256=entry['sha256'],index=-1)
            opened.assert_called_once_with(entry['url'],new=2)
            self.assertEqual(result['status'],'requested')
        with patch('webbrowser.open')as opened:
            with self.assertRaises(ValueError):self.call('origin_open',entry_id=entry['id'],expected_entry_sha256='0'*64,index=-1)
            with self.assertRaises(ValueError):self.call('origin_open',entry_id=entry['id'],expected_entry_sha256=entry['sha256'],index=0)
            opened.assert_not_called()
    def test_registry_and_empty_dossier_preserve_unknowns(self):
        d=self.get()
        self.assertEqual(d['case_id'],self.cid)
        self.assertIn('1688',[p['id']for p in d['platforms']])
        self.assertIn('yiwugo',[p['id']for p in d['platforms']])
        self.assertEqual(d['sources'],[])
        self.assertEqual(d['economics']['status'],'HOLD')
        self.assertFalse(d['external_execution_allowed'])
        self.assertIn('commerce_product_evidence_review_save',[t[0]for t in TOOLS])
    def test_supplier_save_history_idempotency_and_conflict(self):
        first=self.save(key='first');self.assertEqual(first['entry']['revision'],1)
        retry=self.save(key='first',snapshot=first['previous_dossier_sha256'])
        self.assertEqual(retry['entry']['id'],first['entry']['id'])
        self.assertEqual(len(self.get()['sources']),1)
        data=self.source(notes='已补充')
        second=self.save(data,first['entry']['id'],1,'second')
        self.assertEqual([x['revision']for x in second['entry']['history']],[2,1])
        with self.assertRaisesRegex(ValueError,'conflict|changed'):
            self.save(data,first['entry']['id'],1,'stale')
    def test_changed_external_input_invalidates_write_guard(self):
        old=self.get()['dossier_sha256'];self.app.organization.set_currency(self.cid,'RUB')
        with self.assertRaisesRegex(ValueError,'changed'):
            self.save(snapshot=old)
    def test_platform_identity_and_credential_or_private_urls_rejected(self):
        for url in ['https://yiwugo.com/product/1.html','https://user:pass@detail.1688.com/offer/1.html','https://127.0.0.1/x','https://detail.1688.com/offer/1.html?access_token=secret']:
            with self.subTest(url=url),self.assertRaises(ValueError):self.save(self.source(url=url))
        self.save(self.source(platform='yiwugo',url='https://www.yiwugo.com/product/detail/123456.html'),key='yiwu')
    def test_cross_case_or_unknown_quote_reference_rejected(self):
        with self.assertRaisesRegex(ValueError,'reference'):
            self.save(self.source(quote_ids=['not-this-case']))
    def test_quote_and_cost_are_original_domain_values(self):
        self.app.organization.set_currency(self.cid,'RUB')
        w=self.app.product_workspace.get(self.cid)
        self.app.product_workspace.supply.save(self.cid,'testq',{'supplier':'原报价','currency':'CNY','purchase_cost':8},0,w['source_sha256'],'quote')
        self.save(self.source(quote_ids=['testq']))
        d=self.get()
        self.assertEqual(d['quotes'][0]['fields']['purchase_cost'],8)
        self.assertEqual(d['sources'][0]['quote_ids'],['testq'])
        self.assertEqual(d['economics']['status'],'HOLD')
        self.assertNotIn('purchase_cost',d['sources'][0])
    def test_proposal_versions_and_review_expiry_on_change(self):
        d=self.get();p=self.call('proposal_save',payload=self.proposal(),expected_revision=0,expected_dossier_sha256=d['dossier_sha256'],idempotency_key='proposal',actor='操作者')
        self.assertEqual(p['proposal']['revision'],1)
        review=self.hold_review()
        self.assertTrue(review['review']['current'])
        self.save(key='changed-source')
        self.assertFalse(self.get()['reviews'][0]['current'])
    def hold_review(self):
        d=self.get()
        checks={k:{'status':'pending','note':'资料尚缺','evidence_refs':[]}for k in d['criteria']}
        return self.call('review_save',payload={'decision':'hold','reason':'等待需求、正式报价、样品和完整费用','checks':checks},expected_dossier_sha256=d['dossier_sha256'],idempotency_key='review-hold',actor='合成评审')
    def test_hold_is_immutable_local_review_not_permission(self):
        r=self.hold_review()['review'];self.assertEqual(r['decision'],'hold')
        self.assertFalse(r['external_execution_allowed'])
        self.assertEqual(len(self.get()['reviews']),1)
    def test_trial_cannot_be_granted_from_self_declared_checks(self):
        source=self.save()['entry'];d=self.get()
        ref='source:'+source['id']+'@1'
        checks={k:{'status':'pass','note':'宣称通过','evidence_refs':[ref]}for k in d['criteria']}
        with self.assertRaisesRegex(ValueError,'trial_not_ready'):
            self.call('review_save',payload={'decision':'trial','reason':'不能靠勾选放行','checks':checks},expected_dossier_sha256=d['dossier_sha256'],idempotency_key='fake-trial',actor='合成评审')
    def test_evidence_refs_cannot_cross_scope_or_be_fabricated(self):
        d=self.get()
        checks={k:{'status':'pending','note':'待核','evidence_refs':[]}for k in d['criteria']}
        checks['demand']={'status':'pass','note':'无效引用','evidence_refs':['source:foreign@1']}
        with self.assertRaisesRegex(ValueError,'reference'):
            self.call('review_save',payload={'decision':'hold','reason':'无效','checks':checks},expected_dossier_sha256=d['dossier_sha256'],idempotency_key='badref',actor='操作者')
    def test_commercial_rights_cannot_be_checked_without_proof(self):
        with self.assertRaisesRegex(ValueError,'rights'):
            self.save(self.source(rights_status='authorized'))
    def test_archive_keeps_old_original_source(self):
        row=self.save()['entry']
        changed=self.source(archived=True)
        result=self.save(changed,row['id'],1,'archive')['entry']
        self.assertTrue(result['archived'])
        self.assertEqual(len(result['history']),2)
        self.assertEqual(result['history'][1]['payload']['url'],self.source()['url'])
    def test_unrelated_task_does_not_expire_review(self):
        r=self.hold_review()['review']
        self.app.core.invoke('commerce_task_create',{'kind':'report','input':{'title':'unrelated'},'idempotency_key':'unrelated'})
        self.assertEqual(self.get()['reviews'][0]['current'],True)
        self.assertEqual(self.get()['reviews'][0]['id'],r['id'])
    def test_original_executions_stay_case_bound(self):
        for label,case in [('ours',self.cid),('other','unrelated-case')]:
            self.app.core.invoke('commerce_task_create',{'kind':'report','input':{'title':label,'organization_case':case},'idempotency_key':label})
        d=self.get();titles=[t['title']for t in d['executions']]
        self.assertIn('ours',titles);self.assertNotIn('other',titles)
    def test_unknown_save_can_be_reconciled_without_a_second_mutation(self):
        first=self.save(key='receipt-key')['entry']
        r=self.call('operation_get',idempotency_key='receipt-key')
        self.assertEqual(r['status'],'saved');self.assertEqual(r['id'],first['id'])
        self.assertEqual(self.call('operation_get',idempotency_key='missing')['status'],'not_found')
        self.assertEqual(len(self.get()['sources']),1)

    def test_new_record_cannot_adopt_a_foreign_or_unknown_identity(self):
        with self.assertRaisesRegex(ValueError,'not_found'):
            self.save(entry_id='ev_'+'e'*32,key='foreign-entry')

    def test_nullable_market_metrics_stay_unknown_instead_of_crashing(self):
        self.save(self.source(kind='competitor',platform='other',url='https://example.com/product',metrics={'price':None,'sales_units':None,'searches':None,'window_days':None},review_state='checked',verification_note='无数据，保留未知'))
        self.assertFalse(self.get()['readiness']['trial_prerequisites_met'])

    def test_private_ipv6_source_url_is_rejected(self):
        with self.assertRaises(ValueError):
            self.save(self.source(platform='other',url='https://[fe80::1]/product'))

    def test_complete_local_evidence_can_record_trial_without_granting_execution(self):
        self.fixture.prepare_cost()
        quote={'supplier':'合成正式供应商','currency':'CNY','purchase_cost':30,'lead_time_days':14,'moq':1,'source_ref':'synthetic:formal-quote','valid_until':stamp(7),'packaging':{'length_cm':10,'width_cm':8,'height_cm':5,'weight_kg':0.2,'units_per_pack':1}}
        w=self.app.product_workspace.get(self.cid)
        q=self.app.product_workspace.supply.save(self.cid,'ready-quote',quote,0,w['source_sha256'],'ready-quote')
        self.app.product_workspace.supply.select(self.cid,'ready-quote',q['sha256'],self.app.product_workspace.get(self.cid)['source_sha256'],'select-ready')
        supplier=self.save(self.source(quote_ids=['ready-quote'],review_state='checked',verification_note='合成样品核对'),key='supplier')['entry']
        for n in range(2):
            self.save(self.source(kind='competitor',platform='other',url='https://example.com/competitor/'+str(n),label='合成竞品'+str(n),review_state='checked',verification_note='合成可比资料',images=[{'url':'https://example.com/image/'+str(n)+'.png','media_id':'','label':'合成原图链接','role':'original'}],metrics={'price':100,'currency':'CNY','sales_units':10,'window_days':28}),key='competitor-'+str(n))
        p=self.proposal();p.update(currency='CNY',trial_quantity=10,trial_budget=2000,max_loss=200,min_contribution_rate=.1)
        self.call('proposal_save',payload=p,expected_revision=0,expected_dossier_sha256=self.get()['dossier_sha256'],idempotency_key='trial-plan',actor='合成操作者')
        d=self.get();self.assertTrue(d['readiness']['trial_prerequisites_met'],d['readiness'])
        ref='source:'+supplier['id']+'@1'
        checks={k:{'status':'pass','note':'合成环境本地核对','evidence_refs':[ref]}for k in d['criteria']}
        r=self.call('review_save',payload={'decision':'trial','reason':'限合成数据的本地评审，不发起采购','checks':checks},expected_dossier_sha256=d['dossier_sha256'],idempotency_key='trial-review',actor='合成评审')
        self.assertEqual(r['review']['decision'],'trial')
        self.assertFalse(r['review']['external_execution_allowed'])
    def test_trial_rejects_cost_that_disagrees_with_selected_quote(self):
        self.test_complete_local_evidence_can_record_trial_without_granting_execution()
        data=copy.deepcopy(self.app.organization.artifact(self.cid,'economics')['payload']);data['purchase_cost']=1
        self.app.organization.record(self.cid,'economics',data,'mismatched-after-review')
        self.assertFalse(self.get()['readiness']['trial_prerequisites_met'])

    def test_trial_rejects_damaged_original_supply_artifact(self):
        self.test_complete_local_evidence_can_record_trial_without_granting_execution()
        artifact=self.app.organization.artifact(self.cid,'supply')
        with self.app.core.db()as db:db.execute("UPDATE org_artifacts SET sha='changed' WHERE id=?",(artifact['id'],))
        self.assertFalse(self.get()['readiness']['trial_prerequisites_met'])

    def test_connection_switch_rejects_prior_product(self):
        self.app.live.configure({'ozon_client_id':'654321'})
        with self.assertRaisesRegex(ValueError,'case_not_found'):self.get()

    def test_trial_budget_must_cover_full_planned_cost_not_only_goods(self):
        self.test_complete_local_evidence_can_record_trial_without_granting_execution()
        d=self.get();p={k:d['proposal'][k]for k in self.proposal()};p['trial_budget']=500
        self.call('proposal_save',payload=p,expected_revision=d['proposal']['revision'],expected_dossier_sha256=d['dossier_sha256'],idempotency_key='low-full-budget',actor='合成评审')
        self.assertFalse(self.get()['readiness']['trial_prerequisites_met'])

class ProductEvidenceMediaTests(ProductEvidenceTests):
    def test_original_image_upload_keeps_bytes_and_is_idempotent(self):
        from unittest.mock import patch
        raw=b'RIFF'+(100).to_bytes(4,'little')+b'WEBP'+b'VP8 '+b'synthetic-image-bytes'
        source=self.save()['entry'];sha=hashlib.sha256(raw).hexdigest()
        begin=self.call('upload_begin',entry_id=source['id'],expected_entry_sha256=source['sha256'],filename='original.webp',size=len(raw),sha256=sha,source_url='https://example.com/original.webp',role='original',actor='合成上传')
        self.call('upload_chunk',upload_id=begin['upload_id'],index=0,content_base64=base64.b64encode(raw).decode())
        with patch.object(self.app.creative,'probe',return_value={'width':100,'height':100,'duration_seconds':0,'has_audio':False}):
            result=self.call('upload_finish',upload_id=begin['upload_id'])
            again=self.call('upload_finish',upload_id=begin['upload_id'])
        self.assertEqual(result['media_id'],again['media_id'])
        source=next(s for s in self.get()['sources']if s['id']==source['id'])
        self.assertEqual(source['revision'],2)
        read=self.call('image',entry_id=source['id'],expected_entry_sha256=source['sha256'],index=0)
        self.assertEqual(base64.b64decode(read['content_base64']),raw)
        self.assertEqual(read['mime'],'image/webp')
        self.assertEqual(read['role'],'original')
        self.assertFalse(read['independently_verified'])
    def test_uploaded_generated_image_cannot_be_relabelled_original(self):
        from unittest.mock import patch
        raw=b'RIFF'+(100).to_bytes(4,'little')+b'WEBP'+b'VP8 '+b'synthetic-image-bytes'
        source=self.save()['entry']
        begin=self.call('upload_begin',entry_id=source['id'],expected_entry_sha256=source['sha256'],filename='ai.webp',size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),source_url='',role='generated',actor='合成上传')
        self.call('upload_chunk',upload_id=begin['upload_id'],index=0,content_base64=base64.b64encode(raw).decode())
        with patch.object(self.app.creative,'probe',return_value={'width':100,'height':100,'duration_seconds':0,'has_audio':False}):self.call('upload_finish',upload_id=begin['upload_id'])
        row=self.get()['sources'][0]
        payload=self.source(images=copy.deepcopy(row['images']));payload['images'][0]['role']='original'
        with self.assertRaisesRegex(ValueError,'image_role'):
            self.save(payload,row['id'],row['revision'],'rename-generated')
    def test_upload_is_rejected_for_unknown_source(self):
        with self.assertRaisesRegex(ValueError,'not_found'):
            self.call('upload_begin',entry_id='ev_'+'a'*32,expected_entry_sha256='a'*64,filename='x.png',size=10,sha256='a'*64,source_url='',role='original',actor='操作者')
    def test_image_from_other_source_cannot_be_attached(self):
        first=self.save(key='a')['entry'];second=self.save(self.source(label='other'),key='b')['entry']
        data=self.source(images=[{'url':'','media_id':'peimg_'+'f'*32,'label':'x','role':'original'}])
        with self.assertRaisesRegex(ValueError,'image'):
            self.save(data,second['id'],1,'attach-foreign')

if __name__=='__main__':unittest.main()
