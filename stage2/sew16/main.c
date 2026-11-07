// 复用全部 e8 功能检查和参考计算，构建为独立新镜像。
#define VDOT_TEST_E16 1
#define main legacy_main
#include "../vdot-tests/main.c"
#undef main

extern void wide_mixed(uint64_t *, const int16_t *, const int16_t *);
extern uintptr_t wide_invalid(uint64_t *, const int16_t *, const int16_t *, uintptr_t);
extern void control_branch(void *, const void *, const void *, uintptr_t);
extern void control_exception(void *, const void *, const void *);
extern void control_trap_handler(void);
extern char control_exception_pc[];
volatile uintptr_t control_trap_armed, control_trap_count, control_trap_resume;
volatile uintptr_t control_trap_cause, control_trap_pc, control_trap_value;
static int16_t wa[8] __attribute__((aligned(64)));
static int16_t wb[8] __attribute__((aligned(64)));
static uint64_t wo[12] __attribute__((aligned(64)));
static unsigned wide_passed;

static int64_t wide_oracle(const int16_t *x, const int16_t *y) {
  int64_t s = 0;
  for (int i = 0; i < 8; ++i) s += (int64_t)x[i] * y[i];
  return s;
}
static int16_t half_signed(unsigned x) {
  return x < 32768u ? (int)x : (int)x - 65536;
}
static int wide_check(unsigned mode, unsigned policy) {
  for (int i = 0; i < 12; ++i) wo[i] = UINT64_C(0xa5a5a5a5a5a5a5a5);
  int64_t expected = wide_oracle(wa, mode == 3 || mode == 4 ? wa : wb);
  if (mode == 9) {
    int16_t intermediate[8] = {0};
    for (int i = 0; i < 4; ++i) intermediate[i] = half_signed(((uint64_t)expected >> (16 * i)) & 65535u);
    expected = wide_oracle(intermediate, wb);
  }
  uintptr_t before = wide_passed & 7u;
  asm volatile("csrw vcsr, %0" : : "r"(before) : "memory");
  vdot_compute((uint32_t *)wo, (const int8_t *)wa, (const int8_t *)wb, mode, policy | 8u);
  uintptr_t vl, type, csr, start;
  asm volatile("csrr %0, vl; csrr %1, vtype; csrr %2, vcsr; csrr %3, vstart"
      : "=r"(vl), "=r"(type), "=r"(csr), "=r"(start));
  if (wo[0] != (uint64_t)expected || wo[1] || vl != 8 || type != (policy | 8u) || csr != before || start) {
    printf("sew16 FAIL case=%u mode=%u got=%lx high=%lx expected=%lx vl=%lu type=%lx csr=%lu/%lu start=%lu\n",
      wide_passed, mode, wo[0], wo[1], (uint64_t)expected, vl, type, csr, before, start);
    return 1;
  }
  ++wide_passed;
  return 0;
}

