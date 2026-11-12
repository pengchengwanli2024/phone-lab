"""All contracts/source contexts and synthetic lifecycle tests; no paid model calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from sealeap_library import SkillLibrary
from sealeap_contracts import contract_for,input_template,validate_input,digest
from sealeap_drafts import SkillDrafts,validate_response,DraftValidationError


def synthetic_input(entry):
    value=input_template(entry)
    value['goal']='仅使用合成依据完成本技能可确定部分；真实缺项请提问，不执行平台操作。'
    value['scope'].update(marketplace='synthetic-US',currency='USD',period='synthetic-2026-10')
    value['facts']=[dict(id='F1',text='合成测试对象是一款无品牌的蓝色收纳盒，材质为PP；没有提供销量、权利文件或当期平台规则。',source_ref='synthetic_fixture',label='synthetic')]
    return value


def mock_response(payload):
    return dict(provider='synthetic_mock',model='no-network',tools_enabled=False,draft=dict(status='needs_inputs',
        sections=[dict(id=key,items=[dict(text='合成对象为蓝色收纳盒。',kind='fact',basis_refs=['F1']),dict(text='补齐技能原文要求的证据后再执行本节。',kind='proposal',basis_refs=['K1'])]) for key in payload['contract']['sections']],
        questions=['缺少当前规则与任务明细，请提供。'],limitations=['仅合成夹具，未调用模型或平台。'],
        requirement_checks=[dict(requirement_id=r['id'],status='missing',basis_refs=[],section_ids=[],note='合成门槛检查，原始要求缺少资料。') for r in payload['contract']['source_requirements']]))


class Drafts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.lib=SkillLibrary(Core(self.root/'state.sqlite'),self.root)
        self.entry=self.lib.entry('sealeap-ebay-category-keywords')
        if not self.lib.verify(self.entry):self.skipTest('pinned source snapshots not provisioned')
    def tearDown(self):self.tmp.cleanup()
    def case(self,value=None,key='case',skill=None,mode=None):
        return self.lib.prepare(dict(skill_id=skill or self.entry['id'],input=synthetic_input(self.entry) if value is None else value,synthetic=True,idempotency_key=key,**({'mode_id':mode} if mode else {})))
    def wait(self,ident):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            item=self.lib.drafts.get(ident)
            if item['status'] not in ['running','queued']:return item
            time.sleep(.02)
        self.fail('synthetic job did not terminate')
    def complete(self,key='job'):
        case=self.case()
        def model(payload,cancel):return validate_response(payload,mock_response(payload))
        with patch('sealeap_drafts.invoke_model',side_effect=model) as call:
            item=self.lib.drafts.start(case['id'],key);item=self.wait(item['id']);self.assertEqual(call.call_count,1)
        return case,item

    def test_all_778_contracts_and_source_contexts(self):
        contracts=[];families=set();counts={'omitted_files':0,'mode_contexts':0}
        for e in self.lib.entries.values():
            if e['adapter']:
                self.assertIsNone(e.get('draft_contract'));continue
            with self.subTest(skill=e['id']):
                c=e['draft_contract'];contracts.append(c['sha256']);families.add(c['family'])
                self.assertEqual(c,contract_for(e));self.assertEqual(c['source_sha256'],e['source_sha256'])
                self.assertTrue(c['source_input_excerpt']);self.assertTrue(c['source_delivery_excerpt'])
                self.assertFalse(c['platform_operations_enabled'])
                template=input_template(e);_,missing=validate_input(template,c);self.assertIn('facts_with_source',missing)
                case=dict(skill_id=e['id'],source_sha256=e['source_sha256'],input=synthetic_input(e),synthetic=True)
                payload,missing=self.lib.drafts.context(case);self.assertEqual(missing,['mode_id'] if c['mode_selection_required'] else [])
                self.assertEqual(payload['references'][0]['path'],'SKILL.md')
                self.assertLessEqual(sum(len(r['content']) for r in payload['references']),48000)
                counts['omitted_files']+=len(payload['omitted_references'])
                validate_response(payload,mock_response(payload))
                for mode in e.get('subcapabilities',[]):
                    mp,_=self.lib.drafts.context(dict(case,mode_id=mode['name'],mode_sha256=digest(mode)))
                    self.assertIn(mode['reference'],[r['path'] for r in mp['references']]);counts['mode_contexts']+=1
        self.assertEqual(len(contracts),778);self.assertEqual(len(set(contracts)),778);self.assertEqual(len(families),8)
        self.assertEqual(counts['mode_contexts'],227)

    def test_empty_inputs_stop_before_model_for_every_contract(self):
        with patch('sealeap_drafts.invoke_model') as model:
            for e in self.lib.entries.values():
                if not e.get('draft_contract'):continue
                case=self.case(input_template(e),e['id'],e['id']);item=self.lib.drafts.start(case['id'],e['id'])
                self.assertEqual(item['status'],'needs_inputs');self.assertFalse(item['result']['model_requested'])
            model.assert_not_called()

    def test_input_types_credential_keys_and_unknown_facts(self):
        value=synthetic_input(self.entry);value['facts'][0]['label']='unknown'
        normalized,missing=validate_input(value,self.entry['draft_contract']);self.assertFalse(normalized['facts']);self.assertIn('facts_with_source',missing)
        for change in [{'parameters':{'nested':[{'api_key':'synthetic'}]}},{'facts':[{}]},{'scope':{'unexpected':'x'}},{'unknown':True},{'parameters':[]}]:
            with self.assertRaises(ValueError):validate_input(dict(synthetic_input(self.entry),**change),self.entry['draft_contract'])

    def test_citation_and_schema_rejections(self):
        payload,_=self.lib.drafts.context(self.case());valid=mock_response(payload)
        for change in ['unknown_ref','method_fact','no_ref','missing_section','duplicate_section','extra_key','missing_question']:
            data=copy.deepcopy(valid);raw=data['draft'];item=raw['sections'][0]['items'][0]
            if change=='unknown_ref':item['basis_refs']=['F99']
            elif change=='method_fact':item['basis_refs']=['K1']
            elif change=='no_ref':item['basis_refs']=[]
            elif change=='missing_section':raw['sections'].pop()
            elif change=='duplicate_section':raw['sections'][1]['id']=raw['sections'][0]['id']
            elif change=='extra_key':raw['platform_verified']=True
            else:raw['questions']=[]
            with self.subTest(change=change),self.assertRaises(ValueError):validate_response(payload,data)

    def test_idempotency_review_and_private_exports(self):
        case,item=self.complete();self.assertEqual(item['status'],'needs_inputs');self.assertTrue(item['source_matches_current'])
        with patch('sealeap_drafts.invoke_model') as model:
            self.assertEqual(self.lib.drafts.start(case['id'],'job')['id'],item['id']);model.assert_not_called()
        other=self.case(key='other')
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.lib.drafts.start(other['id'],'job')
        with self.assertRaises(ValueError):self.lib.drafts.review(item['id'],'wrong','accept')
        review=self.lib.drafts.review(item['id'],item['result_sha256'],'reject','synthetic reviewer')
        self.assertEqual(review['review']['decision'],'reject')
        with self.assertRaisesRegex(ValueError,'already_recorded'):self.lib.drafts.review(item['id'],item['result_sha256'],'accept')
        export=self.lib.drafts.export(item['id'],'markdown');self.assertIn('合成输入：True',export['content']);self.assertIn('F1',export['content'])
        self.assertEqual(self.lib.drafts.export(item['id'])['export_kind'],'private_skill_draft')
        with self.assertRaises(ValueError):self.lib.drafts.export(item['id'],'html')
        self.assertEqual(self.lib.summary()['execution'].get('live_verified',0),0)

    def test_unknown_never_automatically_replayed(self):
        case=self.case()
        with patch('sealeap_drafts.invoke_model',side_effect=ValueError('sealeap_draft_outcome_unknown_timeout')) as model:
            item=self.lib.drafts.start(case['id'],'unknown');item=self.wait(item['id'])
            self.assertEqual(item['status'],'unknown');self.lib.drafts.start(case['id'],'unknown');self.assertEqual(model.call_count,1)
        with self.assertRaises(ValueError):self.lib.drafts.review(item['id'],item['result_sha256'],'accept')

    def test_invalid_model_response_is_retained_without_becoming_reviewable(self):
        case=self.case();raw=dict(draft=dict(untrusted_claim='synthetic_invalid_output'))
        with patch('sealeap_drafts.invoke_model',side_effect=DraftValidationError('sealeap_draft_invalid_response',raw)):
            item=self.lib.drafts.start(case['id'],'invalid-output');item=self.wait(item['id'])
        self.assertEqual(item['status'],'failed');self.assertEqual(item['result']['unvalidated_response'],raw)
        self.assertFalse(item['result']['automatic_retry'])
        with self.assertRaises(ValueError):self.lib.drafts.review(item['id'],item['result_sha256'],'accept')

    def test_cancellation_and_restart_recovery(self):
        case=self.case();entered=threading.Event()
        def slow(payload,cancel):
            entered.set();deadline=time.monotonic()+5
            while not cancel() and time.monotonic()<deadline:time.sleep(.01)
            raise ValueError('sealeap_draft_outcome_unknown_cancel_requested')
        with patch('sealeap_drafts.invoke_model',side_effect=slow):
            item=self.lib.drafts.start(case['id'],'cancel');self.assertTrue(entered.wait(2));self.lib.drafts.cancel(item['id']);self.assertEqual(self.wait(item['id'])['status'],'unknown')
        with self.lib.core.db() as db:
            db.execute("UPDATE sealeap_drafts SET status='running' WHERE id=?",(item['id'],))
        restarted=SkillDrafts(self.lib);self.assertEqual(restarted.get(item['id'])['status'],'unknown')
        self.assertIn('restart_no_resubmit',restarted.get(item['id'])['result']['error'])

    def test_source_contract_and_selected_mode_version_changes(self):
        case,item=self.complete();entry=self.lib.entries[self.entry['id']]
        entry['draft_contract']['sha256']='changed';self.assertFalse(self.lib.drafts.get(item['id'])['source_matches_current'])
        with self.assertRaises(ValueError):self.lib.drafts.review(item['id'],item['result_sha256'],'accept')
        with patch.object(self.lib,'verify',return_value=False),self.assertRaisesRegex(ValueError,'source_integrity'):self.lib.drafts.context(case)
        e=next(e for e in self.lib.entries.values() if e.get('subcapabilities'));mode=e['subcapabilities'][0]
        c=self.case(synthetic_input(e),'mode',e['id'],mode['name']);c['mode_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'mode_changed'):self.lib.drafts.context(c)

    def test_legacy_draft_is_readable_but_not_accepted_as_current_contract(self):
        case,item=self.complete()
        with self.lib.core.db() as db:
            raw=db.execute('SELECT payload,result FROM sealeap_drafts WHERE id=?',(item['id'],)).fetchone();payload,result=map(json.loads,raw)
            payload['contract'].update(version='source-bound-draft-v1',sha256='synthetic-old-contract');payload['contract'].pop('source_requirements');result.pop('requirement_checks')
            db.execute('UPDATE sealeap_drafts SET payload=?,result=? WHERE id=?',(json.dumps(payload),json.dumps(result),item['id']))
        legacy=self.lib.drafts.get(item['id']);self.assertFalse(legacy['source_matches_current']);self.assertTrue(legacy['result']['sections'])
        self.assertIn('当前来源仍匹配：False',self.lib.drafts.export(item['id'],'markdown')['content'])
        with self.assertRaises(ValueError):self.lib.drafts.review(item['id'],legacy['result_sha256'],'accept')


if __name__=='__main__':unittest.main()
