#!/usr/bin/env python3
"""复现原正式镜像，定位并采集端到端调用窗口。"""
import datetime
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'stage3/logs/20261006T060358-16-isolation-perf-full-run0-20261006T063347-16-bench.full.log'
COMMIT = re.compile(r'\[\d{2}\] commit pc ([0-9a-f]+) inst ([0-9a-f]+) wen (\d+) dst (\d+) data ([0-9a-f]+) idx [0-9a-f]+[^\n]*\n')

def need(ok, message):
    if not ok:
        raise ValueError(message)

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')

def calibrate(path):
    scope, selected, values, offsets = [], {}, {}, []
    time, clock = 0, None
    def sample():
        nonlocal clock
        current=values.get('clock')
        if clock==1 and current==0 and 'mcycle' in values and 'cycle' in values:
            offsets.append(dict(time=time,mcycle=values['mcycle'],cycle=values['cycle'],offset=(values['mcycle']-values['cycle']) % (1<<64)))
        clock=current
    with path.open() as stream:
        header=True
        for line in stream:
            line=line.strip()
            fields=line.split()
            if header:
                if line.startswith('$scope'): scope.append(fields[2])
                elif line.startswith('$upscope'): scope.pop()
                elif line.startswith('$var'):
                    name='.'.join(scope+[fields[4]])
                    if name=='TOP.clock': selected[fields[3]]='clock'
                    elif name.endswith('.csr.csrMod.mcycle.reg_ALL'): selected[fields[3]]='mcycle'
                    elif name.endswith('.rob.difftest_module_8.io_bits_cycleCnt'): selected[fields[3]]='cycle'
                elif line.startswith('$enddefinitions'):
                    need(set(selected.values())=={'clock','mcycle','cycle'}, 'missing boot calibration signals: '+str(selected))
                    header=False
                continue
            if line.startswith('#'):
                sample(); time=int(line[1:])
            elif line.startswith('b'):
                bits,code=line[1:].split()
                if code in selected and not re.search('[xz]',bits): values[selected[code]]=int(bits,2)
            elif line[:1] in ('0','1') and line[1:].strip() in selected:
                values[selected[line[1:].strip()]]=int(line[0])
    sample()
    stable=[x for x in offsets if x['cycle']>=8]
    need(len(stable)>=8 and len({x['offset'] for x in stable})==1, 'unstable mcycle/trap calibration')
    return dict(offset=stable[-1]['offset'],samples=stable,wave_sha256=sha(path),qualification='short boot calibration only, NOT full architectural regression')

def windows(text):
    """使用原 ELF 中的 PC，不根据改过布局的诊断 ELF 推断地址。"""
    pending = None
    pairs = []
    for match in COMMIT.finditer(text):
        pc, inst, wen, dst, data = match.groups()
        pc, inst, data = int(pc,16), int(inst,16), int(data,16)
        if pc in (0x8000034c, 0x800003d4, 0x80000448, 0x800004a0):
            need(pending is None and inst == 0xb0002373 and (wen,dst)==('1','06'), 'invalid start timestamp')
            pending = dict(start=data, start_pc=hex(pc))
        elif pc == 0x800004c8:
            need(pending is not None and inst == 0xb0002e73 and (wen,dst)==('1','28'), 'invalid end timestamp')
            pending.update(end=data, cycles=data-pending['start'])
            pairs.append(pending)
            pending = None
    need(pending is None and len(pairs)==96, 'need all 96 original kernel timestamp pairs')
    for n, pair in enumerate(pairs):
        kind, position = divmod(n,32)
        phase, within = divmod(position,16)
        rep, slot = divmod(within,2)
        impl = rep % 2 ^ slot
        expected_pc = ((0x800003d4,0x8000034c),(0x800003d4,0x8000034c),(0x800004a0,0x80000448))[kind][impl]
        need(pair['start_pc']==hex(expected_pc), 'call order/implementation differs from original first=0')
        need(pair['cycles']>0 and (not n or pair['start']>pairs[n-1]['end']), 'nonmonotonic timestamps')
        pair.update(index=n, kind=('batch4','e2e','chain')[kind], phase=('warm','measured')[phase], rep=rep, slot=slot, impl=('vdot','rvv')[impl])
    return pairs

