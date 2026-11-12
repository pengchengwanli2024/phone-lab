from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from translation_evaluation import evaluate,screen,sha

CASES=[{'id':'a','language':'en','text':'Not waterproof. 12 USD.','tokens':['12','USD'],'negative_zh':'不防水'},{'id':'b','language':'ru','text':'2 kg','tokens':['2','kg'],'negative_zh':''}]
class FidelityScreenTests(unittest.TestCase):
    def test_flags_are_screening_not_approval(self):
        self.assertEqual(screen(CASES[0],'不防水。12 USD。'),[])
        self.assertIn('negative_meaning_needs_review',screen(CASES[0],'防水。12 USD。'))
        self.assertIn('literal_token_changed:USD',screen(CASES[0],'不防水。12 CNY。'))
    def test_private_bilingual_result_preserves_source_and_review_state(self):
        def runner(data):return {'model':'synthetic','provider':'synthetic','translations':[{'id':v['id'],'zh':'不防水。12 USD。'if v['id']=='a'else'2 kg','original_sha256':sha(v['text']),'zh_sha256':sha('不防水。12 USD。'if v['id']=='a'else'2 kg')}for v in data['items']]}
        with tempfile.TemporaryDirectory()as state:
            result=evaluate(state,runner=runner,corpus=CASES);self.assertEqual(result['details']['completed_items'],2);self.assertFalse(result['details']['human_semantic_acceptance'])
            self.assertEqual(result['report'].stat().st_mode&0o777,0o600);self.assertIn('中文译文',(result['report'].parent/'bilingual.csv').read_text(encoding='utf-8-sig'))
    def test_provider_failure_is_not_retried(self):
        calls=[]
        def runner(data):calls.append(data);raise ValueError('translation_provider_failed')
        with tempfile.TemporaryDirectory()as state:
            result=evaluate(state,runner=runner,corpus=CASES);self.assertEqual(len(calls),1);self.assertEqual(result['details']['status'],'partial');self.assertEqual(result['details']['batches'][-1]['status'],'not_run_after_provider_failure')
if __name__=='__main__':unittest.main()
