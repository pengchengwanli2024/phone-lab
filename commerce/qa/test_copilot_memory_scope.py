"""Project memory stays inside frozen task identity; real temporary SQLite only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from agent_runtime.policy import check_call, tool_menu, project


class ProjectMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        self.context = dict(module='tasks', demo=True, platform='ozon', store_id='ozon-demo', market='RU', entity={'kind':'product','id':'product-one'})
        self.counter = 0

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.tmp.cleanup()

    def source(self, *, store='ozon-demo', subject='product-one', demo=True, value='cotton shared name', key='material'):
        self.counter += 1
        doc = self.app.business.template('price')['document']
        doc.update(kind='facts', synthetic=demo, scope=dict(platform='ozon',store_ref=store,subject_ref=subject), records=[dict(key=key,value=value)])
        imported = self.app.business.import_source(doc, 'source-'+str(self.counter))
        return imported, doc

    def fact(self, source, value='cotton shared name', confirmed=True, supersedes=None):
        self.counter += 1
        row = self.app.memory.propose(value, [dict(source_id=source['source_id'], version=source['version'], sha256=source['sha256'], record_key='material', quote='cotton')], 'fact-'+str(self.counter), supersedes)
        if confirmed:
            row = self.app.memory.decide('confirm', row['id'], row['revision'], row['sha256'], True, 'confirm-'+str(self.counter))
        return row

    def read(self, context=None, query='cotton'):
        from copilot.memory_scope import retrieve
        return retrieve(self.app, self.context if context is None else context, query)

    def test_menu_offers_query_only_and_parent_injects_exact_frozen_context(self):
        entries = {r['tool']:r for r in tool_menu('workspace', {'context':self.context})}
        self.assertIn('commerce_project_memory_search', entries)
        self.assertEqual(set(entries['commerce_project_memory_search']['arguments']), {'query'})
        name, args = check_call('workspace', {'context':self.context}, dict(tool='commerce_project_memory_search', arguments={'query':'cotton'}), set())
        self.assertEqual(args, {'context':self.context,'query':'cotton'})
        self.assertIsNot(args['context'], self.context)
        for bad in ({'query':'x','store_id':'all'}, {'context':{}}, {'query':None}, {'query':'x'*101}, {'query':['x']}):
            with self.assertRaisesRegex(ValueError, 'agent_invalid_tool_arguments'):
                check_call('workspace', {'context':self.context}, dict(tool=name,arguments=bad),set())
        for name in ('commerce_memory_get','commerce_memory_list','commerce_memory_search','commerce_memory_confirm'):
            with self.assertRaisesRegex(ValueError,'agent_tool_outside_scope'):
                check_call('workspace', {'context':self.context}, dict(tool=name,arguments={}),set())

    def test_exact_entity_store_and_mode_with_effective_facts_summaries_and_l1(self):
        own, _ = self.source()
        fact = self.fact(own)
        summary = self.app.memory.summarize([fact['id']], 'Material facts', 'summary')
        self.source(store='alternate-store',value='cotton CROSS_STORE shared name')
        self.source(subject='another-product',value='cotton CROSS_PRODUCT shared name')
        self.source(demo=False,value='cotton REAL_MODE shared name')
        proposed = self.fact(own, 'cotton UNCONFIRMED', confirmed=False)
        result = self.read()
        self.assertEqual({h['layer'] for h in result['hits']}, {'L1','L2','L3'})
        self.assertEqual({h['id'] for h in result['hits'] if h['layer']!='L1'}, {fact['id'],summary['id']})
        self.assertNotIn(proposed['id'], str(result))
        self.assertFalse(any(x in str(result) for x in ('CROSS_STORE','CROSS_PRODUCT','REAL_MODE')))
        for hit in result['hits']:
            self.assertTrue(hit['citations'])
            self.assertEqual(set(hit['citations'][0]), {'source_id','version','sha256','record_key','quote'})
        self.assertEqual(next(h for h in result['hits'] if h['layer']=='L1')['status'], 'imported_unverified')
        self.assertFalse(result['external_execution_allowed'])
        self.assertEqual(project('commerce_project_memory_search', result), result)

    def test_unknown_general_and_missing_identity_never_expand_to_all_shops(self):
        self.source()
        for context in ({'module':'overview'}, {**self.context,'entity':{'kind':'unknown','id':'product-one'}}, {**self.context,'store_id':'all'}, {k:v for k,v in self.context.items() if k!='demo'}, {**self.context,'market':'all'}):
            with self.subTest(context=context):
                result = self.read(context)
                self.assertEqual(result['hits'], [])
                self.assertEqual(result['scope_status'], 'unavailable')

    def test_case_and_task_use_authoritative_identity_and_reject_mismatch(self):
        source, _ = self.source(store='case-store',subject='case-subject')
        scope=dict(platform='ozon',market='RU',store_ref='case-store',subject_ref='case-subject',synthetic=True)
        with self.app.core.db() as db:
            db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',('case-one','', 'row-one', json.dumps(scope),None,'2026-01-01'))
        context=dict(module='organization',demo=True,platform='ozon',market='RU',entity={'kind':'case','id':'case-one'})
        self.assertEqual(len(self.read(context)['hits']),1)
        task=self.app.core.invoke('commerce_task_create',dict(kind='analysis',input={'organization_case':'case-one'},idempotency_key='task'))
        taskcontext={**context,'module':'tasks','entity':{'kind':'task','id':task['id']}}
        self.assertEqual(len(self.read(taskcontext)['hits']),1)
        self.assertEqual(self.read({**context,'store_id':'other-store'})['hits'],[])
        self.assertEqual(self.read({**context,'entity':{'kind':'case','id':'wrong-case'}})['hits'],[])
        with self.app.core.db() as db:db.execute('UPDATE org_cases SET scope=? WHERE id=?',(json.dumps(dict(platform='ozon',market='RU')),'case-one'))
        self.assertEqual(self.read(context)['hits'],[])

    def test_workflow_task_source_context_is_not_replaced_by_model_filters(self):
        self.source()
        task=self.app.core.invoke('commerce_task_create',dict(kind='analysis',input={'demo':True,'source_context':dict(demo=True,platform='ozon',store_id='ozon-demo',market='RU',entity_kind='product',entity_id='product-one',record_sha256='0'*64)},idempotency_key='workflow-task'))
        context={**self.context,'entity':{'kind':'task','id':task['id']}}
        self.assertEqual(len(self.read(context)['hits']),1)
        self.assertEqual(self.read({**context,'store_id':'alternate-store'})['hits'],[])

    def test_withdrawal_replacement_revision_and_expiration_invalidate_derived_content(self):
        source, doc = self.source()
        fact=self.fact(source)
        summary=self.app.memory.summarize([fact['id']],'Summary','summary')
        self.app.memory.decide('withdraw',fact['id'],fact['revision'],fact['sha256'],True,'withdraw')
        self.assertEqual({r['layer'] for r in self.read()['hits']},{'L1'})
        other=self.fact(source)
        replacement=self.fact(source,'cotton replacement',supersedes=other['id'])
        self.assertNotIn(other['id'],str(self.read()))
        doc['records'][0]['value']='cotton revised'
        self.app.business.import_source(doc,'revision',source['source_id'],source['version'])
        result=self.read()
        self.assertEqual({r['layer'] for r in result['hits']},{'L1'})
        self.assertEqual(result['hits'][0]['citations'][0]['version'],2)
        now=datetime.now(timezone.utc)
        doc['observed_at']=(now-timedelta(days=2)).isoformat()
        doc['valid_until']=(now-timedelta(days=1)).isoformat()
        self.app.business.import_source(doc,'expired',source['source_id'],2)
        self.assertEqual(self.read()['hits'],[])

    def test_revalidation_rejects_changes_before_consumption(self):
        from copilot.memory_scope import revalidate
        source, doc=self.source()
        result=self.read()
        self.assertTrue(revalidate(self.app,self.context,result))
        doc['records'][0]['value']='cotton revised'
        self.app.business.import_source(doc,'changed',source['source_id'],1)
        with self.assertRaisesRegex(ValueError,'agent_memory_evidence_changed'):
            revalidate(self.app,self.context,result)

    def start_run(self):
        return self.app.agent_runtime.create('请检索当前商品已确认材质资料', 'conductor','workspace','memory-run',{'context':self.context})

    def test_worker_reads_scoped_memory_through_existing_run_and_receipt(self):
        from test_agent_runtime import inspect, answer
        source,_=self.source()
        self.fact(source)
        run=self.start_run()
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_project_memory_search',{'query':'cotton'}),answer()]) as model:
            self.app.agent_runtime.run_once()
        value=self.app.agent_runtime.get(run['id'])
        self.assertEqual(value['status'],'completed',value.get('result'))
        self.assertEqual(model.call_count,2)
        observed=value['result']['observations'][0]
        self.assertEqual(observed['tool'],'commerce_project_memory_search')
        self.assertEqual({h['layer'] for h in observed['data']['hits']},{'L1','L2'})
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        self.assertEqual(model.call_args_list[1].args[0]['observations'][0],observed)

    def test_worker_withdrawn_memory_never_reaches_second_model_turn(self):
        from test_agent_runtime import inspect, answer
        source,_=self.source()
        fact=self.fact(source)
        run=self.start_run()
        def withdraw_after_projection(name,value):
            result=project(name,value)
            if name=='commerce_project_memory_search':
                self.app.memory.decide('withdraw',fact['id'],fact['revision'],fact['sha256'],True,'worker-withdraw')
            return result
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_project_memory_search',{'query':'cotton'}),answer()]) as model, patch('agent_runtime.project',side_effect=withdraw_after_projection):
            self.app.agent_runtime.run_once()
        value=self.app.agent_runtime.get(run['id'])
        self.assertEqual(value['result'].get('error'),'agent_memory_evidence_changed')
        self.assertEqual(model.call_count,1)

    def test_worker_updated_source_never_reaches_second_model_turn(self):
        from test_agent_runtime import inspect, answer
        source,doc=self.source()
        self.fact(source)
        run=self.start_run()
        def update_after_projection(name,value):
            result=project(name,value)
            if name=='commerce_project_memory_search':
                doc['records'][0]['value']='cotton revised'
                self.app.business.import_source(doc,'worker-update',source['source_id'],1)
            return result
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_project_memory_search',{'query':'cotton'}),answer()]) as model, patch('agent_runtime.project',side_effect=update_after_projection):
            self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result'].get('error'),'agent_memory_evidence_changed')
        self.assertEqual(model.call_count,1)

    def test_worker_rechecks_memory_after_model_returns_before_publishing_answer(self):
        from test_agent_runtime import inspect, answer
        source,_=self.source()
        fact=self.fact(source)
        run=self.start_run()
        def respond(context,*args,**kwargs):
            if not context['observations']:return inspect('commerce_project_memory_search',{'query':'cotton'})
            self.app.memory.decide('withdraw',fact['id'],fact['revision'],fact['sha256'],True,'during-model')
            return answer()
        with patch('agent_runtime.model.invoke',side_effect=respond):self.app.agent_runtime.run_once()
        result=self.app.agent_runtime.get(run['id'])['result']
        self.assertEqual(result.get('error'),'agent_memory_evidence_changed')
        self.assertNotIn('answer',result)

    def test_worker_scope_changed_between_enqueue_and_execution_rejects_read(self):
        from test_agent_runtime import inspect
        self.source()
        scope=dict(platform='ozon',market='RU',store_ref='ozon-demo',subject_ref='product-one',synthetic=True)
        with self.app.core.db() as db:
            db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',('case-one','','row-one',json.dumps(scope),None,'2026-01-01'))
        self.context={**self.context,'entity':{'kind':'case','id':'case-one'}}
        run=self.start_run()
        scope['store_ref']='alternate-store'
        with self.app.core.db() as db:db.execute('UPDATE org_cases SET scope=? WHERE id=?',(json.dumps(scope),'case-one'))
        with patch('agent_runtime.model.invoke',return_value=inspect('commerce_project_memory_search',{'query':'cotton'})) as model:
            self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result'].get('error'),'agent_memory_scope_changed')
        model.assert_not_called()

    def test_withdrawn_memory_turn_is_excluded_from_conversation_and_direct_parent(self):
        from test_agent_runtime import inspect, answer
        source,_=self.source()
        fact=self.fact(source)
        chat=self.app.copilot
        thread=chat.open(self.context,'history-open')
        first=chat.send(thread['id'],'请检索当前商品材质',thread['context_sha256'],'history-first')
        response=answer();response['decision']['answer']='MEMORY_DERIVED_PRIVATE_SENTINEL'
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_project_memory_search',{'query':'cotton'}),response]):self.app.agent_runtime.run_once()
        parent=chat.get(thread['id'])['latest_run']['id']
        self.app.memory.decide('withdraw',fact['id'],fact['revision'],fact['sha256'],True,'history-withdraw')
        second=chat.send(thread['id'],'请重新核对当前材质',thread['context_sha256'],'history-second')
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]) as model:self.app.agent_runtime.run_once()
        self.assertNotIn('MEMORY_DERIVED_PRIVATE_SENTINEL',json.dumps(model.call_args_list[0].args[0]))
        self.assertIsNone(second['latest_run']['parent_id'])
        direct=self.app.agent_runtime.create('继续核对材质','conductor','workspace','direct-after-withdraw',{'context':self.context},parent)
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]) as model:self.app.agent_runtime.run_once()
        self.assertNotIn('MEMORY_DERIVED_PRIVATE_SENTINEL',json.dumps(model.call_args_list[0].args[0]))

    def test_queued_history_provenance_is_rechecked_before_model_consumption(self):
        from test_agent_runtime import inspect, answer
        source,_=self.source()
        fact=self.fact(source)
        chat=self.app.copilot
        thread=chat.open(self.context,'queued-history-open')
        chat.send(thread['id'],'请检索商品材质',thread['context_sha256'],'queued-history-first')
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_project_memory_search',{'query':'cotton'}),answer()]):self.app.agent_runtime.run_once()
        second=chat.send(thread['id'],'继续核对材质',thread['context_sha256'],'queued-history-second')
        self.app.memory.decide('withdraw',fact['id'],fact['revision'],fact['sha256'],True,'queued-history-withdraw')
        with patch('agent_runtime.model.invoke') as model:self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(second['latest_run']['id'])['result'].get('error'),'agent_memory_evidence_changed')
        model.assert_not_called()

    def test_replaced_memory_invalidates_transitive_history_provenance(self):
        from test_agent_runtime import inspect, answer
        source,_=self.source()
        fact=self.fact(source)
        chat=self.app.copilot
        thread=chat.open(self.context,'transitive-open')
        chat.send(thread['id'],'请检索当前商品材质',thread['context_sha256'],'transitive-first')
        first_answer=answer();first_answer['decision']['answer']='ORIGINAL_MEMORY_SENTINEL'
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_project_memory_search',{'query':'cotton'}),first_answer]):self.app.agent_runtime.run_once()
        chat.send(thread['id'],'解释已有资料',thread['context_sha256'],'transitive-second')
        second_answer=answer();second_answer['decision']['answer']='INHERITED_MEMORY_SENTINEL'
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),second_answer]):self.app.agent_runtime.run_once()
        self.fact(source,'cotton corrected',supersedes=fact['id'])
        third=chat.send(thread['id'],'重新核对当前资料',thread['context_sha256'],'transitive-third')
        self.assertIsNone(third['latest_run']['parent_id'])
        with patch('agent_runtime.model.invoke',side_effect=[inspect(),answer()]) as model:self.app.agent_runtime.run_once()
        modelcontext=json.dumps(model.call_args_list[0].args[0])
        self.assertNotIn('ORIGINAL_MEMORY_SENTINEL',modelcontext)
        self.assertNotIn('INHERITED_MEMORY_SENTINEL',modelcontext)

    def test_internal_context_hashes_and_model_query_contract_cannot_broaden_provenance(self):
        from business_workflows.store import digest
        from copilot.memory_scope import history_refs
        self.source()
        result=self.read()
        self.assertEqual(result['context_sha256'],digest(self.context))
        self.assertRegex(result['scope_binding_sha256'],r'^[0-9a-f]{64}$')
        from copilot.memory_scope import revalidate
        altered={**self.context,'store_id':'alternate-store'}
        with self.assertRaisesRegex(ValueError,'agent_memory_evidence_changed'):revalidate(self.app,altered,result)
        self.assertIsNone(history_refs(self.app,self.context,'unseen-run'))
        params={'context':self.context}
        with self.assertRaisesRegex(ValueError,'agent_tool_outside_scope'):
            check_call('runtime',{},dict(tool='commerce_project_memory_search',arguments={'query':'cotton'}),set())
        for args in ({'query':'cotton','synthetic':False},{'query':'cotton','memory_id':'unseen-id'},{'query':'cotton','limit':500}):
            with self.assertRaisesRegex(ValueError,'agent_invalid_tool_arguments'):
                check_call('workspace',params,dict(tool='commerce_project_memory_search',arguments=args),set())

    def test_ambiguous_or_malformed_task_identity_fails_closed(self):
        self.source()
        sourcecontext=dict(demo=True,platform='ozon',store_id='ozon-demo',market='RU',entity_kind='product',entity_id='product-one',record_sha256='0'*64)
        with self.app.core.db() as db:
            scope=dict(platform='ozon',market='RU',store_ref='ozon-demo',subject_ref='product-one',synthetic=True)
            db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',('conflict-case','','conflict-row',json.dumps(scope),None,'2026-01-01'))
        task=self.app.core.invoke('commerce_task_create',dict(kind='analysis',input={'organization_case':'conflict-case','source_context':sourcecontext},idempotency_key='ambiguous-task'))
        context={**self.context,'entity':{'kind':'task','id':task['id']}}
        self.assertEqual(self.read(context)['hits'],[])
        sourcecontext['demo']='true'
        malformed=self.app.core.invoke('commerce_task_create',dict(kind='analysis',input={'source_context':sourcecontext},idempotency_key='malformed-task'))
        self.assertEqual(self.read({**context,'entity':{'kind':'task','id':malformed['id']}})['hits'],[])

    def proposal_run(self):
        from test_agent_runtime import inspect, answer
        self.context={**self.context,'calculator':'unit_economics','input':{}}
        run=self.start_run()
        response=answer(proposals=[{'operation':'unit_economics','reason':'按已有资料审阅本地测算'}])
        with patch('agent_runtime.model.invoke',side_effect=[inspect('commerce_project_memory_search',{'query':'cotton'}),response]):self.app.agent_runtime.run_once()
        value=self.app.agent_runtime.get(run['id'])
        self.assertEqual(value['status'],'awaiting_review',value['result'])
        return value

    def test_apply_rechecks_memory_before_any_task_creation(self):
        source,_=self.source()
        fact=self.fact(source)
        run=self.proposal_run()
        self.app.memory.decide('withdraw',fact['id'],fact['revision'],fact['sha256'],True,'apply-withdraw')
        with self.assertRaisesRegex(ValueError,'agent_memory_evidence_changed'):
            self.app.agent_runtime.apply(run['id'],'P1',run['result_sha256'])
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM agent_actions').fetchone()[0],0)

    def test_applied_retry_returns_existing_receipt_after_memory_withdrawal(self):
        source,_=self.source()
        fact=self.fact(source)
        run=self.proposal_run()
        first=self.app.agent_runtime.apply(run['id'],'P1',run['result_sha256'])
        self.app.memory.decide('withdraw',fact['id'],fact['revision'],fact['sha256'],True,'after-apply-withdraw')
        with patch.object(self.app.autonomy,'request',wraps=self.app.autonomy.request) as request:
            second=self.app.agent_runtime.apply(run['id'],'P1',run['result_sha256'])
        self.assertEqual(first['task']['id'],second['task']['id'])
        request.assert_not_called()
        self.assertEqual(len(self.app.core.invoke('commerce_task_list',{})['tasks']),1)

    def test_sensitive_record_keys_are_never_exposed_as_content_or_citations(self):
        self.source(key='password',value='cotton PRIVATE_VALUE_SENTINEL')
        self.assertEqual(self.read()['hits'],[])

    def test_live_alias_without_frozen_connection_and_old_case_connection_fail_closed(self):
        self.source(store='ozon-live',demo=False,value='cotton ALIAS_SENTINEL')
        context={**self.context,'demo':False,'store_id':'ozon-live'}
        self.assertEqual(self.read(context)['hits'],[])
        with self.app.core.db() as db:
            scope=dict(platform='ozon',market='RU',store_ref='old-connection',subject_ref='case-old')
            db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',('case-old','old-connection','old-row',json.dumps(scope),None,'2026-01-01'))
        self.source(store='old-connection',subject='case-old',demo=False,value='cotton OLD_CONNECTION_SENTINEL')
        context=dict(module='tasks',demo=False,entity={'kind':'case','id':'case-old'})
        self.assertEqual(self.read(context)['hits'],[])

    def test_bounded_projection_credentials_and_legacy_api(self):
        for i in range(12):self.source(value='cotton '+('long '*1000)+str(i))
        self.source(value='cotton api_key=PRIVATE_CREDENTIAL_SENTINEL')
        result=self.read()
        self.assertLessEqual(len(result['hits']),5)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),12000)
        self.assertTrue(result['truncated'])
        self.assertNotIn('PRIVATE_CREDENTIAL_SENTINEL',str(result))
        self.assertTrue(all(len(h['content'])<=800 and all(len(c['quote'])<=300 for c in h['citations']) for h in result['hits']))
        self.assertTrue(self.app.memory.search('cotton',True)['hits'])
        self.assertEqual(self.app.memory.listing(True)['items'],[])
        for query in (None,[], 'x'*101):
            with self.assertRaises(ValueError):self.read(query=query)


if __name__=='__main__':unittest.main()
