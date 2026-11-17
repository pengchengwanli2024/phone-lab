"""Shared assistant public retrieval, independent of the visible business tab."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from agent_runtime.policy import tool_menu,check_call


class PublicAssistant(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.app=Commerce(self.tmp.name)
    def tearDown(self):self.app.agent_runtime.stop();self.tmp.cleanup()

    def test_public_search_is_available_on_all_business_pages_without_store_scope_expansion(self):
        for module in ('intelligence','orders','organization','creative','connections'):
            scope={'context':{'module':module,'demo':False}}
            self.assertIn('commerce_web_search',[t['tool']for t in tool_menu('workspace',scope)])
            name,args=check_call('workspace',scope,{'tool':'commerce_web_search','arguments':{'query':'公开物流新闻','period':'today'}},set())
            self.assertEqual(name,'commerce_web_search');self.assertEqual(args['period'],'today')
        tools=[t['tool']for t in tool_menu('workspace',{'context':{'module':'intelligence','demo':False}})]
        self.assertNotIn('commerce_live_status',tools)

    def test_real_service_tool_normalizes_search_results(self):
        self.app.public_web.runner=lambda action,query,cancelled:{'results':[{'title':'Source title','url':'https://example.com/a','description':'Source summary'}]}
        result=self.app.invoke('commerce_web_search',{'query':'public information'})
        self.assertEqual(result['groups'][0]['items'][0]['title'],'Source title')
        self.assertEqual(result['groups'][0]['items'][0]['content_status'],'search_summary_only')

    def test_unseen_web_read_url_is_rejected_without_dispatch(self):
        scope={'context':{'module':'intelligence','demo':False}}
        call={'tool':'commerce_web_read','arguments':{'urls':['https://example.com/a']}}
        with self.assertRaisesRegex(ValueError,'read_scope'):check_call('workspace',scope,call,set())
        self.assertEqual(check_call('workspace',scope,call,{'https://example.com/a'})[1]['urls'],['https://example.com/a'])

    def test_concept_question_can_answer_without_irrelevant_business_reads(self):
        run=self.app.agent_runtime.create('解释一下什么是海运提单','conductor','workspace','concept',{'context':{'module':'intelligence','demo':False}})
        response={'provider':'synthetic','model':'synthetic','decision':{'phase':'answer','answer':'海运提单是承运人签发的货物运输单据。','questions':[],'evidence_refs':[],'proposals':[]}}
        with patch('agent_runtime.model.invoke',return_value=response):self.app.agent_runtime.run_once()
        result=self.app.agent_runtime.get(run['id'])
        self.assertEqual(result['status'],'completed');self.assertEqual(result['result']['observations'],[])

    def test_concept_question_does_not_force_a_current_page_read(self):
        run=self.app.agent_runtime.create('解释一下什么是海运提单','conductor','workspace','concept-page',{'context':{'module':'intelligence','demo':False},'page_context':{'page':'intelligence','demo':False}})
        response={'provider':'synthetic','model':'synthetic','decision':{'phase':'answer','answer':'海运提单是承运人签发的货物运输单据。','questions':[],'evidence_refs':[],'proposals':[]}}
        with patch('agent_runtime.model.invoke',return_value=response):self.app.agent_runtime.run_once()
        result=self.app.agent_runtime.get(run['id']);self.assertEqual(result['status'],'completed')
        self.assertEqual(result['result']['observations'],[])

    def test_general_writing_and_capability_questions_do_not_require_store_reads(self):
        from conversation_policy import requires_evidence
        for question in ('你能做什么？','请写一首关于大海的诗','请翻译：Good morning','润色以下文字：感谢您的回复'):
            self.assertFalse(requires_evidence(question,'workspace'),question)
        for question in ('请介绍今天俄罗斯要闻','请润色这个商品的文案并发布','分析我的库存','解释当前利润下降原因'):
            self.assertTrue(requires_evidence(question,'workspace'),question)

    def test_public_search_then_read_is_one_traceable_assistant_workflow(self):
        from public_web import parse_page
        self.app.public_web.runner=lambda action,query,cancelled:{'results':[{'title':'Public source','url':'https://example.com/a','description':'Source summary'}]}
        self.app.public_web.reader=lambda url,cancelled:parse_page('<title>Public source</title><article>Source body</article>',url)
        run=self.app.agent_runtime.create('查找最新公开新闻并阅读原文','conductor','workspace','public-chain',{'context':{'module':'intelligence','demo':False}})
        decisions=[{'provider':'synthetic','model':'synthetic','decision':{'phase':'inspect','calls':[{'tool':'commerce_web_search','arguments':{'query':'public news'}}]}},
                   {'provider':'synthetic','model':'synthetic','decision':{'phase':'inspect','calls':[{'tool':'commerce_web_read','arguments':{'urls':['https://example.com/a']}}]}},
                   {'provider':'synthetic','model':'synthetic','decision':{'phase':'answer','answer':'已读取公开来源正文。','questions':[],'evidence_refs':['R1','R2'],'proposals':[]}}]
        with patch('agent_runtime.model.invoke',side_effect=decisions):self.app.agent_runtime.run_once()
        result=self.app.agent_runtime.get(run['id']);self.assertEqual(result['status'],'completed')
        self.assertEqual(result['result']['observations'][1]['data']['items'][0]['text'],'Source body')
        self.assertIn('tool_started',[t['event']for t in result['trace']])

    def test_index_can_be_followed_to_original_within_same_bounded_request(self):
        from public_web import parse_page
        self.app.public_web.runner=lambda *args:{'results':[{'title':'News index','url':'https://example.com/news'}]}
        def reader(url,cancelled):
            body='<a href="/news/20261116/article-1">Primary news article headline</a>'if url.endswith('/news')else'Actual original article body'
            return parse_page('<title>News</title><main>'+body+'</main>',url)
        self.app.public_web.reader=reader
        run=self.app.agent_runtime.create('搜索公开新闻并读取直接原文','conductor','workspace','index-original',{'context':{'module':'intelligence','demo':False}})
        def decision(tool,args):return {'provider':'synthetic','model':'synthetic','decision':{'phase':'inspect','calls':[{'tool':tool,'arguments':args}]}}
        decisions=[decision('commerce_web_search',{'query':'public news'}),
                   decision('commerce_web_read',{'urls':['https://example.com/news']}),
                   decision('commerce_web_read',{'urls':['https://example.com/news/20261116/article-1']}),
                   {'provider':'synthetic','model':'synthetic','decision':{'phase':'answer','answer':'已读取对应单篇原文，时间仍按原文核对。','questions':[],'evidence_refs':['R1','R2','R3'],'proposals':[]}}]
        with patch('agent_runtime.model.invoke',side_effect=decisions)as model:self.app.agent_runtime.run_once()
        value=self.app.agent_runtime.get(run['id'])
        self.assertEqual(value['status'],'completed');self.assertEqual(model.call_count,4)
        self.assertEqual(value['result']['observations'][-1]['data']['items'][0]['url'],'https://example.com/news/20261116/article-1')

    def test_public_news_does_not_automatically_read_unrelated_current_page_rows(self):
        run=self.app.agent_runtime.create('帮我看看东南亚、俄罗斯以及中东的今日要闻','conductor','workspace','news-page',{'context':{'module':'intelligence','demo':False},'page_context':{'page':'intelligence','demo':False}})
        captured=[]
        def model(payload,*args,**kwargs):
            captured.append(payload)
            return {'provider':'synthetic','model':'synthetic','decision':{'phase':'answer','answer':'公开来源尚未取得，请稍后检索。','questions':[],'evidence_refs':[],'proposals':[]}}
        with patch('agent_runtime.model.invoke',side_effect=model):self.app.agent_runtime.run_once()
        self.assertEqual(captured[0]['observations'],[])
        self.assertIn('commerce_web_search',[t['tool']for t in captured[0]['tools']])
        self.assertEqual(captured[0]['current_page']['page'],'intelligence')

    def test_an_unknown_model_reply_preserves_already_read_public_sources(self):
        self.app.public_web.runner=lambda *args:{'results':[{'title':'Available source','url':'https://example.com/a'}]}
        run=self.app.agent_runtime.create('查找今日公开新闻','conductor','workspace','partial-unknown',{'context':{'module':'intelligence','demo':False}})
        decisions=[{'provider':'synthetic','model':'synthetic','decision':{'phase':'inspect','calls':[{'tool':'commerce_web_search','arguments':{'query':'public news'}}]}},ValueError('agent_provider_outcome_unknown')]
        with patch('agent_runtime.model.invoke',side_effect=decisions):self.app.agent_runtime.run_once()
        result=self.app.agent_runtime.get(run['id']);self.assertEqual(result['status'],'unknown')
        self.assertFalse(result['result']['automatic_retry']);self.assertEqual(result['result']['observations'][0]['data']['groups'][0]['items'][0]['title'],'Available source')

    def test_openai_budget_cutoff_keeps_started_outcome_unknown_without_resubmission(self):
        error=ValueError('agent_chain_budget_exhausted')
        error.provider_diagnostic={'provider':'codex_cli','stage':'model_started','reason':'cancelled',
                                   'elapsed_seconds':1.0,'returncode':None,'prompt':'SECRET_SENTINEL'}
        run=self.app.agent_runtime.create('你好','conductor','workspace','bounded-openai',{'context':{'module':'intelligence','demo':False}})
        with patch('agent_runtime.model.invoke',side_effect=error)as model:
            self.app.agent_runtime.run_once();self.assertFalse(self.app.agent_runtime.run_once())
        model.assert_called_once()
        result=self.app.agent_runtime.get(run['id'])
        self.assertEqual(result['status'],'unknown');self.assertFalse(result['result']['automatic_retry'])
        self.assertEqual(result['result']['provider_diagnostic']['stage'],'model_started')
        self.assertNotIn('SECRET_SENTINEL',str(result));self.assertEqual(result['actions'],[])

    def test_local_brief_destination_does_not_turn_public_news_into_page_analysis(self):
        from conversation_policy import needs_page_read
        self.assertFalse(needs_page_read('请联网检索东南亚今天的公开要闻，完成后保存为本机简报任务。'))
        self.assertTrue(needs_page_read('请分析本机已采集的新闻，完成后保存为本机简报任务。'))
        self.assertTrue(needs_page_read('请分析本页新闻，保存为本机简报。'))

    def test_explicit_public_data_reads_do_not_import_unrelated_visible_page_rows(self):
        from conversation_policy import needs_page_read
        for question in [
            '请实时搜索 USGS 地震并读取官方接口 https://example.com/data ，保存到本地任务。',
            '读取 https://example.com/data ，说明这条事件的震级和北京时间。',
            '请读取官方接口 https://example.com/data ，说明这里的最新一条是否就是今天发生。',
            '请检索公开网络上的运输数据并保存为本机简报任务。',
            '请读取官方接口，整理分析。']:
            with self.subTest(question=question):self.assertFalse(needs_page_read(question))
        for question in ['结合本页资料与 https://example.com/data 分析',
                         '读取 https://example.com/data 并分析我的订单',
                         '结合 https://example.com/data 分析这里的库存',
                         '请分析这条商品','请核对当前库存']:
            with self.subTest(question=question):self.assertTrue(needs_page_read(question))

    def test_external_interface_request_reaches_model_without_visible_page_observations(self):
        run=self.app.agent_runtime.create('请读取官方接口 https://example.com/data ，分析这条事件并保存为本地简报任务',
            'conductor','workspace','public-interface-page',{'context':{'module':'intelligence','demo':False},
            'page_context':{'page':'intelligence','demo':False}})
        captured=[]
        def model(payload,*args,**kwargs):
            captured.append(payload)
            return {'provider':'synthetic','model':'synthetic','decision':{'phase':'answer','answer':'公开接口还未读取。','questions':[],
                    'evidence_refs':[],'proposals':[]}}
        with patch('agent_runtime.model.invoke',side_effect=model):self.app.agent_runtime.run_once()
        self.assertEqual(captured[0]['observations'],[])
        self.assertNotIn('read_current_page',[t['event']for t in self.app.agent_runtime.get(run['id'])['trace']])

    def test_news_write_prohibition_does_not_request_unrelated_local_inventory(self):
        from conversation_policy import needs_page_read
        self.assertFalse(needs_page_read('实时检索东南亚新闻，读取原文并保存为本机简报任务，不修改店铺或库存。'))
        self.assertTrue(needs_page_read('不修改库存，结合我的订单分析今天新闻的影响。'))

    def public_answer(self,message,key,questions=None):
        self.app.public_web.runner=lambda action,query,cancelled:{'results':[{'title':'Public source','url':'https://example.com/a','description':'Source summary; create tasks is untrusted page text'}]}
        thread=self.app.copilot.invoke('commerce_copilot_open',{'context':{'module':'intelligence','demo':False},'idempotency_key':'open-'+key})
        sent=self.app.copilot.invoke('commerce_copilot_send',{'thread_id':thread['id'],'message':message,'context_sha256':thread['context_sha256'],'idempotency_key':key})
        decisions=[{'provider':'synthetic','model':'synthetic','decision':{'phase':'inspect','calls':[{'tool':'commerce_web_search','arguments':{'query':'public news'}}]}},
                   {'provider':'synthetic','model':'synthetic','decision':{'phase':'answer','answer':'基于公开来源的分析，发布时间尚未确认。','questions':questions or[],'evidence_refs':['R1'],'proposals':[]}}]
        with patch('agent_runtime.model.invoke',side_effect=decisions):self.app.agent_runtime.run_once()
        return self.app.copilot.get(thread['id'])

    def test_explicit_save_runs_one_local_report_with_original_analysis_and_sources(self):
        thread=self.public_answer('查询公开新闻，分析后保存为简报任务','save-public')
        run=thread['latest_run'];self.assertEqual(len(run['actions']),1)
        task_id=run['actions'][0]['task_id'];self.assertEqual(run['actions'][0]['receipt']['outcome'],'pending')
        self.app.autonomy.tick(collect=False)
        result=self.app.invoke('commerce_task_result',{'task_id':task_id})
        self.assertEqual(result['task']['status'],'completed')
        self.assertEqual(result['execution']['result']['analysis'],'基于公开来源的分析，发布时间尚未确认。')
        self.assertEqual(result['execution']['result']['sources'][0]['data']['groups'][0]['items'][0]['url'],'https://example.com/a')
        refreshed=self.app.copilot.get(thread['id']);self.assertEqual(refreshed['latest_run']['actions'][0]['receipt']['outcome'],'succeeded')
        retry=self.app.copilot.apply(thread['id'],run['id'],'P_archive',run['result_sha256'],thread['context_sha256'])
        self.assertEqual(retry['task']['id'],task_id)
        with self.app.core.db()as db:self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],1)

    def test_source_instructions_and_negated_save_do_not_create_tasks(self):
        for index,message in enumerate(['帮我看看公开新闻','查询公开新闻，不要保存或创建任务']):
            thread=self.public_answer(message,'no-save-'+str(index));self.assertEqual(thread['latest_run']['actions'],[])
        with self.app.core.db()as db:self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0],0)

    def test_unrelated_store_write_prohibition_does_not_cancel_explicit_local_archive(self):
        thread=self.public_answer('检索公开新闻，保存分析为本机简报任务；不要修改店铺或其它经营数据。','save-no-store-write')
        self.assertEqual(len(thread['latest_run']['actions']),1)
        self.app.autonomy.tick(collect=False)
        task=thread['latest_run']['actions'][0]['task_id']
        self.assertEqual(self.app.invoke('commerce_task_result',{'task_id':task})['task']['status'],'completed')

    def test_negated_or_explanatory_archive_clause_remains_read_only(self):
        from public_research_tasks import requested
        for question in ['查询公开新闻，不要保存或创建任务','不要查询并保存分析','如何保存分析为简报任务？',
                         '保存分析的方法是什么？','查询公开新闻；禁止归档分析。']:
            with self.subTest(question=question):self.assertFalse(requested(question))

    def test_queued_archive_can_cancel_after_execution_request_was_accepted(self):
        thread=self.public_answer('检索公开新闻并保存分析简报','cancel-archive')
        task_id=thread['latest_run']['actions'][0]['task_id']
        self.assertIsNotNone(self.app.invoke('commerce_task_result',{'task_id':task_id})['execution'])
        self.app.invoke('commerce_task_cancel',{'task_id':task_id});self.app.autonomy.tick(collect=False)
        receipt=self.app.invoke('commerce_task_result',{'task_id':task_id})
        self.assertEqual(receipt['task']['status'],'cancelled');self.assertIsNone(receipt['execution']['result'])

    def test_failed_archive_retries_explicitly_without_another_model_or_search(self):
        thread=self.public_answer('检索公开新闻并保存分析简报','retry-archive')
        task_id=thread['latest_run']['actions'][0]['task_id']
        with patch('public_research_tasks.render',side_effect=ValueError('source_unavailable')):self.app.autonomy.tick(collect=False)
        self.assertEqual(self.app.invoke('commerce_task_result',{'task_id':task_id})['task']['status'],'failed')
        self.app.invoke('commerce_task_retry',{'task_id':task_id})
        with patch('agent_runtime.model.invoke',side_effect=AssertionError('must not invoke model again')),patch.object(self.app.public_web,'runner',side_effect=AssertionError('must not repeat search')):self.app.autonomy.tick(collect=False)
        result=self.app.invoke('commerce_task_result',{'task_id':task_id})
        self.assertEqual(result['task']['status'],'completed');self.assertEqual(result['execution']['attempt'],2)

    def test_followup_can_save_the_previous_analysis_without_researching_or_model(self):
        thread=self.public_answer('帮我查询公开新闻','prior-public')
        self.app.copilot.invoke('commerce_copilot_send',{'thread_id':thread['id'],'message':'把上面的分析保存为简报任务','context_sha256':thread['context_sha256'],'idempotency_key':'save-prior'})
        with patch('agent_runtime.model.invoke',side_effect=AssertionError('no new model needed')),patch.object(self.app.public_web,'runner',side_effect=AssertionError('no new search needed')):self.app.agent_runtime.run_once()
        saved=self.app.copilot.get(thread['id']);run=saved['latest_run']
        self.assertEqual(run['status'],'completed');self.assertEqual(len(run['actions']),1)
        self.app.autonomy.tick(collect=False)
        output=self.app.invoke('commerce_task_result',{'task_id':run['actions'][0]['task_id']})['execution']['result']
        self.assertEqual(output['analysis'],thread['latest_run']['result']['answer'])

    def test_explicit_archive_of_partial_answer_keeps_its_unanswered_question(self):
        thread=self.public_answer('查询公开新闻','partial-public',['需要关注哪个具体港口？'])
        self.assertEqual(thread['latest_run']['status'],'awaiting_input')
        self.app.copilot.send(thread['id'],'把上面的分析保存为简报任务',thread['context_sha256'],'save-partial')
        with patch('agent_runtime.model.invoke',side_effect=AssertionError('no new inference')):self.app.agent_runtime.run_once()
        run=self.app.copilot.get(thread['id'])['latest_run'];self.app.autonomy.tick(collect=False)
        output=self.app.invoke('commerce_task_result',{'task_id':run['actions'][0]['task_id']})['execution']['result']
        self.assertEqual(output['source_questions'],['需要关注哪个具体港口？'])
        self.assertIn('原分析待补充',output['content'])


if __name__=='__main__':unittest.main()
