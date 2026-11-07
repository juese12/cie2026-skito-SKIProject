#!/usr/bin/env python3
"""复用已验收的 sew16 RTL，仅增加模型只读可见性和低相位事件记录。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
XS=ROOT.parent/'XiangShan'
BASE=XS/'build/sew16-fixed8'
BUILD=XS/'build/sew16-events'
SRC=ROOT/'stage2/e16-events'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(args,**kw):
    print('[command]',*map(str,args),flush=True)
    subprocess.run(list(map(str,args)),check=True,**kw)

def generate_fields():
    header=(BUILD/'emu-compile/VSimTop___024root.h').read_text()
    base='SimTop__DOT__l_soc__DOT__core_with_l2__DOT__core__DOT__backend__DOT__'
    paths=dict(d=base+'inner_ctrlBlock__DOT__dispatch__DOT__',
      r=base+'inner_ctrlBlock__DOT__rob__DOT__',
      c=base+'inner_ctrlBlock__DOT__',
      e=base+'inner_vfExuBlock__DOT__exus__DOT__',
      u=base+'inner_vfExuBlock__DOT__exus__DOT__Vimac__DOT__',
      v=base+'inner_vfExuBlock__DOT__exus__DOT__Vimac__DOT__vdot__DOT__')
    used=[]
    def s(group,name):
        full=paths[group]+name
        assert full+';' in header,f'missing retained model field {full}'
        used.append(full)
        return 'r->'+full
    def tag(group,prefix):return f'(256u*{s(group,prefix+"flag")}+{s(group,prefix+"value")})'
    def wide(group,name):
        value=s(group,name)
        return '{'+','.join(f'{value}[{i}]' for i in range(4))+'}'
    lines=['#pragma once','#include "VSimTop___024root.h"','namespace e16events {',
      'inline void sample_model(const VSimTop___024root *r, uint64_t cycle) {',
      'auto &collector=instance(); if(!collector.enabled()) return;',
      'Frame f{}; f.cycle=cycle; f.reset=r->reset;']
    for i in range(6):
        p=f'io_enqRob_req_{i}_bits_'
        lines.append(f'f.alloc[{i}]={{bool({s("d","io_enqRob_canAccept")} && {s("d",f"io_enqRob_req_{i}_valid")}),{tag("d",p+"robIdx_")},{s("d",p+"pc")},{s("d",p+"instr")},{s("d",p+"vpu_vsew")}}};')
    for i in range(8):
        lines.append(f'f.commit[{i}]={{bool({s("r","io_commits_isCommit")} && {s("r",f"io_commits_commitValid_{i}")}),{tag("r",f"io_commits_robIdx_{i}_")}}};')
    for j,i in enumerate((1,3,5,7)):
        p=f'io_fromWB_wbData_{i}_bits_redirect_bits_'
        lines.append(f'f.decision[{j}]={{bool({s("c",f"io_fromWB_wbData_{i}_valid")} && {s("c",f"io_fromWB_wbData_{i}_bits_redirect_valid")}),{tag("c",p+"robIdx_")},bool({s("c",p+"cfiUpdate_taken")}),bool({s("c",p+"cfiUpdate_isMisPred")})}};')
    i_values=['bool('+s('v','io_enable_0')+')',tag('e','io_in_bits_robIdx_'),s('u','io_in_bits_ctrl_vpu_vsew'),
      '('+s('e','io_in_bits_src_4')+'[0] & 255u)']
    i_values += [s('e','io_in_bits_vpu_'+n) for n in ('vlmul','vm','vstart','vill')]
    i_values += [wide('u','io_in_bits_data_src_'+str(n)) for n in (0,1)]
    lines.append('f.input={'+','.join(i_values)+'};')
    o_values=['bool('+s('u','io_out_valid')+' && '+s('u','io_in_bits_ctrlPipe_2_fuOpType')+'==0x160)',
      tag('u','io_out_bits_ctrl_robIdx_'),s('u','io_in_bits_ctrlPipe_2_vpu_vsew'),s('u','io_in_bits_dataPipe_2_src_4')]
    o_values += [s('u','io_in_bits_ctrlPipe_2_vpu_'+n) for n in ('vlmul','vm','vstart','vill')]
    o_values += [s('u','io_out_bits_ctrl_exceptionVec_2'),wide('u','io_out_bits_res_data')]
    lines.append('f.output={'+','.join(o_values)+'};')
    for name,group,prefix in (('redirect','c','io_redirect_'),('flush','r','io_flushOut_')):
        lines.append(f'f.{name}={{bool({s(group,prefix+"valid")}),{tag(group,prefix+"bits_robIdx_")},{s(group,prefix+"bits_level")}}};')
    lines += ['f.exception='+s('r','io_exception_valid')+';',
      'f.instruction='+s('r','io_exception_bits_instr')+';',
      'f.illegal='+s('r','io_exception_bits_exceptionVec_2')+';',
      'collector.sample(f);','}','}']
    (BUILD/'emulator/event_fields.h').write_text('\n'.join(lines)+'\n')
    (BUILD/'observed-fields.json').write_text(json.dumps(sorted(set(used)),indent=2))

def main():
    assert not BUILD.exists(),'event build exists; inspect logs before resuming'
    BUILD.mkdir(parents=True)
    files=list((BASE/'rtl').glob('*.sv'))+list((BASE/'generated-src').rglob('*'))
    files=[p for p in files if p.is_file()]
    files += [BASE/'emu',ROOT.parent/'NEMU/build/sew16/riscv64-nemu-interpreter-so',
      XS/'difftest/src/test/csrc/verilator/emu.cpp',SRC/'collector.h',SRC/'visibility.vlt',Path(__file__)]
    inputs={str(p.resolve()):sha(p) for p in files}
    (BUILD/'inputs.json').write_text(json.dumps(inputs,indent=2))
    shutil.copytree(BASE/'generated-src',BUILD/'generated-src')
    for n in ('chisel_db.cpp','chisel_db.h'):shutil.copy2(BASE/n,BUILD/n)
    shutil.copytree(XS/'difftest/src/test/csrc/verilator',BUILD/'emulator')
    emu=BUILD/'emulator/emu.cpp'
    text=emu.read_text()
    assert text.count('#include "emu.h"')==1
    text=text.replace('#include "emu.h"','#include "emu.h"\n#include "collector.h"',1)
    start=text.index('inline void Emulator::single_cycle()')
    pos=text.index('  dut_ptr->eval();',text.index('  dut_ptr->clock = 0;',start))+len('  dut_ptr->eval();')
    text=text[:pos]+'\n  e16events::sample_model(dut_ptr->rootp, cycles);'+text[pos:]
    emu.write_text(text)
    shutil.copy2(SRC/'collector.h',BUILD/'emulator/collector.h')
    args=['make','-C',XS/'difftest',f'BUILD_DIR={BUILD}',f'RTL_DIR={BASE/"rtl"}',
      f'DESIGN_DIR={XS}','NUM_CORES=1','WITH_DRAMSIM3=1','WITH_CONSTANTIN=0',
      'EMU_THREADS=0','EMU_TRACE=0',f'EMU_CSRC_DIR={BUILD/"emulator"}','-j2']
    env=os.environ.copy();env['NOOP_HOME']=str(XS);env['NEMU_HOME']=str(ROOT.parent/'NEMU')
    env['DRAMSIM3_HOME']=str(ROOT.parent/'DRAMsim3')
    env['VEXTRA_FLAGS']=str(SRC/'visibility.vlt')
    run(args+[str(BUILD/'emu-compile/VSimTop.mk')],env=env)
    generate_fields()
    run(args+['build_emu'],env=env)
    assert all(sha(p)==h for p,h in inputs.items()),'frozen input changed'
    (BUILD/'complete.json').write_text(json.dumps(dict(status='PASS',emu_sha256=sha(BUILD/'emu'),
      rtl_source='sew16-fixed8/rtl',waveform=False,mode='read-only public_flat_rd and C++ settled-low events'),indent=2))
    print('[event build COMPLETE]',BUILD/'emu',flush=True)

if __name__=='__main__':main()
