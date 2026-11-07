#!/usr/bin/env python3
"""固定版本的 v4 启动参数覆盖、整核调用及严格原始数据解析。"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
SRC=Path(__file__).resolve().parent
_edition_spec=importlib.util.spec_from_file_location('perf_chinese_edition',ROOT/'scripts/chinese-edition.py')
EDITION=importlib.util.module_from_spec(_edition_spec)
_edition_spec.loader.exec_module(EDITION)
IMAGE=SRC/'build/cie2026-vdot-sew16-perf-v4-riscv64-xs.bin'
ELF=IMAGE.with_suffix('.elf')
CORES={
 'new':(ROOT.parent/'XiangShan/build/sew16-fixed8/emu',ROOT.parent/'NEMU/build/sew16/riscv64-nemu-interpreter-so'),
 'old':(ROOT.parent/'XiangShan/build/operand-isolation/emu',ROOT.parent/'NEMU/build/riscv64-nemu-interpreter-so'),
 'events':(ROOT.parent/'XiangShan/build/sew16-perf-events/emu',ROOT.parent/'NEMU/build/sew16/riscv64-nemu-interpreter-so')}

def need(ok,msg):
    if not ok:raise ValueError(msg)

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def symbols():
    out=subprocess.check_output(['riscv64-linux-gnu-nm',str(ELF)],text=True)
    return {p[2]:int(p[0],16) for row in out.splitlines() if len(p:=row.split())==3}

def overlay(path,profile,first,wide,data):
    need(profile in (0,1,2) and first in (0,1) and wide in (0,1) and 0<data<2**32,'bad parameters')
    offset=symbols()['perf_params']-0x80000000;original=IMAGE.read_bytes()
    need(0<=offset and offset+8<min(len(original),0xf00),'parameter outside safe boot prefix')
    need(original[offset:offset+8]==bytes([4,1,0,1])+bytes.fromhex('544f4456'),'unexpected original parameter bytes')
    result=bytearray(original[:offset+8]);result[offset:offset+8]=bytes([4,profile,first,wide])+data.to_bytes(4,'little')
    changes=[i for i,(a,b) in enumerate(zip(original,result)) if a!=b]
    need(all(offset<=i<offset+8 for i in changes),'executable bytes changed')
    with Path(path).open('xb') as f:f.write(result)
    return dict(offset=offset,overwrite_nbytes=len(result),changed_offsets=changes,overlay_sha256=sha(path))

def oracle(a,b,bits):
    def lanes(raw):
        raw=int(raw,16)
        return [v-(1<<bits) if v&(1<<(bits-1)) else v for v in ((raw>>(bits*i))&((1<<bits)-1) for i in range(8))]
    return sum(x*y for x,y in zip(lanes(a),lanes(b)))%2**(32 if bits==8 else 64)

def fields(row):
    return dict(re.findall(r'(\w+)=([\w]+)',row))

def parse(path,params):
    raw=Path(path).read_text(errors='replace')
    raw=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',raw)
    # 已知且完整的宿主记录可能插在 UART 字符之间。
    guest=re.sub(r'\[(?:PERF|DEBUG|INFO) *\]\[time=[^\n]*\n','',raw)
    need('Difftest enabled' in raw and raw.count('HIT GOOD TRAP')==1,'missing differential GOOD TRAP')
    need(not re.search(r'FAIL|HIT BAD TRAP|ABORT|different at pc',raw+'\n'+guest),'architectural failure')
    need(re.findall(r'^\[process exit\] (-?\d+)$',raw,re.M)==['0'],'missing actual process exit zero')
    need(guest.count('perf4 PASS full128=1 CSR=1 nonzero_feedback=1 exact_signed=1')==1,'missing exact final coverage')
    meta=[fields(x) for x in guest.splitlines() if x.startswith('perf4 meta ')]
    need(len(meta)==1,'missing/duplicate metadata');meta=meta[0]
    profile,first,wide,data=[params[k] for k in ('profile','first','wide','data')]
    reps=(2,4,8)[profile];warm=(0,2,8)[profile];random=(0,8,64)[profile]
    expected_meta=dict(schema='4',profile=str(profile),first=str(first),wide=str(wide),data=f'{data:08x}',
      reps=str(reps),warm=str(warm),random=str(random),deferred='1')
    need(meta==expected_meta,'metadata differs from frozen invocation')
    widths=[8,16] if wide else [8];equivalence={};cases={};samples={}
    for row in guest.splitlines():
        if row.startswith('perf4 equivalence '):
            x=fields(row);bits=int(x['bits']);need(bits in widths and bits not in equivalence,'bad equivalence width')
            need(x==dict(bits=str(bits),dot=str(32+random),rvv=str(32+random),full128='1',CSR='1'),'incomplete equivalence')
            equivalence[bits]=x
        elif row.startswith('perf4 case '):
            x=fields(row);bits=int(x['bits']);kind=int(x['kind']);key=(bits,kind)
            need(bits in widths and kind in range(5) and key not in cases,'bad/duplicate case')
            lengths=[(1,4,64)[profile]]*2+([4,16,64] if profile==2 else [1,2,4])
            need(int(x['batches'])==lengths[kind] and int(x['dots'])==4*lengths[kind],'wrong case length')
            need(len(x['a'])==len(x['b'])==32 and len(x['expected'])==16,'not full-width input/expected')
            value=x['a'];previous=None;count=int(x['dots']) if kind>=2 else 1
            for _ in range(count):
                answer=oracle(value,x['b'],bits)
                if kind>=2:need(answer and answer!=previous,'zero/fixed feedback sequence')
                previous=answer;value=f'{answer:032x}'
            need(int(x['expected'],16)==answer and int(x['chain_steps'])==(count if kind>=2 else 0),'independent oracle disagreement')
            cases[key]=x
        elif row.startswith('perf4 raw '):
            x=fields(row);bits,kind,phase,rep,slot,impl,cycles=[int(x[k]) for k in ('bits','kind','phase','rep','slot','impl','cycles')]
            need(bits in widths and kind in range(5) and phase in (0,1) and slot in (0,1),'bad sample address')
            need(0<=rep<(reps if phase else warm) and impl==(first^(rep&1)^slot) and cycles>0,'bad sample order/value')
            key=(bits,kind,phase,rep,impl);need(key not in samples,'duplicate sample');samples[key]=dict(x)
        elif row.startswith('perf4 seq '):
            head,sep,values=row.partition(' cycles=');x=fields(head)
            need(bool(sep),'missing compact values')
            bits,kind,phase,impl=[int(x[k]) for k in ('bits','kind','phase','impl')]
            need(bits in widths and kind in range(5) and phase in (0,1) and impl in (0,1),'bad compact sample group')
            vector=values.split(',');need(len(vector)==(reps if phase else warm),'missing compact samples')
            for rep,value in enumerate(vector):
                need(value.isdecimal() and int(value)>0,'bad compact cycle value')
                slot=impl^first^(rep&1);key=(bits,kind,phase,rep,impl)
                need(key not in samples,'duplicate sample')
                samples[key]=dict(bits=str(bits),kind=str(kind),phase=str(phase),rep=str(rep),slot=str(slot),impl=str(impl),cycles=value)
    need(set(equivalence)==set(widths) and len(cases)==5*len(widths),'missing widths/cases')
    need(len(samples)==len(widths)*5*(warm+reps)*2,'missing raw samples')
    inst,cycles=map(int,re.search(r'Core-0 instrCnt = (\d+), cycleCnt = (\d+)',raw).groups())
    return dict(status='PASS',meta=meta,equivalence=list(equivalence.values()),cases=list(cases.values()),
      samples=list(samples.values()),instructions=inst,cycles=cycles,log_sha256=sha(path))

def inputs(core):
    paths=list(CORES[core])+[IMAGE,ELF,SRC/'main.c',SRC/'bench.S',SRC/'params.S',SRC/'Makefile',Path(__file__)]
    return {str(p):sha(p) for p in paths}

def frozen(hashes):
    # 原实验记录不变，只额外接受内容和注释边界均已严格核对的中文版本。
    need(all(EDITION.matches_expected(ROOT,p,h) for p,h in hashes.items()),'frozen input changed')

def run(prefix,label,core,profile,first,wide,data,seed):
    prefix=Path(str(prefix)+'-'+label)
    params=dict(profile=profile,first=first,wide=wide,data=data,seed=seed)
    hashes=inputs(core);frozen(hashes)
    log=Path(str(prefix)+'.full.log');ov=Path(str(prefix)+'.overlay.bin')
    boot=overlay(ov,profile,first,wide,data);emu,ref=CORES[core]
    event=Path(str(prefix)+'.jsonl')
    cmd=[str(emu),'--diff='+str(ref),'-i',str(IMAGE),'--seed='+str(seed),'--max-cycles=10000000',
      '-b','0','-e','0','--gcpt-restore='+str(ov),'--overwrite-nbytes='+str(boot['overwrite_nbytes'])]
    record=dict(label=label,core=core,params=params,inputs=hashes,overlay=boot,command=cmd,log=str(log))
    env=os.environ.copy();env.pop('VDOT_EVENT_PATH',None)
    if core=='events':
        env['VDOT_EVENT_PATH']=str(event);env['VDOT_EVENT_STOP_CYCLE']='100000'
        record['events']=str(event);record['event_stop_cycle']=100000
    with Path(str(prefix)+'.invocation.json').open('x') as f:json.dump(record,f,indent=2)
    print('[run]',label,core,params,flush=True)
    with log.open('x') as f:
        code=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
        f.write(f'\n[process exit] {code}\n')
    need(code==0,f'CPU exit {code}: {log}')
    record['audit']=parse(log,params);frozen(hashes)
    with Path(str(prefix)+'.audit.json').open('x') as f:json.dump(record,f,indent=2)
    print('[PASS]',label,'cycles',record['audit']['cycles'],flush=True)
    return record
