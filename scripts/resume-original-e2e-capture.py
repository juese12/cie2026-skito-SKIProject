#!/usr/bin/env python3
"""仅恢复中断的波形复现，保留已经完成的定位证据。"""
import argparse
import datetime
import fcntl
import json
from pathlib import Path
import re
import subprocess
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('capture',ROOT/'scripts/capture-original-e2e-events.py')
c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous',type=Path)
    parser.add_argument('--detach',action='store_true')
    args=parser.parse_args(); previous=args.previous.resolve()
    if args.detach:
        monitor=ROOT/'stage3/logs'/datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S-original-e2e-recovery.coordinator.log')
        with monitor.open('x') as stream:
            process=subprocess.Popen(['python3','-u',str(Path(__file__).resolve()),str(previous)],cwd=ROOT.parent,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        print(json.dumps(dict(pid=process.pid,coordinator=str(monitor))))
        return
    locks=[]
    for name in ('benchmark.lock','e2e-diagnostic.lock'):
        lock=(ROOT/'stage3/logs'/name).open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); locks.append(lock)
    old_inputs=json.loads(previous.with_suffix('.inputs.json').read_text())
    c.need(all(c.sha(p)==h for p,h in old_inputs.items()),'original capture input changed')
    c.need(not previous.with_suffix('.capture.json').exists(),'previous capture already completed; do not repeat')
    guard=c.module('recovery_guard',ROOT/'scripts/complete-vdot-isolation-performance.py')
    state=json.loads((ROOT/'stage3/logs/20261006T060358-16-isolation-perf.state.json').read_text()); guard.check_frozen(state)
    bench=c.module('recovery_bench',ROOT/'stage3/tests/analyze-bench.py')
    reference=bench.audit(c.OLD)
    located=bench.audit(previous.with_name(previous.name+'-locate.uart.log'))
    for key in ('meta','groups','empty','warmup_summaries'): c.need(located[key]==reference[key],'completed locate audit changed')
    windows=json.loads(previous.with_suffix('.windows.json').read_text())
    raw_old=previous.with_name(previous.name+'-wave.full.log')
    old_text=raw_old.read_text(errors='replace')
    c.need('HIT GOOD TRAP' not in old_text and '[process exit]' not in old_text,'previous replay finished; inspect before retry')
    prefix=ROOT/'stage3/logs'/datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S-original-e2e-events-resumed')
    print('[prefix]',prefix,flush=True)
    protected=dict(old_inputs)
    for path in (Path(__file__),ROOT/'stage3/tests/analyze-original-e2e-events.py',ROOT/'stage3/tests/test-original-e2e-events.py',previous.with_suffix('.windows.json'),previous.with_name(previous.name+'-locate.audit.json')): protected[str(path.resolve())]=c.sha(path)
    c.write(prefix.with_suffix('.inputs.json'),protected)
    c.write(prefix.with_suffix('.windows.json'),windows)
    c.write(prefix.with_suffix('.recovery.json'),dict(previous=str(previous),interrupted_log=str(raw_old),interrupted_log_sha256=c.sha(raw_old),interrupted_wave=str(previous.with_suffix('.vcd')),interrupted_wave_sha256=c.sha(previous.with_suffix('.vcd')),qualification='previous window evidence retained; previous wave run has no GOOD TRAP/recorded exit and is NOT a full PASS'))
    cmd=json.loads(re.search(r'^\[command\] (.+)$',old_text,re.M)[1])
    wave=prefix.with_suffix('.vcd'); cmd=[('--wave-path='+str(wave)) if x.startswith('--wave-path=') else x for x in cmd]
    runtime=json.loads(re.search(r'^\[runtime parameter\] (.+)$',old_text,re.M)[1])
    log=prefix.with_name(prefix.name+'-wave.full.log')
    with log.open('x') as stream:
        stream.write('[command] '+json.dumps(cmd)+'\n[runtime parameter] '+json.dumps(runtime)+'\n')
        for role,value in re.findall(r'^\[artifact (emu|ref|image)\] ([0-9a-f]{64})$',old_text,re.M): stream.write(f'[artifact {role}] {value}\n')
        stream.flush(); print('[running] waveform replay only',flush=True)
        process=subprocess.run(cmd,cwd=ROOT.parent,stdout=stream,stderr=subprocess.STDOUT)
        stream.write(f'\n[process exit] {process.returncode}\n')
    c.need(process.returncode==0,'resumed emulator failed')
    text=log.read_text(errors='replace'); normal=prefix.with_name(prefix.name+'-wave.uart.log')
    with normal.open('x') as stream: stream.write(c.COMMIT.sub('',text))
    audit=bench.audit(normal)
    for key in ('meta','groups','empty','warmup_summaries'): c.need(audit[key]==reference[key],'resumed sample changed: '+key)
    for pattern in (r'instrCnt = (\d+), cycleCnt = (\d+)',r'Guest cycle spent: (\d+)'):
        c.need(re.findall(pattern,text)==re.findall(pattern,c.OLD.read_text()) and re.findall(pattern,text),'execution totals changed')
    c.write(prefix.with_name(prefix.name+'-wave.audit.json'),dict(raw_log=str(log),raw_sha256=c.sha(log),normalized_audit=audit))
    c.write(prefix.with_suffix('.capture.json'),dict(status='PASS',wave=str(wave),wave_sha256=c.sha(wave),wave_bytes=wave.stat().st_size,windows=str(prefix.with_suffix('.windows.json')),completed_locate=str(previous)))
    c.need(all(c.sha(p)==h for p,h in protected.items()),'protected recovery input changed')
    guard.check_frozen(state)
    print('[PASS original resumed replay]',flush=True)
    subprocess.run(['python3',str(ROOT/'stage3/tests/analyze-original-e2e-events.py'),str(prefix)],cwd=ROOT.parent,check=True)
    print('[recovery COMPLETE]',prefix,flush=True)

if __name__=='__main__': main()
