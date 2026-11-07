#!/usr/bin/env python3
"""验证缓存的真实探针图和统计图，不进行处理器仿真。"""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('baseline_comparison',ROOT/'stage3/tests/render-baseline-comparison.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.windows=json.loads((M.OUT/'probe-samples.json').read_text())['windows']
        self.pairs=json.loads(M.TIMER.read_text())['checked_pairs'][:2]

    def test_real_probe_uops_and_results(self):
        a,b=[M.audit_window(p,self.windows[str(p['impl'])]) for p in self.pairs]
        self.assertEqual(a['checked_result_groups'],dict(dot=32,mul=0,red=0))
        self.assertEqual(b['checked_result_groups'],dict(dot=0,mul=32,red=32))
        self.assertEqual((a['raw_output_uops'],b['raw_output_uops']),(32,192))
        self.assertEqual((a['cycles'],b['cycles']),(170,313))

    def corrupt(self,impl,port):
        p=self.pairs[impl];rows=copy.deepcopy(self.windows[str(impl)])
        event=M.audit_window(p,rows)['events'][0 if port=='mac' else -1]
        for r in rows:
            if r['time']==event['time']:r[port+'data']^=1
        return p,rows

    def test_dot_result_tamper_rejected(self):
        with self.assertRaises(ValueError):M.audit_window(*self.corrupt(0,'mac'))

    def test_wide_multiply_tamper_rejected(self):
        with self.assertRaises(ValueError):M.audit_window(*self.corrupt(1,'mac'))

    def test_reduction_tamper_rejected(self):
        with self.assertRaises(ValueError):M.audit_window(*self.corrupt(1,'ipu'))

    def test_missing_result_rejected(self):
        rows=self.windows['0']
        for r in rows:r['macvalid']=0
        with self.assertRaises(ValueError):M.audit_window(self.pairs[0],rows)

    def test_counter_tamper_rejected(self):
        self.pairs[0]['end']['data']+=1
        with self.assertRaises(ValueError):M.audit_window(self.pairs[0],self.windows['0'])

    def test_formal_full_samples_recomputed(self):
        data=json.loads(M.FORMAL.read_text());values=M.formal_values(data)
        self.assertEqual([v['vdot'] for v in values],[1247,5178,7199.5])
        data['runs'][0]['groups']['batch4']['rvv']['raw']=[0]*8
        with self.assertRaises(ValueError):M.formal_values(data)

    def test_figures_valid_and_limitations_explicit(self):
        checks={str(p['impl']):M.audit_window(p,self.windows[str(p['impl'])]) for p in self.pairs}
        wave=M.wave_figure(self.pairs,self.windows,checks).finish()
        formal=M.formal_figure(M.formal_values(json.loads(M.FORMAL.read_text()))).finish()
        for s in (wave,formal):self.assertTrue(ET.fromstring(s).tag.endswith('svg'))
        for token in ('TOP.clock','Vimac.out.valid','Vipu.out.valid','not commit'):self.assertIn(token,wave)
        for token in ('NOT a waveform','stable=False','29727.25 cycles'):self.assertIn(token,formal)


if __name__=='__main__':unittest.main()
