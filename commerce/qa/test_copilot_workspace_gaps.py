"""Actionable, bounded workspace evidence over the real organization gates."""
from pathlib import Path
import copy
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_organization as fixtures
from agent_runtime.policy import project
from test_agent_runtime import inspect, answer


class WorkspaceGaps(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OrganizationTests()
        self.fixture.setUp()
        self.app, self.case_id = self.fixture.app, self.fixture.cid

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.fixture.tearDown()

    def read(self):
        value = self.app.invoke('commerce_workspace_get', {'case_id': self.case_id}, 'test')
        return project('commerce_workspace_get', value)

    def test_assistant_can_explain_missing_supply_owner_and_recheck_without_dispatch(self):
        value = self.read()
        stage = next(s for s in value['stages'] if s['id'] == 'S3')
        self.assertGreater(stage['missing'], 0)
        self.assertTrue(stage.get('gaps'), 'missing reasons must reach the assistant')
        gap = next(g for g in stage['gaps'] if g['id'] == 'artifact')
        self.assertEqual(gap['status'], 'HOLD')
        self.assertEqual(gap['owner'], 'sourcer')
        self.assertIn('supply', gap['reason'])
        self.assertTrue(gap['verify'])
        self.assertEqual(stage['artifact_kind'], 'supply')
        self.assertIn('S1', stage['depends_on'])
        self.assertFalse(value['external_execution_allowed'])
        self.assertEqual(self.app.core.invoke('commerce_task_list', {})['tasks'], [])

    def test_new_read_reflects_produced_artifact_and_keeps_unavailable_capability_blocked(self):
        before = self.read()
        self.fixture.prepare_cost()
        after = self.read()
        self.assertNotEqual(before['source_sha256'], after['source_sha256'])
        stage = next(s for s in after['stages'] if s['id'] == 'S3')
        self.assertEqual(stage['status'], 'PASS')
        self.assertEqual(stage.get('gaps'), [])
        unavailable = next(s for s in after['stages'] if s['id'] == 'S7')
        gap = next(g for g in unavailable.get('gaps', []) if g['id'] == 'capability')
        self.assertEqual(gap['status'], 'BLOCKED')
        self.assertIn('广告', gap['reason'])
        self.assertNotIn('payload', json.dumps(after))

    def test_large_gap_list_is_bounded_without_losing_original_missing_count(self):
        value = self.app.invoke('commerce_workspace_get', {'case_id': self.case_id}, 'test')
        gap = dict(id='artifact', status='HOLD', reason='缺少来源' * 200,
                   owner='sourcer', verify='核对当前产物' * 200, raw_note='PRIVATE_SENTINEL')
        for stage in value['stages']:
            stage['gaps'] = [copy.deepcopy(gap) for _ in range(100)]
            stage['checks'] = [{'raw_note': 'PRIVATE_SENTINEL'}]
        result = project('commerce_workspace_get', value)
        self.assertLess(len(json.dumps(result, ensure_ascii=False)), 16000)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        for stage in result['stages']:
            self.assertEqual(stage['missing'], 100)
            self.assertTrue(stage.get('gaps_truncated'))
            self.assertTrue(stage.get('gaps'), 'each stage retains an actionable gap')

    def test_real_assistant_read_delivers_gap_details_to_model_and_saved_evidence(self):
        context = dict(module='organization', demo=False, platform='ozon', market='RU',
                       entity={'kind':'case', 'id':self.case_id})
        chat = self.app.copilot.open(context, 'workspace-gap-chat')
        self.app.copilot.send(chat['id'], '还缺哪些产物，谁补齐，怎样复验？',
                              chat['context_sha256'], 'workspace-gap-question')
        with patch('agent_runtime.model.invoke', side_effect=[
                inspect('commerce_workspace_get', {'case_id': self.case_id}), answer()]) as provider:
            self.app.agent_runtime.run_once()
        consumed = provider.call_args_list[1].args[0]['observations'][0]['data']
        self.assertTrue(any(g['owner'] == 'sourcer' and g['verify']
                            for s in consumed['stages'] for g in s.get('gaps', [])))
        run = self.app.copilot.get(chat['id'])['latest_run']
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['result']['observations'][0]['data'], consumed)
        self.assertEqual(self.app.core.invoke('commerce_task_list', {})['tasks'], [])


if __name__ == '__main__':
    unittest.main()
