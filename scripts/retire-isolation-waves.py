#!/usr/bin/env python3
"""仅在旧隔离实验的信号图、采样与固定二进制重放入口齐全时精简四份大波形。"""
import argparse
import importlib.util
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
JOURNAL=ROOT/'manifest/isolation-wave-retirement.json'
TARGETS={
    'stage2/waveform/20261006T033620-isolation-control-resumed.vcd':5982685858,
    'stage3/logs/20261008T114325-original-e2e-events-resumed.vcd':2644565481,
    'stage3/logs/20261007T221501-original-e2e-events.vcd':2644563660,
    'stage3/logs/20261008T200238-original-other-bins.vcd.gz':224101577,
}


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


R=module('retirement_replay','scripts/replay-isolation-evidence.py')
F=module('retirement_signals','stage3/tests/render-isolation-retained-signals.py')
need=R.need


def check():
    plan=json.loads(R.PLAN.read_text());proof=R.check(plan)
    saved=json.loads((F.OUT/'signal-excerpts.json').read_text());F.validate_control(saved['control'])
    manifest=json.loads((F.OUT/'evidence-manifest.json').read_text())
    for name,expected in manifest['files'].items():need(R.sha(F.OUT/name)==expected,'saved figure/sample differs: '+name)
    for doc,figure in [('stage2/reports/隔离版本整核构建与控制验证报告.md','control-signals.png'),
                       ('stage3/reports/原镜像端到端快慢窗口事件诊断.md','e2e-signals.png')]:
        need(figure in (ROOT/doc).read_text(),'required signal figure is not in document')
    return proof


def metadata(path):
    s=path.stat()
    return dict(size=s.st_size,inode=s.st_ino,device=s.st_dev,mtime_ns=s.st_mtime_ns,allocated=s.st_blocks*512,links=s.st_nlink)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    proof=check();print('[replay readiness / retained signals PASS]',json.dumps(proof),flush=True)
    if not args.execute:return
    need(not JOURNAL.exists(),'cleanup journal already exists; do not blindly repeat')
    expected={
        list(TARGETS)[0]:json.loads((ROOT/R.CONTROL_JSON).read_text())['wave_sha256'],
        list(TARGETS)[1]:json.loads((ROOT/R.FAST).with_suffix('.capture.json').read_text())['wave_sha256'],
        list(TARGETS)[2]:json.loads((ROOT/R.FAST).with_suffix('.recovery.json').read_text())['interrupted_wave_sha256'],
        list(TARGETS)[3]:json.loads((ROOT/R.MID).with_suffix('.events.json').read_text())['wave_sha256'],
    }
    records=[]
    for name,size in TARGETS.items():
        p=ROOT/name;need(p.resolve()==p and not p.is_symlink() and p.is_file(),'not exact regular file: '+name)
        m=metadata(p);need(m['size']==size and m['links']==1,'unexpected file size/link count: '+name)
        need(R.sha(p)==expected[name],'source VCD differs from original audit: '+name)
        records.append(dict(path=name,metadata=m,sha256=expected[name],status='verified'))
        print('[source verified]',name,flush=True)
    journal=dict(status='verified-before-delete',started=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                 authorization='User requested retirement of old isolated control/e2e waveforms after preserving key signals and reproducibility; latest-core simulation is not authorized by this cleanup.',
                 replay_plan=str(R.PLAN.relative_to(ROOT)),reproduction_check_before=proof,files=records)
    def save():JOURNAL.write_text(json.dumps(journal,indent=2)+'\n')
    save()
    for record in records:
        p=ROOT/record['path'];need(metadata(p)==record['metadata'],'file changed during preflight')
        p.unlink();record['status']='deleted';save();print('[deleted]',record['path'],flush=True)
    journal.update(status='complete',finished=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                   removed_allocated_bytes=sum(r['metadata']['allocated'] for r in records),
                   reproduction_check_after=check())
    save();print('[cleanup complete]',journal['removed_allocated_bytes'],'allocated bytes',flush=True)


if __name__=='__main__':main()
