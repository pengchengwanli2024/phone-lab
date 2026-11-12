"""Pinned source and offline bridge acceptance; all scenario inputs are synthetic."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from sealeap_library import SkillLibrary
from sealeap_ingest import audit_script


class Skills(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.core=Core(self.root/'state.sqlite');self.lib=SkillLibrary(self.core,self.root)
    def tearDown(self):self.tmp.cleanup()
    def require_sources(self):
        if not self.lib.source_root.is_dir():
            self.skipTest('optional pinned upstream source snapshots not provisioned')
    def prepare(self,skill,data=None,key='synthetic-case'):
        self.require_sources()
        detail=self.lib.get(skill)
        self.assertTrue(detail['integrity'],'provisioned upstream source snapshot failed integrity check')
        return self.lib.prepare({'skill_id':skill,'input':detail['example_input'] if data is None else data,'synthetic':True,'idempotency_key':key})

    def test_whole_catalogue_and_individual_source_index(self):
        summary=self.lib.summary();self.assertEqual(summary['total'],797);self.assertEqual(summary['offline_adapters'],19)
        self.assertEqual(summary['nested_modes'],227)
        self.assertEqual(sum(summary['platforms'].values()),797)
        self.assertEqual({s['id']:s['skills'] for s in summary['sources']},{'ecommerce':195,'amazon':602})
        self.assertEqual(summary['execution'].get('live_verified',0),0)
        self.assertTrue(all(e['files'] and e['sections'] and len(e['source_sha256'])==64 for e in self.lib.entries.values()))

    def test_search_and_pagination_filters(self):
        first=self.lib.search({'repo':'amazon','limit':20});self.assertEqual(first['total'],602);self.assertEqual(len(first['items']),20)
        second=self.lib.search({'repo':'amazon','offset':20,'limit':20});self.assertTrue(set(e['id'] for e in first['items']).isdisjoint(e['id'] for e in second['items']))
        tiktok=self.lib.search({'repo':'ecommerce','platform':'tiktokshop'});self.assertEqual(tiktok['total'],22)
        self.assertGreater(self.lib.search({'query':'ACOS'})['total'],0)
        legacy=self.lib.search({'query':'sealeap-athena-temu-eu-product'});self.assertGreater(legacy['total'],0)
        self.assertEqual(legacy['items'][0]['platform'],'temu')
        for value in [True,-1,'20',10001]:
            with self.assertRaisesRegex(ValueError,'pagination'):self.lib.search({'offset':value})

    def test_all_nineteen_real_examples_and_guarded_listing(self):
        self.require_sources()
        for e in self.lib.entries.values():
            if not e['adapter']:continue
            with self.subTest(skill=e['id']):
                case=self.prepare(e['id'],key=e['id']);result=self.lib.execute(case['id'])
                self.assertEqual(result['status'],'hold' if e['id']=='sealeap-amazon-listing-optimizer' else 'completed',result['output'])
                self.assertFalse(result['marketplace_writes']);self.assertFalse(result['output']['external_requests_submitted'])
                self.assertTrue(result['synthetic']);self.assertEqual(result['output']['script_sha256'],e['adapter']['script_sha256']);self.assertEqual(result['output']['adapter_id'],e['adapter']['id'])
        self.assertEqual(self.lib.summary()['execution'].get('local_verified'),18)
        self.assertEqual(self.lib.summary()['execution'].get('live_verified',0),0)

    def test_acos_recalculation_and_zero_denominator(self):
        skill='sealeap-amazon-acos-diagnostics';c=self.prepare(skill);r=self.lib.execute(c['id'])
        derived=r['output']['result']['derived'];self.assertEqual(derived['acos_pct'],24.0);self.assertEqual(derived['tacos_pct'],12.0)
        detail=self.lib.get(skill);data=copy.deepcopy(detail['example_input']);data['metrics']['ad_sales']=0
        c=self.prepare(skill,data,key='zero');r=self.lib.execute(c['id']);self.assertIsNone(r['output']['result']['derived']['acos_pct'])

    def test_tiktok_cohorts_fixed_costs_and_commodity_facts(self):
        c=self.prepare('sealeap-tiktokshop-unit-economics');r=self.lib.execute(c['id']);d=r['output']['result']['summary']
        self.assertEqual(d['orders'],100);self.assertEqual(d['commission'],'468.00');self.assertEqual(d['ad_spend'],'240.00');self.assertEqual(d['campaign_costs'],'200.00');self.assertEqual(d['contribution'],'1092.00')

    def test_missing_data_and_failed_input_never_become_verified(self):
        skill='sealeap-tiktokshop-unit-economics';c=self.prepare(skill,{},'empty');self.assertEqual(c['status'],'needs_inputs');self.assertEqual(self.lib.execute(c['id'])['status'],'needs_inputs')
        data=self.lib.get(skill)['example_input'];data.pop('unit_costs');c=self.prepare(skill,data,'missing');r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold')
        self.assertEqual(self.lib.get(skill)['coverage']['execution'],'adapter_ready')

    def test_idempotency_replay_and_no_automatic_reexecution(self):
        skill='sealeap-amazon-acos-diagnostics';c=self.prepare(skill);self.assertEqual(c['id'],self.prepare(skill)['id'])
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.prepare(skill,{},'synthetic-case')
        result=self.lib.execute(c['id']);self.assertEqual(result,self.lib.execute(c['id']))
        with self.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM sealeap_receipts').fetchone()[0],1)

    def test_unmapped_workflow_produces_guidance_not_fictional_result(self):
        e=next(e for e in self.lib.entries.values() if not e['adapter'])
        c=self.prepare(e['id'],{});self.assertEqual(c['status'],'guidance_ready');self.assertEqual(self.lib.execute(c['id']),c)
        self.assertTrue(c['output']['workflow']);self.assertTrue(c['output']['related_tools_are_partial_analogues'])

    def test_reference_traversal_and_content_tamper_rejected(self):
        self.require_sources()
        e=self.lib.entry('sealeap-amazon-acos-diagnostics')
        with self.assertRaisesRegex(ValueError,'not_registered'):self.lib.read(e['id'],'../../config.json')
        old=self.lib.source_root;self.lib.source_root=self.root/'sources'
        base=self.lib.source_root/e['repo']/Path(e['path']).parent;base.mkdir(parents=True)
        for file in e['files']:
            target=base/file['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(old/e['repo']/Path(e['path']).parent/file['path'],target)
        self.assertTrue(self.lib.verify(e));(base/'SKILL.md').write_text('changed')
        self.assertFalse(self.lib.verify(e));self.assertEqual(self.lib.get(e['id'])['coverage']['execution'],'unmapped')
        self.assertEqual(self.lib.search({'query':e['id']})['items'][0]['coverage']['execution'],'unmapped')
        with self.assertRaisesRegex(ValueError,'integrity'):self.lib.prepare({'skill_id':e['id'],'input':{},'idempotency_key':'tampered'})

    def test_unreviewed_script_imports_are_rejected(self):
        for code in ['import urllib.request','import subprocess','eval("1")','from os import environ','from pathlib import Path\nPath("output").write_text("x")']:
            with self.assertRaises(ValueError):audit_script(code)

    def test_restart_keeps_interruption_and_receipts_scoped(self):
        c=self.prepare('sealeap-amazon-acos-diagnostics')
        with self.core.db() as db:db.execute("UPDATE sealeap_cases SET status='running' WHERE id=?",(c['id'],))
        reopened=SkillLibrary(self.core,self.root);self.assertEqual(reopened.case(c['id'])['status'],'interrupted');self.assertEqual(reopened.execute(c['id'])['status'],'interrupted')

    def test_export_complete_rows_and_provenance(self):
        exported=self.lib.export();self.assertEqual(len(exported['rows']),797)
        self.assertTrue(all(e['source_sha256'] and e['commit'] and e['source_url'] for e in exported['rows']))
        csv=self.lib.export('csv');self.assertEqual(csv['rows'],797);self.assertNotIn(str(self.root),csv['content'])

    def test_walmart_wrong_destination_and_reused_label_hold(self):
        self.require_sources()
        skill='sealeap-walmart-wfs-box-reconciliation';data=self.lib.get(skill)['example_input'];data['boxes'][0]['destination']='SYN-WRONG'
        c=self.prepare(skill,data);r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold');self.assertIn('WRONG_DESTINATION',[e['code'] for e in r['output']['result']['errors']])

    def test_apollo_ads_evidence_and_economics(self):
        skill='sealeap-apollo-ad-planning';c=self.prepare(skill);r=self.lib.execute(c['id']);d=r['output']['result']
        self.assertEqual(d['contribution_before_ads'],22);self.assertEqual(d['target_cpa'],8);self.assertAlmostEqual(d['max_cpc'],.8)
        data=self.lib.get(skill)['example_input'];data['evidence']=[];c=self.prepare(skill,data,'missing-evidence');r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold');self.assertTrue(r['output']['result']['gaps'])

    def test_running_discount_reduction_is_held(self):
        self.require_sources()
        skill='sealeap-apollo-price-discounts';data=self.lib.get(skill)['example_input'];data['targets'][0]['target_percent']=5
        c=self.prepare(skill,data);r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold');self.assertFalse(r['output']['result']['submitted'])

    def test_title_policy_missing_and_utf16_scope(self):
        self.require_sources()
        skill='sealeap-apollo-batch-title-rewrite';data=self.lib.get(skill)['example_input'];data['policy']['verified']=False
        c=self.prepare(skill,data);r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold');self.assertEqual(r['output']['result']['counts']['HOLD'],1)
        data=self.lib.get(skill)['example_input'];data['policy'].update(count_method='utf16',title_max=2);data['rows'][0]['title']='😀x'
        c=self.prepare(skill,data,'utf16');r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold');self.assertEqual(r['output']['result']['rows'][0]['title_characters'],3)

    def test_snapshot_identity_and_incomparable_units(self):
        skill='sealeap-apollo-competitor-monitor';c=self.prepare(skill);r=self.lib.execute(c['id']);self.assertEqual(r['output']['result']['comparisons'][0]['changes'][0]['delta'],-2)
        data=self.lib.get(skill)['example_input'];data['records'][1]['metrics']['price']['unit']='EUR'
        c=self.prepare(skill,data,'different-unit');r=self.lib.execute(c['id']);d=r['output']['result']['comparisons'][0]['changes'][0];self.assertFalse(d['comparable']);self.assertIsNone(d['delta'])
        data=self.lib.get(skill)['example_input'];data['records'][1]['captured_at']=data['records'][0]['captured_at'];c=self.prepare(skill,data,'conflicting-identity');self.assertEqual(self.lib.execute(c['id'])['status'],'failed')

    def test_budget_and_historical_insight_scopes(self):
        self.require_sources()
        skill='sealeap-amazon-ca-apparel-ads';data=self.lib.get(skill)['example_input'];data['allocation']['sp_auto']=19
        c=self.prepare(skill,data);r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold');self.assertEqual(r['output']['result']['total_pct'],99)
        c=self.prepare('sealeap-amazon-prime-day-planning',key='history');r=self.lib.execute(c['id']);self.assertEqual(r['output']['result']['historical_reference_period'],'2025');self.assertFalse(r['output']['result']['current_policy_or_performance_verified'])

    def test_mpstats_estimate_staleness_and_missing_days(self):
        skill='sealeap-ozon-mpstats-data-audit';c=self.prepare(skill);r=self.lib.execute(c['id']);d=r['output']['result'];self.assertEqual(d['estimated_orders'],9);self.assertEqual(d['metric_kind'],'ESTIMATE');self.assertFalse(d['api_contacted'])
        data=self.lib.get(skill)['example_input'];data['as_of']='2026-11-11';c=self.prepare(skill,data,'stale');r=self.lib.execute(c['id']);self.assertEqual(r['status'],'hold');self.assertIn('stale_capture',r['output']['result']['errors'])

    def test_mode_preparation_is_versioned_and_does_not_grant_account_access(self):
        self.require_sources()
        parent=self.lib.entry('sealeap-athena-1688-sourcing-research');m=parent['subcapabilities'][0];args=dict(skill_id=parent['id'],mode_id=m['name'],input={},idempotency_key='mode')
        c=self.lib.prepare(args);plan=c['output']['mode_plan'];self.assertEqual(c['mode_id'],m['name']);self.assertTrue(plan['missing_fields_across_routes']);self.assertTrue(plan['unregistered_tools']);self.assertFalse(plan['external_requests_submitted'])
        self.assertTrue(c['output']['mode_workflow']['content']);self.assertEqual(plan['account_entitlement'],'not_verified')
        with self.assertRaisesRegex(ValueError,'idempotency_conflict'):self.lib.prepare(dict(args,mode_id=parent['subcapabilities'][1]['name']))
        with self.assertRaisesRegex(ValueError,'mode_not_in_skill'):self.lib.prepare(dict(args,mode_id='sealeap-athena-temu-eu-product',idempotency_key='wrong-mode'))
        fields={name:'SYNTHETIC_FIELD' for cap in m['capabilities'] for name in cap.get('required_fields',[])};tool=m['capabilities'][0]['tool'];self.lib.tool_catalog=lambda:[(tool,'',{})]
        c=self.lib.prepare(dict(args,input=fields,idempotency_key='mode-with-fields'));plan=c['output']['mode_plan'];self.assertFalse(plan['missing_fields_across_routes']);self.assertTrue(plan['contracts'][0]['registered_in_workbench']);self.assertEqual(plan['account_entitlement'],'not_verified')

    def test_adapter_contract_change_withdraws_prepared_execution(self):
        c=self.prepare('sealeap-apollo-ad-planning');e=self.lib.entries[c['skill_id']];e['adapter']['id']='changed'
        with self.assertRaisesRegex(ValueError,'adapter_changed'):self.lib.execute(c['id'])


if __name__=='__main__':unittest.main()
