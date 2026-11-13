"""Independent public read contracts for repeated synthetic studies of one product.

Only temporary state is used. Model, native availability and collection I/O are
synthetic; this suite does not replace daily native host acceptance.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce, TOOLS
from research import canonical, digest
from market_research.collector import extract
from test_market_research import HTML


class ResearchWorkspaceContextContract(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state = Path(temporary.name)
        (state / 'agent-model.json').write_text(json.dumps(
            {'provider': 'codex', 'model': 'synthetic-workspace-model'}))
        for guard in (
            patch('host_execution.shutil.which', return_value='/synthetic/codex'),
            patch('host_native.hermes_command', side_effect=ValueError('synthetic_native_unavailable')),
            patch('host_native.invoke', side_effect=AssertionError('Native execution is forbidden in this fixture')),
            patch('agent_runtime.model.invoke', side_effect=AssertionError('Native model I/O is forbidden')),
        ):
            guard.start()
            self.addCleanup(guard.stop)
        self.app = Commerce(state)
        self.addCleanup(self.app.agent_runtime.stop)
        self.label = ''
        self.product = '123'
        self.old = self.study('first')
        self.new = self.study('second')
        self.case = self.old['candidates'][0]['case_id']
        self.assertEqual(self.case, self.new['candidates'][0]['case_id'])
        self.original_scope = deepcopy(self.app.organization.case(self.case)['scope'])
        self.current = self.app.product_workspace.get(self.case)
        with self.app.core.db() as db:
            self.original_artifacts = {}
            for job in (self.old, self.new):
                row = db.execute('SELECT payload,sha FROM org_artifacts WHERE id=?',
                                 (job['candidates'][0]['artifact_id'],)).fetchone()
                self.original_artifacts[job['task_id']] = (json.loads(row[0]), row[1])

    def capture(self, url, directory, cancelled):
        if 'maxidom' not in url:
            raise ValueError('market_research_http_403')
        return {**extract(HTML.replace('/123/', '/' + self.product + '/').encode(), url),
                'captured_at': datetime.now(timezone.utc).isoformat()}

    def generate(self, phase, payload, cancelled, route):
        data = {'query_ru': 'органайзер для кухни', 'questions': []}
        if phase == 'analyzing':
            data = {'summary': self.label + ' 合成目录样本，需求待核实。',
                    'findings': ['合成供给样本。'], 'limitations': ['合成资料；销量和利润未知。'],
                    'evidence_refs': ['S1'], 'candidates': [{'product_ref': 'S1:P1',
                    'reason': self.label + ' 合成研究依据。', 'source_ids': ['S1']}]}
        return {'data': data, 'provider': 'synthetic-private-fixture', 'model': 'synthetic'}

    def study(self, label):
        self.label = label
        thread = self.app.copilot.open({'module': 'research', 'market': 'RU', 'demo': False}, label + ':open')
        sent = self.app.copilot.send(thread['id'], '请调研俄罗斯厨房收纳，采集资料并保存候选商品。合成研究 ' + label,
                                     thread['context_sha256'], label + ':send')
        with patch('market_research.collector.capture', side_effect=self.capture), \
                patch('market_research.model.generate', side_effect=self.generate):
            self.assertTrue(self.app.agent_runtime.run_once())
        job = self.app.market_research.get(sent['research_job']['task_id'])
        self.assertEqual((job['status'], job['candidate_count']), ('partial', 1))
        return job

    def get(self, job=None, *, case=None, client='codex'):
        args = {'case_id': case or self.case}
        if job is not None:
            args['research_task_id'] = job['task_id']
        return self.app.invoke('commerce_workspace_get', args, client)

    def rows(self):
        with self.app.core.db() as db:
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {name: db.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid').fetchall()
                    for name in tables}

    def selected(self, value, job, current):
        context = value['research_context']
        candidate = job['candidates'][0]
        self.assertEqual(context['task_id'], job['task_id'])
        self.assertEqual(context['artifact_id'], candidate['artifact_id'])
        self.assertEqual(context['artifact']['id'], candidate['artifact_id'])
        payload, sha = self.original_artifacts[job['task_id']]
        self.assertEqual(context['artifact']['payload'], payload)
        self.assertEqual(context['artifact']['sha256'], sha)
        self.assertTrue(context['artifact']['intact'])
        self.assertEqual(context['status'], job['status'])
        self.assertEqual(context['run_id'], job['run_id'])
        self.assertEqual(context['revision'], job['revision'])
        self.assertIs(context['is_current_artifact'], current)
        self.assertIs(context['read_only'], True)
        # Historical research is an additive read view, not a replacement for
        # the current cost/form/CAS input or the case's immutable creation scope.
        for field in ('artifacts', 'forms', 'source_sha256', 'calculation', 'stages'):
            self.assertEqual(value[field], self.current[field], field)
        self.assertEqual(value['case']['scope'], self.original_scope)
        self.assertEqual(value['calculation']['status'], 'HOLD')
        self.assertFalse(value['facts_independently_verified'])
        self.assertFalse(value['external_execution_allowed'])
        return context

    def assert_scope_rejection(self, args):
        before = self.rows()
        with self.assertRaises(ValueError) as failed:
            self.app.product_workspace.get(**args)
        self.assertNotIn(str(failed.exception), ('unknown_tool', 'invalid_arguments', 'workspace_invalid_arguments'))
        self.assertEqual(before, self.rows())

    def test_fixture_preserves_one_product_creation_scope_and_two_artifact_versions(self):
        self.assertEqual(self.original_scope['research_task_id'], self.old['task_id'])
        self.assertNotEqual(self.old['candidates'][0]['artifact_id'], self.new['candidates'][0]['artifact_id'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM org_cases').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM org_artifacts WHERE case_id=?', (self.case,)).fetchone()[0], 2)

    def test_all_clients_select_each_studys_exact_immutable_artifact(self):
        for client in ('harness', 'hermes', 'codex'):
            for job, current in ((self.old, False), (self.new, True)):
                with self.subTest(client=client, task=job['task_id']):
                    self.selected(self.get(job, client=client), job, current)

    def test_case_only_default_selects_context_of_current_research_head(self):
        value = self.get()
        self.selected(value, self.new, True)
        references = {(item['task_id'], item['artifact_id']) for item in value['research_contexts']}
        self.assertEqual(references, {(job['task_id'], job['candidates'][0]['artifact_id'])
                                     for job in (self.old, self.new)})

    def test_schema_and_candidate_urls_expose_optional_task_context_without_writes(self):
        schema = next(schema for name, _, schema in TOOLS if name == 'commerce_workspace_get')
        self.assertIn('research_task_id', schema['properties'])
        self.assertNotIn('research_task_id', schema['required'])
        before = self.rows()
        for original in (self.old, self.new):
            job = self.app.market_research.get(original['task_id'])
            candidate = job['candidates'][0]
            self.assertEqual(candidate['research_task_id'], job['task_id'])
            query = parse_qs(urlsplit(candidate['workspace_url']).query)
            self.assertEqual(query['case_id'], [self.case])
            self.assertEqual(query['research_task_id'], [job['task_id']])
        self.assertEqual(before, self.rows())

    def test_unknown_task_and_another_cases_task_are_rejected(self):
        self.selected(self.get(self.old), self.old, False)
        self.product = '456'
        other = self.study('another-product')
        self.assertNotEqual(other['candidates'][0]['case_id'], self.case)
        for task in ('missing-task', other['task_id']):
            with self.subTest(task=task):
                self.assert_scope_rejection({'case_id': self.case, 'research_task_id': task})

    def test_same_case_artifact_owned_by_another_task_cannot_be_substituted(self):
        self.selected(self.get(self.old), self.old, False)
        with self.app.core.db() as db:
            job = json.loads(db.execute('SELECT document FROM market_research_jobs WHERE task_id=?',
                                        (self.old['task_id'],)).fetchone()[0])
            job['candidates'][0]['artifact_id'] = self.new['candidates'][0]['artifact_id']
            db.execute('UPDATE market_research_jobs SET document=? WHERE task_id=?',
                       (canonical(job), self.old['task_id']))
        self.assert_scope_rejection({'case_id': self.case, 'research_task_id': self.old['task_id']})

    def test_tampered_historical_artifact_is_rejected_without_latest_fallback(self):
        self.selected(self.get(self.old), self.old, False)
        with self.app.core.db() as db:
            artifact = self.old['candidates'][0]['artifact_id']
            payload, kind, sha = db.execute('SELECT payload,kind,sha FROM org_artifacts WHERE id=?',
                                      (artifact,)).fetchone()
        for field, value, consistent_hash in (('payload', '{}', False),
                                              ('payload', '[]', True),
                                              ('kind', 'economics', False)):
            with self.subTest(tampered=field, consistent_hash=consistent_hash):
                with self.app.core.db() as db:
                    db.execute('UPDATE org_artifacts SET ' + field + '=? WHERE id=?', (value, artifact))
                    if consistent_hash:
                        db.execute('UPDATE org_artifacts SET sha=? WHERE id=?',
                                   (digest(canonical(json.loads(value))), artifact))
                try:
                    self.assert_scope_rejection({'case_id': self.case, 'research_task_id': self.old['task_id']})
                finally:
                    with self.app.core.db() as db:
                        db.execute('UPDATE org_artifacts SET payload=?,kind=?,sha=? WHERE id=?',
                                   (payload, kind, sha, artifact))

    def test_direct_read_of_both_contexts_and_default_changes_no_database_row(self):
        before = self.rows()
        for job in (self.old, self.new):
            self.selected(self.app.product_workspace.get(self.case, research_task_id=job['task_id']),
                          job, job is self.new)
        self.selected(self.app.product_workspace.get(self.case), self.new, True)
        self.assertEqual(before, self.rows())


if __name__ == '__main__':
    unittest.main()
