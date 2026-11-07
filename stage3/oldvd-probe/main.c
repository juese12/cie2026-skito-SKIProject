#include <am.h>
#include <klib.h>
#include <stdint.h>

extern uintptr_t oldvd_probe(uint32_t *out, uintptr_t kind, uintptr_t policy);
static uint32_t out[4] __attribute__((aligned(64)));
static uintptr_t cycles[4][6][2];

int main(void) {
  uintptr_t vs = 0x600;
  asm volatile("csrs mstatus,%0\ncsrwi vstart,0\ncsrwi vcsr,0"
               :: "r"(vs) : "memory");
  for (unsigned policy=0; policy<4; ++policy)
    for (unsigned kind=0; kind<6; ++kind)
      for (unsigned rep=0; rep<2; ++rep) {
        cycles[policy][kind][rep]=oldvd_probe(out,kind,policy);
        uint32_t expected=(kind==3||kind==5)?0:16;
        if(out[0]!=expected||out[1]||out[2]||out[3]) {
          printf("oldvd probe FAIL: policy=%u kind=%u rep=%u output\n",policy,kind,rep);
          return 1;
        }
        uintptr_t vl,type,start,csr;
        asm volatile("csrr %0,vl\ncsrr %1,vtype\ncsrr %2,vstart\ncsrr %3,vcsr"
                     : "=r"(vl),"=r"(type),"=r"(start),"=r"(csr));
        if(vl!=8||type!=((uintptr_t)policy<<6)||start||csr) {
          printf("oldvd probe FAIL: policy=%u kind=%u rep=%u CSR\n",policy,kind,rep);
          return 1;
        }
      }
  for (unsigned policy=0; policy<4; ++policy)
    for (unsigned kind=0; kind<6; ++kind)
      for (unsigned rep=0; rep<2; ++rep)
        printf("oldvd sample policy=%u kind=%u rep=%u dots=32 cycles=%lu\n",
               policy,kind,rep,(unsigned long)cycles[policy][kind][rep]);
  printf("oldvd probe PASS: 48 calls, full128 outputs and CSR; directed evidence, NOT application/PPA\n");
  return 0;
}
