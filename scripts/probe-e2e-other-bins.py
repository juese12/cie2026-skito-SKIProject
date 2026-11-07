#!/usr/bin/env python3
"""仅补采原镜像中一个 4924 周期调用，复用已有快慢窗口证据。"""
import argparse
import datetime
import fcntl
import gzip
import json
import multiprocessing
import os
from pathlib import Path
import re
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
import importlib.util
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m
c = module('bin_capture', ROOT/'scripts/capture-original-e2e-events.py')
ev = module('bin_events', ROOT/'stage3/tests/analyze-original-e2e-events.py')
PREVIOUS = ROOT/'stage3/logs/20261007T221501-original-e2e-events'
REUSE = ROOT/'stage3/logs/20261008T114325-original-e2e-events-resumed'
TARGET_INDEX = 55

def compress_fifo(fifo, destination):
    # 不保存未压缩波形；FIFO 由本次任务独立创建并管理。
    with open(fifo,'rb') as source, gzip.open(destination,'xb',compresslevel=1) as target:
        shutil.copyfileobj(source,target,1<<20)

def filtered_stream(path, spans):
    """仅保留预定义保护窗口；扫描完整 VCD，不为间隙虚构采样行。"""
    scope, signals, values, columns = [], {}, {}, []
    rows=[]; time=0; previous_clock=None
    def sample():
        nonlocal previous_clock
        clock=values.get(signals['TOP.clock'])
        falling=previous_clock==1 and clock==0; previous_clock=clock
        if not falling: return
        timestamp=values.get(signals[ev.MCYCLE])
        if timestamp is None or not any(a<=timestamp<b for a,b in spans): return
        row=[values.get(signals[n]) for n in columns]
        c.need(all(v is not None for v in row),'unknown selected signal')
        rows.append([time]+row)
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rt',encoding='ascii') as stream:
        header=True
        for raw in stream:
            line=raw.strip(); fields=line.split()
            if header:
                if line.startswith('$scope'): scope.append(fields[2])
                elif line.startswith('$upscope'): scope.pop()
                elif line.startswith('$var'):
                    name='.'.join(scope+[fields[4]])
                    if ev.selected(name): signals[name]=fields[3]
                elif line.startswith('$enddefinitions'):
                    c.need(all(n in signals for n in ('TOP.clock',ev.MCYCLE,ev.CYCLE)), 'missing counters')
                    columns=sorted(signals); codes=set(signals.values()); header=False
                continue
            if line.startswith('#'):
                if values: sample()
                time=int(line[1:])
            elif line.startswith('b'):
                bits,code=line[1:].split()
                if code in codes: values[code]=int(bits,2) if not re.search('[xz]',bits) else None
            elif line[:1] in ('0','1','x','z') and line[1:] in codes:
                values[line[1:]]=int(line[0]) if line[0] in '01' else None
    sample()
    c.need(rows and all(b[0]>a[0] for a,b in zip(rows,rows[1:])), 'invalid timeline')
    return ['vcd_time']+columns,rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detach',action='store_true')
    args=parser.parse_args()
    if args.detach:
        log=ROOT/'stage3/logs'/datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S-other-bins.coordinator.log')
        with log.open('x') as stream:
            p=subprocess.Popen(['python3','-u',str(Path(__file__).resolve())],cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        print(json.dumps(dict(pid=p.pid,coordinator=str(log)))); return
    locks=[]
    for name in ('benchmark.lock','e2e-diagnostic.lock'):
        lock=(ROOT/'stage3/logs'/name).open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(lock)
    guard=module('bins_guard',ROOT/'scripts/complete-vdot-isolation-performance.py')
    state=json.loads((ROOT/'stage3/logs/20261006T060358-16-isolation-perf.state.json').read_text());guard.check_frozen(state)
    inputs=json.loads(PREVIOUS.with_suffix('.inputs.json').read_text())
    for path in (Path(__file__),Path(ev.__file__),PREVIOUS.with_suffix('.windows.json'),PREVIOUS.with_suffix('.calibration.json'),REUSE.with_suffix('.capture.json'),REUSE.with_suffix('.events.json'),REUSE.with_suffix('.cycles.json'),REUSE.with_name(REUSE.name+'-wave.full.log')): inputs[str(path.resolve())]=c.sha(path)
    c.need(all(c.sha(p)==h for p,h in inputs.items()),'capture input changed')
    original=json.loads(PREVIOUS.with_suffix('.windows.json').read_text())
    target=original['all_calls'][TARGET_INDEX]
    c.need(target['cycles']==4924 and target['impl']=='vdot' and target['kind']=='e2e','predefined target changed')
    reused=json.loads(REUSE.with_suffix('.events.json').read_text())
    c.need(reused['status']=='PASS' and reused['wave_sha256']==json.loads(REUSE.with_suffix('.capture.json').read_text())['wave_sha256'],'reused evidence is not finalized')
    offset=json.loads(PREVIOUS.with_suffix('.calibration.json').read_text())['offset']
    begin=target['start']-offset-128;end=target['end']-offset+64
    prefix=ROOT/'stage3/logs'/datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S-original-other-bins')
    c.write(prefix.with_suffix('.inputs.json'),inputs)
    c.write(prefix.with_suffix('.plan.json'),dict(target=target,reuse=str(REUSE),log_begin=begin,log_end=end,pre_guard=128,post_guard=64,qualification='ONE original call; fast/slow cycles reused, no intervention; gzip FIFO avoids raw VCD on disk'))
    old=(PREVIOUS.with_name(PREVIOUS.name+'-wave.full.log')).read_text(errors='replace')
    command=json.loads(re.search(r'^\[command\] (.+)$',old,re.M)[1]);wave=prefix.with_suffix('.vcd.gz')
    command[command.index('-b')+1]=str(begin);command[command.index('-e')+1]=str(end)
    log=prefix.with_name(prefix.name+'-wave.full.log')
    print('[running]',prefix,flush=True)
    with tempfile.TemporaryDirectory(prefix='e2e-one-wave-',dir=ROOT/'stage3/logs') as tmp:
        fifo=Path(tmp)/'wave.fifo';os.mkfifo(fifo)
        command=[('--wave-path='+str(fifo)) if x.startswith('--wave-path=') else x for x in command]
        compressor=multiprocessing.get_context('fork').Process(target=compress_fifo,args=(fifo,wave));compressor.start()
        try:
            with log.open('x') as stream:
                stream.write('[command] '+json.dumps(command)+'\n[compressed wave] '+str(wave)+'\n')
                for line in old.splitlines():
                    if line.startswith(('[runtime parameter]','[artifact ')):stream.write(line+'\n')
                stream.flush();p=subprocess.run(command,cwd=ROOT.parent,stdout=stream,stderr=subprocess.STDOUT)
                stream.write(f'\n[process exit] {p.returncode}\n')
            if p.returncode==0:
                compressor.join(30);c.need(not compressor.is_alive() and compressor.exitcode==0,'wave compression failed')
        finally:
            if compressor.is_alive():compressor.terminate();compressor.join()
    c.need(p.returncode==0,'other-bin emulator failed')
    text=log.read_text(errors='replace');normal=prefix.with_name(prefix.name+'-wave.uart.log')
    with normal.open('x') as stream:stream.write(c.COMMIT.sub('',text))
    bench=module('bins_bench',ROOT/'stage3/tests/analyze-bench.py')
    reference=bench.audit(c.OLD);audit=bench.audit(normal)
    for key in ('meta','groups','empty','warmup_summaries'):c.need(audit[key]==reference[key],'original samples changed: '+key)
    for pattern in (r'instrCnt = (\d+), cycleCnt = (\d+)',r'Guest cycle spent: (\d+)'):c.need(re.findall(pattern,text)==re.findall(pattern,c.OLD.read_text()),'original totals changed')
    c.write(prefix.with_suffix('.audit.json'),dict(raw_sha256=c.sha(log),audit=audit))
    print('[full replay PASS; parsing selected windows]',flush=True)
    columns,new_rows=filtered_stream(wave,[(target['start']-128,target['end']+64)])
    reused_cycles=json.loads(REUSE.with_suffix('.cycles.json').read_text())
    c.need(columns==reused_cycles['columns'],'reused signal columns differ')
    rows=reused_cycles['rows']+new_rows
    comparisons=[]
    fast=original['all_calls'][47]
    for label in ('fast','slow'):
        reference_target=reused['windows'][label]['target']
        windows=dict(fast=reference_target,slow=target)
        result=ev.analyze(columns,rows,windows)
        counts=ev.committed(REUSE.with_name(REUSE.name+'-wave.full.log').read_text(errors='replace')+text,windows)
        result['committed_pc_counts']=counts
        result['interval_attribution']=ev.attribution(columns,rows,result,counts)
        comparisons.append(dict(reference_label=label,**result))
    c.need(all(c.sha(p)==h for p,h in inputs.items()),'protected input changed at completion');guard.check_frozen(state)
    c.write(prefix.with_suffix('.events.json'),dict(status='PASS',comparisons=comparisons,wave_sha256=c.sha(wave),wave_bytes=wave.stat().st_size,inputs=inputs))
    # 只保存新增观察周期，已有参考记录继续使用原路径。
    c.write(prefix.with_suffix('.cycles.json'),dict(columns=columns,rows=new_rows,reused_cycles=str(REUSE.with_suffix('.cycles.json'))))
    print('[other bins COMPLETE]',prefix,flush=True)

if __name__=='__main__':main()
