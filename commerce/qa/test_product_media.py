"""Product browsing and versioned media production, using isolated synthetic data."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import base64
import hashlib
import sys
import tempfile
import json
import subprocess
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from service import Commerce
import test_organization as organization_fixtures
from test_creative_studio import BRIEF


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = organization_fixtures.OrganizationTests(); self.fixture.setUp()
        self.app = self.fixture.app; self.cid = self.fixture.cid

    def tearDown(self): self.fixture.tearDown()

    def test_cards_and_details_preserve_source_and_missing_values(self):
        self.fixture.prepare_cost()
        result = self.app.invoke('commerce_catalog_list', {})
        item = next(i for i in result['items'] if i['id'] == self.cid)
        self.assertIsNone(item['price'])
        self.assertEqual(item['supplier_count'], 1)
        detail = self.app.invoke('commerce_catalog_get', {'case_id': self.cid})
        self.assertEqual(detail['suppliers'][0]['purchase_cost'], 30)
        self.assertEqual(detail['suppliers'][0]['currency'], 'CNY')
        self.assertFalse(detail['independently_verified'])
        self.assertEqual(detail['images'], [])
        self.assertEqual(detail['fields'][0]['key'], 'title')
        self.assertEqual(self.app.invoke('commerce_catalog_list', {'query': 'absent-product'})['items'], [])

    def test_linked_creative_is_explicit_idempotent_and_connection_scoped(self):
        detail = self.app.invoke('commerce_catalog_get', {'case_id': self.cid})
        args = dict(case_id=self.cid, expected_source_sha256=detail['source_sha256'], idempotency_key='link')
        one = self.app.invoke('commerce_catalog_creative', args)
        two = self.app.invoke('commerce_catalog_creative', args)
        self.assertEqual(one['id'], two['id'])
        self.assertEqual(one['brief']['product_binding']['case_id'], self.cid)
        self.assertEqual(one['brief']['product']['verified_facts'], [])
        sales=self.app.invoke('commerce_media_overview',{'project_id':one['id']})['sales_context']
        self.assertEqual(sales['units'],2)
        self.assertIsNone(sales['revenue'])
        self.assertFalse(sales['sales_attribution_established'])
        self.app.live.configure({'ozon_client_id': '654321'})
        self.assertEqual(self.app.invoke('commerce_catalog_list', {})['items'], [])
        with self.assertRaisesRegex(ValueError, 'case_not_found'):
            self.app.invoke('commerce_catalog_get', {'case_id': self.cid})

    def test_research_media_links_are_bounded_and_unsafe_urls_not_rendered(self):
        data = self.fixture.research()
        data['record']['fields']['images']['original'] = 'https://example.com/item.png\nfile:///private/a.png\njavascript:alert(1)'
        self.app.organization.record(self.cid, 'research', data, 'pictures')
        detail = self.app.invoke('commerce_catalog_get', {'case_id': self.cid})
        self.assertEqual([i['url'] for i in detail['images']], ['https://example.com/item.png'])
        self.assertEqual(detail['images'][0]['origin'], 'source_link_unverified')

    def test_catalog_image_import_is_bound_to_the_selected_product(self):
        detail=self.app.catalog.get(self.cid)
        project=self.app.catalog.creative(self.cid,detail['source_sha256'],'import-project')
        source=Path(self.fixture.tmp.name)/'synthetic-source.png'
        source.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII='))
        asset=self.app.creative.register(project['id'],'product_image',source,{'source_ref':'synthetic:catalog'})
        d=self.app.catalog.get(self.cid)
        result=self.app.invoke('commerce_catalog_image_import',{'case_id':self.cid,'project_id':project['id'],
            'expected_source_sha256':d['source_sha256'],'index':0,'kind':'reference_image'})
        self.assertEqual(result['asset']['kind'],'reference_image')
        self.assertTrue(any(a['id']==result['asset']['id'] for a in self.app.creative.get(project['id'])['assets']))
        again=self.app.invoke('commerce_catalog_image_import',{'case_id':self.cid,'project_id':project['id'],
            'expected_source_sha256':d['source_sha256'],'index':0,'kind':'reference_image'})
        self.assertEqual(result['asset']['id'],again['asset']['id'])


class ProductMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.app = Commerce(self.tmp.name)
        self.p = self.app.creative.create(deepcopy(BRIEF), 'project')
        self.pid = self.p['id']
        image = Path(self.tmp.name) / 'synthetic.png'
        image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII='))
        self.asset = self.app.creative.register(self.pid, 'product_image', image, {'source_ref': 'synthetic:product'})
        ref = Path(self.tmp.name) / 'reference.png'
        ref.write_bytes(self.app.creative.asset(self.pid, self.asset['id'])[0].read_bytes())
        self.reference = self.app.creative.register(self.pid, 'reference_image', ref, {'source_ref': 'synthetic:reference'})

    def tearDown(self): self.tmp.cleanup()
    def call(self, name, **args): return self.app.invoke('commerce_media_' + name, args)

    def direction(self):
        return self.call('direction_save', project_id=self.pid, expected_revision=self.p['revision'],
                         reference_asset_ids=[self.reference['id']],
                         analysis={'layout': '单一主体，顶部卖点', 'elements': '产品、文字、场景', 'style': '简洁真实',
                                   'colors': '中性色配产品本色', 'typography': '清晰字级',
                                   'selling_points': '先看规格再看使用细节', 'shots': '场景中景与产品特写交替',
                                   'rhythm': '开头场景、细节、演示、收尾', 'adaptation': '突出自己的500毫升容量',
                                   'avoid': '不复制品牌标识，不编造体验'})

    def request(self, kind='product_main'):
        self.p = self.direction()
        return self.call('request_create', project_id=self.pid, expected_revision=self.p['revision'],
                         kind=kind, idempotency_key='request-' + kind)

    def test_direction_is_required_and_reference_claims_do_not_become_product_facts(self):
        with self.assertRaisesRegex(ValueError, 'direction_required'):
            self.call('request_create', project_id=self.pid, expected_revision='1', kind='ugc_video', idempotency_key='blocked')
        p = self.direction()
        self.assertEqual(p['brief']['product'], BRIEF['product'])
        self.assertEqual(p['brief']['design_direction']['status'], 'operator_reviewed')
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.direction()

    def test_image_and_both_video_plans_share_product_facts_and_specific_shots(self):
        req = self.request('ugc_video')
        self.assertEqual(req['status'], 'awaiting_media')
        self.assertFalse(req['external_generation_submitted'])
        roles = [s['role'] for s in req['spec']['shots']]
        self.assertIn('usage_scene', roles); self.assertIn('product_closeup', roles)
        self.assertIn('demonstration', roles)
        self.assertEqual(req['spec']['fact_ids'], ['f1'])
        self.assertIn('500', req['spec']['prompt'])
        same = self.call('request_create', project_id=self.pid, expected_revision=self.p['revision'], kind='ugc_video', idempotency_key='request-ugc_video')
        self.assertEqual(req['id'], same['id'])
        display = self.call('request_create', project_id=self.pid, expected_revision=self.p['revision'], kind='showcase_video', idempotency_key='showcase')
        self.assertEqual(display['spec']['format'], 'showcase_video')

    def test_actual_media_receipt_and_review_are_hash_and_version_bound(self):
        req = self.request()
        attached = self.call('request_attach', request_id=req['id'], asset_ids=[self.asset['id']], expected_revision=self.p['revision'])
        self.assertEqual(attached['status'], 'awaiting_review')
        reviewed = self.call('request_review', request_id=req['id'], expected_result_sha256=attached['result_sha256'], decision='approved', note='合成验收已检查产品与文字')
        self.assertEqual(reviewed['status'], 'approved')
        self.app.creative.asset(self.pid, self.asset['id'])[0].write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'asset_changed'):
            self.call('request_review', request_id=req['id'], expected_result_sha256=attached['result_sha256'], decision='approved', note='不可接受变更')

    def test_changed_product_invalidates_old_direction_and_requests(self):
        req = self.request()
        b = deepcopy(self.p['brief']); b['product']['verified_facts'][0]['text'] = '合成示例：容量600毫升'
        updated = self.app.creative.save(self.pid, b, self.p['revision'])
        self.assertNotIn('design_direction', updated['brief'])
        with self.assertRaisesRegex(ValueError, 'request_stale'):
            self.call('request_attach', request_id=req['id'], asset_ids=[self.asset['id']], expected_revision=updated['revision'])

    def test_adopted_video_script_enters_production_and_changes_invalidate_that_version(self):
        self.p=self.direction();b=deepcopy(self.p['brief'])
        b['reviewed_script']={**self.p['plan']['scripts'][0],'hook':'合成验收：看看实际使用细节',
                              'review_status':'caller_reviewed_not_independently_verified'}
        self.p=self.app.creative.save(self.pid,b,self.p['revision'],allow_reviewed=True)
        request=self.call('request_create',project_id=self.pid,expected_revision=self.p['revision'],kind='ugc_video',idempotency_key='script-video')
        self.assertEqual(request['spec']['script']['hook'],b['reviewed_script']['hook'])
        b['reviewed_script']['hook']='合成验收：另一版开头'
        self.app.creative.save(self.pid,b,self.p['revision'],allow_reviewed=True)
        self.assertTrue(self.call('request_get',request_id=request['id'])['stale'])

    def test_assets_cannot_cross_projects_and_zero_metrics_remain_unknown_ratios(self):
        req = self.request()
        p2 = self.app.creative.create(deepcopy(BRIEF), 'another')
        with self.assertRaisesRegex(ValueError, 'asset_not_found'):
            self.app.creative.asset(p2['id'],self.asset['id'])
        perf = self.call('performance_save', project_id=self.pid, payload={'period_start': '2026-11-01T00:00:00+08:00',
            'period_end': '2026-11-02T00:00:00+08:00', 'source_ref': 'synthetic:report', 'request_id': req['id'],
            'impressions': 0, 'clicks': 0, 'orders': 0}, idempotency_key='metrics')
        self.assertIsNone(perf['metrics']['ctr']); self.assertIsNone(perf['metrics']['conversion_rate'])

    def test_metrics_reject_invalid_counts_and_keep_idempotency(self):
        self.request()
        payload={'period_start': '2026-11-01T00:00:00Z', 'period_end': '2026-11-02T00:00:00Z',
                 'source_ref': 'synthetic:report', 'impressions': 100, 'clicks': 10, 'orders': 2}
        first=self.call('performance_save', project_id=self.pid, payload=payload, idempotency_key='metrics')
        self.assertEqual(first['metrics']['ctr'], .1); self.assertEqual(first['metrics']['conversion_rate'], .2)
        self.assertEqual(first['id'], self.call('performance_save', project_id=self.pid, payload=payload, idempotency_key='metrics')['id'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.call('performance_save', project_id=self.pid, payload={**payload, 'orders': 1}, idempotency_key='metrics')
        for changes in ({'clicks': 101}, {'orders': -1}, {'orders': True}, {'period_end': payload['period_start']}):
            with self.assertRaises(ValueError):
                self.call('performance_save', project_id=self.pid, payload={**payload, **changes}, idempotency_key='invalid')

    def test_periodic_review_persists_one_due_report_without_generation_or_publication(self):
        self.request()
        policy=self.call('policy_save', project_id=self.pid, expected_revision=0, enabled=True, interval_days=7)
        at=datetime(2026,11,14,tzinfo=timezone.utc).timestamp()
        # Deterministic clock: the policy may be saved on another date by CI.
        with self.app.core.db() as db: db.execute('UPDATE creative_review_policies SET next_due=?', (at-1,))
        self.app.media.tick(at=at)
        self.app.media.tick(at=at)
        result=self.call('overview', project_id=self.pid)
        self.assertEqual(len(result['reviews']),1)
        self.assertEqual(result['reviews'][0]['status'],'needs_data')
        self.assertFalse(result['reviews'][0]['generation_submitted'])
        self.assertEqual(len(result['requests']),1)
        with self.assertRaisesRegex(ValueError,'policy_conflict'):
            self.call('policy_save', project_id=self.pid, expected_revision=0, enabled=False, interval_days=7)

    def test_iteration_request_keeps_the_actual_review_reason_and_data_lineage(self):
        self.request()
        perf=self.call('performance_save',project_id=self.pid,payload={'period_start':'2026-11-01T00:00:00Z',
            'period_end':'2026-11-08T00:00:00Z','source_ref':'synthetic:metrics','impressions':1000,'clicks':30,'orders':3},idempotency_key='review-data')
        review=self.call('review_now',project_id=self.pid,idempotency_key='review-iteration')
        request=self.call('request_create',project_id=self.pid,expected_revision=self.p['revision'],kind='product_main',
                          review_id=review['id'],recommendation_index=0,idempotency_key='iterate')
        self.assertEqual(request['spec']['iteration']['review_id'],review['id'])
        self.assertIn(perf['id'],request['spec']['iteration']['performance_ids'])
        self.assertIn('点击率',request['spec']['prompt'])
        with self.assertRaises(ValueError):
            self.call('request_create',project_id=self.pid,expected_revision=self.p['revision'],kind='ugc_video',
                      review_id=review['id'],recommendation_index=0,idempotency_key='mismatch')

    def test_real_local_single_image_and_five_shot_video_receipts(self):
        req=self.request('product_main')
        job=self.call('request_execute',request_id=req['id'],expected_revision=self.p['revision'],asset_ids=[self.asset['id']])
        self.assertEqual(job['project_id'],self.pid)
        deadline=time.time()+100
        while time.time()<deadline:
            result=self.call('request_get',request_id=req['id'])
            if result['status'] not in ('queued','running'):break
            time.sleep(.1)
        self.assertEqual(result['status'],'awaiting_review',result)
        self.assertEqual(result['assets'][0]['kind'],'image_layout_draft')
        video=self.call('request_create',project_id=self.pid,expected_revision=self.p['revision'],kind='showcase_video',idempotency_key='video')
        self.call('request_execute',request_id=video['id'],expected_revision=self.p['revision'],asset_ids=[self.asset['id']]*5)
        deadline=time.time()+100
        while time.time()<deadline:
            result=self.call('request_get',request_id=video['id'])
            if result['status'] not in ('queued','running'):break
            time.sleep(.1)
        self.assertEqual(result['status'],'awaiting_review',result)
        meta=self.app.creative.asset(self.pid,result['assets'][0]['id'])[1]
        self.assertAlmostEqual(meta['media']['duration_seconds'],30,delta=.2)
        self.assertEqual(len(meta['parent_asset_ids']),5)
        self.assertFalse(meta['generated_actor_in_this_job'])


class VisionTransportTests(unittest.TestCase):
    def test_actual_subprocess_receives_owned_image_snapshot(self):
        from agent_runtime import codex_provider as provider
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);image=root/'private-original.png'
            image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRz8AAAAASUVORK5CYII='))
            cli=root/'fake.py';cli.write_text('import json,sys,pathlib\nimg=pathlib.Path(sys.argv[sys.argv.index("--image")+1])\nassert img.name=="reference-0.png"\nassert img.read_bytes().startswith(b"\\x89PNG")\njson.load(sys.stdin)\npathlib.Path("answer.json").write_text(json.dumps({"layout":"synthetic"}))\nprint(json.dumps({"type":"turn.completed"}))\n')
            with patch.object(provider,'command',return_value=[sys.executable,str(cli)]):
                result=provider.invoke_json({},lambda:False,{'model':'synthetic'},{},'synthetic',images=[image])
            self.assertEqual(result['layout'],'synthetic')

    def test_microdata_images_are_preserved_as_source_links(self):
        from market_research.collector import extract
        html='<title>Synthetic</title><article itemtype="https://schema.org/Product"><a itemprop="url" href="/catalog/1/"><span itemprop="name">Synthetic item</span></a><img itemprop="image" src="https://example.com/1.png"></article>'
        product=extract(html.encode(),'https://www.maxidom.ru/catalog/')['products'][0]
        self.assertEqual(product['images'],['https://example.com/1.png'])


if __name__ == '__main__': unittest.main()
