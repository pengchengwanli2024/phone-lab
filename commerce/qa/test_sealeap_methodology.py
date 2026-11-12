"""Literal provenance and original-requirement enforcement, with synthetic outputs."""
import copy
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sealeap_methodology import method_for,validate_checks
from test_sealeap_drafts import mock_response
from sealeap_drafts import validate_response
from commerce_core import Core
from sealeap_library import SkillLibrary


class Methodology(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries=json.loads((Path(__file__).resolve().parents[1]/'sealeap/catalogue.json').read_text())['skills']
    def entry(self,ident='sealeap-baihu-amazon-keyword-to-video-storyboard'):
        return next(e for e in self.entries if e['id']==ident)
    def payload(self):
        e=self.entry();return dict(contract=e['draft_contract'],references=[dict(id='K1')],task=dict(facts=[dict(id='F1',text='合成收纳盒')]))

    def test_all_797_literal_units_have_exact_source_locators(self):
        source_root=Path(os.environ.get('SEALEAP_SOURCE_ROOT',str(Path(__file__).resolve().parents[2]/'.local/sealeap-sources')))
        if not source_root.is_dir():self.skipTest('optional pinned upstream source snapshots not provisioned')
        totals={k:0 for k in ['inputs','deliverables','procedures','boundaries']};gaps=0
        for entry in self.entries:
            with self.subTest(skill=entry['id']):
                method=method_for(entry);self.assertEqual(method,entry['source_method']);self.assertEqual(method['semantic_review'],'pending')
                self.assertFalse(method['reference_requirements_exhaustive']);gaps+=not bool(method['inputs'])
                source_file=next(f for f in entry['files'] if f['path']=='SKILL.md')
                for kind in totals:
                    totals[kind]+=len(method[kind])
                    for item in method[kind]:
                        anchor=item['source']
                        if 'section_index' in anchor:
                            section=entry['sections'][anchor['section_index']];start=anchor['section_relative_line']-1;length=len(item['text'].splitlines());self.assertEqual('\n'.join(section['text'].splitlines()[start:start+length]),item['text']);self.assertEqual(anchor['file_sha256'],source_file['sha256'])
                        else:
                            path=source_root/entry['repo']/Path(entry['path']).parent/anchor['path'];lines=path.read_text().splitlines();self.assertEqual('\n'.join(lines[anchor['file_line_start']-1:anchor['file_line_end']]),item['text'])
                if entry.get('draft_contract'):
                    self.assertEqual(entry['draft_contract']['method_sha256'],method['sha256'])
                    self.assertEqual(entry['draft_contract']['source_requirements'],method['inputs']+method['deliverables'])
        self.assertEqual(gaps,38);self.assertTrue(all(not e['source_method']['extraction_gaps'] for e in self.entries));self.assertGreater(totals['inputs'],2000);self.assertGreater(totals['deliverables'],3000)

    def test_all_451_begin_before_sections_are_exposed(self):
        entries=[e for e in self.entries if any(s['heading']=='开始前要拿到' for s in e['sections'])]
        self.assertEqual(len(entries),451)
        for e in entries:
            self.assertTrue(any(r['source']['heading']=='开始前要拿到' for r in e['source_method']['inputs']),e['id'])
            if e.get('draft_contract'):self.assertNotEqual(e['draft_contract']['source_input_excerpt'],e['description'])

    def test_nested_fact_pack_and_original_video_deliverables(self):
        e=self.entry('sealeap-amazon-creative-ai');m=e['source_method'];self.assertTrue(any('建立事实包' in r['source']['heading'] for r in m['inputs']))
        e=self.entry();requirements=e['draft_contract']['source_requirements'];self.assertTrue(any('关键词证据与买家任务卡' in r['text'] for r in requirements));self.assertTrue(any('镜头—信息—证据分镜表' in r['text'] for r in requirements))
        self.assertTrue(e['source_method']['procedures']);self.assertTrue(e['source_method']['boundaries'])

    def test_exported_coverage_contains_real_input_instead_of_description(self):
        with tempfile.TemporaryDirectory() as folder:
            lib=SkillLibrary(Core(Path(folder)/'state.sqlite'),folder);rows=list(csv.DictReader(io.StringIO(lib.export('csv')['content'])))
        row=next(r for r in rows if r['skill_id']==self.entry()['id'])
        self.assertIn('高意图搜索词',row['input_contract_preview']);self.assertTrue(row['method_sha256'])
        router=next(r for r in rows if r['skill_id']=='sealeap-athena-1688-procurement');self.assertEqual(router['method_extraction_gaps'],'');self.assertIn('请选择',router['input_contract_preview'])

    def test_no_invented_input_fields_for_mode_router(self):
        m=self.entry('sealeap-athena-1688-procurement')['source_method'];self.assertFalse(m['inputs']);self.assertFalse(m['extraction_gaps']);self.assertTrue(m['mode_selection_required']);self.assertIn('offer/SKU',next(iter(m['mode_methods'].values()))['inputs'][0]['text'])
        self.assertTrue(m['deliverables']);self.assertTrue(all(r.get('classification')=='combined_workflow_and_delivery_requires_review' for r in m['deliverables']))

    def test_omitted_and_duplicate_original_requirements_fail(self):
        payload=self.payload();valid=mock_response(payload)
        self.assertTrue(validate_response(payload,valid)['source_requirement_gaps'])
        for mutation in ['omit','duplicate','unknown','bad_section','no_input_fact','no_delivery_section','unknown_fact']:
            response=copy.deepcopy(valid);rows=response['draft']['requirement_checks'];first=rows[0]
            if mutation=='omit':rows.pop()
            elif mutation=='duplicate':rows[-1]=copy.deepcopy(first)
            elif mutation=='unknown':first['requirement_id']='I999'
            elif mutation=='bad_section':first['section_ids']=['invented_section']
            elif mutation=='no_input_fact':first.update(status='covered_in_draft',basis_refs=[])
            elif mutation=='unknown_fact':first['basis_refs']=['F99']
            elif mutation=='no_delivery_section':next(r for r in rows if r['requirement_id'].startswith('D')).update(status='covered_in_draft',section_ids=[])
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_response(payload,response)

    def test_missing_requirements_cannot_claim_ready(self):
        payload=self.payload();response=mock_response(payload);response['draft']['status']='draft'
        with self.assertRaisesRegex(ValueError,'contradict'):validate_response(payload,response)

    def test_even_covered_items_remain_model_self_assessment(self):
        payload=self.payload();response=mock_response(payload)
        for row in response['draft']['requirement_checks']:
            row.update(status='covered_in_draft',basis_refs=['F1'] if row['requirement_id'].startswith('I') else [],section_ids=[payload['contract']['sections'][0]],note='合成自评，不证明资料确实充分。')
        value=validate_response(payload,response)
        self.assertEqual(value['source_requirement_review'],'model_assessment_requires_business_review');self.assertFalse(value['independently_verified']);self.assertFalse(value['platform_operations_executed'])

    def test_method_reference_explains_requirements_but_cannot_supply_inputs(self):
        payload=self.payload();response=mock_response(payload)
        for check in response['draft']['requirement_checks']:check['basis_refs']=['K1']
        validate_response(payload,response)
        first=response['draft']['requirement_checks'][0];first['status']='partial'
        with self.assertRaisesRegex(ValueError,'evidence_required'):validate_response(payload,response)
        first['basis_refs'].append('F1');validate_response(payload,response)


if __name__=='__main__':unittest.main()
