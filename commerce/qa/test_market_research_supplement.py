"""Synthetic intake exercises real source versions, queue, artifacts and views."""
from datetime import datetime, timezone, timedelta
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
from test_market_research import HTML
from market_research.collector import extract


class SupplementFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.tmp.name)
        thread = self.app.copilot.open({'module': 'research', 'demo': False, 'market': 'RU'}, 'thread')
        sent = self.app.copilot.send(thread['id'], '请调研俄罗斯厨房收纳，采集资料分析并保存候选商品', thread['context_sha256'], 'send')
        self.thread_id, self.task_id = thread['id'], sent['research_job']['task_id']
        self.execute_research()
        self.before = self.app.market_research.get(self.task_id)

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.tmp.cleanup()

    def capture(self, url, directory, cancelled):
        if 'maxidom' not in url:
            raise ValueError('market_research_source_timeout')
        return {**extract(HTML.encode(), url), 'captured_at': datetime.now(timezone.utc).isoformat()}

    def generate(self, phase, payload, cancelled, route):
        if phase == 'planning':
            data = {'query_ru': 'органайзер для кухни', 'questions': []}
        else:
            refs = list(payload['products'])
            ref = refs[0]
            sid = payload['products'][ref]['source_id']
            data = {'summary': '供给样本待核验；价格为历史公开快照，未验证需求和利润。',
                    'findings': ['观察到公开供给。'], 'limitations': ['未独立核实，非实时价格，包装成本未知。'],
                    'evidence_refs': [sid], 'candidates': [{'product_ref': ref, 'reason': '待进一步核验。', 'source_ids': [sid]}]}
        return {'data': data, 'provider': 'synthetic', 'model': 'fixture'}

    def execute_research(self):
        with patch('market_research.collector.capture', side_effect=self.capture), patch('market_research.model.generate', side_effect=self.generate):
            self.app.agent_runtime.run_once()

    def source(self, **changes):
        now = datetime.now(timezone.utc)
        url = 'https://www.ozon.ru/product/synthetic-kitchen-organizer-123456789/'
        notes = {'kind': 'product_snapshot', 'url': url, 'crawl_age_reported': '2 days ago',
                 'facts': {'product': 'Synthetic shelf', 'snapshot_price_rub_other_banks': 998},
                 'limits': ['Synthetic fixture; not a live price.']}
        doc = {'schema': 'commerce-business-source-v1', 'kind': 'facts',
               'scope': {'platform': 'ozon', 'store_ref': None, 'subject_ref': self.task_id},
               'label': 'Synthetic source fixture', 'origin_ref': url,
               'observed_at': now.isoformat(), 'valid_until': (now + timedelta(hours=1)).isoformat(),
               'synthetic': False, 'records': [{'key': k, 'value': v} for k, v in {
                   'acquisition': 'remote_indexed_snapshot', 'local_live_capture': False,
                   'review_status': 'operator_import_unverified', 'source_notes': notes}.items()]}
        doc.update(changes)
        result = self.app.business.import_source(doc, 'source-' + str(len(self.app.business.listing(False)['sources'])))
        return {'id': result['source_id'], 'version': result['version'], 'sha256': result['sha256']}, doc

    def supplement(self, refs=None, **changes):
        args = {'task_id': self.task_id, 'expected_revision': self.before['revision'],
                'source_refs': refs or [self.source()[0]], 'idempotency_key': 'supplement'}
        args.update(changes)
        return self.app.invoke('commerce_market_research_supplement', args, 'test')

    def test_same_task_new_evidence_analysis_preserves_old_artifact_and_run(self):
        before = copy.deepcopy(self.before)
        old = self.app.organization.artifact(before['candidates'][0]['case_id'], 'research')
        source, _ = self.source()
        queued = self.supplement([source])
        self.assertEqual(queued['task_id'], before['task_id'])
        self.assertNotEqual(queued['run_id'], before['run_id'])
        self.assertEqual(queued['source_count'], 1)
        self.assertEqual(queued['supplemental_source_count'], 1)
        with patch('market_research.collector.capture', side_effect=AssertionError('must not refetch')):
            with patch('market_research.model.generate', side_effect=self.generate):
                self.app.agent_runtime.run_once()
        after = self.app.market_research.get(self.task_id)
        self.assertEqual(after['status'], 'partial')
        self.assertEqual(len(after['candidates']), 2)
        self.assertEqual(after['report_history'][0]['report'], before['report'])
        self.assertEqual(after['candidates'][0]['research_run_id'], before['run_id'])
        self.assertEqual(self.app.organization.artifact(old['case_id'] if 'case_id' in old else before['candidates'][0]['case_id'], 'research'), old)
        new = after['candidates'][1]
        artifact = self.app.organization.artifact(new['case_id'], 'research')
        self.assertIn('笔记', artifact['payload']['record']['evidence_note'])
        self.assertNotIn('原始页SHA256', artifact['payload']['record']['evidence_note'])
        self.assertEqual(self.app.core.invoke('commerce_task_list', {})['tasks'][0]['id'], self.task_id)
        view = self.app.product_workspace.get(before['candidates'][0]['case_id'], research_task_id=self.task_id)
        self.assertEqual(view['research_context']['run_id'], before['run_id'])

    def test_idempotency_does_not_enqueue_twice_and_different_refs_conflict(self):
        ref, _ = self.source()
        first = self.supplement([ref])
        second = self.supplement([ref])
        self.assertEqual(first['run_id'], second['run_id'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.supplement([dict(ref, sha256='0' * 64)])

    def test_rejects_wrong_scope_hash_and_revision_without_queueing(self):
        ref, _ = self.source(scope={'platform': 'ozon', 'store_ref': None, 'subject_ref': 'another-task'})
        with self.assertRaisesRegex(ValueError, 'market_research_supplement'):
            self.supplement([ref])
        ref, _ = self.source()
        with self.assertRaisesRegex(ValueError, 'market_research_supplement'):
            self.supplement([dict(ref, sha256='0' * 64)])
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.supplement([ref], expected_revision=self.before['revision'] - 1)
        self.assertEqual(self.app.market_research.get(self.task_id)['run_id'], self.before['run_id'])
