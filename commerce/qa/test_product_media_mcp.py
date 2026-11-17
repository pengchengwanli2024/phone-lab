"""Actual three-client MCP discovery and shared product/media state."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import test_paos_mcp as transport

ROOT=Path(__file__).resolve().parents[1]


class ProductMediaMCP(unittest.TestCase):
    call=classmethod(transport.AdoptionMCP.call.__func__)
    mcp=transport.AdoptionMCP.mcp
    rpc=transport.AdoptionMCP.rpc

    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.state=Path(cls.tmp.name)
        cls.token='synthetic-product-media-mcp';(cls.state/'auth.token').write_text(cls.token)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));cls.port=sock.getsockname()[1]
        cls.env={**os.environ,'COMMERCE_STATE':str(cls.state),'COMMERCE_PORT':str(cls.port)}
        cls.process=subprocess.Popen([sys.executable,str(ROOT/'qa/fixture_product_media.py')],env=cls.env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(150):
            try:
                if cls.call('commerce_catalog_list',{})['items']:
                    cls.fixture=json.loads((cls.state/'product-media-fixture.json').read_text());break
            except (OSError,ValueError,FileNotFoundError):pass
            time.sleep(.05)
        else:raise AssertionError('isolated product media server unavailable')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=10);cls.process.stderr.close();cls.tmp.cleanup()

    def test_image_options_reach_same_request_through_all_three_clients(self):
        pid=self.fixture['project_id'];project=self.call('commerce_creative_get',{'project_id':pid})
        project=self.call('commerce_media_direction_save',{'project_id':pid,'expected_revision':project['revision'],
            'reference_asset_ids':[self.fixture['reference_id']],
            'analysis':{k:'Synthetic reviewed design reference, not product evidence.' for k in
                ('layout','elements','style','colors','typography','selling_points','shots','rhythm','adaptation','avoid')}})
        request_id=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                self.assertIn('image_options',tools['commerce_media_request_create']['inputSchema']['properties'])
                result=self.rpc(process,'tools/call',{'name':'commerce_media_request_create','arguments':{
                    'project_id':pid,'expected_revision':project['revision'],'kind':'product_main',
                    'idempotency_key':'shared-platform-image','image_options':{'profile_id':'ozon_ru','set_size':6,'label':'Synthetic main'}}})['result']
                self.assertFalse(result.get('isError'),str(result));request=result['structuredContent']
                if request_id is None:request_id=request['id']
                self.assertEqual(request['id'],request_id)
                self.assertEqual(request['spec']['image_delivery']['aspect_ratio'],'3:4')
                self.assertFalse(request['external_generation_submitted'])

    def test_preflight_is_read_only_on_all_three_actual_mcp_clients(self):
        pid=self.fixture['project_id'];p=self.call('commerce_creative_get',{'project_id':pid})
        p=self.call('commerce_media_direction_save',{'project_id':pid,'expected_revision':p['revision'],
            'reference_asset_ids':[self.fixture['reference_id']],
            'analysis':{k:'Synthetic reviewed design.' for k in
                ('layout','elements','style','colors','typography','selling_points','shots','rhythm','adaptation','avoid')}})
        request=self.call('commerce_media_request_create',{'project_id':pid,'expected_revision':p['revision'],
            'kind':'showcase_video','idempotency_key':'preflight-mcp'})
        before=self.call('commerce_creative_get',{'project_id':pid})
        reports=[]
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                descriptor=next(t for t in self.rpc(process,'tools/list',{})['result']['tools'] if t['name']=='commerce_media_request_preflight')
                self.assertTrue(descriptor['annotations']['readOnlyHint'])
                self.assertFalse(descriptor['annotations']['openWorldHint'])
                result=self.rpc(process,'tools/call',{'name':'commerce_media_request_preflight','arguments':{
                    'request_id':request['id'],'expected_revision':p['revision'],'asset_ids':[self.fixture['asset_id']]*5}})['result']
                self.assertFalse(result.get('isError'),result)
                report=result['structuredContent'];reports.append(report)
                self.assertTrue(report['can_render']);self.assertEqual(report['summary']['still_duration_ms'],30000)
                self.assertIsNone(report['semantic_motion_verified'])
        self.assertEqual(reports[0],reports[1]);self.assertEqual(reports[1],reports[2])
        self.assertEqual(self.call('commerce_creative_get',{'project_id':pid}),before)

    def test_three_clients_share_catalog_and_media_effects_without_duplicate_writes(self):
        pid=self.fixture['project_id'];metric_id=None
        for client in ('codex','hermes','harness'):
            with self.subTest(client=client),self.mcp(client) as process:
                tools={t['name']:t for t in self.rpc(process,'tools/list',{})['result']['tools']}
                for name in ('commerce_catalog_list','commerce_catalog_get','commerce_media_overview','commerce_media_request_get'):
                    self.assertTrue(tools[name]['annotations']['readOnlyHint'])
                self.assertTrue(tools['commerce_creative_design_analyze']['annotations']['openWorldHint'])
                self.assertFalse(tools['commerce_media_request_execute']['annotations']['readOnlyHint'])
                def call(name,args):
                    result=self.rpc(process,'tools/call',{'name':name,'arguments':args})['result']
                    self.assertFalse(result.get('isError'),str(result));return result['structuredContent']
                case=call('commerce_catalog_get',{'case_id':self.fixture['case_id']})
                self.assertGreater(len(case['images']),0)
                overview=call('commerce_media_overview',{'project_id':pid})
                self.assertIn('ugc_video',overview['formats']);self.assertIn('showcase_video',overview['formats'])
                metric=call('commerce_media_performance_save',{'project_id':pid,'payload':{'period_start':'2026-11-01T00:00:00Z',
                    'period_end':'2026-11-08T00:00:00Z','source_ref':'synthetic:mcp-performance','impressions':200,'clicks':10},'idempotency_key':'same-effect-record'})
                if metric_id is None:metric_id=metric['id']
                self.assertEqual(metric['id'],metric_id)
                denied=self.rpc(process,'tools/call',{'name':'commerce_catalog_get','arguments':{'case_id':'not-selected-scope'}})['result']
                self.assertTrue(denied['isError'])
        self.assertEqual(len(self.call('commerce_media_overview',{'project_id':pid})['performance']),1)


if __name__=='__main__':unittest.main()
