"""Selected store views preserve original authority and never read global data."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from service import Commerce
from live_connections import DEFAULTS
from store_scopes import source_id
from copilot.context import validate_context
from copilot.page_context import validate_page_context, read_page
from copilot.store_scope import arguments, workbench, projection
from agent_runtime.policy import tool_menu, check_call, project
from test_ops_alerts import observation, NOW
from test_agent_runtime import answer,inspect


class StoreScopedCopilot(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name)
        self.app.live._save({**DEFAULTS,'connection_id':'fixture-live','store_label':'Synthetic live label'})
        self.app.operations.record(observation(event_id='event-a',store_id='store-a'),current=NOW)
        self.app.operations.record(observation(event_id='event-b',store_id='store-b'),current=NOW)
        self.a=source_id('manual','ozon','RU','store-a');self.b=source_id('manual','ozon','RU','store-b')
        self.live=source_id('live','ozon','RU','fixture-live')

    def tearDown(self):
        self.app.agent_runtime.stop();self.app.autonomy.stop();self.app.extensions.stop();self.temp.cleanup()

    def context(self,scope=None):return {'module':'orders','demo':False,'store_scope':scope or self.a}
    def page(self,scope=None):
        return {'page':'store-ops','demo':False,'filters':{'scope':scope or self.a},'source_refs':{'store_scope':self.app.store_scopes.catalog()['sha256']}}
    def snapshot(self):
        with self.app.core.db() as db:
            return {name:db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='clients'")}
    def guarded(self):
        stack=ExitStack()
        for owner,name in ((self.app.operations,'list'),(self.app.product_workspace,'listing'),(self.app.business,'listing'),(self.app.platforms,'listing'),(self.app.platforms,'recover'),(self.app.live,'status'),(self.app.attention,'listing'),(self.app.channels,'status')):
            stack.enter_context(patch.object(owner,name,side_effect=AssertionError('global read '+name)))
        return stack
    def case(self,ident,connection='',target=None,**fields):
        scope={'synthetic':False,'platform':'ozon','market':'RU','label':'Synthetic '+ident,'origin':'research_candidate_not_inventory','research_task_id':'fixture-research',**fields}
        with self.app.core.db() as db:
            db.execute('INSERT INTO org_cases VALUES(?,?,?,?,?,?)',(ident,connection,ident,json.dumps(scope),'CNY','2026-11-17T00:00:00Z'))
        if target:
            self.app.form_drafts.save({'module':'product_workspace','form':'listing','case_id':ident},{'target':target},0)

    def test_context_schema_is_optional_and_selected_context_cannot_replace_prior_authority(self):
        self.assertEqual(validate_context({'module':'orders','demo':False}),{'module':'orders','demo':False})
        self.assertEqual(validate_context(self.context()),self.context())
        self.assertEqual(validate_context(self.context('unassigned'))['store_scope'],'unassigned')
        for changes in ({'store_scope':'all'},{'store_scope':'named store'},{'module':'overview'},{'store_id':'other-store'}, {'entity':{'kind':'order','id':'some-order'}},{'demo':None}):
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'invalid_context'):
                validate_context({**self.context(),**changes})

    def test_page_scope_and_catalog_hash_are_required_and_mismatch_never_resets_all(self):
        self.assertEqual(validate_page_context(self.page(),self.context())['filters']['scope'],self.a)
        for change in ({'page':'orders'},{'filters':{'scope':self.b}},{'filters':{}},{'source_refs':{}},{'source_refs':{'store_scope':'invalid'}}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_page_context({**self.page(),**change},self.context())
        with self.assertRaisesRegex(ValueError,'page_scope_changed'):
            validate_page_context(self.page(),{'module':'orders','demo':False})

    def test_model_menu_and_check_only_offer_exact_version_bound_selected_read(self):
        parameters={'context':self.context(),'page_context':self.page()}
        menu=tool_menu('workspace',parameters);names={row['tool'] for row in menu}
        self.assertIn('commerce_store_workbench',names)
        self.assertTrue(names.isdisjoint({'commerce_orders_list','commerce_products_list','commerce_live_status','commerce_channel_status'}))
        expected=arguments(self.context(),self.page())
        self.assertEqual(next(row['arguments'] for row in menu if row['tool']=='commerce_store_workbench'),expected)
        self.assertEqual(check_call('workspace',parameters,{'tool':'commerce_store_workbench','arguments':expected},set()),('commerce_store_workbench',expected))
        for name,args in [('commerce_orders_list',{'demo':False,'platform':'all','market':'all','store_id':'all'}),('commerce_live_status',{}),('commerce_store_workbench',{**expected,'store_scope':'all'}),('commerce_store_workbench',{**expected,'store_scope':self.b}),('commerce_store_workbench',{k:v for k,v in expected.items() if k!='expected_catalog_sha256'})]:
            with self.subTest(name=name,args=args),self.assertRaises(ValueError):check_call('workspace',parameters,{'tool':name,'arguments':args},set())
        old=tool_menu('workspace',{'context':{'module':'orders','demo':False}})
        self.assertIn('commerce_orders_list',{row['tool'] for row in old})

    def test_selected_alert_read_never_runs_global_getters_recovery_or_database_writes(self):
        before=self.snapshot()
        with self.guarded():view=workbench(self.app,**arguments(self.context(),self.page()))
        self.assertEqual(before,self.snapshot())
        self.assertTrue(view['read_only']);self.assertEqual(view['store_scope'],self.a)
        self.assertTrue(view['imported_alerts']['alerts'])
        self.assertEqual({row['store_id'] for row in view['imported_alerts']['alerts']},{'store-a'})
        self.assertIsNone(view['live']);self.assertIsNone(view['attention']);self.assertIsNone(view['channels'])
        self.assertNotIn('store-b',json.dumps(view['imported_alerts']))
        self.assertEqual(view['imported_alerts']['read_mode'],'saved_alerts_no_evaluation')

    def test_selected_cases_use_explicit_live_or_listing_targets_and_keep_original_visibility(self):
        self.case('live-case','fixture-live')
        self.case('first-listing',target={'platform':'ozon','market':'RU','store_ref':'listing-a'})
        self.case('second-listing',target={'platform':'ozon','market':'RU','store_ref':'listing-b'})
        self.case('unassigned-case')
        self.case('forbidden-old-account','old-foreign-account',target={'platform':'ozon','market':'RU','store_ref':'listing-a'})
        scope=source_id('listing','ozon','RU','listing-a')
        with self.guarded():
            selected=workbench(self.app,store_scope=scope)
            live=workbench(self.app,store_scope=self.live)
            unassigned=workbench(self.app,store_scope='unassigned')
        self.assertEqual([row['id'] for row in selected['products']],['first-listing'])
        self.assertEqual([row['id'] for row in live['products']],['live-case'])
        self.assertEqual([row['id'] for row in unassigned['products']],['unassigned-case'])

    def test_projection_excludes_global_catalog_labels_references_customer_ids_and_secrets(self):
        with self.guarded():view=workbench(self.app,store_scope=self.a)
        view['channels']={'secret':'private-channel'};view['attention']={'secret':'private-attention'}
        value=project('commerce_store_workbench',view)
        raw=json.dumps(value)
        for token in ('store-b','store-a','synthetic-order','synthetic-wh','store_scopes','mapping','reference','private-channel','private-attention','Synthetic live label'):
            self.assertNotIn(token,raw)
        self.assertEqual(value['read_scope'],'selected_store_view_only')
        self.assertEqual(value['selected_scope']['source_ids'],[self.a])
        self.assertFalse(value['external_execution_allowed'])

    def test_large_selected_views_remain_bounded_without_hiding_original_totals(self):
        value=workbench(self.app,store_scope=self.a)
        value['products']=[dict(id='case-'+str(i)+'x'*120,platform='ozon',market='RU',candidate=False,synthetic=False) for i in range(100)]
        value['selected_scope']['source_ids']=['store_source_'+str(i).zfill(32) for i in range(1000)]
        projected=projection(value)
        self.assertLess(len(json.dumps(projected,ensure_ascii=False).encode()),16000)
        self.assertEqual(projected['product_total'],100)
        self.assertEqual(projected['selected_scope']['source_total'],1000)
        self.assertTrue(projected['products_truncated']);self.assertTrue(projected['selected_scope']['sources_truncated'])

    def test_automatic_page_read_calls_only_selected_workbench_and_version_change_is_unavailable(self):
        with patch.object(self.app,'invoke',wraps=self.app.invoke) as invoke,self.guarded():
            value=read_page(self.app,self.context(),self.page())
        self.assertEqual(value['source_status'],'read');self.assertEqual(invoke.call_count,1)
        self.assertEqual(invoke.call_args.args,('commerce_store_workbench',arguments(self.context(),self.page()),'local'))
        stale=self.page();stale['source_refs']['store_scope']='a'*64
        with patch.object(self.app,'invoke',side_effect=AssertionError('must reject before reads')):
            value=read_page(self.app,self.context(),stale)
        self.assertEqual(value['source_status'],'unavailable');self.assertIsNone(value['data'])

    def test_model_supplemental_read_uses_real_service_and_only_the_same_selected_sources(self):
        thread=self.app.copilot.open(self.context(),'model-read-open');page=self.page()
        sent=self.app.copilot.send(thread['id'],'继续检查当前店铺提醒',thread['context_sha256'],'model-read-send',page_context=page)
        responses=[inspect('commerce_store_workbench',arguments(self.context(),page)),answer(refs=['R1','R2'])]
        with patch.object(self.app,'invoke',wraps=self.app.invoke) as invoke,patch('agent_runtime.model.invoke',side_effect=responses),self.guarded():
            self.app.agent_runtime.run_once()
        self.assertEqual([call.args[0] for call in invoke.call_args_list],['commerce_store_workbench','commerce_store_workbench'])
        run=self.app.agent_runtime.get(sent['latest_run']['id'])
        self.assertEqual(run['status'],'completed')
        self.assertEqual(run['result']['observations'][-1]['data']['store_scope'],self.a)
        self.assertNotIn('store-b',json.dumps(run['result']['observations']))

    def test_selected_platform_reads_only_its_own_snapshots_and_never_job_recovery(self):
        from platform_connections.protocols import digest
        first,second='a'*32,'b'*32
        entries={ident:dict(store_id=ident,platform='amazon',market='US',label='Synthetic '+ident,
                           revision='revision-'+ident,enabled=True,scope_reviewed=True,access_token='SYNTHETIC-PRIVATE-ACCESS-TOKEN') for ident in (first,second)}
        with self.app.platforms.configs(write=True) as values:values.update(entries)
        with self.app.core.db() as db:
            for ident in (first,second):
                document={'records':[{'id':'private-order-'+ident,'customer':'private-customer'}],'observed_at':time.time()}
                document['sha256']=digest(document)
                db.execute('INSERT INTO platform_snapshots VALUES(?,?,?,?,?,?)',('snapshot-'+ident,ident,'orders',entries[ident]['revision'],json.dumps(document),time.time()))
                db.execute('INSERT INTO platform_latest VALUES(?,?,?)',(ident,'orders','snapshot-'+ident))
        scope=source_id('platform','amazon','US',first)
        before=self.snapshot()
        with patch.object(self.app.platforms,'snapshot',wraps=self.app.platforms.snapshot) as snapshots,self.guarded():
            value=workbench(self.app,store_scope=scope)
        self.assertEqual(before,self.snapshot());self.assertEqual([c.args[0] for c in snapshots.call_args_list],[first,first])
        self.assertEqual(value['platforms']['stores'][0]['snapshots']['orders']['record_count'],1)
        projected=json.dumps(projection(value))
        for private in (first,second,'SYNTHETIC-PRIVATE-ACCESS-TOKEN','private-order','private-customer','Synthetic '+first):self.assertNotIn(private,projected)

    def test_catalog_change_rejects_proposal_approval_but_same_send_key_reads_original_run(self):
        thread=self.app.copilot.open(self.context(),'proposal-open');page=self.page()
        sent=self.app.copilot.send(thread['id'],'当前店铺有哪些待办',thread['context_sha256'],'proposal-send',page_context=page)
        with patch('agent_runtime.model.invoke',return_value=answer()),self.guarded():self.app.agent_runtime.run_once()
        self.app.operations.record(observation(event_id='new-store',store_id='store-c'),current=NOW)
        reread=self.app.copilot.send(thread['id'],'当前店铺有哪些待办',thread['context_sha256'],'proposal-send',page_context=page)
        self.assertEqual(reread['latest_run']['id'],sent['latest_run']['id'])
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'store_scope_catalog_changed'):
            self.app.copilot.apply(thread['id'],sent['latest_run']['id'],'P1','not-a-result',thread['context_sha256'])
        self.assertEqual(before,self.snapshot())

    def test_missing_or_stale_page_cannot_enqueue_selected_questions(self):
        thread=self.app.copilot.open(self.context(),'open-selected')
        for i,page in enumerate((None,{'page':'store-ops','filters':{'scope':self.b}}, {**self.page(),'source_refs':{'store_scope':'0'*64}})):
            with self.subTest(page=page),self.assertRaises(ValueError):
                self.app.copilot.send(thread['id'],'当前店铺有什么提醒？',thread['context_sha256'],f'bad-{i}',page_context=page)
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],0)

    def test_version_change_between_enqueue_and_execution_never_reads_global_sources(self):
        thread=self.app.copilot.open(self.context(),'open-selected');page=self.page()
        sent=self.app.copilot.send(thread['id'],'当前店铺有什么提醒？',thread['context_sha256'],'send-selected',page_context=page)
        self.app.operations.record(observation(event_id='new-source',store_id='store-c'),current=NOW)
        seen=[]
        def model(payload,*args,**kwargs):
            seen.append(payload)
            return answer()
        with patch('agent_runtime.model.invoke',side_effect=model),self.guarded():self.app.agent_runtime.run_once()
        self.assertTrue(seen)
        observed=seen[0]['observations'][0]['data']
        self.assertEqual(observed['source_status'],'unavailable');self.assertIsNone(observed['data'])
        run=self.app.agent_runtime.get(sent['latest_run']['id'])
        self.assertEqual(run['parameters']['context']['store_scope'],self.a)
        self.assertEqual(run['parameters']['page_context']['source_refs']['store_scope'],page['source_refs']['store_scope'])

    def test_same_scope_continuation_preserves_budget_lineage_and_rejects_changed_scope_review(self):
        thread=self.app.copilot.open(self.context(),'open-lineage')
        sent=self.app.copilot.send(thread['id'],'当前店铺有什么提醒？',thread['context_sha256'],'lineage-one',page_context=self.page())
        def invoke(name,args,client='local'):
            if name=='commerce_store_workbench':return workbench(self.app,**args)
            return original(name,args,client)
        original=self.app.invoke
        with patch.object(self.app,'invoke',side_effect=invoke),patch('agent_runtime.model.invoke',return_value=answer()),self.guarded():self.app.agent_runtime.run_once()
        continued=self.app.copilot.send(thread['id'],'继续说明原范围',thread['context_sha256'],'lineage-two',page_context=self.page())
        self.assertEqual(continued['latest_run']['parent_id'],sent['latest_run']['id'])
        with self.app.core.db() as db:
            first=self.app.chain_budget._scope(db,sent['latest_run']['id']);second=self.app.chain_budget._scope(db,continued['latest_run']['id'])
        self.assertEqual(first[0],second[0]);self.assertGreater(second[1],first[1])
        self.app.copilot.cancel(thread['id'],continued['latest_run']['id'])
        changed=self.app.copilot.context(thread['id'],self.context(self.b),thread['context_sha256'])
        with self.assertRaisesRegex(ValueError,'context_changed'):
            self.app.copilot.apply(thread['id'],sent['latest_run']['id'],'P1','not-a-result',changed['context_sha256'])


if __name__=='__main__':unittest.main()
