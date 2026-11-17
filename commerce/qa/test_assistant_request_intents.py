"""Everyday requests need no unrelated business evidence; live facts still do."""
import sys,unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conversation_policy import requires_evidence,clock_question,clock_fields

class RequestIntents(unittest.TestCase):
    def test_supplied_quantity_word_problem_and_unsent_draft_can_answer_directly(self):
        for question in ['一共有5箱，每箱24件，拿走37件后还剩多少件？请说明计算过程。',
                         '给供应商写一封礼貌的催交期邮件草稿，只写草稿，不要发送。',
                         '请写一封道歉邮件，不要发布或提交。']:
            with self.subTest(question=question):self.assertFalse(requires_evidence(question,'workspace'))

    def test_current_business_and_real_actions_remain_evidence_bound(self):
        for question in ['我的库存5箱，每箱24件，当前库存还剩多少？',
                         '请把当前商品发布到店铺','给供应商写一封邮件并发送。',
                         '计算今天订单的利润','查询今天俄罗斯新闻','请保存这次分析为任务']:
            with self.subTest(question=question):self.assertTrue(requires_evidence(question,'workspace'))

    def test_clock_only_request_is_separate_from_current_news_and_orders(self):
        for question in ['请根据当前北京时间告诉我今天的年月日，以及明天星期几。',
                         '现在北京时间几点？','今天几月几号，明天周几？']:
            self.assertTrue(clock_question(question));self.assertFalse(requires_evidence(question,'workspace'))
        for question in ['北京时间今天有哪些新闻？','请按今天日期导出订单','今天会不会下雨？','解释时区是什么意思']:
            self.assertFalse(clock_question(question))

    def test_weekdays_and_cross_day_use_server_clock_with_explicit_zones(self):
        stamp=datetime(2026,11,16,16,30,tzinfo=timezone.utc).timestamp()
        value=clock_fields(stamp)
        self.assertEqual(value['now_beijing'],'2026-11-17 00:30:00 +08:00')
        self.assertEqual(value['date_beijing'],'2026-11-17')
        self.assertEqual(value['weekday_beijing'],'星期二')
        self.assertEqual(value['tomorrow_date_beijing'],'2026-11-18')
        self.assertEqual(value['tomorrow_weekday_beijing'],'星期三')

if __name__=='__main__':unittest.main()
