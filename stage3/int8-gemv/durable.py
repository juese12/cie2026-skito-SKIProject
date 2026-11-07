#!/usr/bin/env python3
"""Host-side detached, locked, resumable formal queue. Never rebuild the image."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import analyze as A
import run as R
import report as REPORT

def freeze_inputs(full,allow_existing=False):
    """Validate compiled input copies before resuming a completed process."""
    snapshots=full/'compiled-inputs'
    pairs=(('measurement.bin',R.IMAGE),('measurement.elf',R.ELF))
    if not snapshots.exists():
        if not allow_existing:
            assert not list(full.glob('*.result.json')),'completed results lack saved input copies; use a new prefix'
        temporary=full/'.compiled-inputs-creating'
        if temporary.exists():temporary.rename(full/('.compiled-inputs-interrupted-'+str(time.time_ns())))
        temporary.mkdir()
        for name,path in pairs:shutil.copy2(path,temporary/name)
        code=temporary/'source';code.mkdir()
        for path in R.SRC.iterdir():
            if path.is_file() and (path.suffix in ('.c','.h','.S') or path.name in ('Makefile','protocol.json')):
                shutil.copy2(path,code/path.name)
        R.write(temporary/'说明.json',dict(scope='exact compiled application and source copies for resume; not a new run',time=R.stamp()))
        temporary.rename(snapshots)
    for name,path in pairs:
        assert (snapshots/name).read_bytes()==path.read_bytes(),'compiled application differs from saved experiment; use a new prefix'
    return R.IMAGE.read_bytes(),R.ELF.read_bytes()

def worker_status(prefix,proc_root=Path('/proc')):
    state=Path(str(prefix)+'.pipeline.json')
    data=json.loads(state.read_text()) if state.exists() else dict(status='NOT_STARTED')
    pid=data.get('pid');command=proc_root/str(pid)/'cmdline';alive=False
    if command.exists():
        args=command.read_bytes().split(b'\0')
        alive=str(Path(__file__).resolve()).encode() in args and str(prefix).encode() in args and b'--worker' in args
    result=dict(pipeline=data,worker_alive=alive)
    seed=data.get('current_seed')
    if seed:
        path=Path(str(prefix)+'-full')/('full-'+str(seed)+'.process.json')
        if path.exists():
            result['process']=json.loads(path.read_text());child=result['process']['pid']
            current=proc_root/str(child)/'cmdline';child_alive=False
            if current.exists():
                args=current.read_bytes().split(b'\0')
                overlay=Path(str(prefix)+'-full')/('full-'+str(seed)+'.overlay.bin')
                child_alive=str(R.IMAGE).encode() in args and ('--gcpt-restore='+str(overlay)).encode() in args
            result['child_alive']=child_alive
            if child_alive:
                fields=(proc_root/str(child)/'stat').read_text().split()
                result['child_state']=fields[2]
                result['child_cpu_seconds']=(int(fields[13])+int(fields[14]))/os.sysconf('SC_CLK_TCK')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prefix',type=Path,required=True)
    mode=p.add_mutually_exclusive_group();mode.add_argument('--worker',action='store_true')
    mode.add_argument('--status',action='store_true');mode.add_argument('--stop',action='store_true')
    p.add_argument('--figures',type=Path,default=R.ROOT/'stage3/reports/figures/int8-gemv')
    a=p.parse_args();prefix=a.prefix.resolve();figures=a.figures.resolve()
    if a.status or a.stop:
        data=worker_status(prefix)
        if a.stop and data['worker_alive']:
            os.kill(data['pipeline']['pid'],signal.SIGTERM);data['stop_requested']=True
        elif a.stop and data.get('child_alive'):
            os.kill(data['process']['pid'],signal.SIGTERM);data['orphan_stop_requested']=True
        print(json.dumps(data,ensure_ascii=False));return
    if not a.worker:
        out=Path(str(prefix)+'.durable.log')
        launch=Path(str(prefix)+'.durable-launch.json');attempt=0
        while out.exists() or launch.exists():
            attempt+=1;out=Path(str(prefix)+f'.durable-retry{attempt}.log')
            launch=Path(str(prefix)+f'.durable-launch-retry{attempt}.json')
        with out.open('x') as stream:
            child=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--worker','--prefix',str(prefix),'--figures',str(figures)],
                cwd=R.ROOT.parent,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                close_fds=True,start_new_session=True)
        R.write(launch,dict(pid=child.pid,time=R.stamp(),log=str(out),
            command='detached host worker; sequential four-process formal queue; no RTL changes'))
        print(json.dumps(dict(started=True,pid=child.pid,log=str(out))));return
    lock=Path(str(prefix)+'.durable.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=Path(str(prefix)+'.pipeline.json');full=Path(str(prefix)+'-full');full.mkdir(exist_ok=True)
    def stage(name,status='RUNNING',**extra):
        R.update(state,dict(stage=name,status=status,pid=os.getpid(),time=R.stamp(),**extra))
        print(R.stamp(),name,status,flush=True)
    def terminated(signum,frame):
        stage('worker-interrupted','FAIL',signal=signum)
        if R.ACTIVE_PROCESS is not None:R.ACTIVE_PROCESS.terminate()
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,terminated);signal.signal(signal.SIGINT,terminated)
    try:
        stage('checking-inputs');frozen,elf=freeze_inputs(full)
        runs=[]
        for i,(seed,data) in enumerate(zip((101,202,303,404),(0x56444f54,1,0x9e3779b9,0xdeadbeef))):
            assert R.IMAGE.read_bytes()==frozen and R.ELF.read_bytes()==elf,'compiled image changed during measurement'
            label='full-'+str(seed);saved=full/(label+'.result.json')
            stage('formal',current_seed=seed,completed=len(runs))
            if saved.exists():
                record=json.loads(saved.read_text())
                assert (record['profile'],record['first'],record['data'],record['seed'])==(2,i,data,seed)
                if record['status']=='PASS' and record['returncode']==0:
                    local=dict(record,log=str(full/(label+'.full.log')));A.parse(local);runs.append(record)
                    print(R.stamp(),label,'REUSED COMPLETE',flush=True);continue
            incomplete=[p for p in full.glob(label+'.*') if p.is_file()]
            if incomplete:
                active=full/(label+'.process.json')
                if active.exists():
                    prior=json.loads(active.read_text());pid=prior.get('pid')
                    command=Path('/proc/'+str(pid)+'/cmdline')
                    if prior.get('status')=='RUNNING' and command.exists():
                        argv=command.read_bytes().replace(b'\0',b' ').decode(errors='replace')
                        assert str(R.IMAGE) not in argv,'prior measurement is still alive; refusing duplicate'
                archive=full/('interrupted-'+label+'-'+str(time.time_ns()));archive.mkdir()
                for path in incomplete:path.rename(archive/path.name)
                R.write(archive/'interruption.json',dict(status='INCOMPLETE_NOT_REUSED',time=R.stamp(),
                    reason='no successful result and validated complete log; previous files preserved'))
            record=R.execute(full,label,2,i,data,seed)
            A.parse(record);runs.append(record)
        if not (full/'results.json').exists():R.write(full/'results.json',dict(status='PASS',runs=runs))
        stage('analysis');analysis=A.analyze(full)
        target=Path(str(prefix)+'.analysis.json')
        if target.exists():assert json.loads(target.read_text())==json.loads(json.dumps(analysis))
        else:
            subprocess.run([sys.executable,str(R.SRC/'analyze.py'),str(full),'--out',str(target)],check=True)
        evidence=json.loads((figures/'signal-evidence.json').read_text());assert evidence['status']=='PASS'
        stage('report');path=R.ROOT/'stage3/reports/INT8矩阵向量乘应用测试与性能报告.md'
        R.update(Path(str(prefix)+'.report-ready.json'),dict(status='PASS',time=R.stamp()))
        text=REPORT.report(analysis,evidence,path,prefix,figures);temporary=path.with_suffix('.tmp');temporary.write_text(text);temporary.replace(path)
        stage('simulation-and-analysis','PASS')
        delivery=Path(str(prefix)+'.delivery.json')
        if not delivery.exists():R.write(delivery,dict(status='PASS',time=R.stamp(),formal_processes=4,
            samples=analysis['total_samples'],warnings=len(analysis['warnings']),report=str(path),
            figures=[str(p) for p in sorted(figures.glob('*.png'))],scope='durable host recovery; same compiled GEMV image'))
        print(R.stamp(),'DURABLE GEMV COMPLETE',flush=True)
    except BaseException as e:
        stage('failed','FAIL',error=repr(e));raise
if __name__=='__main__':main()
