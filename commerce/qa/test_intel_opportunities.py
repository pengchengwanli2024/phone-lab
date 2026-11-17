"""Synthetic archive provenance and bounded headless opportunity contracts."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commerce_core import Core
from intelligence import Intelligence


class Opportunities(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('intel_opportunities'), 'headless opportunity contracts are not implemented')
        from intel_opportunities import IntelOpportunities
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.core = Core(Path(self.tmp.name) / 'db.sqlite')
        self.intel = Intelligence(self.core)
        self.app = IntelOpportunities(SimpleNamespace(intelligence=self.intel))
        self.now = time.time()
        self.ids = []
        with self.core.db() as db:
            for source in ('wto', 'usgs'):
                db.execute('INSERT INTO intel_sources VALUES (?,?)', (source, json.dumps({'status': 'ok', 'last_success': self.now})))
                for index in range(12):
                    ident = (('a' if source == 'wto' else 'b') + str(index).zfill(23))
                    row = {'id': ident, 'source': source, 'source_key': str(index), 'title': 'Synthetic public news ' + str(index),
                           'url': 'https://example.org/synthetic/' + source + '/' + str(index), 'published': self.now - index,
                           'category': 'trade' if source == 'wto' else 'earthquake', 'country': None, 'country_code': None,
                           'location': None, 'publisher_alert': None, 'collected_at': __import__('datetime').datetime.fromtimestamp(self.now, __import__('datetime').timezone.utc).isoformat(),
                           'verification': 'publisher_report_not_independently_verified'}
                    self.intel.store.archive(db, row, self.now);self.ids.append(ident)

    def analysis(self, packet):
        return {'summary': '仅为合成新闻产生的待查假设。', 'opportunities': [
            {'hypothesis': '需要补充目标市场需求证据。', 'evidence_ids': [packet['items'][0]['id']],
             'confidence': 'low', 'status': 'needs_evidence', 'next_checks': ['查询同市场真实搜索与成交数据。']}],
            'platform_hot_terms': {'status': 'unknown', 'terms': None}}

    def test_packet_uses_archive_without_fetching_balances_sources_and_bounds_output(self):
        packet = self.app.packet(8)
        self.assertEqual(len(packet['items']), 8)
        self.assertEqual({r['source'] for r in packet['items']}, {'wto', 'usgs'})
        self.assertTrue(all(r['url'].startswith('https://example.org/synthetic/') and len(r['record_sha256']) == 64 for r in packet['items']))
        self.assertEqual(packet['platform_hot_terms'], {'status': 'unknown', 'terms': None})
        self.assertLess(len(json.dumps(packet).encode()), 16000)
        self.assertEqual(self.core.invoke('commerce_task_list', {})['tasks'], [])

    def test_validated_analysis_preserves_exact_source_packet_and_no_execution_grants(self):
        packet = self.app.packet(8);result = self.app.validate(packet, self.analysis(packet))
        self.assertEqual(result['packet_sha256'], packet['packet_sha256'])
        self.assertEqual(result['verification'], 'news_derived_hypotheses_needs_evidence')
        self.assertFalse(result['external_execution_allowed'])
        self.assertEqual(result['platform_hot_terms']['status'], 'unknown')

    def test_forged_packet_or_unknown_reference_is_rejected(self):
        packet = self.app.packet(8);bad = copy.deepcopy(packet);bad['items'][0]['title'] = 'Forged'
        with self.assertRaises(ValueError):self.app.validate(bad, self.analysis(packet))
        analysis = self.analysis(packet);analysis['opportunities'][0]['evidence_ids'] = ['missing']
        with self.assertRaises(ValueError):self.app.validate(packet, analysis)

    def test_rehashed_caller_metadata_cannot_be_reported_as_verified_platform_data(self):
        from intel_opportunities import digest
        packet = self.app.packet(8);packet['coverage']['status'] = 'verified_platform_hot_terms'
        packet['packet_sha256'] = digest({k: v for k, v in packet.items() if k != 'packet_sha256'})
        with self.assertRaises(ValueError):self.app.validate(packet, self.analysis(packet))

    def test_revised_original_and_expired_packet_are_not_replayed_as_current(self):
        packet = self.app.packet(8)
        with self.core.db() as db:db.execute('DELETE FROM intel_archive WHERE id=?', (packet['items'][0]['id'],))
        with self.assertRaises(ValueError):self.app.validate(packet, self.analysis(packet))
        from unittest.mock import patch
        packet = self.app.packet(8)
        with patch('intel_opportunities.time.time', return_value=time.time() + 3700):
            with self.assertRaises(ValueError):self.app.validate(packet, self.analysis(packet))

    def test_stale_or_missing_sources_do_not_invent_zero_search_volume(self):
        with self.core.db() as db:
            db.execute('UPDATE intel_sources SET state=?', (json.dumps({'status': 'ok', 'last_success': self.now - 25000}),))
        packet = self.app.packet(8)
        self.assertEqual(packet['items'], [])
        self.assertEqual(packet['platform_hot_terms'], {'status': 'unknown', 'terms': None})
        self.assertEqual(packet['coverage']['status'], 'needs_fresh_sources')

    def test_high_confidence_platform_ranking_and_spending_fields_are_rejected(self):
        packet = self.app.packet(8)
        for key, value in [('confidence', 'high'), ('rank', 1), ('search_volume', 100), ('purchase', True)]:
            analysis = self.analysis(packet);analysis['opportunities'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):self.app.validate(packet, analysis)
        analysis = self.analysis(packet);analysis['platform_hot_terms'] = {'status': 'known', 'terms': ['fabricated']}
        with self.assertRaises(ValueError):self.app.validate(packet, analysis)

    def test_empty_evidence_requires_empty_hypotheses_and_bad_types_are_rejected(self):
        for value in (True, 0, 9, '8'):
            with self.subTest(limit=value), self.assertRaises(ValueError):self.app.packet(value)
        with self.core.db() as db:db.execute('DELETE FROM intel_archive')
        packet = self.app.packet(8)
        analysis = {'summary': '没有可用的合成新鲜证据。', 'opportunities': [], 'platform_hot_terms': {'status': 'unknown', 'terms': None}}
        self.assertEqual(self.app.validate(packet, analysis)['opportunities'], [])

    def test_headless_daily_template_uses_original_tasks_and_does_not_replay_unknown(self):
        from unittest.mock import patch
        from extension_runtime import ExtensionRuntime
        from extension_runtime.contracts import SAFE_BUILTINS
        template_path = Path(__file__).resolve().parents[1] / 'examples/intel-opportunities-daily.json'
        self.assertTrue(template_path.is_file(), 'headless daily template is not implemented')
        template = json.loads(template_path.read_text())
        route = {'provider': 'compatible', 'profile_id': 'synthetic-local', 'profile_revision': '1',
                 'engine': 'llama_cpp', 'model': 'synthetic-local', 'base_url': 'http://127.0.0.1:1/v1', 'json_mode': True}
        service = SimpleNamespace(core=self.core, state=Path(self.tmp.name),
            models=SimpleNamespace(snapshot=lambda *a, **k: route, runtime_route=lambda value: value),
            invoke=lambda name, args, client='local': self.app.invoke(name, args))
        with patch.dict(SAFE_BUILTINS, {'commerce_intel_opportunity_packet': None, 'commerce_intel_opportunity_validate': None}):
            runtime = ExtensionRuntime(service);self.addCleanup(runtime.stop)
            def drain(value):
                for _ in range(12):
                    runtime._process(value['id']);value = runtime.run_get(value['id'])
                    if value['status'] not in ('queued', 'running'):return value
                self.fail('bounded workflow did not settle')
            def ready(definition):
                ext = runtime.save(definition)
                run = runtime.launch(ext['id'], idempotency_key='test-' + ext['id'], test=True)
                self.assertEqual(drain(run)['status'], 'succeeded')
                return runtime.enable(ext['id'], ext['version'], True)
            analyst = copy.deepcopy(template['analyst']);analyst['spec']['model_id'] = 'synthetic-local'
            analyst = ready(analyst)
            workflow = copy.deepcopy(template['workflow']);workflow['spec']['steps'][1]['uses']['extension_id'] = analyst['id']
            workflow = ready(workflow)
            schedule = copy.deepcopy(template['schedule']);schedule['extension_id'] = workflow['id']
            schedule = runtime.schedule_save(schedule);schedule = runtime.schedule_enable(schedule['id'], schedule['revision'], True)
            calls = []
            def model(payload, cancelled, model_route, instructions, output_schema=None):
                calls.append(model_route['provider'])
                return {'action': 'finish', 'output': self.analysis(payload['input']['packet'])}
            with patch.object(runtime, '_model', side_effect=model):
                runtime._schedule_tick(self.now);runtime._schedule_tick(self.now)
                runs = [r for r in runtime.invoke('commerce_extension_run_list', {})['runs'] if not r['test']]
                self.assertEqual(len(runs), 1);result = drain(runs[0])
                self.assertEqual(result['status'], 'succeeded')
                self.assertEqual(result['output']['result']['verification'], 'news_derived_hypotheses_needs_evidence')
                self.assertEqual(calls, ['compatible'])
                self.assertEqual(self.core.invoke('commerce_task_get', {'task_id': result['task_id']})['status'], 'completed')
            with patch.object(runtime, '_model', side_effect=ValueError('agent_provider_outcome_unknown')):
                runtime._schedule_tick(self.now + 86400)
                run = next(r for r in runtime.invoke('commerce_extension_run_list', {})['runs'] if not r['test'] and r['id'] != result['id'])
                unknown = drain(run);self.assertEqual(unknown['status'], 'unknown')
                runtime.recover();runtime._schedule_tick(self.now + 86400)
                self.assertEqual(len([r for r in runtime.invoke('commerce_extension_run_list', {})['runs'] if not r['test']]), 2)
                with self.assertRaises(ValueError):runtime.resume(run['id'])
            with self.core.db() as db:db.execute('DELETE FROM intel_archive')
            with patch.object(runtime, '_model', side_effect=AssertionError('empty evidence must not invoke a model')):
                runtime._schedule_tick(self.now + 172800)
                latest = next(r for r in runtime.invoke('commerce_extension_run_list', {})['runs'] if not r['test'] and r['id'] not in (result['id'], run['id']))
                empty = drain(latest);self.assertEqual(empty['status'], 'succeeded')
                self.assertEqual(empty['output']['packet']['coverage']['status'], 'needs_fresh_sources')
                self.assertEqual(empty['output']['result']['status'], 'skipped')
                self.assertEqual(empty['usage']['model_calls'], 0)


if __name__ == '__main__':unittest.main()
