#include <am.h>
#include <klib.h>
#include <stdint.h>

#ifndef VDOT_BASELINE_ONLY
#define VDOT_BASELINE_ONLY 0
#endif
#ifndef VDOT_BENCH_REPS
#define VDOT_BENCH_REPS 8
#endif
#ifndef VDOT_BENCH_WARMUP
#define VDOT_BENCH_WARMUP 8
#endif
#ifndef VDOT_BENCH_BATCHES
#define VDOT_BENCH_BATCHES 256
#endif
#ifndef VDOT_BENCH_RANDOM
#define VDOT_BENCH_RANDOM 1000
#endif
#ifndef VDOT_BENCH_FIRST
#define VDOT_BENCH_FIRST 0
#endif
#ifndef VDOT_BENCH_SMOKE
#define VDOT_BENCH_SMOKE 0
#endif
#ifndef VDOT_BENCH_RUNTIME_ORDER
#define VDOT_BENCH_RUNTIME_ORDER 0
#endif
#if VDOT_BENCH_RUNTIME_ORDER
extern const volatile uint8_t bench_runtime_order;
static unsigned runtime_first;
#define BENCH_FIRST runtime_first
#define BENCH_SCHEMA 3
#else
#define BENCH_FIRST VDOT_BENCH_FIRST
#define BENCH_SCHEMA 2
#endif
_Static_assert(VDOT_BENCH_REPS >= 2 && VDOT_BENCH_REPS % 2 == 0, "balanced even repetitions");
_Static_assert(VDOT_BENCH_WARMUP >= 2 && VDOT_BENCH_WARMUP % 2 == 0, "balanced warmup");
_Static_assert(VDOT_BENCH_BATCHES > 0 && VDOT_BENCH_BATCHES <= 65536, "bounded nonzero batch count");
_Static_assert(VDOT_BENCH_RANDOM >= 0, "nonnegative random count");
_Static_assert(VDOT_BENCH_FIRST == 0 || VDOT_BENCH_FIRST == 1, "initial order");
extern void bench_compute(uint32_t *, const int8_t *, const int8_t *, uintptr_t, uintptr_t);
extern uintptr_t bench_kernel(uint32_t *, const int8_t *, const int8_t *, uintptr_t, uintptr_t, uintptr_t);
extern uintptr_t bench_empty(uintptr_t);
static int8_t a[16] __attribute__((aligned(64)));
static int8_t b[16] __attribute__((aligned(64)));
static uint32_t out[16] __attribute__((aligned(64)));
static uint32_t seed = 0x56444f54;
static uintptr_t samples[3][2][VDOT_BENCH_REPS];
static uintptr_t warm_first[3][2], warm_last[3][2];
static uintptr_t empty_samples[VDOT_BENCH_REPS];
static uint32_t next(void) { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return seed; }
static int32_t oracle(void) {
  int32_t sum = 0;
  for (int i = 0; i < 8; ++i) sum += (int32_t)a[i] * (int32_t)b[i];
  return sum;
}
static int check(unsigned baseline, unsigned policy) {
  for (int i = 0; i < 4; ++i) out[i] = 0xa5a5a5a5;
  uintptr_t before = (policy >> 6) * 2 + ((policy >> 6) & 1);
  asm volatile("csrw vcsr, %0" : : "r"(before) : "memory");
  bench_compute(out, a, b, baseline, policy);
  uintptr_t vl, type, csr, start;
  asm volatile("csrr %0, vl\ncsrr %1, vtype\ncsrr %2, vcsr\ncsrr %3, vstart"
               : "=r"(vl), "=r"(type), "=r"(csr), "=r"(start));
  if (out[0] != (uint32_t)oracle() || out[1] || out[2] || out[3] ||
      vl != 8 || type != policy || csr != before || start) {
    printf("bench equivalence FAIL baseline=%u policy=%u actual=%x expected=%x high=%x/%x/%x vl=%lu type=%lx csr=%lu/%lu start=%lu\n",
           baseline, policy, out[0], (uint32_t)oracle(), out[1], out[2], out[3],
           (unsigned long)vl, (unsigned long)type, (unsigned long)csr,
           (unsigned long)before, (unsigned long)start);
    return 1;
  }
  return 0;
}
static int kernel_check(unsigned baseline, unsigned kind) {
  for (int j = 0; j < 4; ++j) {
    if (out[j * 4] != (kind == 2 ? 0u : 16u) || out[j * 4 + 1] ||
        out[j * 4 + 2] || out[j * 4 + 3]) {
      printf("bench kernel FAIL baseline=%u kind=%u output=%d\n", baseline, kind, j);
      return 1;
    }
  }
  uintptr_t vl, type, csr, start;
  asm volatile("csrr %0, vl\ncsrr %1, vtype\ncsrr %2, vcsr\ncsrr %3, vstart"
               : "=r"(vl), "=r"(type), "=r"(csr), "=r"(start));
  if (vl != 8 || type || csr || start) {
    printf("bench kernel FAIL CSR baseline=%u kind=%u\n", baseline, kind);
    return 1;
  }
  return 0;
}
int main(void) {
#if VDOT_BENCH_RUNTIME_ORDER
  runtime_first = bench_runtime_order;
  if (runtime_first > 1) { printf("bench runtime FAIL: invalid order\n"); return 1; }
#endif
  uintptr_t enable = 0x600;
  asm volatile("csrs mstatus, %0\ncsrwi vstart, 0\ncsrwi vcsr, 0"
               : : "r"(enable) : "memory");
  for (int c = 0; c < 8 + VDOT_BENCH_RANDOM; ++c) {
    for (int i = 0; i < 16; ++i) {
      unsigned x = next() & 255, y = next() & 255;
      a[i] = x < 128 ? x : (int)x - 256;
      b[i] = y < 128 ? y : (int)y - 256;
      if (c < 8 && i < 8) {
        a[i] = c == 0 ? i + 1 : c == 1 ? -i - 1 : c == 2 || c == 3 ? -128 : c == 4 ? 127 : c == 5 ? 0 : c == 6 ? (i & 1 ? -127 : 127) : i - 4;
        b[i] = c == 2 ? -128 : c == 3 || c == 4 ? 127 : 1;
      }
    }
    for (unsigned p = 0; p < (c < 8 ? 4u : 1u); ++p) {
      unsigned policy = (c < 8 ? p : (unsigned)(c - 8) % 4) << 6;
      if (check(1, policy)) return 1;
      if (!VDOT_BASELINE_ONLY && check(0, policy)) return 1;
    }
  }
  printf("bench equivalence PASS: vectors=%u checks=%u policies=4 baseline=vwmul+vwredsum vdot=%u\n",
         8 + VDOT_BENCH_RANDOM, 32 + VDOT_BENCH_RANDOM, !VDOT_BASELINE_ONLY);
  if (VDOT_BASELINE_ONLY) return 0;
  asm volatile("csrwi vcsr, 0" : : : "memory");
  for (int i = 0; i < 16; ++i) { a[i] = i < 8 ? 1 : 99; b[i] = i < 8 ? 2 : -101; }
  // 全部计时及输出/CSR 检查结束前，不打印成功路径信息。
  // 每组配对交替实现顺序；另一镜像反转初始顺序。
  for (unsigned kind = 0; kind < 3; ++kind) {
    for (unsigned rep = 0; rep < VDOT_BENCH_WARMUP; ++rep) {
      for (unsigned slot = 0; slot < 2; ++slot) {
        unsigned baseline = BENCH_FIRST ^ (rep & 1u) ^ slot;
        uintptr_t elapsed = bench_kernel(out, a, b, baseline, kind, VDOT_BENCH_BATCHES);
        if (kernel_check(baseline, kind)) return 1;
        if (rep == 0) warm_first[kind][baseline] = elapsed;
        warm_last[kind][baseline] = elapsed;
      }
    }
    for (unsigned rep = 0; rep < VDOT_BENCH_REPS; ++rep) {
      for (unsigned slot = 0; slot < 2; ++slot) {
        unsigned baseline = BENCH_FIRST ^ (rep & 1u) ^ slot;
        samples[kind][baseline][rep] = bench_kernel(out, a, b, baseline, kind, VDOT_BENCH_BATCHES);
        if (kernel_check(baseline, kind)) return 1;
      }
    }
  }
  for (unsigned rep = 0; rep < VDOT_BENCH_WARMUP; ++rep) bench_empty(VDOT_BENCH_BATCHES);
  for (unsigned rep = 0; rep < VDOT_BENCH_REPS; ++rep) empty_samples[rep] = bench_empty(VDOT_BENCH_BATCHES);
  printf("bench meta schema=%u profile=%s reps=%u warmup=%u batches=%u random=%u first=%u deferred=1 seed=56444f54 timing=mcycle_vstart_serialized\n",
         BENCH_SCHEMA, VDOT_BENCH_SMOKE ? "smoke" : "full", VDOT_BENCH_REPS, VDOT_BENCH_WARMUP,
         VDOT_BENCH_BATCHES, VDOT_BENCH_RANDOM, BENCH_FIRST);
  for (unsigned kind = 0; kind < 3; ++kind) {
    const char *name = kind == 2 ? "chain" : kind ? "e2e" : "batch4";
    for (unsigned baseline = 0; baseline < 2; ++baseline)
      printf("bench warm kind=%s impl=%s count=%u first_cycles=%lu last_cycles=%lu\n", name,
             baseline ? "rvv" : "vdot", VDOT_BENCH_WARMUP,
             (unsigned long)warm_first[kind][baseline], (unsigned long)warm_last[kind][baseline]);
    for (unsigned rep = 0; rep < VDOT_BENCH_REPS; ++rep) {
      for (unsigned slot = 0; slot < 2; ++slot) {
        unsigned baseline = BENCH_FIRST ^ (rep & 1u) ^ slot;
        printf("bench raw kind=%s impl=%s rep=%u slot=%u dots=%u cycles=%lu\n", name,
               baseline ? "rvv" : "vdot", rep, slot, 4 * VDOT_BENCH_BATCHES,
               (unsigned long)samples[kind][baseline][rep]);
      }
    }
  }
  for (unsigned rep = 0; rep < VDOT_BENCH_REPS; ++rep)
    printf("bench raw kind=empty impl=control rep=%u loops=%u cycles=%lu\n", rep,
           VDOT_BENCH_BATCHES, (unsigned long)empty_samples[rep]);
  printf("vdot benchmark PASS: equivalent exact i32, upper96=0; raw cycles reported\n");
  return 0;
}
