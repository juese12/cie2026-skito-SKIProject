#include <am.h>
#include <klib.h>
#include <stdint.h>
#include "../test-contract.h"

#ifndef CONTROL_SEED
#define CONTROL_SEED 0x56444f54u
#endif
#ifndef CONTROL_RANDOM_CASES
#define CONTROL_RANDOM_CASES 256
#endif
extern void control_branch(void *, const void *, const void *, uintptr_t);
extern void control_exception(void *, const void *, const void *);
extern void control_config(void *, const void *, const void *, uintptr_t);
extern void control_config_fault(void *, const void *, const void *, uintptr_t, uintptr_t);
extern void control_mixed(void *, const void *, const void *, uintptr_t);
extern void control_chain(void *, const void *, const void *, uintptr_t);
extern void vdot_compute(uint32_t *, const int8_t *, const int8_t *, uintptr_t, uintptr_t);
extern void control_trap_handler(void);
extern char control_branch_pc[], control_branch_dot[], control_branch_dot_v0[];
extern char control_exception_pc[], control_younger_dot[], control_younger_dot_v0[], control_younger_dot_alias[];
extern char control_config_fault_pc[];
// 引入的历史汇编仍引用这些变量，但此处不调用其非法指令辅助函数。
volatile uintptr_t vdot_trap_armed, vdot_trap_count, vdot_after_vstart;
volatile uintptr_t control_trap_armed, control_trap_count, control_trap_resume;
volatile uintptr_t control_trap_cause, control_trap_pc, control_trap_value;
static int8_t a[16] __attribute__((aligned(64))), b[16] __attribute__((aligned(64)));
static uint32_t out[24] __attribute__((aligned(64)));
static uint32_t state = CONTROL_SEED;

static uint32_t next(void) {
  state ^= state << 13; state ^= state >> 17; state ^= state << 5; return state;
}
static int8_t byte(unsigned x) { x &= 255; return x < 128 ? x : (int)x - 256; }
static int32_t dot(const int8_t *x, const int8_t *y) {
  int32_t s = 0; for (unsigned i = 0; i < 8; ++i) s += (int32_t)x[i] * y[i]; return s;
}
static int32_t feedback(int32_t x) {
  int8_t tmp[8] = {0}; for (unsigned i = 0; i < 4; ++i) tmp[i] = byte((uint32_t)x >> (8*i));
  return dot(tmp, b);
}
static void poison(void) { for (unsigned i = 0; i < 24; ++i) out[i] = 0xa5a5a5a5u; }
static int result(unsigned offset, int32_t expected) {
  return out[offset] != (uint32_t)expected || out[offset+1] || out[offset+2] || out[offset+3];
}
static int csr(unsigned policy) {
  uintptr_t vl, type, start, vcsr;
  asm volatile("csrr %0,vl\ncsrr %1,vtype\ncsrr %2,vstart\ncsrr %3,vcsr"
    : "=r"(vl), "=r"(type), "=r"(start), "=r"(vcsr));
  return vl != 8 || type != policy || start != 0 || vcsr != 4;
}
#define CHECK(cond, label) do { if (cond) { printf("control FAIL: %s seed=%x\n", label, (unsigned)CONTROL_SEED); return 1; } } while (0)

