/* 复用原标量参考计算、输出/CSR 检查及汇编内核。
 * 不调用历史基准的 main，也不修改历史文件。 */
#define main historical_benchmark_main
#include "../vdot-bench/main.c"
#undef main

static uintptr_t diagnostic_cycles[2][16][2];

__attribute__((noinline)) static int split_driver(unsigned kind) {
  for (unsigned rep=0; rep<8; ++rep) {
    for (unsigned slot=0; slot<2; ++slot) {
      unsigned impl=runtime_first ^ (rep & 1u) ^ slot;
      uintptr_t elapsed=bench_kernel(out,a,b,impl,kind,DIAG_BATCHES);
      if (kernel_check(impl,kind)) return 1;
      diagnostic_cycles[kind][rep][impl]=elapsed;
      if (!rep) warm_first[kind][impl]=elapsed;
      warm_last[kind][impl]=elapsed;
    }
  }
  for (unsigned rep=0; rep<8; ++rep) {
    for (unsigned slot=0; slot<2; ++slot) {
      unsigned impl=runtime_first ^ (rep & 1u) ^ slot;
      diagnostic_cycles[kind][rep+8][impl]=bench_kernel(out,a,b,impl,kind,DIAG_BATCHES);
      if (kernel_check(impl,kind)) return 1;
    }
  }
  return 0;
}

__attribute__((noinline)) static int unified_driver(unsigned kind) {
  /* 全部 16 轮使用同一静态调用点及相同存储、检查路径。
   * 只有全部调用完成后打印时才标注预热与正式轮次。 */
  for (unsigned round=0; round<16; ++round) {
    for (unsigned slot=0; slot<2; ++slot) {
      unsigned impl=runtime_first ^ (round & 1u) ^ slot;
      diagnostic_cycles[kind][round][impl]=bench_kernel(out,a,b,impl,kind,DIAG_BATCHES);
      if (kernel_check(impl,kind)) return 1;
    }
  }
  return 0;
}

int main(void) {
  unsigned parameter=bench_runtime_order;
  if (parameter>3) { printf("e2e diag FAIL invalid parameter\n"); return 1; }
  runtime_first=parameter & 1u;
  unsigned mode=parameter >> 1;
  uintptr_t enable=0x600;
  asm volatile("csrs mstatus,%0\ncsrwi vstart,0\ncsrwi vcsr,0" :: "r"(enable) : "memory");
  /* 定向等价检查用于诊断前置状态，不能算作一千组随机正式覆盖，
   * 也不等于精确复现历史调用上下文。 */
  for (int i=0;i<16;++i) { a[i]=i<8?1:99; b[i]=i<8?2:-101; }
  for (unsigned policy=0;policy<4;++policy)
    for (unsigned impl=0;impl<2;++impl) if (check(impl,policy<<6)) return 1;
  asm volatile("csrwi vcsr,0" ::: "memory");
  /* 两组都保留先 batch4、后端到端调用的阶段顺序。 */
  for (unsigned kind=0;kind<2;++kind)
    if (mode ? unified_driver(kind) : split_driver(kind)) return 1;
  printf("e2e diag meta schema=1 mode=%u first=%u batches=%u warmup=8 reps=8 directed=4\n",mode,runtime_first,DIAG_BATCHES);
  for (unsigned kind=0;kind<2;++kind)
    for (unsigned round=0;round<16;++round)
      for (unsigned slot=0;slot<2;++slot) {
        unsigned impl=runtime_first ^ (round & 1u) ^ slot;
        printf("e2e diag raw kind=%u round=%u impl=%u slot=%u cycles=%lu\n",kind,round,impl,slot,(unsigned long)diagnostic_cycles[kind][round][impl]);
      }
  printf("e2e diag PASS: complete outputs/CSR, all warm and measured calls; NOT formal performance samples\n");
  return 0;
}
