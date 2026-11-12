"""Pure observer thresholds; synthetic clocks never close actual acceptance."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'crawlers'))
from endurance import verdict

class Endurance(unittest.TestCase):
    def setUp(self):self.sources={str(i):{'terminal':95,'succeeded':95} for i in range(8)}
    def test_short_run_never_accepts(self):self.assertEqual(verdict(10,10,30,0,2,self.sources,900,True),'in_progress')
    def test_full_window_with_enough_real_outcomes(self):self.assertEqual(verdict(86400,86400,31,0,2880,self.sources,900,True),'passed')
    def test_gaps_code_or_missing_cycles_fail(self):
        for gap,code,sources in [(121,True,self.sources),(30,False,self.sources),(30,True,{'x':{'terminal':0,'succeeded':0}})]:
            self.assertEqual(verdict(86400,86400,gap,0,2880,sources,900,code),'failed')

if __name__=='__main__':unittest.main()
