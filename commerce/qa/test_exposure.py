"""Conservative geography, versioned mappings and explicit review; synthetic only."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from service import Commerce
from exposure import normalize,relation,distance,segment_distance,digest
from fixture_agent_cases import seed
from intel_store import canonical as intel_canonical,digest as intel_digest


def mapping(**overrides):
    data={'label':'Synthetic coverage','kind':'market','country_codes':['MEX'],'source_ref':'synthetic:coverage','active':True}
    data.update(overrides);return data


def publish(app,**overrides):
    now=time.time();item={'id':'a'*24,'source':'gdacs','source_key':'synthetic-flood','title':'Synthetic flood in Mexico','url':'https://example.org/synthetic-flood','published':now-60,'category':'disaster','country':'Mexico','country_code':'MEX','location':{'lat':10.,'lon':20.},'publisher_alert':'Orange','collected_at':__import__('datetime').datetime.fromtimestamp(now,__import__('datetime').timezone.utc).isoformat(),'source_payload_sha256':'b'*64,'verification':'publisher_report_not_independently_verified'}
    item.update(overrides)
    with app.core.db() as db:
        db.execute('INSERT OR REPLACE INTO intel_items VALUES (?,?,?)',(item['id'],item['source'],json.dumps(item)))
        app.intelligence.store.archive(db,item,now)
        db.execute('INSERT OR REPLACE INTO intel_sources VALUES (?,?)',(item['source'],json.dumps({'status':'ok','last_attempt':now,'last_success':now})))
    return app.intelligence.store.item(item['id'])


class Geography(unittest.TestCase):
    def test_spherical_distance_and_route_crossing_date_line(self):
        self.assertAlmostEqual(distance({'lat':0,'lon':0},{'lat':0,'lon':1}),111.1949,places=3)
        self.assertAlmostEqual(segment_distance({'lat':0,'lon':180},{'lat':0,'lon':179},{'lat':0,'lon':-179}),0,places=6)
        self.assertGreater(segment_distance({'lat':0,'lon':0},{'lat':0,'lon':179},{'lat':0,'lon':-179}),19000)
        self.assertAlmostEqual(segment_distance({'lat':1,'lon':0},{'lat':0,'lon':-1},{'lat':0,'lon':1}),111.1949,places=3)
        self.assertAlmostEqual(distance({'lat':90,'lon':0},{'lat':90,'lon':150}),0,places=6)

    def test_route_projection_beyond_endpoints_uses_endpoint(self):
        p,a,b={'lat':0,'lon':3},{'lat':0,'lon':0},{'lat':0,'lon':1}
        self.assertAlmostEqual(segment_distance(p,a,b),distance(p,b),places=6)
        self.assertAlmostEqual(segment_distance(p,b,a),segment_distance(p,a,b),places=6)

    def test_no_inference_from_title_and_country_code_exactness(self):
        target={'id':'x','version':1,'sha256':'f'*64,'data':normalize(mapping(country_codes=['RUS']))}
        value=relation({'title':'Russia flooding','country':'Russia','country_code':None},target)
        self.assertEqual(value['relation'],'insufficient_data')
        self.assertEqual(relation({'country_code':'BLR'},target)['country_check'],'different')
        self.assertEqual(relation({'country_code':'RUS'},target)['country_check'],'match')
        self.assertEqual(value['business_impact'],'unknown')

    def test_invalid_geometry_and_boolean_radius_are_rejected(self):
        for p in ({'lat':True,'lon':0},{'lat':float('nan'),'lon':0},{'lat':91,'lon':0}):
            with self.assertRaises(ValueError):normalize(mapping(kind='warehouse',point=p,radius_km=1))
        with self.assertRaises(ValueError):normalize(mapping(kind='warehouse',point={'lat':0,'lon':0},radius_km=True))
        with self.assertRaises(ValueError):normalize(mapping(kind='route',path=[{'lat':0,'lon':0},{'lat':0,'lon':180}],radius_km=1))
        with self.assertRaises(ValueError):normalize(mapping(kind='market',point={'lat':0,'lon':0}))
        with self.assertRaises(ValueError):normalize(mapping(country_codes=['Russia']))
        with self.assertRaises(ValueError):normalize(mapping(country_codes=[]))


class ExposureWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Commerce(self.temp.name);self.cid=seed(self.app);self.item=publish(self.app);self.ex=self.app.exposure
    def tearDown(self):self.temp.cleanup()
    def save(self,data=None,key='map',**changes):return self.ex.save(self.cid,data or mapping(),key,**changes)['target']
    def assess(self):return self.ex.assess(self.cid,self.item['id'],self.item['record_sha256'])
    def update(self,target,**data):return self.save({**target['data'],**data},key='edit-'+str(target['version']),target_id=target['id'],expected_sha256=target['sha256'])

    def test_mapping_idempotency_versions_and_prevent_lost_updates(self):
        a=self.save();b=self.save();self.assertEqual(a,b)
        fresh=self.update(a,label='Edited coverage');self.assertEqual(fresh['version'],2)
        with self.assertRaisesRegex(ValueError,'exposure_target_changed'):self.save(mapping(),key='stale',target_id=a['id'],expected_sha256=a['sha256'])
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.save(mapping(label='different'))
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM exposure_versions').fetchone()[0],2)
        self.assertEqual(Commerce(self.temp.name).exposure.targets(self.cid)['targets'][0]['sha256'],fresh['sha256'])

    def test_unknown_coverage_never_becomes_zero_impact(self):
        result=self.assess();self.assertEqual(result['document']['coverage']['active_current'],0)
        self.assertEqual(result['document']['relations'],[]);self.assertEqual(result['business_impact'],'unknown')
        self.save(mapping(country_codes=['RUS']));value=self.assess()['document']['relations'][0]
        self.assertEqual(value['relation'],'no_match_in_available_checks');self.assertEqual(value['business_impact'],'unknown')

    def test_market_warehouse_route_checks_are_distinct_context(self):
        self.save();self.save(mapping(label='Warehouse',kind='warehouse',country_codes=['RUS'],point={'lat':10,'lon':20},radius_km=5),'warehouse')
        self.save(mapping(label='Route',kind='route',country_codes=[],path=[{'lat':10,'lon':19},{'lat':10,'lon':21}],radius_km=5),'route')
        rows=self.assess()['document']['relations'];by={r['kind']:r for r in rows}
        self.assertEqual(by['market']['country_check'],'match');self.assertEqual(by['market']['geometry_check'],'unknown')
        self.assertEqual(by['warehouse']['country_check'],'different');self.assertEqual(by['warehouse']['geometry_check'],'inside')
        self.assertEqual(by['route']['geometry_check'],'inside');self.assertTrue(all(r['business_impact']=='unknown' for r in rows))

    def test_target_and_source_change_withdraw_old_review(self):
        t=self.save();a=self.assess();self.update(t,active=False)
        self.assertEqual(self.ex.get(a['id'])['current_status'],'changed')
        with self.assertRaisesRegex(ValueError,'exposure_evidence_changed'):self.ex.review(a['id'])
        b=self.assess();publish(self.app,title='Changed source record')
        self.assertEqual(self.ex.get(b['id'])['current_status'],'changed')
        with self.assertRaisesRegex(ValueError,'exposure_source_changed'):self.assess()
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])

    def test_reading_and_bookmarking_do_not_change_assessment(self):
        self.save();a=self.assess()
        self.app.intelligence.store.update_item(self.item['id'],'bookmark')
        self.app.intelligence.store.update_item(self.item['id'],'viewed',self.item['record_sha256'])
        b=self.assess();self.assertEqual(a['id'],b['id']);self.assertEqual(a['created_at'],b['created_at'])

    def test_currency_is_not_geographic_scope_and_connection_change_is(self):
        self.save();a=self.assess();self.app.organization.set_currency(self.cid,'USD')
        self.assertEqual(self.ex.get(a['id'])['current_status'],'current')
        self.app.live.configure({'ozon_client_id':'654321'})
        self.assertEqual(self.ex.get(a['id'])['current_status'],'unavailable')
        with self.assertRaisesRegex(ValueError,'exposure_case_unavailable'):self.ex.targets(self.cid)

    def test_version_bound_shared_review_concurrency_and_historical_retry(self):
        t=self.save();a=self.assess()
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.ex.review(a['id']),range(4)))
        self.assertEqual(len({r['task']['id'] for r in results}),1)
        task=results[0]['task'];self.assertEqual(task['input']['execution'],'not_requested')
        self.assertEqual(task['input']['business_impact'],'unknown');self.update(t,label='New label')
        retry=self.ex.review(a['id']);self.assertEqual(retry['task']['id'],task['id']);self.assertEqual(retry['current_status'],'changed')
        self.assertEqual(self.ex.get(a['id'])['document']['targets'][0]['data']['label'],'Synthetic coverage')

    def test_staleness_change_retains_evidence_and_invalidates_fresh_claim(self):
        self.save();a=self.assess()
        with patch('exposure.time.time',return_value=time.time()+22000):
            self.assertEqual(self.ex.get(a['id'])['current_status'],'changed')
            later=self.assess();self.assertTrue(later['document']['source_state']['collection_stale'])
        self.assertEqual(self.ex.get(a['id'])['document']['source']['record_sha256'],self.item['record_sha256'])

    def test_export_integrity_and_corruption_is_not_accepted(self):
        self.save();a=self.assess();doc=json.loads(self.ex.export(a['id'])['content']);sha=doc.pop('export_sha256');self.assertEqual(digest(doc),sha)
        with self.app.core.db() as db:db.execute('UPDATE exposure_assessments SET document=? WHERE id=?',('{}',a['id']))
        with self.assertRaisesRegex(ValueError,'exposure_assessment_integrity_failed'):self.ex.get(a['id'])

    def test_model_only_receives_one_projected_assessment_and_cannot_change_it(self):
        self.save(mapping(kind='warehouse',point={'lat':10,'lon':20},radius_km=5,source_ref='PRIVATE_COVERAGE_NOTE'))
        a=self.assess();run=self.app.agent_runtime.create(question='整理复核问题',role='conductor',topic='business_exposure',parameters={'assessment_id':a['id']},idempotency_key='model')
        responses=[{'decision':{'phase':'inspect','calls':[{'tool':'commerce_exposure_get','arguments':{'assessment_id':a['id']}}]}}, {'decision':{'phase':'answer','answer':'存在关联线索，实际影响需复核。','questions':[],'evidence_refs':['R1'],'proposals':[{'operation':'exposure_review','reason':'复核来源与经营范围','evidence_ref':'R1'}]}}]
        with patch('agent_runtime.model.invoke',side_effect=responses):self.app.agent_runtime.run_once()
        result=self.app.agent_runtime.get(run['id']);self.assertEqual(result['status'],'awaiting_review')
        model_data=result['result']['observations'][0]['data'];self.assertNotIn('targets',model_data);self.assertNotIn('PRIVATE_COVERAGE_NOTE',json.dumps(model_data))
        self.assertEqual(self.app.core.invoke('commerce_task_list',{})['tasks'],[])
        task=self.app.agent_runtime.apply(run['id'],'P1',result['result_sha256'])['task'];self.assertEqual(task['input']['exposure_assessment'],a['id'])
        self.assertEqual(self.ex.review(a['id'])['task']['id'],task['id'])

    def test_model_changes_while_running_are_rejected(self):
        t=self.save();a=self.assess();run=self.app.agent_runtime.create(question='整理资料',role='conductor',topic='business_exposure',parameters={'assessment_id':a['id']},idempotency_key='change-during-model')
        def mutate(*args):
            self.update(t,label='Changed during inference')
            return {'decision':{'phase':'answer','answer':'旧答复','questions':[],'evidence_refs':[],'proposals':[]}}
        with patch('agent_runtime.model.invoke',side_effect=mutate):self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_exposure_evidence_changed')

    def test_active_limit_does_not_disable_prior_mappings(self):
        for i in range(12):self.save(mapping(label='coverage '+str(i)),key='map-'+str(i))
        with self.assertRaisesRegex(ValueError,'exposure_active_target_limit'):self.save(key='too-many')
        self.assertEqual(len(self.ex.targets(self.cid)['targets']),12)

    def test_model_cannot_read_another_retained_assessment(self):
        t=self.save();old=self.assess();self.update(t,label='A new view');current=self.assess()
        run=self.app.agent_runtime.create(question='只读选定资料',role='conductor',topic='business_exposure',parameters={'assessment_id':current['id']},idempotency_key='bounded-assessment')
        decision={'decision':{'phase':'inspect','calls':[{'tool':'commerce_exposure_get','arguments':{'assessment_id':old['id']}}]}}
        with patch('agent_runtime.model.invoke',return_value=decision):self.app.agent_runtime.run_once()
        self.assertEqual(self.app.agent_runtime.get(run['id'])['result']['error'],'agent_exposure_outside_scope')


class ExposureTransport(unittest.TestCase):
    def test_three_stdio_entries_share_mapping_evidence_and_review(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary);(state/'auth.token').write_text('synthetic-exposure-transport')
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            env=dict(os.environ,COMMERCE_STATE=str(state),COMMERCE_PORT=str(port))
            server=subprocess.Popen([sys.executable,str(root/'qa/fixture_exposure.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            def rpc(client,name,args):
                messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':args}}]
                done=subprocess.run([sys.executable,str(root/'mcp_server.py'),client],env=env,input=''.join(json.dumps(m)+'\n' for m in messages),capture_output=True,text=True,timeout=12)
                result=json.loads(done.stdout.splitlines()[-1])['result'];self.assertFalse(result.get('isError'),name);return result['structuredContent']
            try:
                for _ in range(100):
                    with socket.socket() as s:
                        if s.connect_ex(('127.0.0.1',port))==0:break
                    time.sleep(.05)
                cid=rpc('codex','commerce_agent_cases',{})['cases'][0]['id']
                rpc('hermes','commerce_exposure_save',{'case_id':cid,'data':mapping(),'idempotency_key':'transport-map'})
                a=rpc('harness','commerce_exposure_assess',{'case_id':cid,'item_id':'a'*24})
                run=rpc('codex','commerce_agent_start',{'question':'整理关联复核','role':'conductor','topic':'business_exposure','parameters':{'assessment_id':a['id']},'idempotency_key':'transport-model'})
                for _ in range(40):
                    result=rpc('hermes','commerce_agent_get',{'run_id':run['id']})
                    if result['status']=='awaiting_review':break
                    time.sleep(.05)
                self.assertEqual(result['status'],'awaiting_review')
                task=rpc('harness','commerce_agent_apply',{'run_id':run['id'],'proposal_id':'P1','result_sha256':result['result_sha256']})['task']
                self.assertEqual(rpc('codex','commerce_exposure_review',{'assessment_id':a['id']})['task']['id'],task['id'])
                artifact=json.loads(rpc('hermes','commerce_exposure_export',{'assessment_id':a['id']})['content'])
                self.assertEqual(artifact['assessment_id'],a['id']);self.assertEqual(artifact['business_impact'],'unknown')
            finally:server.terminate();server.wait(timeout=8)


if __name__=='__main__':unittest.main(verbosity=2)
