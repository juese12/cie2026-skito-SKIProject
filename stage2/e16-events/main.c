#include <am.h>
#include <klib.h>
#include <stdint.h>
extern void control_branch(void *, const void *, const void *, uintptr_t);
extern void control_exception(void *, const void *, const void *);
extern void control_trap_handler(void);
extern char control_branch_pc[],control_branch_dot[],control_branch_dot_v0[];
extern char control_exception_pc[],control_younger_dot[],control_younger_dot_v0[];
extern char control_younger_dot_alias[],control_exception_resume[];
// 未调用的共享汇编辅助代码仍引用历史陷入处理全局变量。
volatile uintptr_t vdot_trap_armed,vdot_trap_count,vdot_after_vstart;
volatile uintptr_t control_trap_armed,control_trap_count,control_trap_resume;
volatile uintptr_t control_trap_cause,control_trap_pc,control_trap_value;
static int16_t a[8] __attribute__((aligned(64))),b[8] __attribute__((aligned(64)));
static uint64_t out[6] __attribute__((aligned(64)));
static uint32_t state;
static uint32_t next(void) {state^=state<<13;state^=state>>17;state^=state<<5;return state;}
static int16_t half(unsigned v) {v&=65535;return v<32768?(int)v:(int)v-65536;}
static int64_t oracle(void) {int64_t s=0;for(int i=0;i<8;++i)s+=(int64_t)a[i]*b[i];return s;}
static void poison(void) {for(int i=0;i<6;++i)out[i]=UINT64_C(0xa5a5a5a5a5a5a5a5);}
static int csr(void) {
  uintptr_t vl,type,start,vcsr;
  asm volatile("csrr %0,vl; csrr %1,vtype; csrr %2,vstart; csrr %3,vcsr"
    :"=r"(vl),"=r"(type),"=r"(start),"=r"(vcsr));
  return vl!=8 || type!=8 || start || vcsr!=4;
}
#define CHECK(c,label) do {if(c){printf("short FAIL %s\n",label);return 1;}}while(0)
int main(void) {
  uintptr_t vs=0x600;
  asm volatile("csrs mstatus,%0; csrwi vstart,0; csrwi vcsr,4"::"r"(vs):"memory");
  asm volatile("csrw mtvec,%0"::"r"(control_trap_handler):"memory");
  static const uint32_t seeds[]={0x56444f54u,1u,0x9e3779b9u,0xdeadbeefu};
  uintptr_t quotient=UINT64_C(0x1122334455667788);
  for(int i=0;i<6;++i)quotient/=3;
  unsigned trained=0,probed=0,exceptions=0;
  for(unsigned s=0;s<4;++s) {
    state=seeds[s];
    for(int i=0;i<8;++i) {
      a[i]=s==0?-32768:half(next());b[i]=s==0?-32768:half(next());
    }
    int64_t expected=oracle();
    for(unsigned round=0;round<2;++round) {
      for(unsigned t=0;t<16;++t) {
        poison();control_branch(out,a,b,0);
        CHECK(out[0]!=(uint64_t)expected || out[1] || out[2]!=(uint64_t)expected || out[3],"training result64/v0");
        ++trained;
      }
      poison();control_branch(out,a,b,quotient);
      for(int i=0;i<4;++i)CHECK(out[i]!=UINT64_C(0xa5a5a5a5a5a5a5a5),"wrong path architecture");
      CHECK(csr(),"branch CSR");++probed;
      uintptr_t before=control_trap_count;
      poison();control_exception(out,a,b);
      CHECK(control_trap_count!=before+1 || control_trap_cause!=2 ||
        control_trap_pc!=(uintptr_t)control_exception_pc || control_trap_value!=0xffffffffu || control_trap_armed,"precise trap");
      for(int i=0;i<6;++i)CHECK(out[i]!=UINT64_C(0xa5a5a5a5a5a5a5a5),"younger architecture");
      CHECK(csr(),"exception CSR");++exceptions;
    }
  }
  printf("short symbols branch=%lx branch_dot=%lx branch_v0=%lx illegal=%lx young=%lx young_v0=%lx young_alias=%lx resume=%lx\n",
    (uintptr_t)control_branch_pc,(uintptr_t)control_branch_dot,(uintptr_t)control_branch_dot_v0,
    (uintptr_t)control_exception_pc,(uintptr_t)control_younger_dot,(uintptr_t)control_younger_dot_v0,
    (uintptr_t)control_younger_dot_alias,(uintptr_t)control_exception_resume);
  printf("short PASS data_seeds=4 train=%u probe=%u exception=%u contract=e16 witness=8589934592\n",trained,probed,exceptions);
  return 0;
}
