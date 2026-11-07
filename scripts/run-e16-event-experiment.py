#!/usr/bin/env python3
"""先完成观察开关对照，再运行四个独立短整核进程。"""
import importlib.util
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audit',ROOT/'stage2/e16-events/audit.py')
A=importlib.util.module_from_spec(spec);spec.loader.exec_module(A)
BUILD=ROOT.parent/'XiangShan/build/sew16-events'
EMU=BUILD/'emu'
REF=ROOT.parent/'NEMU/build/sew16/riscv64-nemu-interpreter-so'
IMAGE=ROOT/'stage2/e16-events/build/cie2026-e16-events-short-riscv64-xs.bin'
SYMBOLS=ROOT/'stage2/e16-events/build/short.symbols'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline-log',type=Path,
      help='reuse the completed observer-off seed101 log after validating its frozen model/program inputs')
    options=parser.parse_args()
    final=json.loads((BUILD/'final.json').read_text())
    A.need(final['status']=='PASS' and A.sha(EMU)==final['emu_sha256'],'unfinished observer')
    prefix=ROOT/'stage2/logs'/datetime.now().strftime('%Y%m%dT%H%M%S-e16-events')
    protected=[EMU,REF,IMAGE,SYMBOLS,Path(__file__),ROOT/'stage2/e16-events/audit.py',
      ROOT/'stage2/e16-events/main.c',ROOT/'stage2/e16-events/control.S',
      ROOT/'stage2/control-tests/control.S',ROOT/'stage2/control-tests/trap.S',ROOT/'stage2/test-contract.h']
    hashes={str(p):A.sha(p) for p in protected}
    inputs=dict(hashes=hashes,init_seeds=[101,202,303,404],
      data_seeds=['56444f54','00000001','9e3779b9','deadbeef'],pilot_seed=101,
      minimum='each seed has at least one complete branch and one complete exception e16 proof; all attempts retained')
    prefix.with_suffix('.plan.json').write_text(json.dumps(inputs,indent=2))
    def frozen():A.need(all(A.sha(p)==h for p,h in hashes.items()),'experiment input changed')
    def run(label,seed,events,trace=False):
        frozen();log=Path(str(prefix)+'-'+label+'.full.log')
        event=Path(str(prefix)+'-'+label+'.jsonl')
        args=[str(EMU),'--diff='+str(REF),'-i',str(IMAGE),'--seed='+str(seed),'--max-cycles=200000']
        if trace:args+=['--dump-commit-trace','-b','0','-e','200000']
        env=os.environ.copy();env.pop('VDOT_EVENT_PATH',None)
        if events:env['VDOT_EVENT_PATH']=str(event)
        print('[run]',label,seed,log,flush=True)
        with log.open('x') as stream:
            code=subprocess.run(args,env=env,stdout=stream,stderr=subprocess.STDOUT).returncode
            stream.write(f'\n[process exit] {code}\n')
        A.need(code==0,f'CPU exited {code}: {log}')
        arch=A.audit_log(log)
        elf={}
        for row in SYMBOLS.read_text().splitlines():
            parts=row.split()
            if len(parts)==3 and parts[2] in A.NAMES:elf[parts[2]]=int(parts[0],16)
        A.need(arch['symbols']==elf,'runtime/ELF symbol mismatch')
        result=dict(label=label,init_seed=seed,log=str(log),architecture=arch)
        if events:
            result['events']=str(event);result['audit']=A.load_events(event,arch['symbols'])
            Path(str(prefix)+'-'+label+'.audit.json').write_text(json.dumps(result,indent=2))
        frozen();print('[PASS]',label,flush=True)
        return result
    if options.baseline_log:
        log=options.baseline_log.resolve()
        A.need(log.name.endswith('-observer-off-101.full.log'),'wrong reused baseline label')
        oldplan=log.with_name(log.name.removesuffix('-observer-off-101.full.log')+'.plan.json')
        old=json.loads(oldplan.read_text())
        # 首次尝试后只修改了离线审核器和协调器；
        # 硬件、镜像、符号表和测试源码必须保持一致。
        for p,h in hashes.items():
            if p not in (str(Path(__file__)),str(ROOT/'stage2/e16-events/audit.py')):
                A.need(old['hashes'].get(p)==h,'reused baseline input mismatch: '+p)
        A.need('Using seed = 101' in log.read_text(),'wrong reused baseline seed')
        baseline=dict(label='observer-off-101',init_seed=101,log=str(log),
                      architecture=A.audit_log(log),reused_from_plan=str(oldplan))
        inputs['reused_baseline']=dict(log=str(log),log_sha256=A.sha(log),plan_sha256=A.sha(oldplan))
        prefix.with_suffix('.plan.json').write_text(json.dumps(inputs,indent=2))
        print('[reuse baseline]',log,flush=True)
    else:baseline=run('observer-off-101',101,False,True)
    runs=[run('seed101',101,True,True)]
    def commits(log):
        text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',Path(log).read_text())
        return re.findall(r'\[\d{2}\] commit pc [^\n]*',text)
    before,after=commits(baseline['log']),commits(runs[0]['log'])
    A.need(before and before==after,'observer changes or lacks architectural commit trace')
    for name in ('instructions','cycles'):
        A.need(baseline['architecture'][name]==runs[0]['architecture'][name],'observer changed '+name)
    observer=dict(status='PASS',commits=len(before),instructions=runs[0]['architecture']['instructions'],
                  cycles=runs[0]['architecture']['cycles'],scope='same event-capable model, logging disabled vs enabled')
    Path(str(prefix)+'.observer.json').write_text(json.dumps(observer,indent=2))
    print('[pilot COMPLETE]',observer,flush=True)
    for seed in (202,303,404):runs.append(run('seed'+str(seed),seed,True))
    frozen()
    result=dict(status='PASS',plan=inputs,observer=observer,baseline=baseline,runs=runs,
                qualification='four independent init processes, each four data seeds; coverage per actual event, not per probe count')
    prefix.with_suffix('.results.json').write_text(json.dumps(result,indent=2))
    print('[e16 experiment COMPLETE]',prefix,flush=True)

if __name__=='__main__':main()
