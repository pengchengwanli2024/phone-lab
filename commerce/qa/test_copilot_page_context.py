"""Current-page binding is separate from conversation permissions and history."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce


class PageContext(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
        self.thread=self.app.copilot.open({'module':'overview','demo':True},'page-open')

    def tearDown(self):self.app.agent_runtime.stop();self.temp.cleanup()

    def test_team_page_exposes_only_current_configuration_summary(self):
        from copilot.page_context import read_page,validate_page_context
        p=self.app.assistant_team.profile_save({'name':'本机顾问','role_id':'conductor','instructions':'仅作本机配置说明。','model_ids':[],'enabled':False})
        self.app.assistant_team.channel_save({'name':'本机频道','instructions':'不执行工作。','context':{'module':'overview','demo':True},'member_ids':[p['id']]})
        result=read_page(self.app,{'module':'connections','demo':False},{'page':'assistant-team','demo':False})
        self.assertEqual(result['label'],'智能体团队')
        self.assertEqual(result['source_status'],'read')
        self.assertEqual(result['data']['profiles'][0]['name'],'本机顾问')
        self.assertNotIn('instructions',result['data']['profiles'][0])
        self.assertNotIn('context',result['data']['channels'][0])
        self.assertFalse(result['external_execution_allowed'])
        with self.assertRaisesRegex(ValueError,'copilot_page_scope_changed'):
            validate_page_context({'page':'assistant-team','demo':False},{'module':'overview','demo':False})

    def test_current_page_is_frozen_with_question_and_reaches_the_model(self):
        page={'page':'overview','section':'sales-trend','demo':True,'filters':{'platform':'all','market':'all','store_id':'all'}}
        args=dict(thread_id=self.thread['id'],message='这个为什么下降了？',context_sha256=self.thread['context_sha256'],idempotency_key='page-send',page_context=page)
        sent=self.app.copilot.invoke('commerce_copilot_send',args)
        page['section']='inventory-statistics'
        self.assertEqual(sent['latest_run']['parameters']['page_context']['section'],'sales-trend')
        captured=[]
        def model(payload,cancelled,**kwargs):
            captured.append(payload)
            return {'decision':{'phase':'answer','answer':'根据当前运营台的销售趋势分析。','questions':[],'proposals':[],'evidence_refs':['R1']},'provider':'synthetic','model':'synthetic'}
        with patch('agent_runtime.model.invoke',side_effect=model):self.app.agent_runtime.run_once()
        self.assertEqual(captured[0]['current_page']['page'],'overview')
        self.assertEqual(captured[0]['current_page']['section'],'sales-trend')
        self.assertIn('sales',captured[0]['observations'][0]['data']['data'])
        self.assertEqual(self.app.copilot.get(self.thread['id'])['latest_run']['status'],'completed')

    def test_wrong_module_and_sensitive_fields_are_rejected_before_enqueue(self):
        from copilot.page_context import validate_page_context
        for page in ({'page':'models'},{'page':'overview','input':{'api_key':'private'}},{'page':'overview','filters':{'store_id':'another-store'}}):
            with self.subTest(page=page),self.assertRaises(ValueError):validate_page_context(page,{'module':'overview','store_id':'ozon-live'})

    def test_followup_page_intent_can_change_without_expanding_business_scope(self):
        page={'page':'overview','demo':True,'intent':'current_page'}
        first=self.app.copilot.send(self.thread['id'],'当前页显示什么？',self.thread['context_sha256'],'first-page',page_context=page)
        response={'decision':{'phase':'answer','answer':'已读取当前页。','questions':[],'proposals':[],'evidence_refs':['R1']},'provider':'synthetic','model':'synthetic'}
        with patch('agent_runtime.model.invoke',return_value=response):self.app.agent_runtime.run_once()
        follow=self.app.copilot.send(self.thread['id'],'继续说明刚才的结果',self.thread['context_sha256'],'follow-page',page_context={**page,'intent':'original_thread'})
        self.assertNotEqual(first['latest_run']['id'],follow['latest_run']['id'])
        self.assertEqual(follow['latest_run']['parameters']['page_context']['intent'],'original_thread')

    def test_original_thread_hint_cannot_expand_store_or_entity_permissions(self):
        from copilot.page_context import validate_page_context
        for page in ({'page':'overview','filters':{'store_id':'another'}},
                     {'page':'products','entity':{'kind':'product','id':'other'}},
                     {'page':'models'}, {'page':'overview','demo':True}):
            scope={'module':page['page']if page['page']!='models'else'overview','demo':False,'store_id':'ozon-live','entity':{'kind':'product','id':'selected'}}
            with self.subTest(page=page),self.assertRaises(ValueError):validate_page_context({**page,'intent':'original_thread'},scope)

    def test_chart_reads_match_display_version_and_mark_changes_without_upstream_calls(self):
        from copilot.page_context import read_page
        from fixture_page_context import seed
        seed(self.app)
        report=self.app.invoke('commerce_dashboard',{})
        scope={'module':'overview','demo':False,'platform':'ozon','store_id':'ozon-live','market':'RU'}
        page={'page':'overview','demo':False,'section':'sales-trend','filters':{**{k:scope[k]for k in ('platform','store_id','market')},**{k:report['sales_summary'][k]for k in ('date_from','date_to')}},'source_refs':{'sales':report['sales_summary']['source_sha256']}}
        with patch('ozon_reader.fetch',side_effect=AssertionError('No upstream read on navigation or send')):
            result=read_page(self.app,scope,page)
            self.assertEqual(result['data']['sales_summary']['records'][-1]['amount'],'0')
            self.assertFalse(result['display_changed'])
            page['source_refs']['sales']='b'*64
            self.assertTrue(read_page(self.app,scope,page)['display_changed'])

    def test_selected_product_is_bounded_and_excludes_other_products(self):
        from copilot.page_context import read_page
        scope={'module':'products','demo':True,'entity':{'kind':'product','id':'PET-021'}}
        result=read_page(self.app,scope,{'page':'products','demo':True,'entity':scope['entity']})
        self.assertEqual(result['data']['visible_total'],1)
        self.assertEqual(result['data']['selected'][0]['available'],3)
        self.assertNotIn('CUP-014',str(result))

    def test_invalid_numbers_and_unavailable_data_remain_explicit(self):
        from copilot.page_context import read_page,validate_page_context
        with self.assertRaises(ValueError):validate_page_context({'page':'overview','input':{'price':float('nan')}},{'module':'overview'})
        with patch.object(self.app,'invoke',side_effect=ValueError('local_snapshot_missing')):
            result=read_page(self.app,{'module':'overview'},{'page':'overview'})
        self.assertEqual(result['source_status'],'unavailable')
        self.assertIsNone(result['data'])
        self.assertEqual(result['error_code'],'local_snapshot_missing')

    def test_same_request_key_cannot_silently_change_page(self):
        args=dict(thread_id=self.thread['id'],message='这个怎么了？',context_sha256=self.thread['context_sha256'],idempotency_key='same-page-send',page_context={'page':'overview','section':'sales-trend','demo':True})
        first=self.app.copilot.invoke('commerce_copilot_send',args)
        self.assertEqual(first['id'],self.app.copilot.invoke('commerce_copilot_send',args)['id'])
        args['page_context']['section']='inventory-statistics'
        with self.assertRaises(ValueError):self.app.copilot.invoke('commerce_copilot_send',args)

    def test_selected_intelligence_includes_only_its_bound_local_article(self):
        from copilot.page_context import read_page
        from article_binding import text_hash
        item_id='a'*24;record='b'*64;text='Synthetic captured article. '*120
        article=dict(text=text,content_sha256=text_hash(text),record_sha256=record,source_url='https://example.com/synthetic',captured_at='2026-11-16T00:00:00Z',routes=['synthetic_a','synthetic_b'])
        def invoke(tool,args,client):
            self.assertEqual(args,{'item_id':item_id})
            if tool=='commerce_intel_item_get':return dict(id=item_id,title='Synthetic item',record_sha256=record)
            if tool=='commerce_intel_article_list':return {'articles':[dict(status='ready',record_sha256=record,article=article)]}
            self.fail('Unexpected tool '+tool)
        with patch.object(self.app,'invoke',side_effect=invoke):
            result=read_page(self.app,{'module':'intelligence','entity':{'kind':'intel','id':item_id}},{'page':'intelligence','source_refs':{'intel':record,'article':text_hash(text)}})
        self.assertFalse(result['display_changed'])
        self.assertTrue(result['data']['article']['text_truncated'])
        self.assertLessEqual(len(result['data']['article']['text']),2000)
