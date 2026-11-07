#!/usr/bin/env python3
import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('audit',Path(__file__).with_name('audit.py'))
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
S=dict(zip(M.NAMES,(0x1000,0x1004,0x1008,0x2000,0x2004,0x2008,0x200c,0x2010)))
DOT=0x02942a0b
def fixture():
    rows=[dict(c=i,d=[],k=[],b=[]) for i in range(22)]
    def alloc(c,t,pc,inst=DOT):rows[c]['d'].append([t,pc,inst,1])
    def input(c,t):
        rows[c]['i']=dict(tag=t,sew=1,vl=8,lmul=0,vm=1,start=0,vill=0,a='8000'*8,b='8000'*8)
    def output(c,t):
        rows[c]['o']=dict(tag=t,sew=1,vl=8,lmul=0,vm=1,start=0,vill=0,illegal=0,result=f'{8589934592:032x}')
    alloc(0,1,0x1000,0x63);alloc(0,2,0x1004);alloc(0,3,0x1008)
    input(1,2);input(2,3);output(3,2);output(4,3)
    rows[4].update(b=[[1,1,1]],r=[1,0]);rows[5]['k']=[1]
    alloc(7,2,0x1004);alloc(7,3,0x1008)
    input(8,2);input(9,3);output(10,2);output(11,3);rows[12]['k']=[2,3]
    alloc(13,4,0x2000,0xffffffff)
    for t,pc in ((5,0x2004),(6,0x2008),(7,0x200c)):alloc(13,t,pc)
    input(14,5);input(15,6);input(16,7);output(16,5);output(17,6);output(18,7)
    rows[18]['f']=[4,1];rows[19]['x']=[0xffffffff,1]
    alloc(20,8,0x2010,0x23);rows[21]['k']=[8]
    return rows

class EventAuditTests(unittest.TestCase):
    def test_uart_interleaved_with_complete_host_records(self):
        guest='short PASS data_seeds=4\n'
        host='[00] commit pc 0000000080000000 inst 00000013 wen 0\n'
        perf='[PERF ][time= 12] core: counter, 0\n'
        mixed=''.join(ch+host+perf for ch in guest)
        self.assertEqual(M.guest_text(mixed),guest)
        self.assertEqual(M.guest_text('short FAIL result\n'),'short FAIL result\n')

    def test_complete_e16_proof_and_tag_reuse(self):
        result=M.audit_events(fixture(),S)
        self.assertEqual({k:len(v) for k,v in result['proof'].items()},{'branch':1,'exception':1})
        self.assertEqual(result['counts']['witness_outputs'],7)

    def test_squashed_allocation_commit_rejected(self):
        rows=fixture();rows[6]['k']=[2]
        with self.assertRaisesRegex(ValueError,'canceled allocation committed'):M.audit_events(rows,S)

    def test_skipped_execution_is_not_coverage(self):
        rows=fixture();del rows[3]['o']
        with self.assertRaisesRegex(ValueError,'COVERAGE_MISSING'):M.audit_events(rows,S)

    def test_sew_mismatch_rejected(self):
        rows=fixture();rows[1]['i']['sew']=0
        with self.assertRaisesRegex(ValueError,'actual legal e16'):M.audit_events(rows,S)

    def test_bad_result_or_high_bits_rejected(self):
        rows=fixture();rows[3]['o']['result']='1'+('0'*31)
        with self.assertRaisesRegex(ValueError,'128-bit result'):M.audit_events(rows,S)

    def test_unconfirmed_exception_rejected(self):
        rows=fixture();rows[19]['x']=[0,0]
        with self.assertRaisesRegex(ValueError,'precise illegal exception'):M.audit_events(rows,S)

    def test_missing_recovery_tail_rejected(self):
        with self.assertRaisesRegex(ValueError,'COVERAGE_MISSING'):M.audit_events(fixture()[:20],S)

    def test_live_tag_reallocation_rejected(self):
        rows=fixture();rows[1]['d']=[[2,0x1004,DOT,1]]
        with self.assertRaisesRegex(ValueError,'live ROB allocation reused'):M.audit_events(rows,S)

    def test_illegal_pointer_encoding_rejected(self):
        rows=fixture();rows[0]['d'][0][0]=200
        with self.assertRaisesRegex(ValueError,'invalid ROB tag'):M.audit_events(rows,S)

if __name__=='__main__':unittest.main()
