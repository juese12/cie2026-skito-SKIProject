#!/usr/bin/env python3
"""只读审核两组已适配指令约定的整核运行，不启动 emu。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('control',ROOT/'scripts/check-vdot-control.py')
control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('functional',type=Path)
    p.add_argument('control',type=Path)
    p.add_argument('--coordinator',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    records={}
    for kind,path in (('functional',args.functional),('control',args.control)):
        text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',path.read_text(errors='replace'))
        assert 'Difftest enabled' in text and text.count('HIT GOOD TRAP')==1
        assert re.findall(r'^\[process exit\] (\d+)$',text,re.M)==['0']
        assert not re.search(r'FAIL|HIT BAD TRAP|ABORT|different at pc',text)
        if kind=='functional':
            for marker in ('vdot contract=e8-e16 unsupported=e32',
                'vdot e16 legal PASS: cases=32 exact64=1 upper64=0',
                'vdot illegal PASS: VL=0/7/9/16, SEW=e32,',
                'vdot PASS: valid=52 illegal=10;'):
                assert marker in text,marker
        else:
            assert 'control contract=e8-e16 unsupported=e32/e64' in text
            control.audit_log(path,'56444f54')
        inputs={}
        for row in Path(str(path)+'.inputs.sha256').read_text().splitlines():
            expected,name=row.split(maxsplit=1)
            assert sha(name)==expected,name
            inputs[name]=expected
        assert len(inputs)==3
        inst,cycles=map(int,re.search(r'Core-0 instrCnt = (\d+), cycleCnt = (\d+)',text).groups())
        records[kind]=dict(status='PASS',log=str(path),log_sha256=sha(path),inputs=inputs,
            instructions=inst,cycles=cycles,host_ms=int(re.search(r'Host time spent: (\d+)ms',text).group(1)))
    coordinator=args.coordinator.read_text()
    assert all(marker in coordinator for marker in ('[contract PASS] functional',
        '[contract PASS] control','[contract regression COMPLETE]','[exit] 0'))
    result=dict(status='PASS',contract='e8-e16',runs=records,
        coordinator=str(args.coordinator),coordinator_sha256=sha(args.coordinator),
        control_status='NOT_AUDITED',qualification='architectural difference checks; no new internal cancellation trace, no physical analysis')
    with args.out.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(status='PASS',runs=list(records),control_status='NOT_AUDITED')))

if __name__=='__main__':main()
