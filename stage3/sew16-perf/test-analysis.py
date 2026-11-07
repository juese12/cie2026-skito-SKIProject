#!/usr/bin/env python3
import unittest
import analyze as A

class AnalysisTests(unittest.TestCase):
    def rows(self,values):return [dict(cycles=str(v),slot=str(i%2)) for i,v in enumerate(values)]
    def test_constant_stable(self):
        m=A.metrics(self.rows([100]*8),self.rows([100]*8))
        self.assertEqual((m['median'],m['cv'],m['warnings']),(100,0,[]))
    def test_order_warning(self):
        m=A.metrics(self.rows([100,130]*4),[])
        self.assertIn('order',[w['metric'] for w in m['warnings']])
    def test_warm_tail_warning_retained(self):
        m=A.metrics(self.rows([100]*8),self.rows([100,85]))
        self.assertEqual([w['metric'] for w in m['warnings']],['warm_tail'])
    def test_exact_boundary_not_warning(self):
        m=A.metrics(self.rows([100]*8),self.rows([100,90]))
        self.assertEqual(m['warnings'],[])
        m=A.metrics(self.rows([100]*8),self.rows([100,110]))
        self.assertEqual(m['warnings'],[])
    def test_known_linear_cost(self):
        m=A.linear([(16,132),(64,228),(256,612)])
        self.assertEqual(m['slope_cycles_per_dot'],2)
        self.assertEqual(m['intercept_cycles'],100)
        self.assertEqual(m['max_relative_residual'],0)
    def test_nonlinearity_visible(self):
        m=A.linear([(16,100),(64,800),(256,900)])
        self.assertGreater(m['max_relative_residual'],.10)

if __name__=='__main__':unittest.main()
