#!/usr/bin/env python3
"""仅清理已授权的 v0.1/P1 指定文件，不删除整个目录。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT/'manifest/storage-cleanup-v01-p1-20261026.json'
_figure_spec=importlib.util.spec_from_file_location('cleanup_chinese_figures',ROOT/'stage3/tests/chinese-figure-edition.py')
FIGURES=importlib.util.module_from_spec(_figure_spec)
_figure_spec.loader.exec_module(FIGURES)
TARGETS = {
    'stage3/logs/p1-before-20261004.vcd': 5238847771,
    'stage3/logs/20261004T232857-17-p1-after.vcd': 5441896880,
    'stage2/waveform/vdot-core-20261002.vcd': 2652545217,
    'stage3/logs/timer-probe-20261003-window2.vcd': 1668801665,
    'stage2/waveform/control-harness-p1-20261006.vcd': 5982847413,
}


def need(value, message):
    if not value: raise ValueError(message)


def sha(path):
    if (ROOT/'manifest/chinese-figure-edition.json').exists() and path.suffix in ('.svg','.png'):
        return FIGURES.original_digest(ROOT,path)
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def module(name, path):
    spec=importlib.util.spec_from_file_location(name, ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def retained_evidence():
    """复核已保存的真实采样和图件，无需打开原始大 VCD。"""
    for group in ('p1', 'isolation'):
        folder=ROOT/'stage3/reports/figures'/group
        manifest=json.loads((folder/(group+'-wave-figure-manifest.json')).read_text())
        need(manifest['status']=='PASS', 'figure manifest incomplete')
        for name, expected in manifest['files'].items():
            path=folder/name
            need(sha(path)==expected, 'retained figure/excerpt changed: '+str(path))
            if path.suffix=='.svg':ET.fromstring(FIGURES.original_svg(ROOT,path))
            if path.suffix=='.png':
                if not path.exists():
                    successor=FIGURES.record(ROOT)['retired'][str(path.with_suffix('.svg').relative_to(ROOT))]['successor']
                    path=(ROOT/successor).with_suffix('.png')
                with path.open('rb') as stream:need(stream.read(8)==b'\x89PNG\r\n\x1a\n','invalid PNG')
    p1=module('cleanup_p1','stage3/tests/render-p1-wave-figures.py')
    saved=json.loads((p1.DEFAULT_OUTPUT/'p1-wave-excerpts.json').read_text())
    audits={}
    for role, source in saved['sources'].items():
        need(sha(ROOT/source['audit'])==source['audit_sha256'], 'P1 source audit changed')
        audits[role]=json.loads((ROOT/source['audit']).read_text())
        need(audits[role]['status']=='PASS','P1 audit incomplete')
    need(p1.choose(audits['before'],audits['after'])==saved['cases'], 'P1 selection differs')
    for case in saved['cases']:
        actual=FIGURES.original_svg(ROOT,p1.DEFAULT_OUTPUT/('p1-'+case['name']+'.svg'))
        need(p1.svg_figure(case,saved['extracts'])==actual, 'P1 plot differs from retained real samples')
    iso=module('cleanup_isolation','stage3/tests/render-isolation-wave-figures.py')
    folder=ROOT/'stage3/reports/figures/isolation'
    saved_iso=json.loads((folder/'isolation-wave-excerpts.json').read_text())
    for case in saved_iso['cases']:
        actual=FIGURES.original_svg(ROOT,folder/('isolation-'+case['name']+'.svg'))
        need(iso.figure(case,saved_iso['excerpts'][case['name']])==actual,
             'isolation plot differs from retained real samples')
    func=module('cleanup_functional','stage2/tests/render-functional-wave.py')
    cached=json.loads((ROOT/'stage3/reports/figures/functional/functional-samples.json').read_text())
    cases=func.select_cases(func.AUDIT.read_text())
    for case in cases:
        checked=func.audit_case(case,cached['windows'][case['name']])
        need(func.draw(checked,cached['windows'][case['name']])==
             FIGURES.original_svg(ROOT,ROOT/'stage3/reports/figures/functional'/(case['name']+'.svg')),
             'functional plot differs from retained real signals')
    comparison=module('cleanup_comparison','stage3/tests/render-baseline-comparison.py')
    timer=json.loads(comparison.TIMER.read_text());comparison.ART.timer_records(timer)
    cached=json.loads((comparison.OUT/'probe-samples.json').read_text())
    pairs=timer['checked_pairs'][:2]
    for pair in pairs:comparison.audit_window(pair,cached['windows'][str(pair['impl'])])
    comparison.formal_values(json.loads(comparison.FORMAL.read_text()))
    for doc, images in [
        ('stage3/reports/原始核至P1优化对比报告.md', ['p1-oldvd.png','p1-v0.png','p1-true.png']),
        ('stage3/reports/P1至隔离核优化对比报告.md', ['isolation-dot-hold.png','isolation-mac-hold.png','isolation-overlap.png'])]:
        content=(ROOT/doc).read_text()
        need(all(image in content for image in images), 'comparison report missing inline figures')
    return dict(status='PASS',p1_comparisons=3,isolation_comparisons=3,
                functional_cases=len(cases),probe_pairs=2,formal_processes=4)


def protected_files():
    names=[ROOT.parent/'XiangShan/build'/p for p in ('emu','p1-oldvd/emu','operand-isolation/emu')]
    names += [ROOT.parent/'NEMU/build/riscv64-nemu-interpreter-so',
              ROOT/'stage2/vdot-run.NlL7w1/emu.before',
              ROOT/'stage3/logs/p1-artifacts-20261004/emu-before']
    return {str(p):sha(p) for p in names}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='unlink the exact five old VCD files after verification')
    args=parser.parse_args()
    proof=retained_evidence();print('[retained evidence PASS]',json.dumps(proof),flush=True)
    if not args.execute:
        print(json.dumps(dict(mode='read-only',targets={n:p for n,p in TARGETS.items()},evidence=proof)))
        return
    need(not JOURNAL.exists(), 'one-off cleanup already has a journal; do not rerun blindly')
    before=protected_files();records=[]
    sources=json.loads((ROOT/'stage3/reports/figures/p1/p1-wave-excerpts.json').read_text())['sources']
    expected={s['wave']:s['wave_sha256'] for s in sources.values()}
    expected['stage3/logs/timer-probe-20261003-window2.vcd']=json.loads(
        (ROOT/'stage3/logs/timer-probe-20261003-window2-audit.json').read_text())['wave_sha256']
    control=json.loads((ROOT/'stage2/waveform/control-harness-p1-20261006.vcd.control.json').read_text())
    need(control['architectural_status']==control['control_status']=='PASS', 'P1 debug audit incomplete')
    expected['stage2/waveform/control-harness-p1-20261006.vcd']=control['wave_sha256']
    for name, size in TARGETS.items():
        path=ROOT/name
        need(not path.is_symlink() and path.resolve()==path and path.is_file(), 'not exact regular file: '+name)
        st=path.stat();need(st.st_size==size, 'unexpected source size: '+name)
        actual=sha(path)
        if name in expected:need(actual==expected[name], 'source differs from original audit: '+name)
        records.append(dict(path=name,size_bytes=st.st_size,allocated_bytes=st.st_blocks*512,
                            device=st.st_dev,inode=st.st_ino,mtime_ns=st.st_mtime_ns,sha256=actual,status='verified'))
        print('[source verified]',name,flush=True)
    journal=dict(status='verified-before-delete',authorization='User explicitly requested old v0.1/P1 cleanup after preserving comparison figures and reports; isolation and e8/e16 excluded.',
                 started=time.strftime('%Y-%m-%dT%H:%M:%S%z'),evidence=proof,protected_files=before,files=records)
    def save():JOURNAL.write_text(json.dumps(journal,indent=2)+'\n')
    save()
    for record in records:
        path=ROOT/record['path'];st=path.stat()
        need((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==
             (record['device'],record['inode'],record['size_bytes'],record['mtime_ns']), 'target changed since verification')
        path.unlink();record['status']='deleted';save()
        print('[deleted]',record['path'],flush=True)
    need(before==protected_files(),'protected executable changed during cleanup')
    journal.update(status='complete',finished=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                   removed_allocated_bytes=sum(r['allocated_bytes'] for r in records),
                   protected_executables_unchanged=True,retained_evidence_after=retained_evidence())
    save();print('[cleanup complete]',journal['removed_allocated_bytes'],'allocated bytes',flush=True)


if __name__=='__main__':main()
