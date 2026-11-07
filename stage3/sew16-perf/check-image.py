#!/usr/bin/env python3
"""审核真实 v4 ELF 边界、指令及完整 128 位等价基线的构造。"""
import json
import subprocess
import common as C
from datetime import datetime

s=C.symbols();image=C.IMAGE.read_bytes()
def word(pc):return int.from_bytes(image[pc-0x80000000:pc-0x80000000+4],'little')
found={}
for name in ('perf_e8_dot','perf_e8_rvv','perf_e16_dot','perf_e16_rvv'):
    words={k:word(s[name+'_'+k]) for k in ('pre_guard','start_read','start_guard','end_guard','end_read')}
    C.need(all(words[k]==0x00805073 for k in ('pre_guard','start_guard','end_guard')),'not a vstart write')
    C.need(all(words[k]&0xfffff07f==0xb0002073 for k in ('start_read','end_read')),'not a zero-rs1 mcycle read')
    found[name]={k:dict(pc=hex(s[name+'_'+k]),instruction=hex(v)) for k,v in words.items()}
disasm=subprocess.check_output(['riscv64-linux-gnu-objdump','-d',str(C.ELF)],text=True)
C.need(disasm.count('vwmul.vv')==16 and disasm.count('vwredsum.vs')==16,'wrong exact-width baseline body count')
C.need(s['perf_params']-0x80000000<0xf00,'parameter not in prefix')
r=dict(status='PASS',image_sha256=C.sha(C.IMAGE),elf_sha256=C.sha(C.ELF),markers=found,
  parameter_address=hex(s['perf_params']),baseline_widening_instructions=32)
out=C.ROOT/'stage3/logs'/datetime.now().strftime('%Y%m%dT%H%M%S-sew16-perf4-image-audit.json')
with out.open('x') as f:json.dump(r,f,indent=2)
print(json.dumps(dict(status='PASS',image_sha256=r['image_sha256'],markers=20,baseline_instructions=32)))
