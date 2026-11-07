#!/usr/bin/env python3
"""Execute the actual linked scalar/RVV/dot kernels through the NEMU API.
This is a fast software/ISA preflight, not a replacement for RTL Difftest.
"""
import ctypes as C
import json
from pathlib import Path
import random
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[2]
SRC=Path(__file__).resolve().parent
IMAGE=SRC/'build/cie2026-int8-gemv-riscv64-xs.bin'
symbols={p[2]:int(p[0],16) for line in subprocess.check_output(
    ['riscv64-linux-gnu-nm',str(IMAGE.with_suffix('.elf'))],text=True).splitlines()
    if len(p:=line.split())==3}
lib=C.CDLL(str(ROOT.parent/'NEMU/build/sew16/riscv64-nemu-interpreter-so'))
assert C.c_uint.in_dll(lib,'DIFFTEST_REG_SIZE').value==1400
State=C.c_uint64*175
lib.difftest_init()
lib.difftest_memcpy.argtypes=[C.c_uint64,C.c_void_p,C.c_size_t,C.c_bool]
lib.difftest_regcpy.argtypes=[C.c_void_p,C.c_bool]
lib.difftest_exec.argtypes=[C.c_uint64]
def put(addr,data):
    buf=C.create_string_buffer(data);lib.difftest_memcpy(addr,buf,len(data),True)
def get(addr,n):
    buf=C.create_string_buffer(n);lib.difftest_memcpy(addr,buf,n,False);return buf.raw
put(0x80000000,IMAGE.read_bytes())
initial=State();lib.difftest_regcpy(C.byref(initial),False)
initial[82]=0x800ffff0
put(initial[82],struct.pack('<I',0x74446073))
lib.difftest_regcpy(C.byref(initial),True);lib.difftest_exec(1)
lib.difftest_regcpy(C.byref(initial),False)
sentinel=0x800ffff8
addresses=(0x81000010,0x81010010,0x81020010)
def execute(name,w,x,m,k):
    dst,wa,xa=addresses
    put(dst-16,b'\xa5'*(32*4+32));put(wa-16,b'\x5a'*16+w+b'\x5a'*16)
    put(xa-16,b'\x5a'*16+x+b'\x5a'*16)
    s=State(*initial);s[65]=(s[65]&~(1<<42))|0x600
    s[1]=sentinel;s[2]=0x82000000;s[3]=symbols.get('__global_pointer$',0)
    s[10],s[11],s[12],s[13],s[14]=dst,wa,xa,m,k
    s[82]=symbols[name];s[164]=0;s[168]=0;s[169]=0
    lib.difftest_regcpy(C.byref(s),True)
    for steps in range(300000):
        lib.difftest_exec(1);lib.difftest_regcpy(C.byref(s),False)
        if s[82]==sentinel:break
        if s[73]!=initial[73]:raise AssertionError((name,'exception',hex(s[82]),s[73]))
    else:raise AssertionError((name,'did not return',hex(s[82])))
    assert get(wa,len(w))==w and get(xa,len(x))==x,(name,m,k,'input modified',get(wa,min(len(w),32)).hex(),w[:32].hex(),get(xa,min(len(x),32)).hex(),x[:32].hex())
    assert get(dst-16,16)==b'\xa5'*16 and get(dst+4*m,16)==b'\xa5'*16,'output overrun'
    assert s[164]==0 and s[167]==0,'CSR changed'
    return list(struct.unpack('<'+'i'*m,get(dst,m*4)))

def pack(w,x,m,k):
    kp=(k+7)//8*8
    return b''.join(w[r*k:(r+1)*k]+bytes(kp-k) for r in range(m)),x+bytes(kp-k),kp
def signed(v):return v-256 if v>=128 else v
counts={name:0 for name in ('gemv_scalar','gemv_rvv','gemv_dot1','gemv_dot4','gemv_dot1_e2e','gemv_dot4_e2e')}
rows=0
for seed in (0x56444f54,1,0x9e3779b9,0xdeadbeef):
    rng=random.Random(seed)
    shapes=[(0,0),(0,17),(1,0),(4,0),(5,0),(1,1),(1,7),(3,8),(4,9),(5,15),(7,16),(5,17),(8,31),(17,33),(4,256),(32,256)]
    shapes += [(rng.randrange(1,18),rng.randrange(1,257)) for _ in range(8)]
    for case,(m,k) in enumerate(shapes):
        w=bytes((128 if case%5 in (0,1) else 127 if case%5==2 else rng.randrange(256)) for _ in range(m*k))
        x=bytes((128 if case%5==0 else 127 if case%5 in (1,2) else rng.randrange(256)) for _ in range(k))
        want=[sum(signed(w[r*k+c])*signed(x[c]) for c in range(k)) for r in range(m)]
        pw,px,kp=pack(w,x,m,k)
        for name in counts:
            dot=name in ('gemv_dot1','gemv_dot4')
            got=execute(name,pw if dot else w,px if dot else x,m,kp if dot else k)
            assert got==want,(seed,m,k,name,got,want)
            counts[name]+=1;rows+=m
result=dict(status='PASS',kind='NEMU linked application kernels; not RTL',seeds=4,cases=next(iter(counts.values())),checks=counts,checked_rows=rows)
print('GEMV_NEMU_RESULT '+json.dumps(result,sort_keys=True))
