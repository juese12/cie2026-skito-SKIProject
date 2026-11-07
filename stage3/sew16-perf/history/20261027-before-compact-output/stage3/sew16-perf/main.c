#include <am.h>
#include <klib.h>
#include <stdint.h>

extern const volatile uint8_t perf_params[8];
typedef uintptr_t (*Kernel)(void *,const void *,const void *,uintptr_t,uintptr_t);
extern uintptr_t perf_e8_dot(void *,const void *,const void *,uintptr_t,uintptr_t);
extern uintptr_t perf_e8_rvv(void *,const void *,const void *,uintptr_t,uintptr_t);
extern uintptr_t perf_e16_dot(void *,const void *,const void *,uintptr_t,uintptr_t);
extern uintptr_t perf_e16_rvv(void *,const void *,const void *,uintptr_t,uintptr_t);
static Kernel kernels[2][2]={{perf_e8_dot,perf_e8_rvv},{perf_e16_dot,perf_e16_rvv}};
static uint8_t a[16] __attribute__((aligned(64))),b[16] __attribute__((aligned(64)));
static uint64_t out[8] __attribute__((aligned(64)));
static uint64_t warm[2][5][8][2],sample[2][5][8][2];
static uint64_t expected[2][5];
static uint8_t timing_a[2][5][16],timing_b[2][5][16];
static unsigned lengths[5],checks[2][2],steps[2][5];
static uint32_t state;
static uint32_t next(void) {state^=state<<13;state^=state>>17;state^=state<<5;return state;}
static uint64_t raw64(const uint8_t *p) {uint64_t v=0;for(unsigned i=0;i<8;++i)v|=(uint64_t)p[i]<<(8*i);return v;}
static int64_t lane(const uint8_t *p,unsigned i,unsigned bits) {
  unsigned x=p[i*(bits/8)];if(bits==16)x|=(unsigned)p[2*i+1]<<8;
  return x&(1u<<(bits-1))?(int64_t)x-(1u<<bits):x;
}
static void put(uint8_t *p,unsigned i,unsigned bits,int value) {
  unsigned x=(unsigned)value;p[i*(bits/8)]=(uint8_t)x;
  if(bits==16)p[2*i+1]=(uint8_t)(x>>8);
}
static uint64_t oracle(const uint8_t *x,const uint8_t *y,unsigned bits) {
  int64_t s=0;for(unsigned i=0;i<8;++i)s+=lane(x,i,bits)*lane(y,i,bits);
  return bits==8?(uint32_t)s:(uint64_t)s;
}
static int fail(const char *reason,unsigned bits,unsigned impl,unsigned kind) {
  printf("perf4 FAIL reason=%s bits=%u impl=%u kind=%u\n",reason,bits,impl,kind);return 1;
}
static int check(unsigned wi,unsigned impl,unsigned kind,uint64_t answer,uintptr_t csr) {
  unsigned bits=wi?16:8;
  for(unsigned i=0;i<4;++i)if(out[2*i]!=answer || out[2*i+1])return fail("full128",bits,impl,kind);
  uintptr_t vl,type,start,now;
  asm volatile("csrr %0,vl; csrr %1,vtype; csrr %2,vstart; csrr %3,vcsr"
    :"=r"(vl),"=r"(type),"=r"(start),"=r"(now));
  if(vl!=8 || type!=(wi?8:0) || start || now!=csr)return fail("CSR",bits,impl,kind);
  return 0;
}
static void poison(void) {for(unsigned i=0;i<8;++i)out[i]=UINT64_C(0xa5a5a5a5a5a5a5a5);}
static void inputs(unsigned bits,unsigned directed) {
  for(unsigned i=0;i<16;++i){a[i]=(uint8_t)next();b[i]=(uint8_t)next();}
  for(unsigned i=0;i<8;++i) {
    int min=-(1<<(bits-1)),max=(1<<(bits-1))-1;
    int x=directed==0?(int)i+1:directed==1?-(int)i-1:
      directed==2 || directed==3?min:directed==4?max:directed==5?0:directed==6?(i&1?max:-max):(int)i-4;
    int y=directed==2?min:directed==3 || directed==4?max:1;
    if(directed<8){put(a,i,bits,x);put(b,i,bits,y);}
  }
}
int main(void) {
  unsigned profile=perf_params[1],first=perf_params[2],wide=perf_params[3];
  state=(uint32_t)perf_params[4]|((uint32_t)perf_params[5]<<8)|((uint32_t)perf_params[6]<<16)|((uint32_t)perf_params[7]<<24);
  uint32_t initial_seed=state;
  if(perf_params[0]!=4 || profile>2 || first>1 || wide>1 || !state)return fail("parameters",0,0,0);
  unsigned reps=profile==2?8:profile==1?4:2;
  unsigned warms=profile==2?8:profile==1?2:0;
  unsigned randoms=profile==2?64:profile==1?8:0;
  lengths[0]=lengths[1]=profile==2?64:profile==1?4:1;
  lengths[2]=profile==2?4:1;lengths[3]=profile==2?16:2;lengths[4]=profile==2?64:4;
  uintptr_t vs=0x600;
  asm volatile("csrs mstatus,%0; csrwi vstart,0; csrwi vcsr,0"::"r"(vs):"memory");
  for(unsigned wi=0;wi<=wide;++wi) {
    unsigned bits=wi?16:8;
    // Functional coverage is outside all timing intervals. All four outputs,
    // signed boundaries and all four vcsr values are checked on both paths.
    for(unsigned c=0;c<8+randoms;++c) {
      inputs(bits,c<8?c:8);uint64_t answer=oracle(a,b,bits);
      for(unsigned policy=0;policy<(c<8?4u:1u);++policy) {
        uintptr_t csr=c<8?policy:c%4;
        asm volatile("csrw vcsr,%0"::"r"(csr):"memory");
        for(unsigned impl=0;impl<2;++impl) {
          poison();kernels[wi][impl](out,a,b,0,1);
          if(check(wi,impl,0,answer,csr))return 1;
          ++checks[wi][impl];
        }
      }
    }
    asm volatile("csrwi vcsr,0":::"memory");
    for(unsigned kind=0;kind<5;++kind) {
      unsigned mode=kind<2?kind:2,n=lengths[kind];
      if(mode==2) {
        for(unsigned j=0;j<16;++j)a[j]=b[j]=0;
        put(a,0,bits,wi?257:37);put(b,0,bits,3);
        uint8_t feedback[16];for(unsigned j=0;j<16;++j)feedback[j]=a[j];
        uint64_t previous=0;
        for(unsigned j=0;j<4*n;++j) {
          uint64_t result=oracle(feedback,b,bits);
          if(!result || (j && result==previous))return fail("chain-fixed-point",bits,0,kind);
          previous=result;for(unsigned k=0;k<16;++k)feedback[k]=k<8?(uint8_t)(result>>(8*k)):0;
          ++steps[wi][kind];
        }
        expected[wi][kind]=previous;
      } else {
        inputs(bits,8);expected[wi][kind]=oracle(a,b,bits);
        if(!expected[wi][kind])return fail("zero-timing-vector",bits,0,kind);
      }
      for(unsigned j=0;j<16;++j){timing_a[wi][kind][j]=a[j];timing_b[wi][kind][j]=b[j];}
      for(unsigned phase=0;phase<2;++phase) {
        unsigned count=phase?reps:warms;
        for(unsigned rep=0;rep<count;++rep)for(unsigned slot=0;slot<2;++slot) {
          unsigned impl=first^(rep&1)^slot;
          poison();uint64_t elapsed=kernels[wi][impl](out,a,b,mode,n);
          if(!elapsed || check(wi,impl,kind,expected[wi][kind],0))return 1;
          (phase?sample:warm)[wi][kind][rep][impl]=elapsed;
        }
      }
    }
  }
  printf("perf4 meta schema=4 profile=%u first=%u wide=%u data=%08x reps=%u warm=%u random=%u deferred=1\n",
    profile,first,wide,initial_seed,reps,warms,randoms);
  for(unsigned wi=0;wi<=wide;++wi) {
    printf("perf4 equivalence bits=%u dot=%u rvv=%u full128=1 CSR=1\n",wi?16:8,checks[wi][0],checks[wi][1]);
    for(unsigned kind=0;kind<5;++kind) {
      printf("perf4 case bits=%u kind=%u batches=%u dots=%u expected=%016lx chain_steps=%u a=%016lx%016lx b=%016lx%016lx\n",
        wi?16:8,kind,lengths[kind],4*lengths[kind],expected[wi][kind],steps[wi][kind],
        raw64(timing_a[wi][kind]+8),raw64(timing_a[wi][kind]),raw64(timing_b[wi][kind]+8),raw64(timing_b[wi][kind]));
      for(unsigned phase=0;phase<2;++phase)for(unsigned rep=0;rep<(phase?reps:warms);++rep)
        for(unsigned slot=0;slot<2;++slot) {
          unsigned impl=first^(rep&1)^slot;
          printf("perf4 raw bits=%u kind=%u phase=%u rep=%u slot=%u impl=%u cycles=%lu\n",
            wi?16:8,kind,phase,rep,slot,impl,(phase?sample:warm)[wi][kind][rep][impl]);
        }
    }
  }
  printf("perf4 PASS full128=1 CSR=1 nonzero_feedback=1 exact_signed=1\n");
  return 0;
}
