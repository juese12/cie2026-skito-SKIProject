#!/usr/bin/env python3
"""Completion notifications trigger the next step; no periodic process polling."""
import argparse
import ctypes
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import run as R

def wait_for_probe(directory):
    if (directory/'results.json').exists():return
    libc=ctypes.CDLL(None,use_errno=True)
    libc.inotify_init1.argtypes=[ctypes.c_int];libc.inotify_init1.restype=ctypes.c_int
    libc.inotify_add_watch.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_uint32];libc.inotify_add_watch.restype=ctypes.c_int
    descriptor=libc.inotify_init1(os.O_CLOEXEC);assert descriptor>=0
    try:
        assert libc.inotify_add_watch(descriptor,os.fsencode(directory),0x8|0x80)>=0
        while not (directory/'results.json').exists():
            failed=directory/'probe.result.json'
            if failed.exists() and json.loads(failed.read_text())['status']!='PASS':raise RuntimeError('probe failed')
            select.select([descriptor],[],[]);os.read(descriptor,65536)
    finally:os.close(descriptor)
def command(*args):subprocess.run([sys.executable,'-u',*[str(a) for a in args]],check=True)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--probe',type=Path,required=True);p.add_argument('--prefix',type=Path,required=True)
    a=p.parse_args();probe=a.probe.resolve();prefix=a.prefix.resolve();state=Path(str(prefix)+'.pipeline.json')
    assert not state.exists()
    def stage(name,status='RUNNING'):
        tmp=state.with_suffix('.tmp');tmp.write_text(json.dumps(dict(stage=name,status=status,time=R.stamp()),indent=2));tmp.replace(state)
        print(R.stamp(),name,status,flush=True)
    try:
        stage('wait-probe');wait_for_probe(probe)
        stage('timer-audit');command(R.SRC/'audit-timer.py',probe/'probe.events.jsonl','--out',probe/'timer-audit.json')
        smoke=Path(str(prefix)+'-smoke');stage('smoke');command(R.SRC/'run.py','--suite','smoke','--out',smoke)
        import analyze
        run=json.loads((smoke/'results.json').read_text())['runs'][0]
        R.write(smoke/'analysis.json',analyze.parse(run))
        wave=Path(str(prefix)+'-wave');stage('wave')
        if not (R.ROOT.parent/'XiangShan/build/int8-gemv-wave/emu').exists():command(R.SRC/'build-wave-observer.py')
        command(R.SRC/'wave.py','--probe',probe,'--out',wave)
        full=Path(str(prefix)+'-full');stage('formal');command(R.SRC/'run.py','--suite','full','--out',full)
        stage('analysis');command(R.SRC/'analyze.py',full,'--out',Path(str(prefix)+'.analysis.json'))
        stage('simulation-and-analysis','PASS')
    except BaseException as e:
        stage('failed','FAIL');R.write(Path(str(prefix)+'.failure.json'),dict(error=repr(e)));raise
if __name__=='__main__':main()
