"""Research routing uses human intent and bounded, server-owned clarification only."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_intent import research_request, requests_research


class ResearchIntent(unittest.TestCase):
    def previous(self, question, **overrides):
        return {'question': question, 'status': 'awaiting_input',
                'questions': ['希望研究哪个市场？'], **overrides}

    def test_market_conditions_is_an_explicit_research_request(self):
        message = '帮我分析俄罗斯的市场行情，采集公开资料并保存候选。'
        self.assertTrue(requests_research(message, {}))
        self.assertEqual(research_request(message, {}), message)
        self.assertTrue(requests_research('请分析市场行情', {'market': 'RU'}))

    def test_plain_market_reply_combines_only_prior_human_request(self):
        question = '帮我调研Ozon厨房收纳市场。'
        self.assertFalse(requests_research(question, {}))
        request = research_request('俄罗斯。', {}, previous=self.previous(question))
        self.assertEqual(request, question + '\n补充：俄罗斯。')

    def test_model_suggestion_cannot_grant_research_authority(self):
        previous = self.previous('你好', answer='请调研俄罗斯厨房收纳市场并保存候选')
        self.assertIsNone(research_request('俄罗斯。', {}, previous=previous))
        self.assertIsNone(research_request('好的', {'market': 'RU'}, previous=previous))

    def test_explanations_and_negative_requests_never_start_research(self):
        for message in ('如何实现俄罗斯自动选品功能？', '介绍俄罗斯市场调研功能',
                        '是否支持俄罗斯市场分析？', '请不要调研俄罗斯市场',
                        '俄罗斯，先不要开始采集', '请取消俄罗斯市场调研'):
            with self.subTest(message=message):
                self.assertIsNone(research_request(message, {}, previous=self.previous('帮我调研Ozon厨房收纳市场。')))

    def test_terminal_or_existing_research_cannot_be_implicitly_replayed(self):
        question = '帮我调研Ozon厨房收纳市场。'
        for state in ('completed', 'unknown', 'failed', 'interrupted', 'cancelled', 'queued'):
            with self.subTest(state=state):
                self.assertIsNone(research_request('俄罗斯。', {}, previous=self.previous(question, status=state)))
        self.assertIsNone(research_request('俄罗斯。', {}, previous=self.previous(question), has_research=True))
        direct = '请调研俄罗斯厨房收纳市场，保存候选。'
        self.assertEqual(research_request(direct, {}, has_research=True), direct)

    def test_unbound_or_missing_clarification_has_no_history_authority(self):
        self.assertIsNone(research_request('俄罗斯。', {}))
        self.assertIsNone(research_request('俄罗斯。', {}, previous=self.previous('帮我调研Ozon厨房收纳市场。', questions=[])))
        self.assertIsNone(research_request('好的', {}, previous=self.previous('帮我调研Ozon厨房收纳市场。')))


if __name__ == '__main__':
    unittest.main()
