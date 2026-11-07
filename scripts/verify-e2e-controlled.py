#!/usr/bin/env python3
"""固定地址的调用上下文干预，共十二组，不生成波形。"""
import argparse
from collections import Counter
import datetime
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
c=module('control_common',ROOT/'scripts/capture-original-e2e-events.py')
MATRIX=[(phase,pressure) for pressure in range(2) for phase in range(6)]

def prepare(original,symbols,phase,pressure):
    c.need((phase,pressure) in MATRIX,'invalid matrix arm')
    offsets={k:v-0x80000000 for k,v in symbols.items()}
    slots=offsets['diag_phase'];press=offsets['diag_pressure'];parameter=offsets['diag_parameter']
    c.need(all(0<=v<len(original) for v in offsets.values()),'symbol outside image')
    c.need(original[slots:slots+24]==b'\x13\0\0\0'*6,'phase region is not six 32-bit nops')
    c.need(original[press:press+24]==(0x001f8f93).to_bytes(4,'little')*6,'pressure region is not six addi t6,t6,1')
    c.need(original[parameter]==0,'base parameter is not zero')
    result=bytearray(original)
    result[slots:slots+4*phase]=b'\x01\0\x01\0'*phase
    if pressure:result[press:press+24]=(0x03ff8fb3).to_bytes(4,'little')*6
    result[parameter]=phase+(pressure<<3)
    allowed=set(range(slots,slots+4*phase))|({parameter} if phase or pressure else set())
    if pressure:allowed|=set(range(press,press+24))
    changed=[i for i,(a,b) in enumerate(zip(original,result)) if a!=b]
    c.need(set(changed)<=allowed and len(result)==len(original),'unexpected bytes/layout changed')
    return bytes(result),dict(phase=phase,pressure=pressure,extra_nop_instructions=phase,changed_offsets=changed,symbols={k:hex(v) for k,v in symbols.items()})

