import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('analysis',Path(__file__).resolve().parents[1]/'tests/analyze-e2e-context.py')
analysis=importlib.util.module_from_spec(spec); spec.loader.exec_module(analysis)

class AnalysisTests(unittest.TestCase):
    def test_counterbalanced_position(self):
        for first in (0,1):
            values=[200 if (first^(r&1))==0 else 100 for r in range(8)]
            d=analysis.describe(values,values,first,0)
            self.assertEqual(d['positions']['0'],[200]*4)
            self.assertEqual(d['positions']['1'],[100]*4)
            self.assertEqual(d['same_position_warm_tail_drift'],0)
            self.assertEqual(d['slot_effect'],1)
            self.assertNotEqual(d['warm_tail_drift'],0)

    def test_rvv_labels(self):
        d=analysis.describe([100]*8,[200,100]*4,0,1)
        self.assertEqual(d['positions']['0'],[100]*4)
        self.assertEqual(d['warm_last_slot'],0)

    def test_contract_rejection(self):
        for a,b,first,impl in (([1]*7,[1]*8,0,0),([0]*8,[1]*8,0,0),([1]*8,[1]*8,2,0)):
            with self.assertRaises(ValueError): analysis.describe(a,b,first,impl)

if __name__=='__main__': unittest.main()
