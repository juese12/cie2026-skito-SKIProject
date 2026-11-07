#!/usr/bin/env python3
"""固定旧核/原镜像的控制和 e2e 重放；默认仅核查，必须显式 --run 才启动 CPU。"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'manifest/isolation-evidence-replay.json'
FAST='stage3/logs/20261008T114325-original-e2e-events-resumed'
MID='stage3/logs/20261008T200238-original-other-bins'
CONTROL_LOG='stage2/logs/20261006T033620-32-control-56444f54.full.log'
CONTROL_JSON='stage2/waveform/20261006T033620-isolation-control-resumed.vcd.control.json'


def need(value,message):
    if not value:raise ValueError(message)


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def normalized(value):return json.loads(json.dumps(value))


def dependencies(emu):
    result=subprocess.run(['ldd',str(emu)],capture_output=True,text=True,check=True)
    need('not found' not in result.stdout,'missing runtime library')
    return [Path(s).resolve() for s in re.findall(r'(?:=>\s+|^\s*)(/[^\s]+)',result.stdout,re.M)]


def record_plan():
    need(not PLAN.exists(),'replay plan already exists')
    frozen=json.loads((ROOT/'stage3/logs/20261006T060358-16-isolation-perf.state.json').read_text())['frozen']
    paths={
        'emu':ROOT.parent/'XiangShan/build/operand-isolation/emu',
        'ref':ROOT.parent/'NEMU/build/riscv64-nemu-interpreter-so',
        'bench':ROOT/'stage3/vdot-bench-p0/build/cie2026-stage3-vdot-bench-v3-full-riscv64-xs.bin',
        'bench_elf':ROOT/'stage3/vdot-bench-p0/build/cie2026-stage3-vdot-bench-v3-full-riscv64-xs.elf',
        'control':ROOT/'stage2/control-tests/build/cie2026-stage2-control-seed56444f54-riscv64-xs.bin',
        'control_elf':ROOT/'stage2/control-tests/build/cie2026-stage2-control-seed56444f54-riscv64-xs.elf',
        'symbols':ROOT/'stage2/control-tests/build/cie2026-stage2-control-seed56444f54.symbols',
        'overlay':ROOT/'stage3/logs/runtime-overlay.mCdaF2/parameter.bin',
        'dram_config':ROOT.parent/'DRAMsim3/configs/XiangShan.ini',
    }
    for role in ('emu','ref','bench','bench_elf'):
        p=paths[role];need(sha(p)==frozen[str(p)],'original experiment binary changed: '+role)
    control=json.loads((ROOT/CONTROL_JSON).read_text())
    need(sha(ROOT/CONTROL_LOG)==control['log_sha256'] and sha(paths['symbols'])==control['symbols_sha256'],
         'control source audit changed')
    summary=(ROOT/'stage2/logs/20261006T033620-isolation-control-wave-resumed.full.log').read_text()
    for role in ('emu','ref','control'):
        need(sha(paths[role]) in summary,'control binary identity missing from original run: '+role)
    need(paths['overlay'].read_bytes()==paths['bench'].read_bytes()[:1305],'original first=0 overlay differs')
    files=[ROOT/CONTROL_JSON,ROOT/CONTROL_LOG]
    for prefix in (ROOT/FAST,ROOT/MID):
        files.extend(prefix.with_suffix(s) for s in ('.events.json','.cycles.json'))
        files.append(prefix.with_name(prefix.name+'-wave.full.log'))
    files += [ROOT/'stage3/logs/20261007T221501-original-e2e-events.windows.json',
              ROOT/'stage3/logs/20261007T221501-original-e2e-events.calibration.json',
              ROOT/'stage3/logs/20261006T060358-16-isolation-perf-full-run0-20261006T063347-16-bench.full.log',
              ROOT/'stage3/reports/figures/isolation-retained/signal-excerpts.json',
              ROOT/'scripts/check-vdot-control.py',ROOT/'stage3/tests/analyze-original-e2e-events.py',
              ROOT/'stage3/tests/analyze-bench.py',Path(__file__)]
    files += dependencies(paths['emu'])
    identities={str(p.resolve()):sha(p) for p in [*paths.values(),*files]}
    plan=dict(schema=1,paths={k:str(p) for k,p in paths.items()},identities=identities,
              windows={'control':[0,26000],'e2e':[828182,838423],'middle':[892399,897515]},
              seeds={'control':101,'e2e':0,'middle':0},expected_cycles={'fast':4415,'middle':4924,'slow':5178},
              original_control=CONTROL_JSON,original_control_log=CONTROL_LOG,
              original_fast=FAST,original_middle=MID,
              qualification='Exact retained old binaries/images and local runtime environment; original VCDs are NOT required. Reproduction means equivalent measurements/control coverage, not byte-identical dumps.')
    with PLAN.open('x') as stream:json.dump(plan,stream,indent=2)
    return plan


def check(plan):
    for path,expected in plan['identities'].items():need(sha(path)==expected,'replay input changed: '+path)
    for alias in plan['paths'].values():
        resolved=str(Path(alias).resolve())
        need(resolved in plan['identities'] and sha(alias)==plan['identities'][resolved],
             'replay path/config symlink changed: '+alias)
    need('not found' not in subprocess.run(['ldd',plan['paths']['emu']],capture_output=True,text=True,check=True).stdout,
         'missing runtime dependency')
    control=module('replay_control','scripts/check-vdot-control.py')
    saved=json.loads((ROOT/CONTROL_JSON).read_text())
    control.audit_log(ROOT/CONTROL_LOG,'56444f54')
    need(saved['architectural_status']==saved['control_status']=='PASS','old control audit incomplete')
    ev=module('replay_ev','stage3/tests/analyze-original-e2e-events.py')
    full=json.loads((ROOT/FAST).with_suffix('.cycles.json').read_text())
    middle=json.loads((ROOT/MID).with_suffix('.cycles.json').read_text())
    original=json.loads((ROOT/FAST).with_suffix('.events.json').read_text())
    mid_saved=json.loads((ROOT/MID).with_suffix('.events.json').read_text())
    cases=[(full['rows'],original),*(
        (full['rows']+middle['rows'],case) for case in mid_saved['comparisons'])]
    for rows,expected in cases:
        windows={k:v['target'] for k,v in expected['windows'].items()}
        actual=ev.analyze(full['columns'],rows,windows)
        need(normalized(actual)=={k:expected[k] for k in actual},'cached e2e observations do not reproduce')
        intervals=ev.attribution(full['columns'],rows,actual,expected['committed_pc_counts'])
        need(normalized(intervals)==expected['interval_attribution'],'cached cycle attribution differs')
    return dict(status='PASS',mode='read-only; no CPU simulation',
                control_branch_groups=len(saved['proof']['branch']),control_exception_groups=len(saved['proof']['exception']),
                e2e_cycles=[4415,4924,5178],original_vcd_required=False)


def command(plan,kind,wave):
    p=plan['paths'];args=[p['emu'],'--diff='+p['ref'],'-i',p['control'] if kind=='control' else p['bench'],
                        '--max-cycles=10000000','--seed='+str(plan['seeds'][kind])]
    if kind!='control':args+=['--gcpt-restore='+p['overlay'],'--overwrite-nbytes=1305']
    begin,end=plan['windows'][kind]
    return args+['-b',str(begin),'-e',str(end),'--dump-wave-full','--dump-commit-trace','--wave-path='+str(wave)]


def run(plan,kind,out):
    out=out.resolve();need(out!=ROOT and out!=ROOT.parent and not out.exists(),'choose a new dedicated output directory')
    locks=[]
    for name in ('benchmark.lock','e2e-diagnostic.lock','isolation-regression.lock'):
        folder='stage2/logs' if name.startswith('isolation') else 'stage3/logs'
        stream=(ROOT/folder/name).open('a');fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(stream)
    out.mkdir(parents=True);prefix=out/'replay';wave=prefix.with_suffix('.vcd');log=out/'replay-wave.full.log'
    cmd=command(plan,kind,wave)
    with log.open('x') as stream:
        stream.write('[command] '+json.dumps(cmd)+'\n');stream.flush()
        if kind!='control':
            original=(ROOT/FAST).with_name(Path(FAST).name+'-wave.full.log').read_text()
            for line in original.splitlines():
                if line.startswith(('[runtime parameter]','[artifact ')):stream.write(line+'\n')
            stream.flush()
        process=subprocess.run(cmd,cwd=ROOT.parent,stdout=stream,stderr=subprocess.STDOUT)
        stream.write(f'\n[process exit] {process.returncode}\n')
    need(process.returncode==0,'replay CPU failed; preserve outputs')
    if kind=='control':
        control=module('replay_control_run','scripts/check-vdot-control.py')
        result=control.audit_log(log,'56444f54');result.update(control.audit_wave(wave,control.read_symbols(plan['paths']['symbols'])))
    else:
        bench=module('replay_bench','stage3/tests/analyze-bench.py')
        capture=module('replay_capture','scripts/capture-original-e2e-events.py')
        text=log.read_text(errors='replace');normalized_log=out/'replay-wave.uart.log'
        normalized_log.write_text(capture.COMMIT.sub('',text))
        expected=bench.audit(capture.OLD);observed=bench.audit(normalized_log)
        for key in ('meta','groups','empty','warmup_summaries'):need(observed[key]==expected[key],'replay benchmark differs: '+key)
        ev=module('replay_events_run','stage3/tests/analyze-original-e2e-events.py');columns,rows=ev.stream(wave)
        full=json.loads((ROOT/FAST).with_suffix('.events.json').read_text())
        if kind=='e2e':windows={k:v['target'] for k,v in full['windows'].items()}
        else:
            old=json.loads((ROOT/FAST).with_suffix('.cycles.json').read_text());need(columns==old['columns'],'signal columns differ')
            rows=old['rows']+rows
            mid=json.loads((ROOT/MID).with_suffix('.events.json').read_text())
            windows={'fast':full['windows']['fast']['target'],'slow':mid['comparisons'][0]['windows']['slow']['target']}
        result=ev.analyze(columns,rows,windows)
        result['committed_pc_counts']=ev.committed(text if kind=='e2e' else (ROOT/FAST).with_name(Path(FAST).name+'-wave.full.log').read_text()+text,windows)
        result['interval_attribution']=ev.attribution(columns,rows,result,result['committed_pc_counts'])
    with (out/'replay.audit.json').open('x') as stream:json.dump(result,stream,indent=2)
    check(plan);print('Reproduction experiment PASS:',out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-plan',action='store_true');parser.add_argument('--run',choices=['control','e2e','middle'])
    parser.add_argument('--out-dir',type=Path);args=parser.parse_args()
    plan=record_plan() if args.record_plan else json.loads(PLAN.read_text())
    print(json.dumps(check(plan)),flush=True)
    need(bool(args.run)==bool(args.out_dir),'--run and --out-dir must be supplied together')
    if args.run:run(plan,args.run,args.out_dir)


if __name__=='__main__':main()
