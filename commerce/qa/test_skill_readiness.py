"""Read-only skill conditions use the same source and draft gates as execution."""
from pathlib import Path
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_sealeap_library as fixtures
from test_sealeap_drafts import synthetic_input


class Readiness(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.Skills();self.fixture.setUp();self.lib=self.fixture.lib
        self.fixture.require_sources()

    def tearDown(self):self.fixture.tearDown()

    def read(self,skill,data=None,mode=None):
        return self.lib.invoke('commerce_skills_readiness',{'skill_id':skill,'input':data or {},**({'mode_id':mode} if mode else {})})

    def test_offline_calculator_requires_input_and_never_claims_account_execution(self):
        self.assertTrue(hasattr(self.lib,'readiness'),'skill execution conditions must be connected')
        skill='sealeap-tiktokshop-unit-economics'
        empty=self.read(skill)
        self.assertFalse(empty['offline_check']['can_request'])
        supplied=self.read(skill,self.lib.get(skill)['example_input'])
        self.assertTrue(supplied['offline_check']['can_request'])
        self.assertFalse(supplied['external_execution']['available'])
        self.assertEqual(supplied['account_entitlement'],'not_verified')
        with self.lib.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sealeap_cases').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM sealeap_drafts').fetchone()[0],0)

    def test_draft_conditions_show_exact_missing_scope_and_fact_requirements(self):
        skill='sealeap-ebay-category-keywords'
        empty=self.read(skill)
        self.assertIn('facts_with_source',empty['missing_fields'])
        self.assertIn('scope.marketplace',empty['missing_fields'])
        ready=self.read(skill,synthetic_input(self.lib.entry(skill)))
        self.assertTrue(ready['model_draft']['inputs_ready'])
        self.assertEqual(ready['model_draft']['runtime_status'],'not_checked')
        self.assertFalse(ready['external_execution']['available'])

    def test_missing_source_snapshot_blocks_previously_prepared_script(self):
        skill='sealeap-tiktokshop-unit-economics';data=self.lib.get(skill)['example_input']
        case=self.lib.prepare(dict(skill_id=skill,input=data,synthetic=True,idempotency_key='prepared'))
        with tempfile.TemporaryDirectory() as empty:
            self.lib.source_root=Path(empty)
            result=self.lib.case(case['id'])
            self.assertFalse(result['readiness']['offline_check']['can_request'])
            self.assertEqual(result['readiness']['state'],'source_unavailable')


if __name__=='__main__':unittest.main()
