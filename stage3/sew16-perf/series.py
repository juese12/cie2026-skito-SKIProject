#!/usr/bin/env python3
"""烟雾测试及计时证据通过后，运行四组配对的新旧核 v4 进程。"""
import argparse
from datetime import datetime
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import common as C

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preflight',type=Path,required=True);p.add_argument('--timer',type=Path,required=True)
    p.add_argument('--resume',type=Path)
    args=p.parse_args()
    lock=(C.ROOT/'stage3/logs/sew16-perf4.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    pre=json.loads(args.preflight.read_text());timer=json.loads(args.timer.read_text())
    C.need(pre['status']==timer['status']=='PASS','unfinished smoke/boundary gate')
    C.need([r['label'] for r in pre['runs']]==['probe','smoke0','smoke1','old-smoke'],'wrong preflight set')
    C.need(timer['elf_sha256']==C.sha(C.ELF) and timer['event_sha256']==C.sha(pre['runs'][0]['events']),'probe/image mismatch')
    for r in pre['runs']:
        C.frozen(r['inputs']);C.need(C.parse(r['log'],r['params'])==r['audit'],'preflight replay mismatch')
    if args.resume:
        state_path=args.resume;state=json.loads(state_path.read_text());prefix=Path(state['prefix'])
        C.need(state['gates']=={str(args.preflight):C.sha(args.preflight),str(args.timer):C.sha(args.timer)},'changed gates')
        C.frozen(state['frozen'])
        for r in state['runs']:C.need(C.parse(r['log'],r['params'])==r['audit'],'completed run changed')
    else:
        prefix=C.ROOT/'stage3/logs'/datetime.now().strftime('%Y%m%dT%H%M%S-sew16-perf4-full')
        state_path=Path(str(prefix)+'.state.json')
        jobs=[]
        for i,(seed,data) in enumerate(zip((101,202,303,404),(0x56444f54,1,0x9e3779b9,0xdeadbeef))):
            for core in (('old','new') if i%2==0 else ('new','old')):
                jobs.append(dict(label=core+str(i),core=core,profile=2,first=i%2,wide=int(core=='new'),data=data,seed=seed))
        frozen={**C.inputs('new'),**C.inputs('old')}
        for file in (Path(__file__),C.SRC/'protocol.json'):frozen[str(file)]=C.sha(file)
        analysis_sources={str(p):C.sha(p) for p in (C.SRC/'analyze.py',C.SRC/'protocol.json')}
        state=dict(status='RUNNING',prefix=str(prefix),jobs=jobs,runs=[],attempts=[],frozen=frozen,analysis_sources=analysis_sources,
          gates={str(args.preflight):C.sha(args.preflight),str(args.timer):C.sha(args.timer)})
        with open(str(prefix)+'.analysis-sources.json','x') as f:json.dump({str(p):Path(p).read_text() for p in analysis_sources},f,indent=2)
        with state_path.open('x') as f:json.dump(state,f,indent=2)
    def save():
        with state_path.open('w') as f:json.dump(state,f,indent=2)
    print('[plan]',prefix,flush=True)
    for job in state['jobs'][len(state['runs']):]:
        C.frozen(state['frozen']);attempt=len([a for a in state['attempts'] if a['job']==job['label']])
        label=job['label']+('' if attempt==0 else '-retry'+str(attempt))
        state['status']='RUNNING';state['attempts'].append(dict(job=job['label'],label=label,status='RUNNING'));save()
        try:
            run=C.run(prefix,label,**{k:v for k,v in job.items() if k!='label'})
            text=Path(run['log']).read_text()
            C.need(f'Using seed = {job["seed"]}\n' in text and f'Seed={job["seed"]} Guest cycle spent:' in text,'wrong actual init seed')
            state['runs'].append(run);state['attempts'][-1]['status']='PASS';save()
        except Exception as error:
            state['status']='FAILED';state['attempts'][-1].update(status='FAILED',error=str(error));save();raise
    C.frozen(state['frozen']);state['status']='CPU_PASS';save()
    results=Path(str(prefix)+'.results.json')
    with results.open('x') as f:json.dump(state,f,indent=2)
    print('[perf4 full CPU COMPLETE]',prefix,flush=True)
    C.frozen(state['analysis_sources'])
    analysis=Path(str(prefix)+'.analysis.json')
    report=C.ROOT/'stage3/reports'/(prefix.name+'-performance.md')
    subprocess.run([sys.executable,str(C.SRC/'analyze.py'),str(results),'--out',str(analysis),'--report',str(report)],check=True)
    state.update(report_status='DATA_REPORT_PASS',analysis=str(analysis),report=str(report));save()
    print('[perf4 experiment COMPLETE]',report,flush=True)

if __name__=='__main__':main()
