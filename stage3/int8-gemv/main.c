#include <am.h>
#include <klib.h>
#include "gemv.h"

extern const volatile uint8_t gemv_params[8];
static GemvKernel compute[4]={gemv_scalar,gemv_rvv,gemv_dot1,gemv_dot4};
static GemvKernel e2e[4]={gemv_scalar,gemv_rvv,gemv_dot1_e2e,gemv_dot4_e2e};
static uint8_t wb[GEMV_MAX_M*GEMV_MAX_K+32] __attribute__((aligned(64)));
static uint8_t xb[GEMV_MAX_K+32] __attribute__((aligned(64)));
static uint8_t pb[GEMV_MAX_M*GEMV_MAX_K+32] __attribute__((aligned(64)));
static uint8_t qb[GEMV_MAX_K+32] __attribute__((aligned(64)));
static int8_t *const w=(int8_t *)wb+16,*const x=(int8_t *)xb+16;
static int8_t *const pw=(int8_t *)pb+16,*const px=(int8_t *)qb+16;
static int32_t output[GEMV_MAX_M+2],expected[GEMV_MAX_M];
static uintptr_t samples[2][2][8][4]; /* case, mode, warm+sample index, impl */
static int32_t timing_y[2][GEMV_MAX_M];
static uint32_t timing_seed[2],state;
static unsigned checks[4],cases;
static const size_t shape[2][2]={{16,64},{17,65}};
static const uint32_t data_seeds[4]={0x56444f54,1,0x9e3779b9,0xdeadbeef};
static uint32_t next(void) {state^=state<<13;state^=state>>17;state^=state<<5;return state;}
static int fail(const char *why,unsigned impl,size_t row) {
  printf("gemv FAIL reason=%s impl=%u row=%u case=%u\n",why,impl,(unsigned)row,cases);return 1;
}
static void inputs(size_t m,size_t k,unsigned pattern) {
  memset(wb,0xa5,sizeof(wb));memset(xb,0xa5,sizeof(xb));
  for(size_t c=0;c<k;++c)
    x[c]=pattern==0?0:pattern==1?-128:pattern==2?127:pattern==3?1:(int8_t)(next()&255);
  for(size_t r=0;r<m;++r)for(size_t c=0;c<k;++c)
    w[r*k+c]=pattern==0?0:pattern==1?-128:pattern==2?-128:
      pattern==3?(int8_t)((c&1)?-(int)(r+1):(int)(r+1)):(int8_t)(next()&255);
}
static int prepare(size_t m,size_t k) {
  memset(pb,0xa5,sizeof(pb));memset(qb,0xa5,sizeof(qb));
  size_t kp=gemv_pack(pw,px,w,x,m,k);
  if(!gemv_oracle(expected,w,x,m,k))return fail("oracle-range",0,0);
  for(size_t c=0;c<kp;++c)if(px[c]!=(c<k?x[c]:0))return fail("pack-x",0,c);
  for(size_t r=0;r<m;++r)for(size_t c=0;c<kp;++c)
    if(pw[r*kp+c]!=(c<k?w[r*k+c]:0))return fail("pack-w",0,r);
  return 0;
}
static void poison(void) {for(unsigned r=0;r<GEMV_MAX_M+2;++r)output[r]=(int32_t)0x5a6bc7d8;}
static int check(unsigned impl,size_t m,size_t k) {
  for(size_t r=0;r<m;++r)if(output[r+1]!=expected[r])return fail("output",impl,r);
  for(size_t r=m+1;r<GEMV_MAX_M+2;++r)
    if(output[r]!=(int32_t)0x5a6bc7d8)return fail("output-overrun",impl,r);
  if(output[0]!=(int32_t)0x5a6bc7d8)return fail("output-underrun",impl,0);
  size_t kp=(k+7)&~(size_t)7;
  for(unsigned r=0;r<16;++r)
    if(wb[r]!=0xa5 || xb[r]!=0xa5 || pb[r]!=0xa5 || qb[r]!=0xa5 ||
       wb[16+m*k+r]!=0xa5 || xb[16+k+r]!=0xa5 ||
       pb[16+m*kp+r]!=0xa5 || qb[16+kp+r]!=0xa5)return fail("input-canary",impl,r);
  uintptr_t start,csr;
  asm volatile("csrr %0,vstart; csrr %1,vcsr":"=r"(start),"=r"(csr));
  if(start || csr)return fail("vector-csr",impl,0);
  ++checks[impl];return 0;
}
static int functional(size_t m,size_t k,unsigned pattern) {
  inputs(m,k,pattern);if(prepare(m,k))return 1;
  size_t kp=(k+7)&~(size_t)7;
  for(unsigned mode=0;mode<2;++mode)for(unsigned impl=0;impl<4;++impl) {
    poison();(mode?e2e:compute)[impl](output+1,mode?w:pw,mode?x:px,m,mode?k:kp);
    if(check(impl,m,k))return 1;
  }
  ++cases;return 0;
}
int main(void) {
  unsigned profile=gemv_params[1],first=gemv_params[2];
  uint32_t seed=(uint32_t)gemv_params[4]|((uint32_t)gemv_params[5]<<8)|
    ((uint32_t)gemv_params[6]<<16)|((uint32_t)gemv_params[7]<<24);
  if(gemv_params[0]!=1 || profile>2 || first>3 || gemv_params[3] || !seed)return fail("params",0,0);
  uintptr_t vs=0x600;
  asm volatile("csrs mstatus,%0; csrwi vstart,0; csrwi vcsr,0"::"r"(vs):"memory");
  if(!profile) {
    /* One real four-row call. K=17 forces three dots per row and zero tail. */
    state=seed;inputs(4,17,4);if(prepare(4,17))return 1;poison();
    uintptr_t cycles=gemv_measure(gemv_dot4,output+1,pw,px,4,24);
    if(check(3,4,17))return 1;
    for(unsigned mode=0;mode<2;++mode)for(unsigned impl=0;impl<4;++impl) {
      poison();samples[0][mode][0][impl]=gemv_measure((mode?e2e:compute)[impl],output+1,
        mode?w:pw,mode?x:px,4,mode?17:24);
      if(check(impl,4,17))return 1;
    }
    printf("gemv probe m=4 k=17 kp=24 seed=%08x cycles=%lu y=",seed,cycles);
    for(unsigned r=0;r<4;++r)printf("%s%d",r?",":"",output[r+1]);
    printf("\ngemv PASS profile=0 checked_rows=4\n");return 0;
  }
  state=seed;
  static const unsigned directed[][3]={
    {0,0,0},{0,17,4},{1,0,0},{1,1,2},{1,7,1},{3,8,2},{4,9,1},
    {5,15,3},{7,16,4},{5,17,4},{8,31,4},{17,33,4},{4,256,1},{32,256,2}};
  unsigned count=profile==2?sizeof(directed)/sizeof(directed[0]):8;
  for(unsigned i=0;i<count;++i)
    if(functional(directed[i][0],directed[i][1],directed[i][2]))return 1;
  for(unsigned s=0;s<4;++s) {
    state=data_seeds[s];
    for(unsigned c=0;c<(profile==2?4u:1u);++c)
      if(functional(1+next()%9,1+next()%41,4))return 1;
  }
  unsigned warms=profile==2?2:1,reps=profile==2?6:2;
  for(unsigned c=0;c<2;++c) {
    size_t m=profile==2?shape[c][0]:c?5:4,k=profile==2?shape[c][1]:c?17:16;
    timing_seed[c]=seed^(0x13579bdfu*(c+1));if(!timing_seed[c])timing_seed[c]=1;
    state=timing_seed[c];inputs(m,k,4);if(prepare(m,k))return 1;
    for(size_t r=0;r<m;++r)timing_y[c][r]=expected[r];
    for(unsigned mode=0;mode<2;++mode)for(unsigned rep=0;rep<warms+reps;++rep)
      for(unsigned slot=0;slot<4;++slot) {
        unsigned impl=(first+rep+slot)%4;
        poison();
        uintptr_t elapsed=gemv_measure((mode?e2e:compute)[impl],output+1,
          mode?w:pw,mode?x:px,m,mode?k:(k+7)&~(size_t)7);
        if(!elapsed || check(impl,m,k))return 1;
        samples[c][mode][rep][impl]=elapsed;
      }
  }
  /* Defer all successful UART output until timing has finished. */
  printf("gemv meta schema=1 profile=%u first=%u seed=%08x warm=%u reps=%u cases=%u\n",
    profile,first,seed,warms,reps,cases);
  for(unsigned impl=0;impl<4;++impl)printf("gemv checks impl=%u calls=%u\n",impl,checks[impl]);
  for(unsigned c=0;c<2;++c) {
    size_t m=profile==2?shape[c][0]:c?5:4,k=profile==2?shape[c][1]:c?17:16;
    printf("gemv case id=%u m=%u k=%u kp=%u data=%08x y=",c,(unsigned)m,(unsigned)k,(unsigned)((k+7)&~7u),timing_seed[c]);
    for(size_t r=0;r<m;++r)printf("%s%d",r?",":"",timing_y[c][r]);
    printf("\n");
    for(unsigned mode=0;mode<2;++mode)for(unsigned impl=0;impl<4;++impl) {
      printf("gemv seq case=%u mode=%u impl=%u cycles=",c,mode,impl);
      for(unsigned rep=0;rep<warms+reps;++rep)printf("%s%lu",rep?",":"",samples[c][mode][rep][impl]);
      printf("\n");
    }
  }
  printf("gemv PASS profile=%u checked_each_row=1 guards=1 signed=1 data_seeds=4\n",profile);
  return 0;
}