def audit(log,phase,pressure):
    text=Path(log).read_text(errors='replace')
    c.need(not re.search(r'FAIL|HIT BAD TRAP|ABORT|different at pc',text),'CPU/diagnostic failure')
    c.need(len(re.findall(r'^\[process exit\] 0$',text,re.M))==1,'missing/failed actual exit')
    c.need('Difftest enabled' in text and text.count('HIT GOOD TRAP')==1 and text.count('controlled PASS:')==1,'missing/duplicate complete PASS')
    metas=re.findall(r'controlled meta schema=1 phase=(\d+) pressure=(\d+) batches=256 rounds=6 first=0 directed=4',text)
    c.need(metas==[(str(phase),str(pressure))],'wrong diagnostic metadata')
    rows=re.findall(r'controlled raw round=(\d+) slot=(\d+) impl=(\d+) cycles=(\d+)',text)
    c.need(len(rows)==12 and text.count('controlled raw ')==12,'missing/duplicate/malformed call')
    expected=[(r,s,(r&1)^s) for r in range(6) for s in range(2)]
    c.need([(int(r),int(s),int(i)) for r,s,i,n in rows]==expected,'wrong call order')
    c.need(all(int(n)>0 for r,s,i,n in rows),'nonpositive cycles')
    values=[dict(round=int(r),slot=int(s),impl=int(i),cycles=int(n)) for r,s,i,n in rows]
    bins={}
    for impl in range(2):
        for slot in range(2):
            bins[f'{impl}/{slot}']=dict(Counter(v['cycles'] for v in values if v['impl']==impl and v['slot']==slot))
    return dict(phase=phase,pressure=pressure,calls=values,all_call_bins_by_impl_slot=bins,log=str(log),log_sha256=c.sha(log))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--after',type=Path,required=True,help='single-bin coordinator; require completion before running')
    parser.add_argument('--detach',action='store_true')
    args=parser.parse_args()
    if args.detach:
        log=ROOT/'stage3/logs'/datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S-controlled.coordinator.log')
        with log.open('x') as stream:
            p=subprocess.Popen(['python3','-u',str(Path(__file__).resolve()),'--after',str(args.after.resolve())],cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        print(json.dumps(dict(pid=p.pid,coordinator=str(log))));return
    while True:
        text=args.after.read_text(errors='replace')
        c.need('Traceback' not in text,'single-bin predecessor failed; stop, do not rerun')
        if '[other bins COMPLETE]' in text:break
        print('[waiting for ONE-bin completion; NO wave queue]',datetime.datetime.now().astimezone().isoformat(),flush=True);time.sleep(50)
    predecessor=Path(re.search(r'^\[other bins COMPLETE\] (.+)$',text,re.M)[1])
    evidence=json.loads(predecessor.with_suffix('.events.json').read_text())
    c.need(evidence['status']=='PASS','predecessor evidence not PASS')
    locks=[]
    for name in ('benchmark.lock','e2e-diagnostic.lock'):
        lock=(ROOT/'stage3/logs'/name).open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
    guard=module('control_guard',ROOT/'scripts/complete-vdot-isolation-performance.py')
    state=json.loads((ROOT/'stage3/logs/20261006T060358-16-isolation-perf.state.json').read_text());guard.check_frozen(state)
    directory=ROOT/'stage3/e2e-controlled';image=directory/'build/cie2026-e2e-controlled-riscv64-xs.bin';elf=image.with_suffix('.elf')
    names=('diag_phase','diag_pressure','diag_parameter','bench_kernel')
    nm=subprocess.check_output(['riscv64-linux-gnu-nm','-n',str(elf)],text=True)
    symbols={line.split()[-1]:int(line.split()[0],16) for line in nm.splitlines() if line.split()[-1] in names}
    c.need(set(symbols)==set(names),'missing intervention symbols')
    base=image.read_bytes()
    original=ROOT/'stage3/vdot-bench-p0/build/cie2026-stage3-vdot-bench-v3-full-riscv64-xs.bin'
    offset=symbols['bench_kernel']-0x80000000
    kernel=base[offset:offset+0x1e0]
    c.need(kernel==original.read_bytes()[0x314:0x4f4],'original complete kernel bytes differ')
    emu=ROOT.parent/'XiangShan/build/operand-isolation/emu';ref=ROOT.parent/'NEMU/build/riscv64-nemu-interpreter-so'
    protected=[image,elf,emu,ref,original,Path(__file__),ROOT/'stage3/vdot-bench/main.c',ROOT/'stage3/vdot-bench/bench.S',predecessor.with_suffix('.events.json')]
    protected+=[directory/n for n in ('main.c','bench.S','Makefile')]
    inputs={str(p.resolve()):c.sha(p) for p in protected}
    prefix=ROOT/'stage3/logs'/datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S-e2e-controlled')
    c.write(prefix.with_suffix('.inputs.json'),inputs)
    c.write(prefix.with_suffix('.plan.json'),dict(matrix=MATRIX,rounds=6,batches=256,waveforms=0,kernel_sha256=hashlib.sha256(kernel).hexdigest(),predecessor=str(predecessor),qualification='independent diagnostic caller/layout; phase segmentation and ALU class separately varied; pressure does NOT force IQ2; all 144 calls retained'))
    print('[matrix start]',prefix,flush=True)
    runs=[]
    for phase,pressure in MATRIX:
        c.need(all(c.sha(p)==h for p,h in inputs.items()),'controlled input changed')
        variant,record=prepare(base,symbols,phase,pressure)
        c.need(variant[offset:offset+0x1e0]==kernel,'kernel changed in variant')
        arm=prefix.with_name(prefix.name+f'-s{phase}-p{pressure}')
        binary=arm.with_suffix('.bin')
        with binary.open('xb') as stream:stream.write(variant)
        record.update(image_sha256=c.sha(binary),kernel_sha256=hashlib.sha256(kernel).hexdigest())
        c.write(arm.with_suffix('.variant.json'),record)
        command=[str(emu),'--diff='+str(ref),'-i',str(binary),'--max-cycles=1000000','-b','0','-e','0']
        c.need(not any('wave' in x for x in command),'wave generation forbidden')
        log=arm.with_suffix('.full.log')
        print('[arm running]',phase,pressure,log,flush=True)
        with log.open('x') as stream:
            stream.write('[command] '+json.dumps(command)+'\n[variant] '+json.dumps(record)+'\n');stream.flush()
            p=subprocess.run(command,cwd=ROOT.parent,stdout=stream,stderr=subprocess.STDOUT)
            stream.write(f'\n[process exit] {p.returncode}\n')
        c.need(p.returncode==0,'controlled emulator failed')
        result=audit(log,phase,pressure);result['variant']=record;runs.append(result)
        c.write(arm.with_suffix('.audit.json'),result)
        print('[arm PASS]',phase,pressure,result['all_call_bins_by_impl_slot'],flush=True)
    c.need(all(c.sha(p)==h for p,h in inputs.items()),'controlled input changed at completion');guard.check_frozen(state)
    c.write(prefix.with_suffix('.results.json'),dict(status='PASS',runs=runs,inputs=inputs,qualification='NO new waveform. Timing intervention demonstrates sensitivity, not direct decoder/IQ causal isolation. No sample removed. Not formal performance.'))
    print('[controlled COMPLETE]',prefix,flush=True)

if __name__=='__main__':main()
