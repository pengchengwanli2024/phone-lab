"""Source-backed input recovery and separate route selection; synthetic data only."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from test_sealeap_drafts import synthetic_input,mock_response
from sealeap_contracts import contract_for
from sealeap_input_sources import resolve
from sealeap_library import SkillLibrary
from sealeap_drafts import validate_response
from commerce_core import Core


class InputSources(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.lib=SkillLibrary(Core(self.root/'state.sqlite'),self.root)
        self.addCleanup(self.tmp.cleanup)
        if not self.lib.source_root.is_dir():self.skipTest('optional pinned upstream source snapshots not provisioned')
    def tearDown(self):self.tmp.cleanup()
    def path(self,entry,path):return self.lib.source_root/entry['repo']/Path(entry['path']).parent/path
    def prepare(self,entry,mode=None,key='synthetic'):
        return self.lib.prepare(dict(skill_id=entry['id'],input=synthetic_input(entry),synthetic=True,idempotency_key=key,**({'mode_id':mode['name']} if mode else {})))

    def test_all_73_recovered_sources_and_227_mode_anchors(self):
        recovered=[e for e in self.lib.entries.values() if e['input_sources']['common'] or e['input_sources']['modes']]
        self.assertEqual(len(recovered),73);self.assertEqual(sum(bool(e['source_method']['inputs']) for e in recovered),35)
        self.assertEqual(sum(e['source_method']['mode_selection_required'] for e in recovered),38)
        modes=0
        for e in recovered:
            m=e['source_method'];self.assertFalse(m['extraction_gaps']);self.assertEqual(m['semantic_review'],'pending')
            units=m['inputs'][:]
            for mode in m['mode_methods'].values():units+=mode['inputs']+mode['deliverables'];modes+=1
            for row in units:
                anchor=row['source'];raw=self.path(e,anchor['path']).read_text()
                self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(),anchor['file_sha256'])
                self.assertEqual('\n'.join(raw.splitlines()[anchor['file_line_start']-1:anchor['file_line_end']]),row['text'])
        self.assertEqual(modes,227)

    def test_missing_mode_is_local_gate_without_model_request(self):
        e=self.lib.entry('sealeap-athena-amazon-keyword-traffic');case=self.prepare(e)
        with patch('sealeap_drafts.invoke_model') as model:
            item=self.lib.drafts.start(case['id'],'unselected-mode')
            self.assertEqual(item['status'],'needs_inputs');self.assertIn('mode_id',item['result']['missing_fields']);self.assertFalse(item['result']['model_requested']);model.assert_not_called()

    def test_two_modes_bind_their_own_inputs_and_current_receipts(self):
        e=self.lib.entry('sealeap-athena-amazon-keyword-traffic');seen=[]
        for i,mode in enumerate(e['subcapabilities'][:2]):
            case=self.prepare(e,mode,key='mode-'+str(i));payload,missing=self.lib.drafts.context(case);self.assertNotIn('mode_id',missing)
            c=payload['contract'];self.assertEqual(c['mode_id'],mode['name']);self.assertNotEqual(c['sha256'],e['draft_contract']['sha256'])
            fields=[r for r in c['source_requirements'] if r['id'].startswith('MI')];self.assertTrue(fields);self.assertTrue(all(r['mode_id']==mode['name'] for r in fields));seen.append(fields[0]['text'])
            self.assertIn(mode['reference'],c['required_source_paths']);self.assertIn(mode['reference'],[r['path'] for r in payload['references']]);validate_response(payload,mock_response(payload))
            # Store a completed synthetic response, then read its effective contract back.
            with patch('sealeap_drafts.invoke_model',side_effect=lambda p,cancel:validate_response(p,mock_response(p))):
                job=self.lib.drafts.start(case['id'],'selected-job-'+str(i))
                import time
                deadline=time.monotonic()+4
                while job['status'] in ['queued','running'] and time.monotonic()<deadline:time.sleep(.02);job=self.lib.drafts.get(job['id'])
            self.assertEqual(job['status'],'needs_inputs');self.assertTrue(job['source_matches_current'])
        self.assertNotEqual(seen[0],seen[1]);self.assertFalse(any(r['id'].startswith('MI') for r in e['draft_contract']['source_requirements']))

    def test_reference_input_contract_is_actually_loaded(self):
        e=self.lib.entry('sealeap-apollo-asin-research-brief');payload,_=self.lib.drafts.context(self.prepare(e))
        self.assertIn('references/report-input.md',[r['path'] for r in payload['references']])
        self.assertTrue(any('title' in r['text'] and 'marketplace' in r['text'] for r in payload['contract']['source_requirements'] if r['kind']=='inputs'))

    def test_changed_or_unregistered_reference_fails_closed(self):
        e=self.lib.entry('sealeap-apollo-asin-research-brief')
        with self.assertRaisesRegex(ValueError,'hash_changed'):resolve(e,lambda path:'changed synthetic source')
        changed=copy.deepcopy(e);changed['files']=[f for f in changed['files'] if f['path']!='references/report-input.md']
        with self.assertRaisesRegex(ValueError,'not_registered'):resolve(changed,lambda path:self.path(e,path).read_text())

    def test_required_input_reference_cannot_be_silently_omitted(self):
        e=self.lib.entry('sealeap-apollo-asin-research-brief');case=self.prepare(e);original=self.lib.source_file
        def source(entry,path):
            return Mock(read_text=lambda:'x'*48001) if path=='references/report-input.md' else original(entry,path)
        with patch.object(self.lib,'source_file',side_effect=source),self.assertRaisesRegex(ValueError,'required_source_budget_exceeded'):self.lib.drafts.context(case)


if __name__=='__main__':unittest.main()
