#!/usr/bin/env python3
"""Exercise report rejection paths and the lossless selected-signal filter."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import shutil
import sys
import analyze as A
import run as R

import signals as W
def rejects(fn):
    try:fn()
    except (ValueError,AssertionError):return
    raise AssertionError('malformed evidence accepted')
with tempfile.TemporaryDirectory(prefix='gemv-tools-') as d:
    d=Path(d);results=[]
    for pi,(seed,data) in enumerate(zip((101,202,303,404),(0x56444f54,1,0x9e3779b9,0xdeadbeef))):
        lines=['Difftest enabled','gemv meta schema=1 profile=2 first=%d seed=%08x warm=2 reps=6 cases=30'%(pi,data)]
        lines += ['gemv checks impl=%d calls=92'%i for i in range(4)]
        for c,(m,k) in enumerate(((16,64),(17,65))):
            ds=(data^(0x13579bdf*(c+1)))&0xffffffff or 1
            answer=A.values(ds,m,k)
            lines+=['gemv case id=%d m=%d k=%d kp=%d data=%08x y=%s'%(c,m,k,(k+7)//8*8,ds,','.join(map(str,answer)))]
            for mode in range(2):
                for impl in range(4):lines+=['gemv seq case=%d mode=%d impl=%d cycles=%s'%(c,mode,impl,','.join([str(4000//(impl+1))]*8))]
        lines+=['gemv PASS profile=2 checked_each_row=1 guards=1 signed=1 data_seeds=4','HIT GOOD TRAP','[process exit] 0']
        path=d/('seed%d.log'%seed);path.write_text('\n'.join(lines)+'\n')
        results.append(dict(status='PASS',returncode=0,profile=2,first=pi,data=data,seed=seed,log=str(path)))
    R.write(d/'results.json',dict(status='PASS',runs=results));valid=A.analyze(d)
    assert valid['total_samples']==512 and not valid['warnings']
    with tempfile.TemporaryDirectory(prefix='gemv-moved-') as moved:
        moved=Path(moved)
        shutil.copyfile(d/'results.json',moved/'results.json')
        for r in results:shutil.copyfile(r['log'],moved/Path(r['log']).name)
        metadata=json.loads((moved/'results.json').read_text())
        for r in metadata['runs']:r['log']='/unavailable-old-workspace/'+Path(r['log']).name
        (moved/'results.json').write_text(json.dumps(metadata))
        assert A.analyze(moved)['groups']==valid['groups']
        (moved/Path(results[0]['log']).name).unlink()
        rejects(lambda:A.analyze(moved))
    original=Path(results[0]['log']).read_text()
    for before,after in (('Difftest enabled','Difftest disabled'),('checked_each_row=1','checked_each_row=0'),
        ('HIT GOOD TRAP','HIT BAD TRAP'),('calls=92','calls=91'),('cycles=1000,1000','cycles=0,1000')):
        changed=original.replace(before,after);assert changed!=original
        Path(results[0]['log']).write_text(changed);rejects(lambda:A.parse(results[0]))
    Path(results[0]['log']).write_text(original+'gemv seq case=0 mode=0 impl=0 cycles=1,1,1,1,1,1,1,1\n')
    rejects(lambda:A.parse(results[0]));Path(results[0]['log']).write_text(original)
    broken=copy.deepcopy(results[0]);broken['data']^=1;rejects(lambda:A.parse(broken))
    # Synthetic input tests the reader only, never used in report figures.
    fields=W.REQUIRED;header=['$timescale 1ps $end','$scope module GEMV $end'];code={}
    for i,name in enumerate(sorted(fields)):
        ident='id'+str(i);code[name]=ident;header+=['$var wire '+str(1 if name=='clock' else 128)+' '+ident+' '+name+' $end']
    header+=['$upscope $end']
    header+=['$enddefinitions $end','#17']
    header += [('b0 ' if name=='clock' else 'b101 ')+ident for name,ident in code.items()]
    header+=['b111 unrelated','#18','b1 '+code['clock']]
    source=d/'source.vcd';source.write_text('\n'.join(header)+'\n')
    frames,widths=W.read_wave(source)
    assert len(frames)==2 and frames[0]['time']==17 and frames[1]['time']==18
    assert frames[0]['sum']==frames[1]['sum']==5 and (frames[0]['clock'],frames[1]['clock'])==(0,1)
    source.write_text(source.read_text().replace('b101 '+code['sum'],'bx '+code['sum']))
    rejects(lambda:W.read_wave(source))
import durable as D
saved_paths=(R.IMAGE,R.ELF,R.SRC)
try:
    with tempfile.TemporaryDirectory(prefix='gemv-resume-unit-') as d:
        d=Path(d);source=d/'source';source.mkdir();(source/'main.c').write_text('unit source')
        R.IMAGE=d/'input.bin';R.ELF=d/'input.elf';R.SRC=source
        R.IMAGE.write_bytes(b'unit image');R.ELF.write_bytes(b'unit elf')
        full=d/'full';full.mkdir()
        assert D.freeze_inputs(full)==(b'unit image',b'unit elf')
        assert D.freeze_inputs(full)==(b'unit image',b'unit elf')
        R.IMAGE.write_bytes(b'changed');rejects(lambda:D.freeze_inputs(full))
finally:R.IMAGE,R.ELF,R.SRC=saved_paths
# Real child exit, mocked command selection; no simulated PASS evidence is made.
saved_symbols=R.symbols;sym=R.symbols();saved_popen=R.subprocess.Popen
try:
    R.symbols=lambda:sym
    R.subprocess.Popen=lambda *args,**kwargs:saved_popen([sys.executable,'-c','raise SystemExit(7)'],**kwargs)
    with tempfile.TemporaryDirectory(prefix='gemv-child-exit-unit-') as d:
        d=Path(d)
        try:R.execute(d,'expected-unit-failure',1,0,1,101)
        except RuntimeError:pass
        else:raise AssertionError('failed child accepted')
        assert json.loads((d/'expected-unit-failure.result.json').read_text())['returncode']==7
        assert json.loads((d/'expected-unit-failure.process.json').read_text())['status']=='EXITED'
finally:R.symbols=saved_symbols;R.subprocess.Popen=saved_popen
with tempfile.TemporaryDirectory(prefix='gemv-status-identity-unit-') as d:
    d=Path(d);prefix=d/'run';full=d/'run-full';full.mkdir();proc=d/'proc';proc.mkdir()
    R.write(d/'run.pipeline.json',dict(pid=66,status='RUNNING',current_seed=101))
    R.write(full/'full-101.process.json',dict(pid=77,status='RUNNING'))
    for pid in (66,77):(proc/str(pid)).mkdir()
    worker=[b'python3',str(Path(D.__file__).resolve()).encode(),b'--worker',b'--prefix',str(prefix).encode()]
    (proc/'66/cmdline').write_bytes(b'\0'.join(worker)+b'\0')
    child=[str(R.CORE).encode(),b'-i',str(R.IMAGE).encode(),('--gcpt-restore='+str(full/'full-101.overlay.bin')).encode()]
    (proc/'77/cmdline').write_bytes(b'\0'.join(child)+b'\0')
    fields=['0']*20;fields[2]='R';fields[13]='400';fields[14]='100'
    (proc/'77/stat').write_text(' '.join(fields))
    status=D.worker_status(prefix,proc);assert status['worker_alive'] and status['child_alive'] and status['child_cpu_seconds']>0
    (proc/'77/cmdline').write_bytes(b'python3\0unrelated-job\0')
    assert not D.worker_status(prefix,proc)['child_alive']
    (proc/'66/cmdline').write_bytes(b'python3\0unrelated-worker\0')
    assert not D.worker_status(prefix,proc)['worker_alive']
saved_status=D.worker_status;saved_kill=D.os.kill;saved_argv=sys.argv;sent=[]
try:
    D.worker_status=lambda prefix:dict(pipeline=dict(pid=12345,status='RUNNING'),worker_alive=True)
    D.os.kill=lambda pid,sig:sent.append((pid,sig))
    sys.argv=['durable.py','--prefix','/tmp/unit-prefix','--status'];D.main();assert not sent
    sys.argv=['durable.py','--prefix','/tmp/unit-prefix','--stop'];D.main()
    assert sent==[(12345,D.signal.SIGTERM)]
finally:D.worker_status=saved_status;D.os.kill=saved_kill;sys.argv=saved_argv
print('GEMV tools PASS: matrix oracle, malformed evidence rejection, VCD reader, exact resume inputs, real child failure, status/stop dispatch without signalling a real process')
