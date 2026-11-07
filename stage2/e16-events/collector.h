#pragma once
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>

namespace e16events {
using Wide=std::array<uint32_t,4>;
struct Alloc { bool valid; unsigned tag; uint64_t pc; unsigned inst,sew; };
struct Commit { bool valid; unsigned tag; };
struct Decision { bool valid; unsigned tag; bool taken,miss; };
struct Flush { bool valid; unsigned tag,level; };
struct Input { bool valid; unsigned tag,sew,vl,lmul,vm,start,vill; Wide a,b; };
struct Output { bool valid; unsigned tag,sew,vl,lmul,vm,start,vill,illegal; Wide result; };
struct Frame {
  uint64_t cycle; bool reset;
  std::array<Alloc,6> alloc;
  std::array<Commit,8> commit;
  std::array<Decision,4> decision;
  Input input; Output output; Flush redirect,flush;
  bool exception; unsigned instruction; bool illegal;
};
class Collector {
  FILE *file=nullptr;
  uint64_t rows=0,last=0;
  void wide(const Wide &v) { std::fprintf(file,"\"%08x%08x%08x%08x\"",v[3],v[2],v[1],v[0]); }
public:
  Collector() {
    const char *path=std::getenv("VDOT_EVENT_PATH");
    if(path && *path) {
      file=std::fopen(path,"wx");
      if(!file) throw std::runtime_error("event output exists or cannot be opened");
      std::setvbuf(file,nullptr,_IOFBF,1024*1024);
      std::fprintf(file,"{\"type\":\"header\",\"schema\":1,\"phase\":\"settled_low\",\"rob_entries\":160}\n");
    }
  }
  bool enabled() const { return file!=nullptr; }
  ~Collector() {
    if(file) {
      std::fprintf(file,"{\"type\":\"footer\",\"rows\":%llu,\"last_cycle\":%llu}\n",
        (unsigned long long)rows,(unsigned long long)last);
      if(std::fclose(file)) { std::fprintf(stderr,"event output close failed\n"); std::abort(); }
    }
  }
  void sample(const Frame &f) {
    last=f.cycle;
    if(f.reset) return;
    bool active=f.input.valid||f.output.valid||f.redirect.valid||f.flush.valid||f.exception;
    for(auto &v:f.alloc) active|=v.valid;
    for(auto &v:f.commit) active|=v.valid;
    for(auto &v:f.decision) active|=v.valid;
    if(!active) return;
    if(++rows>200000) throw std::runtime_error("event record cap exceeded; coverage invalid");
    std::fprintf(file,"{\"c\":%llu,\"d\":[",(unsigned long long)f.cycle);
    bool first=true;
    for(auto &v:f.alloc) if(v.valid) {
      std::fprintf(file,"%s[%u,%llu,%u,%u]",first?"":",",v.tag,(unsigned long long)v.pc,v.inst,v.sew);first=false;
    }
    std::fprintf(file,"],\"k\":[");first=true;
    for(auto &v:f.commit) if(v.valid) {std::fprintf(file,"%s%u",first?"":",",v.tag);first=false;}
    std::fprintf(file,"],\"b\":[");first=true;
    for(auto &v:f.decision) if(v.valid) {
      std::fprintf(file,"%s[%u,%u,%u]",first?"":",",v.tag,v.taken,v.miss);first=false;
    }
    std::fprintf(file,"]");
    if(f.input.valid) {
      const auto &v=f.input;
      std::fprintf(file,",\"i\":{\"tag\":%u,\"sew\":%u,\"vl\":%u,\"lmul\":%u,\"vm\":%u,\"start\":%u,\"vill\":%u,\"a\":",v.tag,v.sew,v.vl,v.lmul,v.vm,v.start,v.vill);
      wide(v.a);std::fprintf(file,",\"b\":");wide(v.b);std::fprintf(file,"}");
    }
    if(f.output.valid) {
      const auto &v=f.output;
      std::fprintf(file,",\"o\":{\"tag\":%u,\"sew\":%u,\"vl\":%u,\"lmul\":%u,\"vm\":%u,\"start\":%u,\"vill\":%u,\"illegal\":%u,\"result\":",v.tag,v.sew,v.vl,v.lmul,v.vm,v.start,v.vill,v.illegal);
      wide(v.result);std::fprintf(file,"}");
    }
    if(f.redirect.valid) std::fprintf(file,",\"r\":[%u,%u]",f.redirect.tag,f.redirect.level);
    if(f.flush.valid) std::fprintf(file,",\"f\":[%u,%u]",f.flush.tag,f.flush.level);
    if(f.exception) std::fprintf(file,",\"x\":[%u,%u]",f.instruction,f.illegal);
    std::fprintf(file,"}\n");
    if(std::ferror(file)) throw std::runtime_error("event write failed");
  }
};
inline Collector &instance() { static Collector value; return value; }
}

#include "event_fields.h"
