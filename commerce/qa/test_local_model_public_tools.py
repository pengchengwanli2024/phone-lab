import json
import unittest
from unittest.mock import patch

import jsonschema
from model_providers import inference
from public_web import tool_menu, check_call


class LocalModelPublicTools(unittest.TestCase):
    def schema_for(self, question, observations=None, evidence_required=True):
        # Transport output is irrelevant here; validate the actual offered choices.
        result = {'decision': {'decision': {'phase': 'answer', 'answer': '测试',
                  'questions': [], 'evidence_refs': [], 'proposals': []}}}
        from model_providers.grounded_answers import answer_text
        result['decision']['decision']['answer']=answer_text({'question':question,'observations':observations or[]})or'测试'
        with patch.object(inference, 'invoke_json', return_value=result) as invoke:
            inference.invoke({'question': question, 'tools': tool_menu(),
                              'observations': observations or [],
                              'evidence_required': evidence_required}, lambda: False,
                             {'engine': 'llama_cpp', 'json_mode': True})
        return invoke.call_args.kwargs['output_schema']

    def test_explicit_current_public_read_starts_with_a_read_not_a_permission_question(self):
        schema = self.schema_for('按最近24小时实时检索 USGS 地震信息，读取官方来源。')
        answer = {'decision': {'phase': 'answer', 'answer': '我将查询',
                              'questions': ['你希望查询哪一天？'],
                              'evidence_refs': [], 'proposals': []}}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(answer, schema)
        call = {'decision': {'phase': 'inspect', 'calls': [{
            'tool': 'commerce_web_search', 'arguments':
                {'query': 'USGS earthquake', 'period': '24h'}}]}}
        jsonschema.validate(call, schema)

    def test_explanations_negation_and_missing_subject_still_allow_a_question(self):
        for question in ['如何搜索今天的新闻？', '不要搜索今天新闻，只解释步骤。',
                         '请搜索', '你好']:
            with self.subTest(question=question):
                schema = self.schema_for(question)
                answer = {'decision': {'phase': 'answer', 'answer': '请补充查询范围',
                                      'questions': ['你希望了解什么？'],
                                      'evidence_refs': [], 'proposals': []}}
                jsonschema.validate(answer, schema)

    def test_unrelated_write_prohibition_does_not_disable_required_public_read(self):
        schema=self.schema_for('请读取 USGS 官方接口并分析；不要修改店铺或其它经营数据。')
        answer={'decision':{'phase':'answer','answer':'我将读取','questions':['提供数据好吗？'],
                            'evidence_refs':[],'proposals':[]}}
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(answer,schema)

    def test_explicit_url_is_read_directly_before_search_or_unrelated_tools(self):
        url='https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&limit=1'
        schema=self.schema_for('请读取官方接口 '+url+' ，说明震级和北京时间。')
        good={'decision':{'phase':'inspect','calls':[{'tool':'commerce_web_read',
                  'arguments':{'urls':[url],'period':'any'}}]}}
        jsonschema.validate(good,schema)
        good['decision']['calls'][0]['tool']='commerce_web_search'
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(good,schema)

    def test_public_analysis_does_not_offer_unrelated_business_actions_or_layout_generation(self):
        observation={'id':'R1','tool':'commerce_web_read','data':{'items':[{'status':'ready'}]}}
        schema=self.schema_for('读取 USGS 官方接口，分析并保存本机简报',[observation])
        answer=next(item for item in schema['properties']['decision']['anyOf']if item['properties']['phase']['enum']==['answer'])
        self.assertEqual(answer['properties']['proposals']['maxItems'],0)
        self.assertNotIn('ui',answer['properties'])

    def test_explicit_body_read_uses_returned_urls_before_final_analysis(self):
        observation={'id':'R1','tool':'commerce_web_search','data':{'groups':[{'items':[
            {'url':'https://earthquake.usgs.gov/earthquakes/eventpage/test'}]}]}}
        schema=self.schema_for('搜索 USGS 地震信息并读取官方正文。',[observation])
        answer={'decision':{'phase':'answer','answer':'仅有搜索摘要','questions':[],
                            'evidence_refs':['R1'],'proposals':[]}}
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(answer,schema)
        read={'decision':{'phase':'inspect','calls':[{'tool':'commerce_web_read',
            'arguments':{'urls':['https://earthquake.usgs.gov/earthquakes/eventpage/test'],'period':'24h'}}]}}
        jsonschema.validate(read,schema)
        read['decision']['calls'][0]['tool']='commerce_web_search'
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(read,schema)

    def test_body_read_failure_or_empty_search_can_return_an_honest_limitation(self):
        observations=[{'id':'R1','tool':'commerce_web_search','data':{'groups':[]}}]
        for rows in [observations,observations+[{'id':'R2','tool':'commerce_web_read',
                                               'data':{'items':[{'status':'failed'}]}}]]:
            schema=self.schema_for('搜索 USGS 信息并读取官方正文。',rows)
            answer={'decision':{'phase':'answer','answer':'来源正文暂不可用','questions':[],
                                'evidence_refs':['R1'],'proposals':[]}}
            jsonschema.validate(answer,schema)

    def test_news_index_followup_reads_an_unread_article_not_the_index_again(self):
        index='https://example.com/news';article=index+'/20261116/story-1'
        observations=[{'id':'R1','tool':'commerce_web_read','data':{'items':[
            {'url':index,'status':'ready','page_kind':'index_or_page','article_candidates':[
                {'url':article,'title':'Original news article','content_status':'link_not_read'}]}]}}]
        schema=self.schema_for('请读取公开新闻 '+index+' 并至少读取一篇直接原文。',observations)
        read={'decision':{'phase':'inspect','calls':[{'tool':'commerce_web_read',
            'arguments':{'urls':[article],'period':'24h'}}]}}
        jsonschema.validate(read,schema)
        read['decision']['calls'][0]['arguments']['urls']=[index]
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(read,schema)
        observations.append({'id':'R2','tool':'commerce_web_read','data':{'items':[
            {'url':article,'status':'ready','page_kind':'article','text':'Original body'}]}})
        schema=self.schema_for('请读取公开新闻 '+index+' 并至少读取一篇直接原文。',observations)
        answer={'decision':{'phase':'answer','answer':'已读原文，尚未独立核实。','questions':[],
                            'evidence_refs':['R2'],'proposals':[]}}
        from model_providers.grounded_answers import answer_text
        answer['decision']['answer']=answer_text({'question':'请读取公开新闻原文','observations':observations})
        jsonschema.validate(answer,schema)

    def test_structured_public_reader_accepts_real_urls_and_time_window(self):
        url = 'https://earthquake.usgs.gov/earthquakes/eventpage/test'
        arguments = {'urls': [url], 'period': '24h'}
        check_call('commerce_web_read', arguments, {url})
        answer = {'decision': {'phase': 'inspect', 'calls': [
            {'tool': 'commerce_web_read', 'arguments': arguments}]}}
        with patch.object(inference, 'invoke_json', return_value={'decision': answer}) as invoke:
            inference.invoke({'tools': tool_menu(), 'question':'搜索 USGS 信息并读取正文','observations': [
                {'id':'R1','tool':'commerce_web_search','data':{'groups':[{'items':[{'url':url}]}]}}]}, lambda: False,
                             {'engine': 'llama_cpp', 'json_mode': True})
        schema = invoke.call_args.kwargs['output_schema']
        jsonschema.validate(answer, schema)

    def test_fixed_empty_arguments_stay_fixed_and_tool_scope_stays_exact(self):
        answer = {'decision': {'phase': 'inspect', 'calls': [
            {'tool': 'commerce_runtime_status', 'arguments': {}}]}}
        with patch.object(inference, 'invoke_json', return_value={'decision': answer}) as invoke:
            inference.invoke({'tools': [{'tool': 'commerce_runtime_status', 'arguments': {}}],
                              'observations': []}, lambda: False,
                             {'engine': 'llama_cpp', 'json_mode': True})
        schema = invoke.call_args.kwargs['output_schema']
        jsonschema.validate(answer, schema)
        for call in [{'tool': 'commerce_runtime_status', 'arguments': {'other':1}},
                     {'tool': 'commerce_web_read', 'arguments': {}}]:
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate({'decision': {'phase': 'inspect', 'calls': [call]}}, schema)


if __name__ == '__main__':
    unittest.main()
