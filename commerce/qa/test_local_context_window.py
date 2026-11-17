import copy,json,unittest
from unittest.mock import patch
from model_providers.context_window import prepare,excerpt

class LocalContextWindow(unittest.TestCase):
    def endpoint(self,base,path,body,key):
        if path=='/props':return {'default_generation_settings':{'n_ctx':8192}}
        if path=='/apply-template':return {'prompt':json.dumps(body,ensure_ascii=False)}
        if path=='/tokenize':return {'tokens':[1]*len(body['content'])}
        raise AssertionError(path)

    def test_token_budget_preserves_original_sources_scope_and_regions(self):
        payload={'question':'查询三地区最新新闻','parameters':{'context':{'module':'intelligence'}},'tools':[],
            'observations':[{'id':'R1','sha256':'a'*64,'tool':'commerce_web_read','data':{'items':[
                {'url':'https://example.com/'+str(i),'text':'真实来源文本'*2500,'retrieved_beijing':'2026-11-16 23:00:00 +08:00'}for i in range(3)]}}]}
        original=copy.deepcopy(payload)
        with patch('model_providers.context_window.call',side_effect=self.endpoint):
            value,budget=prepare(payload,'Instructions',{'engine':'llama_cpp','base_url':'http://127.0.0.1:1/v1'},2200,lambda:False)
        self.assertEqual(payload,original);self.assertEqual(value['parameters'],payload['parameters'])
        self.assertTrue(budget['compacted']);self.assertLessEqual(budget['prompt_tokens']+2200+128,8192)
        self.assertEqual(value['observations'][0]['sha256'],'a'*64)
        self.assertEqual(len(value['observations'][0]['data']['items']),3)
        self.assertTrue(value['observations'][0]['data']['items'][0]['text_truncated'])

    def test_required_input_cannot_be_silently_truncated_to_fit(self):
        payload={'question':'Q'*9000,'parameters':{'input':{'cost':123}},'observations':[]}
        with patch('model_providers.context_window.call',side_effect=self.endpoint):
            with self.assertRaisesRegex(ValueError,'agent_model_context_limit'):
                prepare(payload,'Instructions',{'engine':'llama_cpp','base_url':'http://127.0.0.1:1/v1'},2200,lambda:False)
        self.assertEqual(len(payload['question']),9000)

    def test_remote_and_other_engines_never_receive_metadata_requests(self):
        for config in [{'engine':'vllm','base_url':'http://127.0.0.1:1/v1'},{'engine':'llama_cpp','base_url':'https://model.example.com/v1'}]:
            with patch('model_providers.context_window.call')as transport:
                value,budget=prepare({'question':'test'},'Instructions',config,2200,lambda:False)
                transport.assert_not_called();self.assertIsNone(budget)

    def test_unavailable_optional_api_and_cancellation_do_not_infer_or_retry(self):
        config={'engine':'llama_cpp','base_url':'http://127.0.0.1:1/v1'}
        with patch('model_providers.context_window.call',side_effect=OSError('private error'))as transport:
            self.assertEqual(prepare({'question':'test'},'I',config,2200,lambda:False),({'question':'test'},None))
            transport.assert_called_once()
        with patch('model_providers.context_window.call',side_effect=self.endpoint):
            with self.assertRaises(InterruptedError):prepare({'question':'test'},'I',config,2200,lambda:True)
