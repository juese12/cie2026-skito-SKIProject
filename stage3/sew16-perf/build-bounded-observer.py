#!/usr/bin/env python3
"""只重新链接只读观察器，保留原事件模拟器。"""
import json
from pathlib import Path
import shutil
import subprocess
import common as C

base=C.ROOT.parent/'XiangShan/build/sew16-events'
out=C.ROOT.parent/'XiangShan/build/sew16-perf-events'
C.need(not out.exists(),'bounded observer exists')
old=json.loads((base/'final.json').read_text())
C.need(C.sha(base/'emu')==old['emu_sha256'],'original observer changed')
out.mkdir(parents=True)
shutil.copytree(base/'emulator',out/'emulator')
header=out/'emulator/collector.h';text=header.read_text()
C.need(text.count('uint64_t rows=0,last=0;')==1,'wrong collector')
text=text.replace('uint64_t rows=0,last=0;','uint64_t rows=0,last=0,stopCycle=0;')
needle='const char *path=std::getenv("VDOT_EVENT_PATH");'
text=text.replace(needle,needle+'\n    const char *limit=std::getenv("VDOT_EVENT_STOP_CYCLE");\n    if(limit) stopCycle=std::strtoull(limit,nullptr,10);')
lines=text.splitlines()
for i,line in enumerate(lines):
    if 'std::fprintf(file,' in line and 'schema' in line:
        h='{"type":"header","schema":1,"phase":"settled_low","rob_entries":160,"allocation_gate":"firstUop","stop_cycle":%llu}\n'
        lines[i]='      std::fprintf(file,'+json.dumps(h)+',(unsigned long long)stopCycle);'
text='\n'.join(lines)+'\n'
start=text.index('  ~Collector() {');end=text.index('  void sample(',start)
text=text[:start]+r'''  void finish(bool bounded) {
    if(file) {
      std::fprintf(file,"{\"type\":\"footer\",\"rows\":%llu,\"last_cycle\":%llu,\"bounded\":%s}\n",
        (unsigned long long)rows,(unsigned long long)last,bounded?"true":"false");
      if(std::fclose(file)) std::abort();
      file=nullptr;
    }
  }
  ~Collector() { finish(false); }
'''+text[end:]
text=text.replace('last=f.cycle;','last=f.cycle;\n    if(stopCycle && last>stopCycle) { finish(true); return; }',1)
header.write_text(text)
mk=out/'bounded.mk';obj=out/'bounded-emu.o';target=out/'emu'
mk.write_text(f'''include {base}/emu-compile/VSimTop.mk
{obj}: {out}/emulator/emu.cpp {out}/emulator/collector.h
\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<
{target}: {obj} $(filter-out emu.o,$(VK_USER_OBJS)) $(VK_GLOBAL_OBJS) $(VM_PREFIX)__ALL.a
\t$(LINK) $(LDFLAGS) $^ $(LOADLIBES) $(LDLIBS) $(LIBS) $(SC_LIBS) -o $@
''')
frozen={str(p):C.sha(p) for p in [base/'emu',base/'emu-compile/VSimTop__ALL.a',
  *sorted((base/'emu-compile').glob('*.o'))]}
subprocess.run(['make','-C',str(base/'emu-compile'),'-f',str(mk),'-j2','OPT_FAST=-O3','OPT_SLOW=-O0',str(target)],check=True)
C.frozen(frozen)
result=dict(status='PASS',emu_sha256=C.sha(target),original_observer_sha256=old['emu_sha256'],
  original_objects_unchanged=True,frozen=frozen,
  sources={str(p):C.sha(p) for p in (header,out/'emulator/emu.cpp',out/'emulator/event_fields.h')},
  mode='read-only settled-low observer, explicit bounded capture footer; identical model archive; no RTL regeneration')
with (out/'complete.json').open('x') as f:json.dump(result,f,indent=2)
print('[bounded observer COMPLETE]',C.sha(target),flush=True)
