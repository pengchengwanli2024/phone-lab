"""Text-generation domains reuse explicit private routing, never media credentials."""
import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import creative_model,sealeap_drafts

class Routes(unittest.TestCase):
    def test_creative_codex_projects_only_claim_text_and_preserves_review(self):
        brief={'product':{'name':'合成盒','verified_facts':[{'id':'F1','text':'蓝色','evidence_ref':'PRIVATE_SOURCE_SENTINEL'}]},'target':{'language':'zh'},'reference':{'transcript':'合成参考'}}
        raw={'scripts':[{'angle':angle,'hook':'蓝色盒子','body':'查看细节','cta':'核对规格','fact_ids':['F1']}for angle in ['detail','selection','demonstration']],'notes':[]}
        with patch('agent_runtime.codex_provider.invoke_json',return_value=raw)as model,patch('creative_model.model_command',side_effect=AssertionError('Hermes must not run')):
            result=creative_model.refine(brief,route={'provider':'codex','model':'gpt-6.1-sol'})
        self.assertNotIn('PRIVATE_SOURCE_SENTINEL',str(model.call_args.args[0]));self.assertEqual(result['provider'],'codex_cli');self.assertEqual(result['review_status'],'pending_review')
    def test_skill_route_redacts_fact_locations_and_validates_output(self):
        payload={'task':{'facts':[{'id':'F1','text':'合成事实','source_ref':'PRIVATE_SOURCE_SENTINEL'}]}}
        with patch('sealeap_drafts.require_current_protocol'),patch('sealeap_drafts.validate_response',return_value={'status':'needs_inputs'})as validate,patch('agent_runtime.codex_provider.invoke_json',return_value={'status':'needs_inputs'})as model,patch('sealeap_drafts.model_command',side_effect=AssertionError('Hermes must not run')):
            result=sealeap_drafts.invoke_model(payload,lambda:False,route={'provider':'codex','model':'gpt-6.1-sol'})
        self.assertEqual(result['status'],'needs_inputs');validate.assert_called_once();self.assertNotIn('PRIVATE_SOURCE_SENTINEL',str(model.call_args.args[0]))

if __name__=='__main__':unittest.main()
