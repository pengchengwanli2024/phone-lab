"""Unified attention reads over real synthetic records; never run a provider."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce, TOOLS


class Attention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.counter = 0

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.temp.cleanup()

    def run_record(self, *, questions=None, proposals=None, thread=None, status=None, demo=False, parent_id=None):
        self.counter += 1
        if thread:
            run = self.app.copilot.send(thread['id'], '合成事项 ' + str(self.counter), thread['context_sha256'], 'send-' + str(self.counter))['latest_run']
        else:
            run = self.app.agent_runtime.create('合成事项 ' + str(self.counter), 'conductor', 'runtime',
                'run-' + str(self.counter), parameters={'demo': demo}, parent_id=parent_id)
        result = {'answer': '合成结果', 'questions': questions or [], 'proposals': proposals or [],
                  'evidence_refs': [], 'observations': [], 'provider': 'synthetic', 'model': 'synthetic'}
        state = status or ('awaiting_input' if questions else 'awaiting_review' if proposals else 'completed')
        with self.app.core.db() as db:
            db.execute('UPDATE agent_runs SET status=?,result=? WHERE id=?', (state, json.dumps(result), run['id']))
        return self.app.agent_runtime.get(run['id'])

    def thread(self, demo=False):
        self.counter += 1
        return self.app.copilot.open({'module': 'overview', 'demo': demo}, 'thread-' + str(self.counter))

    @staticmethod
    def proposal():
        return {'id': 'P1', 'operation': 'report', 'reason': '审阅合成简报', 'kind': 'report', 'input': {'demo': True}}

    def listing(self, **args):
        return self.app.invoke('commerce_attention_list', args)

    def close(self, item_id, note=''):
        return self.app.invoke('commerce_attention_close', {'item_id': item_id, 'note': note})

    def counts(self):
        with self.app.core.db() as db:
            return [db.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in ('agent_runs', 'tasks')]

    def test_checked_outcome_can_be_closed_without_resubmitting_or_changing_the_run(self):
        unknown = self.run_record(status='unknown');failed = self.run_record(status='failed')
        items = {row['run_id']: row for row in self.listing()['items']}
        before = self.counts();target = items[unknown['id']]
        receipt = self.close(target['id'], '已核对原请求，未产生结果')
        self.assertEqual((receipt['status'], receipt['resubmitted'], receipt['original_changed']), ('closed', False, False))
        self.assertEqual({row['run_id'] for row in self.listing()['items']}, {failed['id']})
        self.assertEqual(self.app.agent_runtime.get(unknown['id'])['status'], 'unknown')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.close(target['id'], '已核对原请求，未产生结果')['status'], 'closed')
        with self.assertRaisesRegex(ValueError, 'attention_item_changed'):
            self.app.invoke('commerce_attention_get', {'item_id': target['id']})

    def test_only_checked_outcomes_can_be_closed_never_questions_or_proposals(self):
        self.run_record(questions=['请补充目标市场']);self.run_record(proposals=[self.proposal()])
        for row in self.listing()['items']:
            with self.subTest(kind=row['kind']), self.assertRaisesRegex(ValueError, 'attention_not_closable'):
                self.close(row['id'])
        self.assertEqual(len(self.listing()['items']), 2)

    def test_closing_is_bound_to_the_exact_version_and_unknown_ids_are_rejected(self):
        run = self.run_record(status='failed');target = self.listing()['items'][0]
        with self.assertRaisesRegex(ValueError, 'attention_item_changed'): self.close('attention_' + 'f' * 64)
        with self.assertRaisesRegex(ValueError, 'invalid_attention_item'): self.close('not-an-id')
        self.close(target['id'])
        # The same run failing differently is a new item and is shown again.
        with self.app.core.db() as db:
            db.execute('UPDATE agent_runs SET result=? WHERE id=?', (json.dumps({'error': 'agent_provider_request_rejected'}), run['id']))
        again = self.listing()['items']
        self.assertEqual(len(again), 1);self.assertNotEqual(again[0]['id'], target['id'])

    def test_close_is_a_write_and_not_marked_read_only(self):
        import mcp_server, service
        self.assertIn('commerce_attention_close', {n for n, _, _ in service.TOOLS})
        self.assertNotIn('commerce_attention_close', mcp_server.CONTROL_READ_ONLY)

    def test_three_clients_share_unresolved_items_without_executing_or_creating_work(self):
        self.assertIn('commerce_attention_list', {name for name, _, _ in TOOLS})
        run = self.run_record(questions=['请补充预算'], proposals=[self.proposal()])
        with self.app.core.db() as db:
            before = db.execute('SELECT count(*) FROM tasks').fetchone()[0]
        with patch('agent_runtime.model.invoke') as provider:
            values = [self.app.invoke('commerce_attention_list', {}, client) for client in ('codex', 'hermes', 'harness')]
        self.assertEqual([item['kind'] for item in values[0]['items']], ['review', 'input'])
        self.assertTrue(all(value['items'] == values[0]['items'] for value in values))
        self.assertTrue(all(item['run_id'] == run['id'] for item in values[0]['items']))
        provider.assert_not_called()
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], before)

    def test_older_unresolved_item_is_not_lost_by_recent_run_limits(self):
        old = self.run_record(questions=['早期待补充'])
        for _ in range(25):
            self.run_record()
        self.assertEqual([item['run_id'] for item in self.listing()['items']], [old['id']])

    def test_keyset_pagination_filters_scope_and_does_not_repeat_items(self):
        for _ in range(5):
            self.run_record(questions=['待补充'])
        self.run_record(questions=['演示范围'], demo=True)
        ids = []
        cursor = None
        while True:
            page = self.listing(limit=2, **({'cursor': cursor} if cursor else {}))
            ids += [item['id'] for item in page['items']]
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(len(self.listing(demo=True)['items']), 1)
        for args in ({'limit': True}, {'limit': 0}, {'limit': 101}, {'cursor': 'arbitrary'}, {'demo': 'false'}):
            with self.assertRaises(ValueError):
                self.listing(**args)

    def test_applied_proposal_disappears_and_old_item_get_is_rejected(self):
        run = self.run_record(proposals=[self.proposal()])
        item = self.listing()['items'][0]
        first = self.app.agent_runtime.apply(run['id'], 'P1', run['result_sha256'])
        self.assertEqual(self.app.agent_runtime.apply(run['id'], 'P1', run['result_sha256'])['task']['id'], first['task']['id'])
        self.assertEqual(self.listing()['items'], [])
        with self.assertRaisesRegex(ValueError, 'attention_item_changed'):
            self.app.invoke('commerce_attention_get', {'item_id': item['id']})

    def test_partial_submission_is_unknown_instead_of_another_approval(self):
        run = self.run_record(proposals=[self.proposal()])
        task = self.app.core.invoke('commerce_task_create', {'kind': 'report', 'input': {'demo': True},
            'idempotency_key': 'agent:' + run['id'] + ':P1'})
        item = self.listing()['items'][0]
        self.assertEqual(item['kind'], 'unknown')
        self.assertEqual(item['status'], 'submission_unknown')
        self.assertEqual(item['task_id'], task['id'])
        self.assertEqual(item['action']['type'], 'agent')
        self.app.invoke('commerce_attention_get', {'item_id': item['id']})
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM task_runs').fetchone()[0], 0)

    def test_changed_context_revision_invalidates_old_items_even_after_returning(self):
        thread = self.thread()
        self.run_record(thread=thread, questions=['补充资料'], proposals=[self.proposal()])
        self.assertEqual(len(self.listing()['items']), 2)
        changed = self.app.copilot.context(thread['id'], {'module': 'products'}, thread['context_sha256'])
        self.app.copilot.context(thread['id'], thread['context'], changed['context_sha256'])
        self.assertEqual(self.listing()['items'], [])

    def test_explicit_followup_consumes_questions_but_keeps_unsubmitted_proposals(self):
        thread = self.thread()
        old = self.run_record(thread=thread, questions=['缺少预算'], proposals=[self.proposal()])
        self.run_record(thread=thread)
        items = self.listing()['items']
        self.assertEqual([(item['run_id'], item['kind']) for item in items], [(old['id'], 'review')])
        self.assertEqual(items[0]['action'], {'type': 'thread', 'id': thread['id']})

    def test_research_identity_supersedes_all_historical_model_runs(self):
        thread = self.thread()
        old = self.run_record(thread=thread, status='unknown')
        current = self.run_record(status='interrupted')
        task = self.app.core.invoke('commerce_task_create', {'kind': 'analysis', 'input': {'operation': 'market_research'}, 'idempotency_key': 'research'})
        job = {'task_id': task['id'], 'run_id': current['id'], 'thread_id': thread['id'], 'revision': 3,
            'status': 'unknown', 'query': '合成研究', 'questions': [], 'updated_at': '2026-11-13T00:00:00+00:00',
            '_context': thread['context']}
        with self.app.core.db() as db:
            db.execute('INSERT INTO market_research_jobs VALUES (?,?)', (task['id'], json.dumps(job)))
            for run in (old, current):
                db.execute('INSERT INTO market_research_runs VALUES (?,?)', (run['id'], task['id']))
        items = self.listing()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source'], 'research')
        self.assertEqual(items[0]['task_id'], task['id'])
        self.assertEqual(items[0]['action'], {'type': 'research', 'id': task['id']})
        job['status'] = 'running'
        with self.app.core.db() as db:
            db.execute('UPDATE market_research_jobs SET document=?', (json.dumps(job),))
        self.assertEqual(self.listing()['items'], [])

    def test_corrupt_source_is_incomplete_while_other_source_remains_visible(self):
        self.run_record(questions=['有效事项'])
        with self.app.core.db() as db:
            db.execute('INSERT INTO market_research_jobs VALUES (?,?)', ('broken', '{invalid'))
        result = self.listing()
        self.assertFalse(result['complete'])
        self.assertEqual(result['source_errors'], ['research'])
        self.assertEqual(len(result['items']), 1)

    def test_nested_source_corruption_keeps_healthy_items_visible(self):
        good = self.run_record(questions=['有效事项'])
        broken = self.run_record(questions=['损坏事项'])
        with self.app.core.db() as db:
            payload = json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?', (broken['id'],)).fetchone()[0])
            payload['parameters'] = None
            db.execute('UPDATE agent_runs SET payload=? WHERE id=?', (json.dumps(payload), broken['id']))
            db.execute('INSERT INTO market_research_jobs VALUES (?,?)', ('broken-context', json.dumps({'run_id': 'broken-run', '_context': None})))
        result = self.listing()
        self.assertFalse(result['complete'])
        self.assertEqual(result['source_errors'], ['agent', 'research'])
        self.assertEqual([item['run_id'] for item in result['items']], [good['id']])

    def test_research_context_return_does_not_revive_an_obsolete_revision(self):
        thread = self.thread()
        value = self.app.copilot.send(thread['id'], '请调研俄罗斯厨房收纳用品并保存候选',
            thread['context_sha256'], 'research-revision')
        job = value['research_job']
        with self.app.core.db() as db:
            stored = json.loads(db.execute('SELECT document FROM market_research_jobs WHERE task_id=?', (job['task_id'],)).fetchone()[0])
            stored['status'] = 'unknown'
            self.app.market_research._save(db, stored)
            db.execute("UPDATE agent_runs SET status='interrupted' WHERE id=?", (job['run_id'],))
        changed = self.app.copilot.context(thread['id'], {'module': 'products'}, thread['context_sha256'])
        self.app.copilot.context(thread['id'], thread['context'], changed['context_sha256'])
        self.assertEqual(self.listing()['items'], [])

    def test_only_bounded_display_fields_are_projected_and_item_detail_is_read_only(self):
        run = self.run_record(questions=['请核对资料'])
        with self.app.core.db() as db:
            payload = json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?', (run['id'],)).fetchone()[0])
            payload['private_context'] = {'token': 'PRIVATE_SENTINEL', 'path': '/private/PRIVATE_SENTINEL'}
            db.execute('UPDATE agent_runs SET payload=? WHERE id=?', (json.dumps(payload), run['id']))
        item = self.listing()['items'][0]
        detail = self.app.invoke('commerce_attention_get', {'item_id': item['id']})
        self.assertEqual(detail['item'], item)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(detail))
        self.assertNotIn('payload', detail['item'])
        self.assertEqual(self.listing(kind='review')['items'], [])

    def test_standalone_case_request_inherits_the_case_data_mode(self):
        with self.app.core.db() as db:
            db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',
                ('synthetic-case', '', 'synthetic-row', json.dumps({'synthetic': True}), None, 'synthetic-time'))
        run = self.app.agent_runtime.create('核对合成商品', 'conductor', 'organization_case', 'synthetic-case-run',
            parameters={'case_id': 'synthetic-case'})
        with self.app.core.db() as db:
            db.execute("UPDATE agent_runs SET status='awaiting_input',result=? WHERE id=?",
                (json.dumps({'answer': '合成结果', 'questions': ['补充合成资料'], 'proposals': []}), run['id']))
        self.assertEqual(self.listing()['items'], [])
        self.assertEqual([item['run_id'] for item in self.listing(demo=True)['items']], [run['id']])

    def test_exposure_request_inherits_its_bound_case_data_mode(self):
        run = self.run_record(questions=['复核合成关联'])
        with self.app.core.db() as db:
            db.execute('INSERT INTO org_cases VALUES (?,?,?,?,?,?)',
                ('exposure-case', '', 'exposure-row', json.dumps({'synthetic': True}), None, 'synthetic-time'))
            db.execute('INSERT INTO exposure_assessments VALUES (?,?,?,?,?)', ('a'*64, 'exposure-case', 'synthetic-item', '{}', 1))
            payload = json.loads(db.execute('SELECT payload FROM agent_runs WHERE id=?', (run['id'],)).fetchone()[0])
            payload.update(topic='business_exposure', parameters={'assessment_id': 'a'*64})
            db.execute('UPDATE agent_runs SET payload=? WHERE id=?', (json.dumps(payload), run['id']))
        self.assertEqual(self.listing()['items'], [])
        self.assertEqual([item['run_id'] for item in self.listing(demo=True)['items']], [run['id']])


if __name__ == '__main__':
    unittest.main()
