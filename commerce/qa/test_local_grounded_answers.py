import copy,unittest
from unittest.mock import patch
from model_providers.grounded_answers import answer_text

class GroundedAnswers(unittest.TestCase):
    def test_unsent_supplier_draft_does_not_invent_demand_or_an_overdue_order(self):
        text=answer_text({'question':'给供应商写一封礼貌的催交期邮件草稿，只写草稿，不要发送。','observations':[]})
        self.assertIn('[订单编号/产品名称]',text)
        for unsupported in('需求有所增加','已逾期','已经付款','未收到货'):self.assertNotIn(unsupported,text)

    def test_provider_cannot_ignore_source_bound_answer_grammar(self):
        from model_providers.inference import invoke
        payload={'observations':[{'id':'R1','tool':'commerce_unit_economics','data':{
            'status':'CALCULATED','total_cost':62,'contribution':38,'contribution_rate':.38,'currency':'CNY'}}]}
        fake={'decision':{'decision':{'phase':'answer','answer':'利润100，任务已创建',
              'questions':[],'proposals':[],'evidence_refs':['R1']}}}
        with patch('model_providers.inference.invoke_json',return_value=fake):
            with self.assertRaisesRegex(ValueError,'agent_model_invalid_response'):
                invoke(payload,lambda:False,{'engine':'llama_cpp','json_mode':True})

    def test_index_headlines_and_old_articles_are_not_current_news(self):
        payload={'question':'检索过去24小时公开新闻并读取原文','observations':[
            {'id':'R1','tool':'commerce_web_search','data':{'groups':[{'region':'russia','items':[{'url':'https://example.com/news'}]}]}},
            {'id':'R2','tool':'commerce_web_read','data':{'items':[
                {'url':'https://example.com/news','status':'ready','page_kind':'index_or_page','text':'不应作为今日报道的栏目旧标题',
                 'article_candidates':[{'url':'https://example.com/old','title':'旧文'}]},
                {'url':'https://example.com/old','title':'旧报道','status':'ready','page_kind':'article','text':'old body',
                 'publication_status':'outside_window','published_beijing':'2026-11-01 08:00:00 +08:00'}]}}]}
        original=copy.deepcopy(payload);text=answer_text(payload)
        self.assertIn('窗口外',text);self.assertNotIn('不应作为今日报道的栏目旧标题',text)
        self.assertIn('本轮覆盖不足',text);self.assertIn('未独立核实',text);self.assertEqual(payload,original)

    def test_workspace_uses_real_gap_owner_and_recheck_not_invented_job(self):
        payload={'question':'核对工作项缺项、责任岗位和复验方法','observations':[
            {'id':'R1','tool':'commerce_workspace_get','data':{'name':'合成工作项','calculation':{'missing':['currency']},
                'stages':[{'id':'S3','name':'成本与交期资料','status':'HOLD','missing':1,'gaps':[
                    {'owner':'sourcer','reason':'缺少供应资料','verify':'核对供应报价版本'}]}]}}]}
        text=answer_text(payload)
        self.assertIn('供应链',text);self.assertIn('核对供应报价版本',text);self.assertNotIn('价格岗',text)

    def test_direct_in_window_article_keeps_title_time_and_source_excerpt(self):
        payload={'question':'读取公开新闻原文','observations':[{'id':'R2','tool':'commerce_web_read','data':{'items':[
            {'url':'https://example.com/a','title':'真实标题','text':'来源正文','status':'ready','page_kind':'article',
             'publication_status':'within_window','published_beijing':'2026-11-16 23:00:00 +08:00'}]}}]}
        text=answer_text(payload);self.assertIn('来源正文',text);self.assertIn('真实标题',text)
        self.assertNotIn('本轮覆盖不足',text)

    def test_calculation_states_unknown_zero_and_proposal_are_distinct(self):
        payload={'observations':[{'id':'R1','tool':'commerce_unit_economics','data':{
            'status':'HOLD','missing':['purchase_cost'],'contribution':None,'contribution_rate':None}}]}
        text=answer_text(payload);self.assertIn('采购成本',text);self.assertIn('不能',text);self.assertNotIn('0.00',text)
        payload['observations'][0]={'id':'R2','tool':'commerce_restock_plan','data':{
            'status':'CALCULATED','velocity':0,'days_of_cover':None,'target_units':0,'suggested_qty':0}}
        text=answer_text(payload);self.assertIn('0',text);self.assertIn('未知',text);self.assertNotIn('已创建',text)
