#!/usr/bin/env python3
"""Wait for completion events, then produce checked wave figures and the report."""
import argparse
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import run as R
import analyze as A
import report as REPORT

def wait_pipeline(state):
    libc=ctypes.CDLL(None,use_errno=True)
    libc.inotify_init1.argtypes=[ctypes.c_int];libc.inotify_init1.restype=ctypes.c_int
    libc.inotify_add_watch.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_uint32];libc.inotify_add_watch.restype=ctypes.c_int
    fd=libc.inotify_init1(os.O_CLOEXEC);assert fd>=0
    try:
        assert libc.inotify_add_watch(fd,os.fsencode(state.parent),0x8|0x80)>=0
        while True:
            if state.exists():
                status=json.loads(state.read_text())
                if status['status']=='FAIL':raise RuntimeError('pipeline failed: inspect preserved logs')
                if status['status']=='PASS':return
            select.select([fd],[],[]);os.read(fd,65536)
    finally:os.close(fd)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prefix',type=Path,required=True);a=p.parse_args()
    prefix=a.prefix.resolve();state=Path(str(prefix)+'.pipeline.json')
    target=Path(str(prefix)+'.delivery.json');assert not target.exists()
    print(R.stamp(),'wait for pipeline completion event',flush=True);wait_pipeline(state)
    figures=R.ROOT/'stage3/reports/figures/int8-gemv'
    if not (figures/'signal-evidence.json').exists():
        subprocess.run([sys.executable,str(R.SRC/'render-evidence.py'),'--wave',str(prefix)+'-wave',
            '--probe',str(prefix)+'-probe','--out',str(figures)],check=True)
    data=A.analyze(Path(str(prefix)+'-full'))
    prior=json.loads(Path(str(prefix)+'.analysis.json').read_text())
    assert json.loads(json.dumps(data))==prior,'analysis changed'
    evidence=json.loads((figures/'signal-evidence.json').read_text())
    path=R.ROOT/'stage3/reports/INT8矩阵向量乘应用测试与性能报告.md'
    assert '当前软件已编译，快速 NEMU 预检通过' in path.read_text(),'refusing to replace a completed report'
    text=REPORT.report(data,evidence,path)
    tmp=path.with_suffix('.tmp');tmp.write_text(text);tmp.replace(path)
    R.write(target,dict(status='PASS',time=R.stamp(),formal_processes=4,samples=data['total_samples'],
        warnings=len(data['warnings']),figures=[str(p) for p in sorted(figures.glob('*.png'))],
        report=str(path),scope='application RTL simulations, analysis, real signal figures and report; top-level navigation updated separately'))
    print(R.stamp(),'GEMV figures/report COMPLETE',flush=True)
if __name__=='__main__':main()
