"""Synthetic clocks and child callbacks: OCR never owns an N-frame timeout budget."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from creative_budget import OCRBudget


class Clock:
    def __init__(self):self.now=0
    def __call__(self):return self.now


class OCRBudgetTests(unittest.TestCase):
    def test_multiple_timeouts_share_one_total_budget(self):
        clock=Clock();budget=OCRBudget(total_seconds=20,call_seconds=8,clock=clock);timeouts=[]
        def child(argv,timeout):
            timeouts.append(timeout);clock.now+=timeout
            raise ValueError('creative_processing_timeout')
        values=[budget.read(child,['ocr','synthetic.png']) for _ in range(12)]
        self.assertEqual(timeouts,[8,8,4]);self.assertEqual(sum(timeouts),20)
        self.assertEqual([v['status'] for v in values[:4]],['unavailable','unavailable','unavailable','skipped'])
        self.assertEqual(values[3]['reason'],'ocr_budget_exhausted')
        self.assertEqual(values[0]['reason'],'ocr_timeout')
        self.assertTrue(all('items' not in v for v in values))

    def test_elapsed_startup_and_between_frame_time_reduce_remaining(self):
        clock=Clock();budget=OCRBudget(total_seconds=20,call_seconds=20,clock=clock);timeouts=[]
        def child(argv,timeout):
            timeouts.append(timeout);clock.now+=3
            return SimpleNamespace(stdout=b'0\t0\t1\t1\t0.8\tSynthetic text\n')
        first=budget.read(child,['ocr','synthetic.png']);clock.now+=12
        second=budget.read(child,['ocr','synthetic.png']);clock.now+=3
        third=budget.read(child,['ocr','synthetic.png'])
        self.assertEqual(timeouts,[20,5]);self.assertEqual(first['items'][0]['text'],'Synthetic text')
        self.assertEqual(second['status'],'completed');self.assertEqual(third['status'],'skipped')

    def test_timeout_and_invalid_output_never_claim_no_text(self):
        budget=OCRBudget()
        failed=budget.read(lambda *a:(_ for _ in ()).throw(ValueError('creative_media_processing_failed')),['ocr','synthetic.png'])
        invalid=budget.read(lambda *a:SimpleNamespace(stdout=b'0\t0\t1\t1\tbad\tSynthetic\n'),['ocr','synthetic.png'])
        self.assertEqual(failed,{'status':'unavailable','reason':'ocr_processing_failed'})
        self.assertEqual(invalid,{'status':'unavailable','reason':'ocr_invalid_output'})
        success=budget.read(lambda *a:SimpleNamespace(stdout=b''),['ocr','synthetic.png'])
        self.assertEqual(success,{'status':'completed','items':[]})


if __name__=='__main__':unittest.main()
