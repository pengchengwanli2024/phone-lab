"""User-visible follow-up contracts; external model/page inputs are synthetic."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Commerce
import test_market_research as research_fixture


def inspect():
    return {'decision': {'phase': 'inspect', 'calls': [
        {'tool': 'commerce_runtime_status', 'arguments': {}}]},
        'provider': 'synthetic', 'model': 'dialogue-contract'}


def answer(text, questions=()):
    return {'decision': {'phase': 'answer', 'answer': text,
                         'questions': list(questions), 'evidence_refs': ['R1'],
                         'proposals': []},
            'provider': 'synthetic', 'model': 'dialogue-contract'}


class ChatDialogueFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Commerce(self.temp.name)
        self.context = {'module': 'overview', 'demo': False}
        self.thread = self.app.invoke('commerce_copilot_open', {
            'context': self.context, 'idempotency_key': 'synthetic-chat'}, 'browser')

    def tearDown(self):
        self.app.agent_runtime.stop()
        self.temp.cleanup()

    def send(self, message, key):
        thread = self.app.invoke('commerce_copilot_get', {
            'thread_id': self.thread['id']}, 'browser')
        return self.app.invoke('commerce_copilot_send', {
            'thread_id': thread['id'], 'message': message,
            'context_sha256': thread['context_sha256'],
            'expected_model_sha256': thread['model_selection']['sha256'],
            'idempotency_key': key}, 'browser')

    def read(self):
        return self.app.invoke('commerce_copilot_get', {
            'thread_id': self.thread['id']}, 'browser')

    def test_acceptance_is_pending_until_actual_answer_and_reads_never_resend(self):
        queued = self.send('请说明这个工作台从哪里开始。', 'initial')
        self.assertEqual(queued['latest_run']['status'], 'queued')
        self.assertIsNone(queued['latest_run']['result'])
        with patch('agent_runtime.model.invoke') as provider:
            for _ in range(3):
                self.assertEqual(self.read()['latest_run']['id'], queued['latest_run']['id'])
            provider.assert_not_called()
        with patch('agent_runtime.model.invoke', side_effect=[
            inspect(), answer('当前为合成空状态；可以先明确研究方向。', ['希望研究什么品类？'])]):
            self.app.agent_runtime.run_once()
        ready = self.read()
        self.assertEqual(ready['latest_run']['status'], 'awaiting_input')
        self.assertEqual(ready['latest_run']['result']['questions'], ['希望研究什么品类？'])
        self.assertTrue(ready['latest_run']['result']['answer'])

    def test_plain_follow_up_uses_original_thread_context_and_previous_question(self):
        first = self.send('先说明我需要补充什么。', 'first')
        with patch('agent_runtime.model.invoke', side_effect=[
            inspect(), answer('请补充目标品类和预算。', ['目标品类和预算是什么？'])]):
            self.app.agent_runtime.run_once()
        second = self.send('厨房收纳用品，预算500元。', 'follow-up')
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(second['context'], self.context)
        self.assertEqual(second['context_sha256'], first['context_sha256'])
        self.assertEqual(second['latest_run']['parent_id'], first['latest_run']['id'])
        with patch('agent_runtime.model.invoke', side_effect=[
            inspect(), answer('已收到同一会话中的品类和预算，尚未进行采购。')]) as provider:
            self.app.agent_runtime.run_once()
        payload = provider.call_args_list[0].args[0]
        self.assertEqual(payload['previous']['questions'], ['目标品类和预算是什么？'])
        self.assertEqual(payload['question'], '厨房收纳用品，预算500元。')
        self.assertEqual(self.read()['total_turns'], 2)

    def test_failed_generation_has_readable_state_without_implicit_retry(self):
        sent = self.send('核对当前工作范围。', 'failure')
        with patch('agent_runtime.model.invoke', side_effect=ValueError(
                'agent_provider_failed_no_automatic_retry')) as provider:
            self.app.agent_runtime.run_once()
            failed = self.read()
            for _ in range(3):
                self.assertEqual(self.read()['latest_run']['id'], sent['latest_run']['id'])
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(failed['latest_run']['status'], 'failed')
        self.assertEqual(failed['latest_run']['result']['error'],
                         'agent_provider_failed_no_automatic_retry')
        self.assertFalse(failed['latest_run']['result']['automatic_retry'])
        self.assertEqual(failed['total_turns'], 1)

    def await_market(self, question='帮我调研Ozon厨房收纳市场。'):
        self.send(question, 'market-question')
        with patch('agent_runtime.model.invoke', side_effect=[
            inspect(), answer('需要补充研究市场。', ['希望调研哪个市场？'])]):
            self.app.agent_runtime.run_once()
        self.assertEqual(self.read()['latest_run']['status'], 'awaiting_input')

    def test_market_conditions_request_reaches_durable_research(self):
        sent = self.send('帮我分析俄罗斯的市场行情，采集公开资料并保存候选。', 'conditions')
        self.assertIsNotNone(sent['research_job'])
        self.assertEqual(sent['research_job']['status'], 'queued')

    def test_plain_market_reply_starts_original_human_research_intent_once(self):
        self.await_market()
        sent = self.send('俄罗斯。', 'market-reply')
        job = sent['research_job']
        self.assertIsNotNone(job)
        self.assertEqual(job['query'], '帮我调研Ozon厨房收纳市场。\n补充：俄罗斯。')
        self.assertEqual(self.send('俄罗斯。', 'market-reply')['research_job']['task_id'], job['task_id'])
        with patch('market_research.model.generate', side_effect=ValueError('agent_provider_outcome_unknown')):
            self.app.agent_runtime.run_once()
        self.assertEqual(self.read()['research_job']['status'], 'unknown')
        later = self.send('俄罗斯。', 'later-reply')
        self.assertIsNone(later['research_job'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)

    def test_model_suggestion_does_not_create_research_from_a_greeting(self):
        self.send('你好', 'greeting')
        response = answer('需要补充研究市场。', ['希望调研哪个市场？'])
        response['decision']['evidence_refs'] = []
        with patch('agent_runtime.model.invoke', return_value=response) as provider:
            self.app.agent_runtime.run_once()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(self.read()['latest_run']['status'], 'awaiting_input')
        self.assertEqual(self.read()['latest_run']['result']['observations'], [])
        self.assertIsNone(self.send('俄罗斯。', 'market-reply')['research_job'])
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 0)

    def test_changed_scope_cannot_borrow_previous_research_intent(self):
        self.await_market()
        waiting = self.read()
        self.app.invoke('commerce_copilot_context', {'thread_id': waiting['id'],
            'context': {'module': 'connections', 'demo': False},
            'expected_context_sha256': waiting['context_sha256']}, 'browser')
        self.assertIsNone(self.send('俄罗斯。', 'changed-scope')['research_job'])

    def test_research_question_then_plain_follow_up_keeps_task_and_opens_saved_candidate(self):
        first = self.send('请调研俄罗斯市场，采集公开资料并保存候选。', 'research')
        task_id = first['research_job']['task_id']
        fixture = research_fixture.ResearchFlow()
        with patch('market_research.model.generate', return_value={
                'data': {'query_ru': '', 'questions': ['希望调研哪个品类？']},
                'provider': 'synthetic', 'model': 'dialogue-contract'}):
            self.app.agent_runtime.run_once()
        waiting = self.read()
        self.assertEqual(waiting['research_job']['status'], 'awaiting_input')
        second = self.send('厨房收纳用品。', 'category')
        self.assertEqual(second['research_job']['task_id'], task_id)
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(second['context'], first['context'])
        with patch('market_research.collector.capture', side_effect=fixture.capture), \
                patch('market_research.model.generate', side_effect=fixture.generate):
            self.app.agent_runtime.run_once()
        finished = self.read()['research_job']
        self.assertEqual(finished['task_id'], task_id)
        self.assertEqual(finished['status'], 'partial')
        self.assertEqual(finished['candidate_count'], 1)
        case_id = finished['candidates'][0]['case_id']
        workspace = self.app.invoke('commerce_workspace_get', {'case_id': case_id}, 'browser')
        self.assertEqual(workspace['case']['scope']['inventory_type'], 'candidate')
        self.assertIsNone(workspace['case']['scope']['sku'])
        self.assertEqual(workspace['calculation']['status'], 'HOLD')
        receipt = self.app.invoke('commerce_task_result', {'task_id': task_id}, 'browser')
        self.assertEqual(receipt['execution']['operation'], 'market_research')
        self.assertEqual(receipt['research_job']['candidate_count'], 1)
        with self.app.core.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM tasks').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