int main(void) {
  uintptr_t vs = 0x600;
  asm volatile("csrs mstatus,%0\ncsrwi vstart,0\ncsrwi vcsr,4" :: "r"(vs) : "memory");
  asm volatile("csrw mtvec,%0" :: "r"(control_trap_handler) : "memory");
  for (unsigned i = 0; i < 16; ++i) { a[i] = byte(i+1); b[i] = i < 8 ? 1 : -101; }
  uintptr_t quotient = 0x1122334455667788UL;
  for (unsigned i = 0; i < 6; ++i) quotient /= 3;
  unsigned branch_training = 0, branch_probes = 0;
  // 在 VCD 前段先执行一次分支反转和一次异常后的年轻指令场景；
  // 后续轮次在相同静态 PC 上重复这些场景。
  for (unsigned round = 0; round < 4; ++round) {
    for (unsigned train = 0; train < 16; ++train) {
      poison(); control_branch(out, a, b, 0);
      CHECK(result(0, dot(a,b)) || result(4, dot(a,b)), "branch training outputs");
      ++branch_training;
    }
    poison(); control_branch(out, a, b, quotient);
    for (unsigned i = 0; i < 8; ++i) CHECK(out[i] != 0xa5a5a5a5u, "branch skipped destination/v0");
    CHECK(csr(0), "branch skipped VL/vtype/vstart/vcsr preserved");
    ++branch_probes;
    poison(); uintptr_t traps = control_trap_count;
    control_exception(out, a, b);
    CHECK(control_trap_count != traps+1 || control_trap_cause != 2 ||
          control_trap_pc != (uintptr_t)control_exception_pc || control_trap_armed,
          "precise illegal exception");
    CHECK(control_trap_value != 0xffffffffUL, "illegal mtval");
    for (unsigned i = 0; i < 12; ++i) CHECK(out[i] != 0xa5a5a5a5u, "younger destination/v0 preserved");
    CHECK(csr(0), "post trap CSR");
  }
  for (unsigned i = 0; i < 24; ++i) {
    for (unsigned j = 0; j < 16; ++j) { a[j] = byte(next()); b[j] = byte(next()); }
    poison(); unsigned policy = (i & 3) << 6;
    control_config(out, a, b, policy);
    CHECK(result(0,dot(a,b)) || result(4,dot(a,b)) || result(8,dot(a,b)) || csr(policy), "VL/vtype transitions");
  }
  for (unsigned i = 0; i < 16; ++i) {
    poison(); uintptr_t traps = control_trap_count;
    unsigned policy = ((i >> 1) & 3) << 6;
#if VDOT_TEST_E16
    unsigned sew_fault = i % 3;
#else
    unsigned sew_fault = i & 1;
#endif
    unsigned expected_type = !sew_fault ? policy : policy | (sew_fault == 2 ? 24 : VDOT_BAD_VTYPE);
    // e32 的 VLMAX 为 4、e64 为 2，vsetvl 会将请求的 AVL=8 相应缩小。
    unsigned expected_vl = !sew_fault ? 7 : sew_fault == 2 ? 2 : VDOT_BAD_VL;
    control_config_fault(out, a, b, policy, sew_fault);
    CHECK(control_trap_count != traps+1 || control_trap_cause != 2 ||
          control_trap_pc != (uintptr_t)control_config_fault_pc || control_trap_armed,
          "last illegal VL/vtype configuration must trap");
    CHECK(control_trap_value != (sew_fault ? 0x02942a0bUL : 0), "config fault exact mtval");
    for (unsigned j = 0; j < 4; ++j) CHECK(out[j] != 0xa5a5a5a5u, "config fault destination preserved");
    CHECK(out[4] != expected_vl || out[5] ||
          out[6] != expected_type || out[7] || csr(0),
          "config fault snapshots/final restored CSR");
  }
  for (unsigned i = 0; i < 16; ++i) {
    for (unsigned j = 0; j < 16; ++j) { a[j] = byte(next()); b[j] = byte(next()); }
    poison(); control_mixed(out, a, b, 32);
    int32_t s = dot(a,b), s1 = feedback(s), s2 = feedback(s1);
    const uint8_t *bytes = (const uint8_t *)out;
    for (unsigned j = 0; j < 16; ++j) {
      CHECK(bytes[j] != (j < 8 ? (uint8_t)(2*(int32_t)a[j]*b[j]) : 0xa5), "ordinary vmul/vmacc merge");
      int8_t x = j < 4 ? byte((uint32_t)s >> (8*j)) : 0;
      CHECK(bytes[16+j] != (j < 8 ? (uint8_t)((int)x*b[j]) : 0xa5), "ordinary vmul with v0 input");
    }
    CHECK(result(8,s) || result(12,s) || result(16,s1) || result(20,s2) || csr(0), "mixed dot/v0 outputs");
    poison(); control_chain(out, a, b, 128);
    int32_t expected = s;
    for (unsigned j = 1; j < 128; ++j) expected = feedback(expected);
    CHECK(result(0,expected) || csr(0), "128-step genuine v0 feedback chain");
  }
  for (unsigned i = 0; i < CONTROL_RANDOM_CASES; ++i) {
    for (unsigned j = 0; j < 16; ++j) { a[j] = byte(next()); b[j] = byte(next()); }
    unsigned mode = i % 11, policy = (i & 3) << 6;
    int32_t expected = dot(a, (mode == 3 || mode == 4) ? a : b);
    if (mode == 9) expected = feedback(expected);
    poison(); vdot_compute(out, a, b, mode, policy);
    CHECK(result(0,expected) || csr(policy), "random signed dot aliases/v0/CSR");
    if (mode == 10) {
      const uint8_t *bytes = (const uint8_t *)(out+4);
      for (unsigned j = 0; j < 16; ++j) {
        unsigned value = j < 8 && (((uint32_t)expected >> j)&1) ? (uint8_t)((int)a[j]+b[j]) : 0;
        CHECK(bytes[j] != value, "random v0 mask consumer");
      }
    }
  }
#if VDOT_TEST_E16
  printf("control contract=e8-e16 unsupported=e32/e64\n");
#endif
  printf("control symbols branch=%lx branch_dot=%lx branch_v0=%lx illegal=%lx young=%lx young_v0=%lx young_alias=%lx\n",
    (uintptr_t)control_branch_pc, (uintptr_t)control_branch_dot, (uintptr_t)control_branch_dot_v0,
    (uintptr_t)control_exception_pc, (uintptr_t)control_younger_dot,
    (uintptr_t)control_younger_dot_v0, (uintptr_t)control_younger_dot_alias);
  printf("control PASS: seed=%x random=%u branch_train=%u branch_probe=%u illegal=%lu configs=24 config_faults=16 mixed=16x32 chains=16x128\n",
    (unsigned)CONTROL_SEED, (unsigned)CONTROL_RANDOM_CASES, branch_training, branch_probes, control_trap_count);
  return 0;
}
