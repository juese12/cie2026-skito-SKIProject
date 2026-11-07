#!/usr/bin/env python3
"""使用整核结果之前，先拒绝不完整或不正确的测量记录。"""
import tempfile
import unittest
from pathlib import Path
import common as C

P=dict(profile=0,first=0,wide=1,data=0x56444f54,seed=101)
def fixture():
    rows=['Difftest enabled','perf4 meta schema=4 profile=0 first=0 wide=1 data=56444f54 reps=2 warm=0 random=0 deferred=1']
    for bits in (8,16):
        rows.append(f'perf4 equivalence bits={bits} dot=32 rvv=32 full128=1 CSR=1')
        for kind,n in enumerate((1,1,1,2,4)):
            seed=37 if bits==8 else 257
            a=f'{seed:032x}';b=f'{3:032x}';x=seed
            for _ in range(4*n if kind>=2 else 1):
                low=x%2**bits
                x=3*(low-2**bits if low>=2**(bits-1) else low)
            result=x%2**(32 if bits==8 else 64)
            rows.append(f'perf4 case bits={bits} kind={kind} batches={n} dots={4*n} expected={result:016x} chain_steps={4*n if kind>=2 else 0} a={a} b={b}')
            for rep in range(2):
                for slot in (0,1):rows.append(f'perf4 raw bits={bits} kind={kind} phase=1 rep={rep} slot={slot} impl={(rep&1)^slot} cycles=100')
    return '\n'.join(rows+['perf4 PASS full128=1 CSR=1 nonzero_feedback=1 exact_signed=1',
      'HIT GOOD TRAP','Core-0 instrCnt = 1234, cycleCnt = 5678','[process exit] 0',''])

class ParserTests(unittest.TestCase):
    def parse(self,text):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'log';p.write_text(text);return C.parse(p,P)
    def test_complete(self):self.assertEqual(len(self.parse(fixture())['samples']),40)
    def compact(self):
        rows=fixture().splitlines();groups={};out=[]
        for row in rows:
            if not row.startswith('perf4 raw '):out.append(row);continue
            x=C.fields(row);key=tuple(x[k] for k in ('bits','kind','phase','impl'))
            groups.setdefault(key,{})[int(x['rep'])]=x['cycles']
        for (bits,kind,phase,impl),values in groups.items():
            out.append(f'perf4 seq bits={bits} kind={kind} phase={phase} impl={impl} cycles='+','.join(values[i] for i in range(2)))
        return '\n'.join(out)+'\n'
    def test_compact_is_lossless(self):
        old=self.parse(fixture());new=self.parse(self.compact())
        key=lambda x:tuple(int(x[k]) for k in ('bits','kind','phase','rep','impl'))
        self.assertEqual(sorted(old['samples'],key=key),sorted(new['samples'],key=key))
    def test_compact_missing_value(self):
        with self.assertRaisesRegex(ValueError,'missing compact'):self.parse(self.compact().replace('cycles=100,100','cycles=100',1))
    def test_missing_sample(self):
        with self.assertRaisesRegex(ValueError,'missing raw'):self.parse(fixture().replace('perf4 raw bits=8 kind=0 phase=1 rep=0 slot=0 impl=0 cycles=100\n',''))
    def test_duplicate(self):
        with self.assertRaisesRegex(ValueError,'duplicate sample'):self.parse(fixture()+'perf4 raw bits=8 kind=0 phase=1 rep=0 slot=0 impl=0 cycles=100\n')
    def test_order(self):
        with self.assertRaisesRegex(ValueError,'sample order'):self.parse(fixture().replace('slot=0 impl=0','slot=0 impl=1',1))
    def test_bad_oracle(self):
        with self.assertRaisesRegex(ValueError,'oracle disagreement'):self.parse(fixture().replace('expected=000000000000006f','expected=0000000000000070',1))
    def test_truncated(self):
        with self.assertRaisesRegex(ValueError,'process exit'):self.parse(fixture().replace('[process exit] 0',''))
    def test_nonzero_exit(self):
        with self.assertRaisesRegex(ValueError,'process exit'):self.parse(fixture().replace('[process exit] 0','[process exit] 1'))
    def test_wrong_parameters(self):
        with self.assertRaisesRegex(ValueError,'metadata'):self.parse(fixture().replace('first=0','first=1',1))
    def test_zero_cycles(self):
        with self.assertRaisesRegex(ValueError,'sample order/value'):self.parse(fixture().replace('cycles=100','cycles=0',1))
    def test_full_width_e16(self):
        self.assertEqual(C.oracle('8000'*8,'8000'*8,16),8589934592)
        self.assertEqual(C.oracle('8000'*8,'7fff'*8,16),(-8589672448)%2**64)

if __name__=='__main__':unittest.main()
