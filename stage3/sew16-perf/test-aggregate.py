#!/usr/bin/env python3
"""仅用内存中的人工数据检查已知成本、配对统计与不完整数据拒绝。"""
import copy
import unittest
from unittest.mock import patch
import analyze as A

def fixture():
    runs=[]
    for i,(seed,data) in enumerate(zip((101,202,303,404),(0x56444f54,1,0x9e3779b9,0xdeadbeef))):
        for core in ('old','new'):
            cases=[];samples=[]
            for bits in ((8,16) if core=='new' else (8,)):
                for kind,n in enumerate((256,256,16,64,256)):
                    cases.append(dict(bits=str(bits),kind=str(kind),dots=str(n),expected='0000000000000001',a='1',b='1'))
                    for phase in (0,1):
                        for rep in range(8):
                            for impl,cost in ((0,2),(1,10)):
                                samples.append(dict(bits=str(bits),kind=str(kind),phase=str(phase),rep=str(rep),
                                  slot=str(impl^(i%2)^(rep&1)),impl=str(impl),cycles=str(100+cost*n)))
            audit=dict(cases=cases,samples=samples,instructions=100,cycles=200,log_sha256='synthetic')
            runs.append(dict(label=core+str(i),core=core,params=dict(profile=2,wide=int(core=='new'),seed=seed,data=data,first=i%2),
              audit=audit,log='synthetic-'+core+str(i)))
    return dict(status='CPU_PASS',runs=runs,frozen={})

def compute(state):
    lookup={r['log']:r['audit'] for r in state['runs']}
    with patch.object(A.C,'frozen'),patch.object(A.C,'parse',side_effect=lambda path,params:lookup[path]):
        return A.analyze(state)

class AggregateTests(unittest.TestCase):
    def test_known_costs_and_four_paired_processes(self):
        r=compute(fixture());self.assertTrue(r['stable'])
        self.assertEqual(len(r['summary']),10)
        self.assertEqual(r['summary'][0]['speedup_median'],2660/612)
        self.assertTrue(all(p['new_over_old_median']==1 for p in r['e8_extension']))
        fits=[f for run in r['runs'] for f in run['fits']]
        self.assertTrue(all(f['slope_cycles_per_dot']==(2 if f['impl']==0 else 10) for f in fits))
        self.assertEqual(sum(len(x['audit']['samples']) for x in fixture()['runs']),1920)
    def test_smoke_cannot_be_formal(self):
        state=fixture();state['runs'][0]['params']['profile']=1
        with self.assertRaisesRegex(ValueError,'smoke/wrong core'):compute(state)
    def test_input_mismatch_cannot_be_hardware_comparison(self):
        state=fixture();state['runs'][0]['audit']['cases'][0]['expected']='0000000000000002'
        with self.assertRaisesRegex(ValueError,'vectors/oracle/length'):compute(state)
    def test_process_seed_mismatch_rejected(self):
        state=fixture();state['runs'][0]['params']['seed']=999
        with self.assertRaisesRegex(ValueError,'seed set'):compute(state)

if __name__=='__main__':unittest.main()
