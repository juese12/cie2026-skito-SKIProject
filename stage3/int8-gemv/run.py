#!/usr/bin/env python3
"""Fixed core/reference, immutable base image, explicit boot-parameter overlay.
No busy polling: subprocess waits directly for completion; progress is logged.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
SRC=Path(__file__).resolve().parent
IMAGE=SRC/'build/cie2026-int8-gemv-riscv64-xs.bin'
ELF=IMAGE.with_suffix('.elf')
REF=ROOT.parent/'NEMU/build/sew16/riscv64-nemu-interpreter-so'
CORE=ROOT.parent/'XiangShan/build/sew16-fixed8/emu'
EVENTS=ROOT.parent/'XiangShan/build/sew16-perf-events/emu'
ACTIVE_PROCESS=None
def stamp():return datetime.now(timezone.utc).isoformat()
def write(path,data):
    with Path(path).open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def update(path,data):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2));temporary.replace(path)
def symbols():
    return {p[2]:int(p[0],16) for row in subprocess.check_output(['riscv64-linux-gnu-nm',str(ELF)],text=True).splitlines()
        if len(p:=row.split())==3}
def overlay(path,profile,first,data):
    raw=IMAGE.read_bytes();offset=symbols()['gemv_params']-0x80000000
    assert 0<=offset and offset+8<0xf00 and raw[offset:offset+8]==bytes([1,1,0,0])+bytes.fromhex('544f4456')
    patch=bytearray(raw[:offset+8]);patch[offset:offset+8]=bytes([1,profile,first,0])+data.to_bytes(4,'little')
    with path.open('xb') as f:f.write(patch)
    return len(patch)
def clean(path):
    raw=path.read_text(errors='replace')
    raw=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',raw)
    return re.sub(r'\[(?:PERF|DEBUG|INFO) *\]\[time=[^\n]*\n','',raw)
def execute(out,label,profile,first,data,seed,events=False,selected_wave=None):
    global ACTIVE_PROCESS
    ov=out/(label+'.overlay.bin');n=overlay(ov,profile,first,data)
    log=out/(label+'.full.log');emu=EVENTS if events else CORE
    command=['stdbuf','-oL','-eL',str(emu),'--diff='+str(REF),'-i',str(IMAGE),'--seed='+str(seed),'--max-cycles=2000000',
        '-b','0','-e','0','--gcpt-restore='+str(ov),'--overwrite-nbytes='+str(n)]
    env=os.environ.copy();env.pop('VDOT_EVENT_PATH',None);env.pop('VDOT_EVENT_STOP_CYCLE',None)
    for key in ('GEMV_WAVE_PATH','GEMV_WAVE_BEGIN','GEMV_WAVE_END'):env.pop(key,None)
    if events:
        env['VDOT_EVENT_PATH']=str(out/(label+'.events.jsonl'));env['VDOT_EVENT_STOP_CYCLE']='200000'
    if selected_wave:
        command[3]=str(ROOT.parent/'XiangShan/build/int8-gemv-wave/emu')
        env.update(GEMV_WAVE_PATH=str(selected_wave[0]),GEMV_WAVE_BEGIN=str(selected_wave[1]),GEMV_WAVE_END=str(selected_wave[2]),
            VDOT_EVENT_PATH=str(out/(label+'.events.jsonl')),VDOT_EVENT_STOP_CYCLE='200000')
    record=dict(label=label,start=stamp(),profile=profile,first=first,data=data,seed=seed,
        command=command,log=str(log),events=env.get('VDOT_EVENT_PATH'))
    if selected_wave:record['wave']=dict(path=str(selected_wave[0]),begin=selected_wave[1],end=selected_wave[2],sampling='after high/low eval; read-only')
    write(out/(label+'.invocation.json'),record)
    print(stamp(),label,'START',flush=True)
    with log.open('x') as stream:
        process=subprocess.Popen(command,cwd=ROOT.parent,env=env,stdout=stream,stderr=subprocess.STDOUT)
        ACTIVE_PROCESS=process
        started=time.monotonic();done=threading.Event();exit_code={}
        def reap():
            exit_code['value']=process.wait();done.set()
        threading.Thread(target=reap,daemon=True).start()
        def progress(status):
            info=dict(label=label,pid=process.pid,status=status,time=stamp(),
                elapsed_seconds=round(time.monotonic()-started,1),log_bytes=log.stat().st_size)
            try:
                fields=Path('/proc/'+str(process.pid)+'/stat').read_text().split()
                info['cpu_seconds']=(int(fields[13])+int(fields[14]))/os.sysconf('SC_CLK_TCK')
            except (OSError,ValueError):pass
            update(out/(label+'.process.json'),info)
            return info
        progress('RUNNING')
        while not done.wait(2400):
            print(stamp(),'40-minute-process-check',json.dumps(progress('RUNNING')),flush=True)
        code=exit_code['value'];progress('EXITED')
        ACTIVE_PROCESS=None
        stream.write('\n[process exit] '+str(code)+'\n')
    raw=clean(log)
    ok=code==0 and 'Difftest enabled' in raw and raw.count('HIT GOOD TRAP')==1 and \
        f'gemv PASS profile={profile} ' in raw and not re.search(r'gemv FAIL|HIT BAD TRAP|ABORT|different at pc',raw)
    record.update(end=stamp(),returncode=code,status='PASS' if ok else 'FAIL')
    write(out/(label+'.result.json'),record)
    print(stamp(),label,record['status'],flush=True)
    if not ok:raise RuntimeError('RTL run failed; preserved '+str(log))
    return record
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--suite',choices=('probe','smoke','full'),required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    if a.suite=='probe':runs=[execute(out,'probe',0,0,0x56444f54,101,True)]
    elif a.suite=='smoke':runs=[execute(out,'smoke',1,0,0x56444f54,101)]
    else:
        runs=[execute(out,'full-'+str(seed),2,i,data,seed) for i,(seed,data) in enumerate(
            zip((101,202,303,404),(0x56444f54,1,0x9e3779b9,0xdeadbeef)))]
    write(out/'results.json',dict(status='PASS',runs=runs))
if __name__=='__main__':main()
