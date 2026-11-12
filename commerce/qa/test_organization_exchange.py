"""Synthetic explicit-context handoffs. No model/network calls or shop writes."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from organization_exchange import OrganizationExchange
from research import canonical,digest


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OrganizationTests();self.fixture.setUp();self.app=self.fixture.app;self.org=self.fixture.org;self.exchange=self.org.exchange;self.cid=self.fixture.cid
    def tearDown(self):self.fixture.tearDown()
    def context(self):return self.exchange.context(self.cid)
    def produce(self,tool,args,**kw):return self.exchange.produce(self.context(),tool,args,**kw)
    def record(self):return self.fixture.research()['record']
    def count(self,kind):
        with self.org.core.db()as db:return db.execute('SELECT count(*) FROM org_artifacts WHERE case_id=? AND kind=?',(self.cid,kind)).fetchone()[0]

    def test_research_and_cost_outputs_handoff_without_json_round_trip(self):
        r=self.record();a=self.produce('commerce_collection_check',{'record':r});b=self.produce('commerce_collection_export',{'record':r,'final':True})
        self.assertEqual(a['artifact_handoff']['status'],'saved');self.assertEqual(a['artifact_handoff']['id'],b['artifact_handoff']['id']);self.assertEqual(self.count('research'),1)
        self.assertEqual(json.loads(b['json'])['record'],r);self.assertEqual(self.org.artifact(self.cid,'research')['payload']['record'],r)
        data=self.fixture.prepare_cost();result=self.produce('commerce_unit_economics',{'input':data});self.assertEqual(result['artifact_handoff']['status'],'saved');sha=result.pop('result_sha256');self.assertEqual(digest(canonical(result)),sha)

    def test_unreviewed_translation_and_missing_cost_remain_hold(self):
        r=self.record();r['fields']['title']['reviewed']=False;self.produce('commerce_collection_check',{'record':r});self.assertNotEqual(self.fixture.stage('S5')['status'],'PASS')
        result=self.produce('commerce_unit_economics',{'input':{}});self.assertEqual(result['status'],'HOLD');self.assertEqual(result['artifact_handoff']['status'],'saved');self.assertIsNone(self.org.case(self.cid)['currency'])

    def test_demo_scope_mismatch_and_currency_drift_are_rejected(self):
        for origin in ('example','edited-example'):
            with self.assertRaisesRegex(ValueError,'example_output'):self.exchange.produce({**self.context(),'origin':origin},'commerce_unit_economics',{'input':{}})
        context=self.context();self.org.set_currency(self.cid,'CNY')
        with self.assertRaisesRegex(ValueError,'scope_changed'):self.exchange.produce(context,'commerce_unit_economics',{'input':{}})
        with self.assertRaisesRegex(ValueError,'currency_mismatch'):self.produce('commerce_unit_economics',{'input':{'currency':'RUB'}})
        r=self.record();r['market']='US'
        with self.assertRaisesRegex(ValueError,'research_scope_mismatch'):self.produce('commerce_collection_check',{'record':r})
        self.assertEqual(self.count('research'),0)

    def test_scope_change_during_source_work_does_not_publish(self):
        original=self.app.invoke
        def changing(name,args,client):
            result=original(name,args,client);self.org.set_currency(self.cid,'CNY');return result
        with patch.object(self.app,'invoke',side_effect=changing):result=self.produce('commerce_unit_economics',{'input':{}})
        self.assertEqual(result['artifact_handoff']['status'],'held');self.assertEqual(self.count('economics'),0)

    def test_newer_source_head_blocks_late_publication_atomically(self):
        r=self.record();original=self.app.invoke
        def changing(name,args,client):
            result=original(name,args,client);new=deepcopy(r);new['fields']['title']['zh']='人工更新。'
            self.org.record(self.cid,'research',self.fixture.research()|{'record':new},'newer-artifact');return result
        with patch.object(self.app,'invoke',side_effect=changing):result=self.produce('commerce_collection_check',{'record':r})
        self.assertEqual(result['artifact_handoff']['code'],'exchange_source_head_changed');self.assertEqual(self.count('research'),1)
        self.assertEqual(self.org.artifact(self.cid,'research')['payload']['record']['fields']['title']['zh'],'人工更新。')

    def test_reverting_to_earlier_content_creates_current_version_without_duplicate_repeats(self):
        a=self.record();b=deepcopy(a);b['fields']['title']['zh']='另一个版本。'
        for r in (a,a,b,b,a,a):self.produce('commerce_collection_check',{'record':r})
        self.assertEqual(self.count('research'),3);self.assertEqual(self.org.artifact(self.cid,'research')['payload']['record'],a)

    def translation(self):
        r=self.record();r['fields']['title']['zh']='';r['fields']['title']['reviewed']=False
        items=[{'id':'title','text':r['fields']['title']['original']}];job='synthetic-translation-job';input={'language':'en','items':items}
        with self.org.core.db()as db:db.execute('INSERT INTO translations VALUES (?,?,?,?,?,?)',(job,'synthetic-translation-key',canonical(input),'running',None,'2026-11-11T00:00:00+00:00'))
        with patch.object(self.app.translations,'start',return_value={'id':job,'status':'running'}):self.produce('commerce_translation_start',{'input':input,'idempotency_key':'synthetic-translation-key'},source_record=r)
        result={'translations':[{'id':'title','zh':'合成译文。','original_sha256':digest(items[0]['text']),'zh_sha256':digest('合成译文。'),'warnings':[]}],'provider':'synthetic','model':'synthetic','translated_at':'2026-11-11T00:00:01+00:00','prompt_version':'synthetic'}
        with self.org.core.db()as db:db.execute("UPDATE translations SET status='completed',result=? WHERE id=?",(canonical(result),job))
        return r,job

    def test_completed_translation_recovers_after_reload_without_resubmission(self):
        r,job=self.translation();restored=OrganizationExchange(self.org)
        with patch.object(self.app.translations,'start')as start:
            result=restored.sync(self.cid);restored.sync(self.cid);start.assert_not_called()
        record=self.org.artifact(self.cid,'research')['payload']['record'];self.assertEqual(record['fields']['title']['zh'],'合成译文。');self.assertFalse(record['fields']['title']['reviewed']);self.assertEqual(record['fields']['title']['original'],r['fields']['title']['original']);self.assertFalse(result['model_requests_submitted'])
        self.assertNotEqual(self.fixture.stage('S5')['status'],'PASS')

    def test_human_translation_edits_are_not_overwritten(self):
        r,job=self.translation();r['fields']['title'].update(zh='人工已校对译文。',reviewed=True);self.org.record(self.cid,'research',self.fixture.research()|{'record':r},'manual-edit')
        self.exchange.sync(self.cid);field=self.org.artifact(self.cid,'research')['payload']['record']['fields']['title'];self.assertEqual(field['zh'],'人工已校对译文。');self.assertTrue(field['reviewed'])

    def test_changed_original_does_not_receive_older_model_output(self):
        r,job=self.translation();r['fields']['title']['original']='Changed source.';self.org.record(self.cid,'research',self.fixture.research()|{'record':r},'changed-source')
        result=self.exchange.sync(self.cid);self.assertTrue(any(v.get('code')=='exchange_source_changed_translation_not_applied'for v in result['results']));self.assertEqual(self.org.artifact(self.cid,'research')['payload']['record']['fields']['title']['zh'],'')

    def test_image_binding_delivers_and_rechecks_changed_file(self):
        self.fixture.prepare_research();project,asset=self.fixture.creative();self.exchange.bind_images(self.context(),project['id'],[asset['id']],False)
        self.exchange.sync(self.cid);self.assertEqual(self.count('images'),1)
        self.assertEqual(self.fixture.stage('S4')['status'],'PASS');payload=self.org.artifact(self.cid,'images')['payload'];file=self.org.state/payload['files'][0]['relative_path'];file.write_bytes(b'changed')
        result=self.exchange.sync(self.cid);self.assertTrue(any(v.get('code')=='delivered_file_changed'for v in result['results']));self.assertEqual(self.fixture.stage('S4')['status'],'FAIL')

    def test_interrupted_local_write_recovers_idempotently(self):
        payload=self.fixture.research();key=self.exchange._queue(self.context(),'research',payload);self.exchange._publish(key)
        with self.org.core.db()as db:db.execute("UPDATE org_exchange SET status='publishing' WHERE id=?",(key,))
        restored=OrganizationExchange(self.org);restored.sync(self.cid);self.assertEqual(self.count('research'),1);self.assertEqual(restored.receipt(key)['status'],'saved')

    def test_non_allowlisted_source_and_inactive_store_are_rejected(self):
        with self.assertRaises(ValueError):self.produce('commerce_live_sync',{})
        self.app.live.configure({'ozon_client_id':'654321'})
        with self.assertRaises(ValueError):self.exchange.context(self.cid)
        self.assertEqual(self.exchange.status()['receipts'],[])

if __name__=='__main__':unittest.main()
