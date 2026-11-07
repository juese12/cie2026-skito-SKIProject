#!/usr/bin/env python3
"""使用同一镜像比较调用上下文，保留全部 64 次调用，不计入正式样本。"""
import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
EMU = ROOT.parent / 'XiangShan/build/operand-isolation/emu'
REF = ROOT.parent / 'NEMU/build/riscv64-nemu-interpreter-so'

def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''): value.update(block)
    return value.hexdigest()

def need(condition,message):
    if not condition: raise ValueError(message)

def prepare(elf,image,parameter,output):
    need(parameter in range(4),'invalid runtime parameter')
    symbols=subprocess.check_output(['riscv64-linux-gnu-nm',str(elf)],text=True)
    found=[int(x.split()[0],16) for x in symbols.splitlines()
           if x.split()[-1]=='bench_runtime_order']
    need(len(found)==1,'missing/duplicate runtime symbol')
    offset=found[0]-0x80000000
    original=image.read_bytes()
    need(0<=offset<min(len(original),0xf00) and original[offset]==0,'unsafe boot parameter')
    prefix=bytearray(original[:offset+1]); prefix[offset]=parameter
    changed=[i for i,(a,b) in enumerate(zip(original,prefix+original[len(prefix):])) if a!=b]
    need(changed==([offset] if parameter else []),'code/layout modified')
    with output.open('xb') as stream: stream.write(prefix)
    return dict(parameter=parameter,mode=parameter>>1,first=parameter&1,
                address=hex(found[0]),offset=offset,overwrite_nbytes=len(prefix),
                changed_offsets=changed,image_sha256=sha(image),overlay_sha256=sha(output))

def audit(path,batches,parameter):
    text=Path(path).read_text(errors='replace')
    need(not re.search(r'FAIL|HIT BAD TRAP|ABORT|different at pc',text),'recorded diagnostic failure')
    need(len(re.findall(r'^\[process exit\] 0$',text,re.M))==1,'missing/failed actual exit')
    need('Difftest enabled' in text and 'HIT GOOD TRAP' in text,'missing difftest/GOOD TRAP')
    need(text.count('e2e diag PASS:')==1,'missing/duplicate diagnostic PASS')
    metas=re.findall(r'e2e diag meta schema=1 mode=(\d+) first=(\d+) batches=(\d+) warmup=8 reps=8 directed=4',text)
    need(metas==[(str(parameter>>1),str(parameter&1),str(batches))],'wrong metadata')
    rows=re.findall(r'e2e diag raw kind=(\d+) round=(\d+) impl=(\d+) slot=(\d+) cycles=(\d+)',text)
    need(len(rows)==64 and text.count('e2e diag raw ')==64,'missing/duplicate/malformed raw records')
    values={}
    for k,r,i,slot,cycles in rows:
        k,r,i,slot,cycles=map(int,(k,r,i,slot,cycles))
        need(k in range(2) and r in range(16) and i in range(2) and slot in range(2),'invalid raw label')
        need(i==((parameter&1)^(r&1)^slot) and cycles>0,'wrong order/cycles')
        need((k,r,i) not in values,'duplicate call')
        values[k,r,i]=cycles
    groups={}
    for k in range(2):
        for i in range(2):
            warm=[values[k,r,i] for r in range(8)]
            measured=[values[k,r,i] for r in range(8,16)]
            median=statistics.median(measured)
            groups[f'{k}/{i}']=dict(warm=warm,measured=measured,median=median,
                warm_tail_drift=warm[-1]/median-1,
                cv=statistics.pstdev(measured)/statistics.mean(measured))
    return dict(mode=parameter>>1,first=parameter&1,batches=batches,groups=groups,
                raw_rows=rows,log=str(path),log_sha256=sha(path))

def write(path,value):
    with path.open('x') as stream: json.dump(value,stream,indent=2); stream.write('\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batches',type=int,choices=(32,256),required=True)
    args=parser.parse_args()
    lock=(ROOT/'stage3/logs/e2e-diagnostic.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # 在诊断前后复核原正式测量记录。
    spec=importlib.util.spec_from_file_location('iso',ROOT/'scripts/complete-vdot-isolation-performance.py')
    iso=importlib.util.module_from_spec(spec); spec.loader.exec_module(iso)
    protected=json.loads((ROOT/'stage3/logs/20261006T060358-16-isolation-perf.state.json').read_text())
    iso.check_frozen(protected)
    stem=f'cie2026-e2e-diagnosis-b{args.batches}-riscv64-xs'
    image=ROOT/'stage3/e2e-diagnosis/build'/f'{stem}.bin'
    elf=image.with_suffix('.elf')
    inputs=[EMU,REF,image,elf,Path(__file__),ROOT/'stage3/vdot-bench/main.c',ROOT/'stage3/vdot-bench/bench.S']
    inputs+=[ROOT/'stage3/e2e-diagnosis'/name for name in ('Makefile','main.c','bench.S','runtime-config.S')]
    frozen={str(p):sha(p) for p in inputs}
    stamp=datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S')
    prefix=ROOT/'stage3/logs'/f'{stamp}-e2e-context-b{args.batches}'
    write(prefix.with_suffix('.inputs.json'),frozen)
    results=[]
    for parameter in range(4):
        need(all(sha(p)==h for p,h in frozen.items()),'diagnostic input changed')
        overlay=prefix.with_name(prefix.name+f'-p{parameter}.parameter.bin')
        record=prepare(elf,image,parameter,overlay)
        log=prefix.with_name(prefix.name+f'-p{parameter}.full.log')
        cmd=[str(EMU),f'--diff={REF}','-i',str(image),'--max-cycles=3000000','-b','0','-e','0',
             f'--gcpt-restore={overlay}',f'--overwrite-nbytes={record["overwrite_nbytes"]}']
        print(f'[diagnostic start] {datetime.datetime.now().astimezone().isoformat()} p={parameter} batches={args.batches} log={log}',flush=True)
        with log.open('x') as stream:
            stream.write('[command] '+json.dumps(cmd)+'\n[parameter] '+json.dumps(record)+'\n[inputs] '+json.dumps(frozen)+'\n')
            stream.flush()
            status=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,cwd=ROOT.parent).returncode
            stream.write(f'\n[process exit] {status}\n')
        result=audit(log,args.batches,parameter)
        result['runtime_parameter']=record
        results.append(result)
        write(prefix.with_name(prefix.name+f'-p{parameter}.audit.json'),result)
        print('[diagnostic PASS] '+json.dumps({k:result[k] for k in ('mode','first','batches','groups','log','log_sha256')},ensure_ascii=False),flush=True)
    need(all(sha(p)==h for p,h in frozen.items()),'diagnostic input changed at end')
    iso.check_frozen(protected)
    write(prefix.with_suffix('.results.json'),dict(runs=results,frozen=frozen,
          caveat='Diagnostic caller intervention, different layout/preconditioning from historic formal binary. Association is not a cache/branch/LSQ root cause. No sample removed.'))
    print(f'[diagnostic suite PASS] {prefix}.results.json',flush=True)

if __name__=='__main__': main()
