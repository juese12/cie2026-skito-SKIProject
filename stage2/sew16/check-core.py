#!/usr/bin/env python3
"""重新审核已保存的固定八项 e8/e16 整核结果及配套材料。"""
import argparse
import hashlib
import json
from pathlib import Path
import re

def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('log',type=Path)
    p.add_argument('--coordinator',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    raw=args.log.read_text(errors='replace')
    clean=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',raw)
    coordinator=args.coordinator.read_text(errors='replace')
    assert 'Difftest enabled' in clean
    assert clean.count('HIT GOOD TRAP')==1
    assert '[process exit] 0' in clean and '[exit] 0' in coordinator
    assert '[sew16 regression COMPLETE]' in coordinator
    assert not re.search(r'FAIL|HIT BAD TRAP|ABORT|different at pc',clean)
    assert 'vdot PASS: valid=1052 illegal=10;' in clean
    assert 'sew16 PASS: wide=836 seeds=4 illegal=4 e8-regression=1564 fixed-items=8;' in clean
    assert 'sew16 control PASS: branch-training=64 branch-probes=4 younger-exceptions=4' in clean
    seeds=re.findall(r'sew16 random PASS seed=([0-9a-f]+) cases=128 alternating-e8-e16',clean)
    assert seeds==['56444f54','1','9e3779b9','deadbeef'],seeds
    inputs={}
    for line in Path(str(args.log)+'.inputs.sha256').read_text().splitlines():
        expected,name=line.split(maxsplit=1)
        assert sha(name)==expected,name
        inputs[name]=expected
    assert len(inputs)==3
    instructions,cycles=map(int,re.search(r'Core-0 instrCnt = (\d+), cycleCnt = (\d+)',clean).groups())
    result=dict(status='PASS',e8_checks=1564,e16_checks=836,data_seeds=seeds,
                e8_illegal=10,e16_illegal=4,branch_training=64,branch_probes=4,younger_exceptions=4,
                instructions=instructions,core_cycles=cycles,
                host_ms=int(re.search(r'Host time spent: (\d+)ms',clean).group(1)),
                inputs=inputs,log=str(args.log),log_sha256=sha(args.log),
                coordinator=str(args.coordinator),coordinator_sha256=sha(args.coordinator),
                qualification='one CPU process, init seed=101, four data seeds; no CPU waveform or physical PPA claim')
    with args.out.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
