#!/usr/bin/env python3
"""Relink only an emulator-side read-only VCD writer against the existing model.
No Scala, RTL, Verilator model or original simulator objects are regenerated.
"""
import json
from pathlib import Path
import shutil
import subprocess
import run as R

base=R.ROOT.parent/'XiangShan/build/sew16-events'
source=R.ROOT.parent/'XiangShan/build/sew16-perf-events'
out=R.ROOT.parent/'XiangShan/build/int8-gemv-wave'
assert not out.exists(),'new observer destination already exists'
header=(base/'emu-compile/VSimTop___024root.h').read_text()
P='SimTop__DOT__l_soc__DOT__core_with_l2__DOT__core__DOT__backend__DOT__inner_vfExuBlock__DOT__exus__DOT__'
D=P+'Vimac__DOT__'
# name, actual C++ model field, bit width. Wide fields are packed little-word first.
fields=[('clock','clock',1),('enable0',D+'vdot__DOT__io_enable_0',1),('enable1',D+'vdot__DOT__io_enable_1',1),
    ('vs1',D+'io_in_bits_data_src_0',128),('vs2',D+'io_in_bits_data_src_1',128),
    ('sum',D+'vdot__DOT__sum',35),('out_valid',D+'io_out_valid',1),
    ('out_data',D+'io_out_bits_res_data',128),('out_op',D+'io_in_bits_ctrlPipe_2_fuOpType',9),
    ('out_tag_flag',D+'io_out_bits_ctrl_robIdx_flag',1),('out_tag_index',D+'io_out_bits_ctrl_robIdx_value',8),
    ('out_vl',D+'io_in_bits_dataPipe_2_src_4',8),('out_sew',D+'io_in_bits_ctrlPipe_2_vpu_vsew',2),
    ('out_illegal',D+'io_out_bits_ctrl_exceptionVec_2',1),
    ('in_tag_flag',P+'io_in_bits_robIdx_flag',1),('in_tag_index',P+'io_in_bits_robIdx_value',8),
    ('in_sew',D+'io_in_bits_ctrl_vpu_vsew',2)]
fields += [(f'p{i}',D+f'vdot__DOT__products_{i}',32) for i in range(8)]
for name,field,width in fields:assert field+';' in header or '('+field+',' in header,'model field not exposed: '+field
out.mkdir();shutil.copytree(source/'emulator',out/'emulator')
cpp=r'''#pragma once
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <stdexcept>
#include "VSimTop___024root.h"
namespace gemvwave {
class Writer {
 FILE *file=nullptr; uint64_t begin=0,end=0,rows=0;
 void val(uint64_t value,unsigned bits,const char *id) {
   std::fputc('b',file);for(int bit=bits-1;bit>=0;--bit)std::fputc('0'+((value>>bit)&1),file);
   std::fprintf(file," %s\n",id);
 }
 template<typename T> void wide(const T &v,const char *id) {
   std::fputc('b',file);for(int bit=127;bit>=0;--bit)std::fputc('0'+((v[bit/32]>>(bit%32))&1),file);
   std::fprintf(file," %s\n",id);
 }
public:
 Writer() {
  const char *path=std::getenv("GEMV_WAVE_PATH");if(!path)return;
  const char *lo=std::getenv("GEMV_WAVE_BEGIN"),*hi=std::getenv("GEMV_WAVE_END");
  if(!lo||!hi)throw std::runtime_error("wave range missing");
  begin=std::strtoull(lo,nullptr,10);end=std::strtoull(hi,nullptr,10);
  if(end<begin||end-begin>10000)throw std::runtime_error("wave range invalid");
  file=std::fopen(path,"wx");if(!file)throw std::runtime_error("wave output exists or failed");
  std::setvbuf(file,nullptr,_IOFBF,1024*1024);
  std::fprintf(file,"$version Actual compiled RTL signals sampled after high/low eval; t=2*cycle+phase $end\n$timescale 1ps $end\n$scope module GEMV $end\n");
DECLARATIONS
  std::fprintf(file,"$upscope $end\n$enddefinitions $end\n");
 }
 ~Writer() {if(file && std::fclose(file))std::abort();}
 void sample(const VSimTop___024root *r,uint64_t cycle,unsigned phase) {
  if(!file||cycle<begin||cycle>end)return;
  if(++rows>20002)throw std::runtime_error("wave sample cap");
  std::fprintf(file,"#%llu\n",(unsigned long long)(2*cycle+phase));
VALUES
  if(std::ferror(file))throw std::runtime_error("wave write error");
 }
};
inline Writer &instance(){static Writer writer;return writer;}
inline void sample(const VSimTop___024root *r,uint64_t cycle,unsigned phase){instance().sample(r,cycle,phase);}
}
'''
decl=[];vals=[]
for i,(name,field,width) in enumerate(fields):
    ident='g'+str(i)
    decl.append('  std::fprintf(file,'+json.dumps(f'$comment {field} $end\n$var wire {width} {ident} {name} $end\n')+');')
    vals.append(f'  '+(f'wide(r->{field},"{ident}");' if width==128 else f'val(r->{field},{width},"{ident}");'))
cpp=cpp.replace('DECLARATIONS','\n'.join(decl)).replace('VALUES','\n'.join(vals))
(out/'emulator/gemv-wave.h').write_text(cpp)
emu=out/'emulator/emu.cpp';text=emu.read_text();text='#include "gemv-wave.h"\n'+text
start=text.index('inline void Emulator::single_cycle()')
prefix,body=text[:start],text[start:]
needle='  dut_ptr->eval();';assert body.count(needle)>=2
body=body.replace(needle,needle+'\n  gemvwave::sample(dut_ptr->rootp, cycles, 0);',1)
needle='  e16events::sample_model(dut_ptr->rootp, cycles);';assert body.count(needle)==1
body=body.replace(needle,needle+'\n  gemvwave::sample(dut_ptr->rootp, cycles, 1);')
emu.write_text(prefix+body)
mk=out/'observer.mk';obj=out/'observer.o';target=out/'emu'
mk.write_text(f'''include {base}/emu-compile/VSimTop.mk
{obj}: {emu} {out}/emulator/gemv-wave.h
\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<
{target}: {obj} $(filter-out emu.o,$(VK_USER_OBJS)) $(VK_GLOBAL_OBJS) $(VM_PREFIX)__ALL.a
\t$(LINK) $(LDFLAGS) $^ $(LOADLIBES) $(LDLIBS) $(LIBS) $(SC_LIBS) -o $@
''')
original=[base/'emu-compile/VSimTop__ALL.a',R.CORE,R.EVENTS]
before={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in original}
subprocess.run(['make','-C',str(base/'emu-compile'),'-f',str(mk),'-j2','OPT_FAST=-O3','OPT_SLOW=-O0',str(target)],check=True)
assert before=={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in original},'original model or simulators changed'
R.write(out/'observer.json',dict(status='PASS',target=str(target),fields=[dict(name=n,field=f,width=w) for n,f,w in fields],
    scope='read-only emulator wrapper relink; same compiled RTL archive; no RTL regeneration',original_unchanged=True))
print('GEMV read-only waveform observer built; original simulators unchanged')
