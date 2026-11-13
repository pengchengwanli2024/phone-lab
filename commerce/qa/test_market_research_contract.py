"""Shared research task boundaries, independently verified through public APIs.

Fixtures are private, synthetic, and never call a model or the network. Live
three-host collection and handoff acceptance is recorded separately.
"""
from datetime import datetime
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce, TOOLS
from market_research.collector import extract
from response_links import with_workspace_link
from test_market_research import HTML as SYNTHETIC_HTML


CLIENTS = ('harness', 'hermes', 'codex')
RESEARCH_TOOLS = {
    'commerce_market_research_list', 'commerce_market_research_get',
    'commerce_market_research_cancel', 'commerce_market_research_resume',
}
STATUSES = {
    'queued', 'running', 'awaiting_input', 'completed', 'partial', 'failed',
    'unknown', 'interrupted', 'cancelling', 'cancelled',
}
PHASES = {'planning', 'collecting', 'analyzing', 'saving', 'finished'}


class MarketResearchContract(unittest.TestCase):
    def setUp(self):
        self.private = tempfile.TemporaryDirectory()
        self.app = Commerce(self.private.name)
        self.executed = Counter()

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.private.cleanup()

    def invoke(self, tool, arguments=None, client='codex'):
        return self.app.invoke(tool, arguments or {}, client)

    def task_count(self):
        with self.app.core.db() as db:
            return db.execute('SELECT count(*) FROM tasks').fetchone()[0]

    def ordinary_task(self):
        return self.invoke('commerce_task_create', {
            'kind': 'analysis', 'input': {'title': 'Synthetic unrelated task', 'demo': True},
            'idempotency_key': 'synthetic-contract-unrelated-task',
        })

    def send_research(self, client='harness', key='contract-research'):
        thread = self.invoke('commerce_copilot_open', {
            'context': {'module': 'research', 'market': 'RU', 'demo': False},
            'idempotency_key': key + ':thread',
        }, client)
        return self.invoke('commerce_copilot_send', {
            'thread_id': thread['id'], 'message': '请调研俄罗斯厨房收纳，采集真实资料并保存候选商品',
            'context_sha256': thread['context_sha256'], 'idempotency_key': key + ':send',
        }, client)

    def capture(self, url, directory, cancelled):
        self.executed['capture'] += 1
        if 'maxidom' not in url:
            raise ValueError('market_research_http_403')
        return {**extract(SYNTHETIC_HTML.encode(), url),
                'captured_at': datetime.now().astimezone().isoformat()}

    def generate(self, phase, payload, cancelled, route):
        self.executed[phase] += 1
        if phase == 'planning':
            data = {'query_ru': 'органайзер для кухни', 'questions': []}
        else:
            product_ref = next(iter(payload['products']))
            source_id = payload['products'][product_ref]['source_id']
            data = {
                'summary': '合成目录列出收纳用品供给，需求仍待核对。',
                'findings': ['合成来源包含一项目录商品。'],
                'limitations': ['合成小样本；销量、需求、利润未知，译文待校对。'],
                'evidence_refs': [source_id],
                'candidates': [{'product_ref': product_ref, 'reason': '合成供给样本，供后续调研。',
                                'source_ids': [source_id]}],
            }
        return {'data': data, 'provider': 'SYNTHETIC_PRIVATE_PROVIDER_MARKER', 'model': 'synthetic'}

    def execute(self, generate=None, capture=None):
        with patch('market_research.model.generate', side_effect=generate or self.generate), \
                patch('market_research.collector.capture', side_effect=capture or self.capture):
            self.assertTrue(self.app.agent_runtime.run_once())

    def unknown_research(self):
        thread = self.send_research()

        def unknown(phase, payload, cancelled, route):
            if phase == 'analyzing':
                self.executed[phase] += 1
                raise ValueError('agent_provider_outcome_unknown')
            return self.generate(phase, payload, cancelled, route)

        self.execute(generate=unknown)
        job = self.invoke('commerce_market_research_get', {'task_id': thread['research_job']['task_id']})
        self.assertEqual(job['status'], 'unknown')
        return thread, job

    def assert_registered_research_error(self, tool, arguments, client):
        with self.assertRaises(ValueError) as failure:
            self.invoke(tool, arguments, client)
        self.assertNotEqual(str(failure.exception), 'unknown_tool',
                            'A missing tool is not a valid resource-scope rejection')

    def assert_job_contract(self, job):
        """Require stable identity, bounded states, and captured-source citations."""
        self.assertEqual(job['schema'], 'commerce-market-research-v1')
        self.assertIsInstance(job['task_id'], str)
        self.assertTrue(job['task_id'])
        self.assertIn(job['status'], STATUSES)
        self.assertIn(job['phase'], PHASES)
        self.assertEqual(job['market'], 'RU')
        self.assertIsInstance(job['query'], str)
        self.assertTrue(job['query'].strip())
        self.assertIs(type(job['revision']), int)
        self.assertGreaterEqual(job['revision'], 1)
        location = urlsplit(job['workspace_url'])
        self.assertEqual(location.scheme, '')
        self.assertEqual(location.netloc, '')
        self.assertEqual(location.path, '/workspace')
        query = parse_qs(location.query)
        self.assertEqual(query, {'tab': ['pilots'], 'research_task_id': [job['task_id']]})
        self.assertIsInstance(job['questions'], list)
        self.assertIsNotNone(datetime.fromisoformat(job['updated_at'].replace('Z', '+00:00')).tzinfo)
        self.assertIsInstance(job['sources'], list)
        self.assertIsInstance(job['candidates'], list)
        self.assertEqual(job['candidate_count'], len(job['candidates']))
        self.assertIsInstance(job['source_count'], int)
        self.assertGreaterEqual(job['source_count'], 0)
        self.assertEqual(job['source_count'], sum(s['status'] == 'collected' for s in job['sources']))
        self.assertFalse(any(key.startswith('_') for key in job))
        sources = {}
        for source in job['sources']:
            self.assertNotIn(source['id'], sources)
            sources[source['id']] = source
            self.assertIn(source['status'], ('collected', 'failed'))
            self.assertEqual(source['evidence_kind'], 'public_page')
            location = urlsplit(source['url'])
            self.assertIn(location.scheme, ('http', 'https'))
            self.assertTrue(location.hostname)
            self.assertIsNone(location.username)
            self.assertIsNone(location.password)
            if source['status'] == 'collected':
                self.assertIsNone(source['error'])
                self.assertRegex(source['sha256'], r'^[0-9a-f]{64}$')
                self.assertTrue(source['excerpt'].strip())
                captured = datetime.fromisoformat(source['captured_at'].replace('Z', '+00:00'))
                self.assertIsNotNone(captured.tzinfo)
            else:
                self.assertIsInstance(source['error'], str)
                self.assertTrue(source['error'])
        collected = {key for key, value in sources.items() if value['status'] == 'collected'}
        if job['report'] is not None:
            report = job['report']
            self.assertTrue(report['summary'].strip())
            self.assertTrue(report['evidence_refs'])
            self.assertLessEqual(set(report['evidence_refs']), collected)
            self.assertIn('findings', report)
            self.assertIn('limitations', report)
        for candidate in job['candidates']:
            self.assertTrue(candidate['case_id'])
            self.assertTrue(candidate['name'].strip())
            self.assertTrue(candidate['source_ids'])
            self.assertLessEqual(set(candidate['source_ids']), collected)
            self.assertIn(candidate['source_url'], {sources[key]['url'] for key in candidate['source_ids']})
            location = urlsplit(candidate['workspace_url'])
            self.assertIn(location.scheme, ('', 'http', 'https'))
            if location.scheme:
                self.assertIn(location.hostname, ('127.0.0.1', 'localhost'))
            else:
                self.assertFalse(location.netloc)
            self.assertEqual(location.path, '/workspace')
            query = parse_qs(location.query)
            self.assertEqual(query.get('case_id'), [candidate['case_id']])
            self.assertFalse(set(query) & {'token', 'ticket', 'secret', 'authorization'})
        if job['error'] is not None:
            self.assertEqual(set(job['error']), {'code', 'message'})
            self.assertTrue(job['error']['code'])
            self.assertTrue(job['error']['message'])

    def test_all_clients_discover_one_registered_research_contract(self):
        names = {name for name, _, _ in TOOLS}
        self.assertLessEqual(RESEARCH_TOOLS, names)
        projections = [self.invoke('commerce_market_research_list', client=client) for client in CLIENTS]
        for projection in projections:
            self.assertEqual(projection['schema'], 'commerce-market-research-list-v1')
            self.assertEqual(projection['jobs'], [])
        self.assertEqual(projections[0], projections[1])
        self.assertEqual(projections[1], projections[2])

    def test_polling_each_client_does_not_create_or_execute_a_task(self):
        original = self.ordinary_task()
        for _ in range(2):
            for client in CLIENTS:
                self.assertEqual(self.invoke('commerce_market_research_list', client=client)['jobs'], [])
                self.assertEqual(self.invoke('commerce_task_get', {'task_id': original['id']}, client), original)
        self.assertEqual(self.task_count(), 1)
        self.assertIsNone(self.invoke('commerce_task_result', {'task_id': original['id']})['execution'])

    def test_research_get_and_cancel_cannot_adopt_an_unrelated_task(self):
        original = self.ordinary_task()
        for client in CLIENTS:
            for tool in ('commerce_market_research_get', 'commerce_market_research_cancel'):
                self.assert_registered_research_error(tool, {'task_id': original['id']}, client)
        self.assertEqual(self.invoke('commerce_task_get', {'task_id': original['id']}), original)
        self.assertEqual(self.task_count(), 1)

    def test_missing_task_reads_never_create_a_research_job(self):
        for client in CLIENTS:
            self.assert_registered_research_error('commerce_market_research_get', {
                'task_id': 'synthetic-task-that-does-not-exist',
            }, client)
        self.assertEqual(self.task_count(), 0)
        self.assertEqual(self.invoke('commerce_market_research_list')['jobs'], [])

    def test_all_clients_read_one_task_and_its_original_versioned_artifact(self):
        thread = self.send_research()
        task_id = thread['research_job']['task_id']
        self.execute()
        job = self.invoke('commerce_market_research_get', {'task_id': task_id}, 'hermes')
        self.assert_job_contract(job)
        self.assertEqual(job['status'], 'partial')
        candidate = job['candidates'][0]
        for client in CLIENTS:
            self.assertEqual(self.invoke('commerce_market_research_get', {'task_id': task_id}, client), job)
            self.assertEqual(self.invoke('commerce_copilot_get', {'thread_id': thread['id']}, client)['research_job'], job)
            task = self.invoke('commerce_task_get', {'task_id': task_id}, client)
            self.assertEqual(task['status'], job['status'])
            workspace = self.invoke('commerce_workspace_get', {'case_id': candidate['case_id']}, client)
            self.assertEqual(workspace['artifacts']['research']['id'], candidate['artifact_id'])
            self.assertTrue(workspace['artifacts']['research']['intact'])
            self.assertIsNone(workspace['case']['scope']['product_id'])
            self.assertIsNone(workspace['case']['scope']['sku'])
            self.assertIsNone(workspace['case']['currency'])
            self.assertFalse(workspace['facts_independently_verified'])
            self.assertEqual(workspace['calculation']['status'], 'HOLD')
        self.assertEqual(self.task_count(), 1)
        self.assertNotIn('SYNTHETIC_PRIVATE_PROVIDER_MARKER', str(job))
        reloaded = Commerce(self.private.name)
        self.assertEqual(reloaded.invoke('commerce_market_research_get', {'task_id': task_id}, 'codex'), job)

    def test_clarification_across_hosts_refreshes_live_job_but_not_frozen_model_output(self):
        original = self.send_research()
        task_id = original['research_job']['task_id']
        first_run_id = original['latest_run']['id']

        def question(phase, payload, cancelled, route):
            self.assertEqual(phase, 'planning')
            return {'data': {'query_ru': '', 'questions': ['需要哪种收纳用品？']},
                    'provider': 'synthetic', 'model': 'synthetic'}

        self.execute(generate=question, capture=lambda *args: self.fail('Clarification cannot collect a source'))
        frozen = self.invoke('commerce_agent_get', {'run_id': first_run_id})
        self.assertEqual(frozen['status'], 'awaiting_input')
        frozen_result = deepcopy(frozen['result'])
        frozen_hash = frozen['result_sha256']
        answered = self.invoke('commerce_copilot_send', {
            'thread_id': original['id'], 'message': '厨房塑料收纳架',
            'context_sha256': original['context_sha256'], 'idempotency_key': 'contract-clarification',
        }, 'hermes')
        self.assertEqual(answered['research_job']['task_id'], task_id)
        self.assertIn('采集真实资料', answered['research_job']['query'])
        self.assertIn('塑料收纳架', answered['research_job']['query'])

        def observe_capture(url, directory, cancelled):
            counts = self.executed.copy()
            for _ in range(2):
                current = self.invoke('commerce_copilot_get', {'thread_id': original['id']}, 'codex')
                archived = self.invoke('commerce_agent_get', {'run_id': first_run_id}, 'codex')
                self.assertEqual(current['research_job']['task_id'], task_id)
                self.assertEqual(current['research_job']['status'], 'running')
                self.assertEqual(current['research_job']['phase'], 'collecting')
                self.assertEqual(archived['research_job']['status'], 'running')
                self.assertEqual(archived['result'], frozen_result)
                self.assertEqual(archived['result_sha256'], frozen_hash)
            self.assertEqual(self.executed, counts, 'Read projections must not collect or invoke the model')
            return self.capture(url, directory, cancelled)

        self.execute(capture=observe_capture)
        final = self.invoke('commerce_copilot_get', {'thread_id': original['id']}, 'codex')
        self.assertEqual(final['research_job']['task_id'], task_id)
        self.assertEqual(final['research_job']['status'], 'partial')
        self.assertEqual(final['latest_run']['status'], 'completed')
        self.assertEqual(self.invoke('commerce_agent_get', {'run_id': first_run_id})['result_sha256'], frozen_hash)
        self.assertEqual(self.task_count(), 1)

    def test_explicit_resume_across_hosts_keeps_identity_and_completed_collection(self):
        thread, job = self.unknown_research()
        task_id = job['task_id']
        original_sources = deepcopy(job['sources'])
        counts = self.executed.copy()
        for client in CLIENTS:
            self.assertEqual(self.invoke('commerce_market_research_get', {'task_id': task_id}, client), job)
        self.assertEqual(self.executed, counts)
        arguments = {'task_id': task_id, 'expected_revision': job['revision'], 'idempotency_key': 'contract-resume'}
        resumed = self.invoke('commerce_market_research_resume', arguments, 'hermes')
        replay = self.invoke('commerce_market_research_resume', arguments, 'codex')
        self.assertEqual(replay['run_id'], resumed['run_id'])
        self.assertEqual(replay['task_id'], task_id)
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.invoke('commerce_market_research_resume', {**arguments, 'expected_revision': resumed['revision']}, 'harness')
        self.execute(capture=lambda *args: self.fail('Confirmed collection must not run again'))
        finished = self.invoke('commerce_market_research_get', {'task_id': task_id}, 'codex')
        self.assert_job_contract(finished)
        self.assertEqual(finished['sources'], original_sources)
        self.assertEqual(finished['status'], 'partial')
        self.assertEqual(self.task_count(), 1)
        self.assertEqual(self.invoke('commerce_copilot_get', {'thread_id': thread['id']})['research_job'], finished)

    def test_resume_rejects_boolean_and_stale_revisions_without_creating_an_attempt(self):
        _, job = self.unknown_research()
        with self.app.core.db() as db:
            original_runs = db.execute('SELECT count(*) FROM agent_runs').fetchone()[0]
        for index, revision in enumerate((True, False, 0, -1, float(job['revision']), str(job['revision']), job['revision'] + 1)):
            with self.subTest(revision=revision), self.assertRaisesRegex(ValueError, 'market_research_revision_conflict'):
                self.invoke('commerce_market_research_resume', {
                    'task_id': job['task_id'], 'expected_revision': revision,
                    'idempotency_key': 'bad-revision-' + str(index),
                }, 'hermes')
        self.assertEqual(self.invoke('commerce_market_research_get', {'task_id': job['task_id']}), job)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0], original_runs)
        self.assertEqual(self.task_count(), 1)

    def test_changed_thread_context_cannot_resume_an_old_task_in_a_new_scope(self):
        thread, job = self.unknown_research()
        self.invoke('commerce_copilot_context', {
            'thread_id': thread['id'], 'context': {'module': 'research', 'market': 'US', 'demo': False},
            'expected_context_sha256': thread['context_sha256'],
        }, 'hermes')
        with self.assertRaisesRegex(ValueError, 'market_research_context_changed'):
            self.invoke('commerce_market_research_resume', {
                'task_id': job['task_id'], 'expected_revision': job['revision'], 'idempotency_key': 'new-scope',
            }, 'codex')
        self.assertEqual(self.invoke('commerce_market_research_get', {'task_id': job['task_id']}), job)
        self.assertEqual(self.task_count(), 1)

    def test_failed_source_citations_and_extra_actions_never_partially_save_candidates(self):
        for index, mutation in enumerate(('failed_report_reference', 'failed_candidate_reference', 'unregistered_action')):
            with self.subTest(mutation=mutation):
                thread = self.send_research(key='bad-output-' + str(index))

                def invalid(phase, payload, cancelled, route):
                    value = self.generate(phase, payload, cancelled, route)
                    if phase == 'analyzing':
                        data = value['data']
                        if mutation == 'failed_report_reference':
                            data['evidence_refs'] = ['S2']
                        elif mutation == 'failed_candidate_reference':
                            other = deepcopy(data['candidates'][0]); other['source_ids'] = ['S2']
                            data['candidates'].append(other)
                        else:
                            data['candidates'][0]['action'] = {'name': 'commerce_task_cancel'}
                    return value

                self.execute(generate=invalid)
                job = self.invoke('commerce_market_research_get', {'task_id': thread['research_job']['task_id']})
                self.assertEqual(job['status'], 'failed')
                self.assertEqual(job['error']['code'], 'market_research_invalid_model_output')
                self.assertEqual(job['candidates'], [])
                self.assertIsNone(job['report'])
                self.assertEqual(self.invoke('commerce_workspace_list')['items'], [])

    def test_empty_summary_or_missing_limitations_is_not_a_publishable_analysis(self):
        for index, field in enumerate(('summary', 'limitations')):
            with self.subTest(field=field):
                prior_cases = {item['id'] for item in self.invoke('commerce_workspace_list')['items']}
                thread = self.send_research(key='empty-output-' + str(index))

                def incomplete(phase, payload, cancelled, route):
                    value = self.generate(phase, payload, cancelled, route)
                    if phase == 'analyzing':
                        value['data'][field] = '   ' if field == 'summary' else []
                    return value

                self.execute(generate=incomplete)
                job = self.invoke('commerce_market_research_get', {'task_id': thread['research_job']['task_id']})
                self.assertEqual(job['status'], 'failed')
                self.assertEqual(job['candidates'], [])
                self.assertEqual({item['id'] for item in self.invoke('commerce_workspace_list')['items']}, prior_cases)

    def test_all_failed_capture_stops_before_analysis_or_candidate_creation(self):
        thread = self.send_research()

        def blocked_capture(*args):
            raise ValueError('market_research_http_403')

        self.execute(capture=blocked_capture)
        job = self.invoke('commerce_market_research_get', {'task_id': thread['research_job']['task_id']})
        self.assert_job_contract(job)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(job['source_count'], 0)
        self.assertEqual(job['candidate_count'], 0)
        self.assertIsNone(job['report'])
        self.assertEqual(self.executed['analyzing'], 0)
        self.assertEqual(self.invoke('commerce_workspace_list')['items'], [])

    def test_terminal_partial_result_is_not_reexecuted_or_undone_by_cancel(self):
        thread = self.send_research(); self.execute()
        job = self.invoke('commerce_market_research_get', {'task_id': thread['research_job']['task_id']})
        with self.assertRaisesRegex(ValueError, 'market_research_not_resumable'):
            self.invoke('commerce_market_research_resume', {
                'task_id': job['task_id'], 'expected_revision': job['revision'], 'idempotency_key': 'repeat-finished',
            }, 'hermes')
        self.assertEqual(self.invoke('commerce_market_research_cancel', {'task_id': job['task_id']}, 'codex'), job)
        self.assertEqual(len(self.invoke('commerce_workspace_list')['items']), 1)
        self.assertEqual(self.task_count(), 1)

    def test_text_fallback_has_a_trusted_absolute_link_before_any_candidate_exists(self):
        job = self.send_research()['research_job']
        self.assertEqual(job['candidates'], [])
        frozen = deepcopy(job)
        decorated = with_workspace_link('commerce_market_research_get', job, 51234)
        link = decorated['links']['workspace']
        location = urlsplit(link['url'])
        self.assertEqual((location.scheme, location.netloc, location.path), ('http', '127.0.0.1:51234', '/workspace'))
        self.assertEqual(parse_qs(location.query), {'tab': ['pilots'], 'research_task_id': [job['task_id']]})
        self.assertTrue(link['requires_authentication'])
        self.assertIn(link['url'], decorated['text'])
        self.assertEqual(job, frozen)


if __name__ == '__main__':
    unittest.main()
