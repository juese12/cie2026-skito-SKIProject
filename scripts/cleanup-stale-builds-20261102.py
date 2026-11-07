#!/usr/bin/env python3
"""一次性清理指定的旧 FIR、可重建预编译头及已停止任务的下载缓存。"""
import argparse
import hashlib
import json
from pathlib import Path
import time

PROJECT=Path(__file__).resolve().parents[1]
WORKSPACE=PROJECT.parent
JOURNAL=PROJECT/'manifest/storage-cleanup-stale-builds-20261102.json'
FILES={
    'XiangShan/build/rtl/SimTop.fir':1489394847,
    'XiangShan/build/p1-oldvd/rtl/SimTop.fir':1488516537,
    'NutShell/build/verilator-compile/VSimTop__pch.h.fast.gch':14070588,
    'NutShell/build/verilator-compile/VSimTop__pch.h.slow.gch':14087016,
}
DOWNLOADS='cie2026-skito-SKIProject/stage3/synthesis/build/downloads/'
FILES.update({DOWNLOADS+name:size for name,size in {
    'yosys_0.52-2_amd64.deb':6600962,
    'yosys-abc_0.52-2_amd64.deb':5296928,
    'opensta_0~20191111gitc018cb2+dfsg-1.1_amd64.deb':1133330,
    'libtcl8.6_8.6.17+dfsg-1build1_amd64.deb':1003440,
    'tcl8.6_8.6.17+dfsg-1build1_amd64.deb':14872,
    'NangateOpenCellLibrary_typical.lib':6692032,
}.items()})
CACHE_DIRS=('verilator/src/obj_opt','verilator/src/obj_dbg')
EXECUTABLES=[
    WORKSPACE/'XiangShan/build'/name for name in
    ('emu','p1-oldvd/emu','operand-isolation/emu','sew16-fixed8/emu',
     'sew16-events/emu','sew16-events/emu-initial-collector','sew16-perf-events/emu')]
EXECUTABLES += [WORKSPACE/'NutShell/build/verilator-compile/emu',
    WORKSPACE/'NEMU/build/riscv64-nemu-interpreter-so',
    WORKSPACE/'NEMU/build/sew16/riscv64-nemu-interpreter-so',
    PROJECT/'stage2/vdot-run.NlL7w1/emu.before',
    PROJECT/'stage3/logs/p1-artifacts-20261004/emu-before',
    Path('/usr/local/bin/verilator'),Path('/usr/local/bin/verilator_bin')]
PRESERVED=(
    'XiangShan/build/operand-isolation/rtl/SimTop.fir',
    'XiangShan/build/sew16-fixed8/rtl/SimTop.fir',
    'cie2026-skito-SKIProject/stage2/waveform/20261006T033620-isolation-control-resumed.vcd',
    'cie2026-skito-SKIProject/stage3/logs/20261008T114325-original-e2e-events-resumed.vcd',
    'cie2026-skito-SKIProject/stage3/logs/20261007T221501-original-e2e-events.vcd',
    'cie2026-skito-SKIProject/stage2/sew16/mixed-module.vcd.gz',
    'cie2026-skito-SKIProject/stage3/logs/20261027T190338-sew16-perf4-full.analysis.samples.csv',
)


def need(value,message):
    if not value:raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def metadata(path):
    need(not path.is_symlink() and path.resolve()==path,'不接受符号链接或改向路径：'+str(path))
    s=path.stat()
    return dict(device=s.st_dev,inode=s.st_ino,size=s.st_size,mtime_ns=s.st_mtime_ns,
                allocated=s.st_blocks*512,links=s.st_nlink)


def preserve():
    return dict(executables={str(p):sha(p) for p in EXECUTABLES},
                files={n:metadata(WORKSPACE/n) for n in PRESERVED})


def verify_protected(journal):
    need(preserve()==journal['preserved_before'],'保留的核、参考库或正式证据发生变化')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--finish',action='store_true',help='管理员缓存清理尝试后，核对保留项并汇总实际释放量')
    args=parser.parse_args()
    need(not(args.execute and args.finish),'只能选择一个执行模式')
    if args.finish:
        journal=json.loads(JOURNAL.read_text());verify_protected(journal)
        for record in journal['cache_directories']:
            record['status']='retained-permission' if (WORKSPACE/record['path']).exists() else 'deleted'
        need(all(not (WORKSPACE/r['path']).exists() for r in journal['files']),'普通清理文件仍存在')
        released=sum(r['metadata']['allocated'] for r in journal['files'])
        released+=sum(r['allocated_before'] for r in journal['cache_directories'] if r['status']=='deleted')
        journal.update(status='complete' if all(r['status']=='deleted' for r in journal['cache_directories']) else 'complete-with-permission-limits',
                       finished=time.strftime('%Y-%m-%dT%H:%M:%S%z'),removed_allocated_bytes=released,
                       protected_executables_and_evidence_unchanged=True)
        JOURNAL.write_text(json.dumps(journal,indent=2)+'\n')
        print(json.dumps(dict(status=journal['status'],removed_allocated_bytes=released,GiB=released/2**30)))
        return
    need(not JOURNAL.exists(),'本轮已有记录，不允许盲目重复执行')
    records=[]
    for name,size in FILES.items():
        path=WORKSPACE/name;m=metadata(path)
        need(path.is_file() and m['size']==size and m['links']==1,'文件大小或类型不符：'+name)
        records.append(dict(path=name,metadata=m,sha256=sha(path),status='verified'))
    caches=[]
    for name in CACHE_DIRS:
        path=WORKSPACE/name;need(path.is_dir() and not path.is_symlink(),'缓存目录不符')
        entries=[path,*path.rglob('*')]
        need(not any(p.is_symlink() for p in entries),'缓存包含符号链接')
        caches.append(dict(path=name,status='pending-permission',
                           allocated_before=sum(p.stat().st_blocks*512 for p in entries),
                           entries=len(entries)))
    if not args.execute:
        print(json.dumps(dict(mode='read-only',files=[r['path'] for r in records],cache_directories=caches)))
        return
    journal=dict(status='verified-before-delete',started=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                 authorization='Explicit user request to delete unused/superseded files and two named old FIRs; isolation and e8/e16 retained.',
                 files=records,cache_directories=caches,preserved_before=preserve())
    def save():JOURNAL.write_text(json.dumps(journal,indent=2)+'\n')
    save()
    for record in records:
        path=WORKSPACE/record['path']
        need(metadata(path)==record['metadata'],'核查后文件发生变化：'+record['path'])
        path.unlink();record['status']='deleted';save();print('[deleted]',record['path'],flush=True)
    verify_protected(journal);journal['status']='user-owned-files-deleted';save()
    print('[protected executables/evidence PASS]',flush=True)


if __name__=='__main__':main()