int main(void) {
  if (legacy_main()) return 1;
  for (int c = 0; c < 8; ++c) {
    for (int i = 0; i < 8; ++i) {
      wa[i] = c < 2 ? -32768 : c == 2 ? 32767 : c == 3 ? 0 : c == 4 ? (i & 1 ? -32767 : 32767) : i * 9001 - 30000;
      wb[i] = c == 0 ? -32768 : c < 3 ? 32767 : c == 5 ? -32768 : i + 1;
    }
    for (unsigned policy = 0; policy < 4; ++policy)
      for (unsigned mode = 0; mode < 10; ++mode)
        if (wide_check(mode, policy << 6)) return 1;
  }
  static const uint32_t seeds[] = {0x56444f54u, 1u, 0x9e3779b9u, 0xdeadbeefu};
  for (unsigned s = 0; s < 4; ++s) {
    random_state = seeds[s];
    for (unsigned n = 0; n < 128; ++n) {
      for (int i = 0; i < 8; ++i) {
        wa[i] = half_signed(next_random() & 65535u);
        wb[i] = half_signed(next_random() & 65535u);
      }
      if (wide_check(n % 10, (n % 4) << 6)) return 1;
      // 每轮切换 SEW，并使用原字节级参考计算核对 e8。
      for (int i = 0; i < 16; ++i) { a[i] = ((const int8_t *)wa)[i]; b[i] = ((const int8_t *)wb)[i]; }
      if (check(n % 10, (n % 4) << 6)) return 1;
    }
    printf("sew16 random PASS seed=%x cases=128 alternating-e8-e16\n", seeds[s]);
  }
  for (int i = 0; i < 8; ++i) { wa[i] = i + 1; wb[i] = 1; }
  wide_mixed(wo, wa, wb);
  int64_t chain_expected = 36;
  for (int n = 0; n < 32; ++n) {
    uint64_t raw = (uint64_t)chain_expected;
    chain_expected = 0;
    for (int i = 0; i < 4; ++i) chain_expected += (int64_t)half_signed((raw >> (16*i)) & 65535u) * 2;
  }
  // e8 看到 01 00 02 00 03 00 04 00；e16 则看到全部八个半字。
  if (wo[0] != 10 || wo[1] || wo[2] != 36 || wo[3] ||
      wo[4] != UINT64_C(0x0004000300020001) || wo[5] != UINT64_C(0x0008000700060005) ||
      wo[6] != 36 || wo[7] || wo[8] != (uint64_t)chain_expected || wo[9] ||
      wo[10] != UINT64_C(0x0000000300000000) || wo[11] != UINT64_C(0x0000000000060000)) {
    printf("sew16 mixed FAIL\n"); return 1;
  }
  for (unsigned n = 0; n < 4; ++n) {
    wo[0] = wo[1] = UINT64_C(0xa5a5a5a5a5a5a5a5);
    uintptr_t before = vdot_trap_count;
    uintptr_t pc = wide_invalid(wo, wa, wb, n);
    uintptr_t expected = n < 2 ? 0 : n == 2 ? 0x0094250bu : 0x0294250bu;
    if (vdot_trap_count != before + 1 || vdot_trap_cause != 2 || vdot_trap_pc != pc ||
        vdot_trap_value != expected || wo[0] != UINT64_C(0xa5a5a5a5a5a5a5a5) || wo[1] != wo[0]) {
      printf("sew16 illegal FAIL case=%u cause=%lu tval=%lx/%lx\n", n, vdot_trap_cause, vdot_trap_value, expected);
      return 1;
    }
    if (wide_check(0, 0)) return 1;
  }
  asm volatile("csrw mtvec,%0" :: "r"(control_trap_handler) : "memory");
  uintptr_t quotient = UINT64_C(0x1122334455667788);
  for (int i = 0; i < 6; ++i) quotient /= 3;
  for (unsigned round = 0; round < 4; ++round) {
    for (unsigned train = 0; train < 16; ++train) {
      control_branch(wo, wa, wb, 0);
      if (wo[0] != 36 || wo[1] || wo[2] != 36 || wo[3]) {
        printf("sew16 branch training FAIL\n"); return 1;
      }
    }
    for (int i = 0; i < 6; ++i) wo[i] = UINT64_C(0xa5a5a5a5a5a5a5a5);
    control_branch(wo, wa, wb, quotient);
    for (int i = 0; i < 4; ++i) if (wo[i] != UINT64_C(0xa5a5a5a5a5a5a5a5)) {
      printf("sew16 wrong-path destination FAIL\n"); return 1;
    }
    uintptr_t before = control_trap_count;
    control_exception(wo, wa, wb);
    if (control_trap_count != before + 1 || control_trap_cause != 2 ||
        control_trap_pc != (uintptr_t)control_exception_pc || control_trap_value != 0xffffffffu || control_trap_armed) {
      printf("sew16 younger exception FAIL\n"); return 1;
    }
    for (int i = 0; i < 6; ++i) if (wo[i] != UINT64_C(0xa5a5a5a5a5a5a5a5)) {
      printf("sew16 younger destination FAIL\n"); return 1;
    }
  }
  printf("sew16 control PASS: branch-training=64 branch-probes=4 younger-exceptions=4\n");
  printf("sew16 PASS: wide=%u seeds=4 illegal=4 e8-regression=%u fixed-items=8; mixed/v0/chain/config/CSR\n", wide_passed, passed);
  return 0;
}
