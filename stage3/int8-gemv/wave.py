#!/usr/bin/env python3
"""Capture one actual GEMV call with the existing-model read-only observer."""
import argparse
import gzip
import json
from pathlib import Path
import run as R
from signals import read_wave

def capture(probe,out):
    audit=json.loads((probe/'timer-audit.json').read_text());assert audit['status']=='PASS'
    call=audit['calls'][0]
    begin=max(1,call['pre_commit']-8);end=call['end_read_commit']+8
    out.mkdir(parents=True,exist_ok=False);path=out/'key-signals.vcd'
    result=R.execute(out,'wave',0,0,0x56444f54,101,selected_wave=(path,begin,end))
    assert path.is_file() and path.stat().st_size>0,'observer emitted no waveform'
    with path.open('rb') as src,gzip.open(out/'key-signals.vcd.gz','xb') as dst:
        import shutil
        shutil.copyfileobj(src,dst)
    model=json.loads((R.ROOT.parent/'XiangShan/build/int8-gemv-wave/observer.json').read_text())
    frames,widths=read_wave(path)
    assert len(frames)==2*(end-begin+1),'incomplete half-cycle sampling'
    meta=dict(status='PASS',begin=begin,end=end,run=result,probe_call=call,fields=model['fields'],
        uncompressed_bytes=path.stat().st_size,compressed_bytes=(out/'key-signals.vcd.gz').stat().st_size,
        scope='actual existing RTL model; read-only high/low phase sampling; t=2*cycle+phase; no RTL regeneration')
    R.write(out/'capture.json',meta)
    print('GEMV actual short VCD PASS compressed_bytes='+str(meta['compressed_bytes']),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--probe',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();capture(a.probe.resolve(),a.out.resolve())
