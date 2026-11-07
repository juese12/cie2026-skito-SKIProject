/* 独立诊断：复用原精确参考计算与检查，不修改正式实验。 */
#define main historical_benchmark_main
#include "../vdot-bench/main.c"
#undef main

const volatile uint8_t diag_parameter = 0;
extern uintptr_t diag_wrapper(uint32_t *, const int8_t *, const int8_t *,
                              uintptr_t, uintptr_t, uintptr_t);
static uintptr_t controlled_cycles[6][2];

int main(void) {
  unsigned parameter = diag_parameter;
  if ((parameter & 7u) > 5u || parameter > 13u) return 1;
  uintptr_t enable = 0x600;
  asm volatile("csrs mstatus,%0\ncsrwi vstart,0\ncsrwi vcsr,0"
               :: "r"(enable) : "memory");
  for (int i=0; i<16; ++i) { a[i]=i<8?1:99; b[i]=i<8?2:-101; }
  for (unsigned policy=0; policy<4; ++policy)
    for (unsigned impl=0; impl<2; ++impl)
      if (check(impl,policy<<6)) return 1;
  asm volatile("csrwi vcsr,0" ::: "memory");
  /* 每组使用相同调用 PC、前序交替、数据、检查和六轮运行。
   * 定长调用前包装只改变空操作分段或 ALU 类别。
   * 包装在内核设置及原计时标记之前结束。 */
  for (unsigned round=0; round<6; ++round)
    for (unsigned slot=0; slot<2; ++slot) {
      unsigned impl=(round & 1u)^slot;
      controlled_cycles[round][impl]=diag_wrapper(out,a,b,impl,1,256);
      if (kernel_check(impl,1)) return 1;
    }
  printf("controlled meta schema=1 phase=%u pressure=%u batches=256 rounds=6 first=0 directed=4\n",
         parameter & 7u, parameter >> 3);
  for (unsigned round=0; round<6; ++round)
    for (unsigned slot=0; slot<2; ++slot) {
      unsigned impl=(round & 1u)^slot;
      printf("controlled raw round=%u slot=%u impl=%u cycles=%lu\n",
             round,slot,impl,(unsigned long)controlled_cycles[round][impl]);
    }
  printf("controlled PASS: outputs/CSR; ALL calls; diagnostic NOT formal performance\n");
  return 0;
}
