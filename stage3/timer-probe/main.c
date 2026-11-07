#include <am.h>
#include <klib.h>
#include <stdint.h>
extern uintptr_t bench_kernel(uint32_t *, const int8_t *, const int8_t *, uintptr_t, uintptr_t, uintptr_t);
static int8_t a[16] __attribute__((aligned(64)));
static int8_t b[16] __attribute__((aligned(64)));
static uint32_t out[16] __attribute__((aligned(64)));
static uintptr_t cycles[3][2];
int main(void) {
  uintptr_t vs = 0x600;
  asm volatile("csrs mstatus,%0\ncsrwi vstart,0\ncsrwi vcsr,0" :: "r"(vs) : "memory");
  for (int i=0; i<16; ++i) { a[i]=i<8?1:99; b[i]=i<8?2:-101; }
  for (unsigned kind=0; kind<3; ++kind)
    for (unsigned impl=0; impl<2; ++impl) {
      cycles[kind][impl]=bench_kernel(out,a,b,impl,kind,8);
      for (unsigned j=0; j<4; ++j)
        if(out[4*j]!=(kind==2?0u:16u)||out[4*j+1]||out[4*j+2]||out[4*j+3]) return 1;
      uintptr_t vl,type,start,csr;
      asm volatile("csrr %0,vl\ncsrr %1,vtype\ncsrr %2,vstart\ncsrr %3,vcsr"
                   : "=r"(vl),"=r"(type),"=r"(start),"=r"(csr));
      if(vl!=8||type||start||csr) return 1;
    }
  for(unsigned k=0;k<3;++k) for(unsigned i=0;i<2;++i)
    printf("timer probe kind=%u impl=%u cycles=%lu\n",k,i,(unsigned long)cycles[k][i]);
  printf("timer probe PASS: outputs and vector CSR; NOT performance samples\n");
  return 0;
}