def main():
    # 两遍处理期间始终持有这两把锁。
    locks=[]
    for name in ('benchmark.lock','e2e-diagnostic.lock'):
        lock=(ROOT/'stage3/logs'/name).open('a')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        locks.append(lock)
    guard=module('event_guard',ROOT/'scripts/complete-vdot-isolation-performance.py')
    state=json.loads((ROOT/'stage3/logs/20261006T060358-16-isolation-perf.state.json').read_text())
    guard.check_frozen(state)
    old=OLD.read_text()
    emu=ROOT.parent/'XiangShan/build/operand-isolation/emu'
    ref=ROOT.parent/'NEMU/build/riscv64-nemu-interpreter-so'
    image=ROOT/'stage3/vdot-bench-p0/build/cie2026-stage3-vdot-bench-v3-full-riscv64-xs.bin'
    elf=image.with_suffix('.elf')
    overlay=ROOT/'stage3/logs/runtime-overlay.mCdaF2/parameter.bin'
    runtime=json.loads(re.search(r'^\[runtime parameter\] (.+)$',old,re.M)[1])
    need(sha(overlay)==runtime['overlay_sha256'] and image.read_bytes()[:1305]==overlay.read_bytes(), 'original unchanged first=0 overlay unavailable')
    prefix=ROOT/'stage3/logs'/datetime.datetime.now().astimezone().strftime('%Y%m%dT%H%M%S-original-e2e-events')
    inputs={str(p):sha(p) for p in (emu,ref,image,elf,overlay,OLD,Path(__file__))}
    write(prefix.with_suffix('.inputs.json'),inputs)
    print('[prefix]',prefix,flush=True)
    base=[str(emu),'--diff='+str(ref),'-i',str(image),'--max-cycles=10000000','--gcpt-restore='+str(overlay),'--overwrite-nbytes=1305']
    bench=module('event_bench',ROOT/'stage3/tests/analyze-bench.py')
    reference=bench.audit(OLD)

    bootwave=prefix.with_name(prefix.name+'-boot.vcd')
    bootlog=prefix.with_name(prefix.name+'-boot.full.log')
    bootcmd=base+['--max-cycles=128','-b','0','-e','128','--dump-wave-full','--wave-path='+str(bootwave)]
    with bootlog.open('x') as stream:
        stream.write('[command] '+json.dumps(bootcmd)+'\n'); stream.flush()
        boot=subprocess.run(bootcmd,cwd=ROOT.parent,stdout=stream,stderr=subprocess.STDOUT)
        stream.write(f'\n[process exit] {boot.returncode}\n')
    calibration=calibrate(bootwave)
    write(prefix.with_suffix('.calibration.json'),calibration)
    print('[boot calibration]',calibration['offset'],flush=True)

    def run(label, extra):
        need(all(sha(p)==h for p,h in inputs.items()), 'capture input changed')
        guard.check_frozen(state)
        raw=prefix.with_name(prefix.name+'-'+label+'.full.log')
        cmd=base+extra
        with raw.open('x') as stream:
            stream.write('[command] '+json.dumps(cmd)+'\n')
            stream.write('[runtime parameter] '+json.dumps(runtime)+'\n')
            for role,p in (('emu',emu),('ref',ref),('image',image)):
                stream.write(f'[artifact {role}] {sha(p)}\n')
            stream.flush()
            print('[running]',label,raw,flush=True)
            process=subprocess.run(cmd,cwd=ROOT.parent,stdout=stream,stderr=subprocess.STDOUT)
            stream.write(f'\n[process exit] {process.returncode}\n')
        need(process.returncode==0, 'emulator process failed: '+str(raw))
        text=raw.read_text(errors='replace')
        normal=prefix.with_name(prefix.name+'-'+label+'.uart.log')
        with normal.open('x') as stream:
            stream.write(COMMIT.sub('',text))
        audit=bench.audit(normal)
        for key in ('meta','groups','empty','warmup_summaries'):
            need(audit[key]==reference[key], 'original benchmark changed under tracing: '+key)
        # 客体及模拟器总计数必须与原运行一致，不能只比较中位数。
        for pattern in (r'instrCnt = (\d+), cycleCnt = (\d+)',r'Guest cycle spent: (\d+)'):
            need(re.findall(pattern,text)==re.findall(pattern,old) and re.findall(pattern,text), 'original execution totals changed')
        write(prefix.with_name(prefix.name+'-'+label+'.audit.json'),dict(raw_log=str(raw),raw_sha256=sha(raw),normalized_audit=audit))
        guard.check_frozen(state)
        print('[PASS original replay]',label,flush=True)
        return text

    trace=run('locate',['-b','0','-e','3000000','--dump-commit-trace'])
    pairs=windows(trace)
    for pair in pairs:
        if pair['phase']=='measured':
            need(pair['cycles']==reference['groups'][pair['kind']][pair['impl']]['raw'][pair['rep']], 'timestamp/raw discrepancy')
        elif pair['rep'] in (0,7):
            warm=next(w for w in reference['warmup_summaries'] if w[:2]==(pair['kind'],pair['impl']))
            need(pair['cycles']==int(warm[3 if pair['rep']==0 else 4]), 'warm timestamp discrepancy')
    fast,slow=pairs[47],pairs[48]
    need((fast['cycles'],slow['cycles'])==(4415,5178), 'target fast/slow mismatch')
    # mcycle 与模拟器陷入周期相差数拍，先保留保护区间；
    # 精确积分边界由实际 CSR 波形数值确定。
    begin,end=(fast['start']-calibration['offset']) % (1<<64)-256,(slow['end']-calibration['offset']) % (1<<64)+256
    need(0<=begin<end<3000000, 'unsafe capture range')
    write(prefix.with_suffix('.windows.json'),dict(status='PASS',all_calls=pairs,fast=fast,slow=slow,log_begin=begin,log_end=end,guard_cycles=256))
    wave=prefix.with_suffix('.vcd')
    need(not wave.exists(), 'wave output exists')
    run('wave',['-b',str(begin),'-e',str(end),'--dump-wave-full','--dump-commit-trace','--wave-path='+str(wave)])
    write(prefix.with_suffix('.capture.json'),dict(status='PASS',wave=str(wave),wave_sha256=sha(wave),wave_bytes=wave.stat().st_size,windows=str(prefix.with_suffix('.windows.json'))))
    need(all(sha(p)==h for p,h in inputs.items()), 'capture input changed at completion')
    guard.check_frozen(state)
    print('[capture COMPLETE]',prefix,flush=True)

if __name__=='__main__':
    main()
