"""Use the configured inference route without altering original text or review status."""
from pathlib import Path
import sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from translation import run_model

class TranslationRoute(unittest.TestCase):
    def test_codex_uses_same_boundary_and_marks_pending_review(self):
        data={'language':'en','items':[{'id':'title','text':'Not waterproof. 2 kg, 12 USD.'}]}
        with patch('agent_runtime.codex_provider.invoke_json',return_value={'translations':[{'id':'title','zh':'不防水。2 kg，12 USD。'}]}) as invoke:
            result=run_model(data,route={'provider':'codex','model':'gpt-6.1-sol'})
        self.assertEqual(result['provider'],'codex_cli');self.assertEqual(result['translations'][0]['status'],'pending_review')
        self.assertEqual(data['items'][0]['text'],'Not waterproof. 2 kg, 12 USD.');self.assertFalse(result['tools_enabled']);invoke.assert_called_once()
    def test_bad_binding_or_partial_output_cannot_complete(self):
        with patch('agent_runtime.codex_provider.invoke_json',return_value={'translations':[]}):
            with self.assertRaisesRegex(ValueError,'translation_incomplete_response'):
                run_model({'language':'en','items':[{'id':'a','text':'12 USD'}]},route={'provider':'codex','model':'gpt-6.1-sol'})

if __name__=='__main__':unittest.main()
