#!/usr/bin/env python3
"""按 firstUop 判断架构指令分配，只重新链接观察器。

NewDispatch 接收全部微操作，而 Rob.scala 仅在 firstUop 时分配新架构指令。
已保留的可见模型包含此位，无需重新生成模型。
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT.parent/'XiangShan/build/sew16-events'

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    assert not (BUILD/'final.json').exists(),'final observer exists'
    base=json.loads((BUILD/'complete.json').read_text())
    assert base['status']=='PASS' and sha(BUILD/'emu')==base['emu_sha256']
    shutil.copy2(BUILD/'emu',BUILD/'emu-initial-collector')
    fields=BUILD/'emulator/event_fields.h';text=fields.read_text()
    model=(BUILD/'emu-compile/VSimTop___024root.h').read_text()
    parent='SimTop__DOT__l_soc__DOT__core_with_l2__DOT__core__DOT__backend__DOT__inner_ctrlBlock__DOT__dispatch__DOT__'
    observed=json.loads((BUILD/'observed-fields.json').read_text())
    for i in range(6):
        v=parent+f'io_enqRob_req_{i}_valid'
        first=parent+f'io_enqRob_req_{i}_bits_firstUop'
        assert first+';' in model,first
        observed.append(first)
        old='r->'+v+'),'
        assert text.count(old)==1,old
        text=text.replace(old,'r->'+v+' && r->'+first+'),')
    fields.write_text(text)
    (BUILD/'observed-fields.json').write_text(json.dumps(sorted(set(observed)),indent=2))
    collector=BUILD/'emulator/collector.h'
    text=collector.read_text()
    old='\\"rob_entries\\":160}'
    assert text.count(old)==1
    collector.write_text(text.replace(old,'\\"rob_entries\\":160,\\"allocation_gate\\":\\"firstUop\\"}'))
    subprocess.run(['make','-C',str(BUILD/'emu-compile'),'-f','VSimTop.mk','-j2',
                    'OPT_FAST=-O3','OPT_SLOW=-O0'],check=True)
    inputs=json.loads((BUILD/'inputs.json').read_text())
    assert all(sha(p)==h for p,h in inputs.items()),'original hardware/source changed'
    result=dict(status='PASS',emu=str(BUILD/'emu'),emu_sha256=sha(BUILD/'emu'),
                initial_collector_sha256=base['emu_sha256'],allocation_gate='firstUop',
                original_inputs_unchanged=True,
                observer_sources={str(p):sha(p) for p in (fields,collector,BUILD/'emulator/emu.cpp')})
    (BUILD/'final.json').write_text(json.dumps(result,indent=2))
    print('[event observer FINAL]',json.dumps(result),flush=True)

if __name__=='__main__':main()
