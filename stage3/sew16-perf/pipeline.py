#!/usr/bin/env python3
"""等待进程结束后自动审核、继续运行并生成报告，避免忙轮询。"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import common as C

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preflight-prefix',type=Path)
a=p.parse_args()
if a.preflight_prefix:prefix=a.preflight_prefix.resolve()
else:
    candidates=[]
    for path in (C.ROOT/'stage3/logs').glob('*-sew16-perf4-preflight-probe.invocation.json'):
        item=json.loads(path.read_text())
        if item['inputs'].get(str(C.IMAGE))==C.sha(C.IMAGE) and item['core']=='events':candidates.append(path)
    C.need(len(candidates)==1,'specify exact preflight prefix; ambiguous attempts')
    prefix=Path(str(candidates[0]).removesuffix('-probe.invocation.json'))
result=Path(str(prefix)+'.results.json')
if not result.exists():
    # 工具命令使用不同 PID 命名空间，通过共享文件关闭事件
    # 获取完成通知，避免查询进程或忙等。
    libc=ctypes.CDLL(None,use_errno=True)
    libc.inotify_init1.argtypes=[ctypes.c_int];libc.inotify_init1.restype=ctypes.c_int
    libc.inotify_add_watch.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_uint32]
    libc.inotify_add_watch.restype=ctypes.c_int
    descriptor=libc.inotify_init1(os.O_CLOEXEC);C.need(descriptor>=0,'cannot create completion notification')
    wrapper=C.ROOT/'stage2/logs'/(prefix.name[:15]+'-sew16-perf-v4-bounded-preflight.full.log')
    try:
        watch=libc.inotify_add_watch(descriptor,os.fsencode(result.parent),0x8|0x80)
        other=libc.inotify_add_watch(descriptor,os.fsencode(wrapper.parent),0x8|0x80)
        C.need(watch>=0 and other>=0,'cannot watch completion directories')
        if wrapper.exists() and '\n[exit] ' in wrapper.read_text():
            C.need(result.exists(),'preflight already ended without successful results')
        print('[wait for completion file, without polling]',prefix,flush=True)
        while not result.exists():
            select.select([descriptor],[],[])
            data=os.read(descriptor,65536);offset=0;wrapper_closed=False
            while offset<len(data):
                wd,mask,cookie,size=struct.unpack_from('iIII',data,offset);offset+=16
                name=data[offset:offset+size].rstrip(b'\0').decode();offset+=size
                if wd==other and name==wrapper.name:wrapper_closed=True
            if wrapper_closed and not result.exists():raise ValueError('preflight wrapper closed without successful results')
    finally:os.close(descriptor)
C.need(result.exists(),'preflight ended without successful completion; inspect its preserved logs')
pre=json.loads(result.read_text());C.need(pre['status']=='PASS','preflight failed')
probe=pre['runs'][0];timer=Path(str(prefix)+'.timer-audit.json')
subprocess.run([sys.executable,str(C.SRC/'audit-timer.py'),probe['events'],'--out',str(timer)],check=True)
subprocess.run([sys.executable,'-u',str(C.SRC/'series.py'),'--preflight',str(result),'--timer',str(timer)],check=True)
print('[perf4 PIPELINE COMPLETE]',prefix,flush=True)
