#!/usr/bin/env python3
"""检查信号提取和算术核对的限制条件，不启动新的 RTL 仿真。"""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('functional_wave',ROOT/'stage2/tests/render-functional-wave.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class FunctionalWaveTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'stage3/reports/figures/functional/functional-samples.json').read_text())
        self.cases=M.select_cases(M.AUDIT.read_text())

    def test_eight_real_windows_arithmetic(self):
        result=[M.audit_case(c,self.data['windows'][c['name']])['expected'] for c in self.cases]
        self.assertEqual(result,[36,120,-36,131072,-130048,129032,0,0])

    def case(self):
        c=self.cases[2];return c,copy.deepcopy(self.data['windows'][c['name']])

    def test_input_change_rejected(self):
        case,rows=self.case()
        for r in rows:
            if r['en0']:r['a']=0
        with self.assertRaises(ValueError):M.audit_case(case,rows)

    def test_product_change_rejected(self):
        case,rows=self.case()
        for r in rows:
            if r['en1']:r['p0']=123
        with self.assertRaises(ValueError):M.audit_case(case,rows)

    def test_sum_change_rejected(self):
        case,rows=self.case()
        for r in rows:
            if r['time']==case['output_time']:r['sum']=0
        with self.assertRaises(ValueError):M.audit_case(case,rows)

    def test_upper_bits_change_rejected(self):
        case,rows=self.case()
        for r in rows:
            if r['time']==case['output_time']:r['result']|=1<<64
        with self.assertRaises(ValueError):M.audit_case(case,rows)

    def test_invalid_output_rejected(self):
        case,rows=self.case()
        for r in rows:
            if r['time']==case['output_time']:r['out_valid']=0
        with self.assertRaises(ValueError):M.audit_case(case,rows)

    def test_missing_clock_edge_rejected(self):
        case,rows=self.case()
        for r in rows:r['unit_clock']=0
        with self.assertRaises(ValueError):M.audit_case(case,rows)

    def test_svg_keeps_clocks_operands_products_and_output(self):
        case,rows=self.case();result=M.audit_case(case,rows)
        svg=M.draw(result,rows);root=ET.fromstring(svg)
        self.assertTrue(root.tag.endswith('svg'))
        for token in ('vdot.enable[0]','vdot.products[7]','vdot.sum (signed19)','io_out.valid','out.data[127:32]'):
            self.assertIn(token,svg)


if __name__=='__main__':unittest.main()
