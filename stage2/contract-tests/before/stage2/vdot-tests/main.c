#include <am.h>
#include <klib.h>
#include <stdint.h>

#ifndef VDOT_RANDOM_CASES
#define VDOT_RANDOM_CASES 1000
#endif
#ifndef VDOT_ORDINARY_ONLY
#define VDOT_ORDINARY_ONLY 0
#endif

extern void vdot_compute(uint32_t *, const int8_t *, const int8_t *, uintptr_t, uintptr_t);
extern void vdot_ordinary(uint32_t *, const int8_t *, const int8_t *, uintptr_t);
extern uintptr_t vdot_invalid(uint32_t *, const int8_t *, const int8_t *, uintptr_t);
extern void vdot_trap_handler(void);
volatile uintptr_t vdot_trap_armed, vdot_trap_count, vdot_trap_cause;
volatile uintptr_t vdot_trap_pc, vdot_trap_value, vdot_after_vstart;
static int8_t a[16] __attribute__((aligned(64)));
static int8_t b[16] __attribute__((aligned(64)));
static uint32_t out[8] __attribute__((aligned(64)));
static uint32_t random_state = 0x56444f54u;
static unsigned passed;

static uint32_t next_random(void) {
  random_state ^= random_state << 13;
  random_state ^= random_state >> 17;
  random_state ^= random_state << 5;
  return random_state;
}
static int32_t oracle(const int8_t *x, const int8_t *y) {
  int32_t sum = 0;
  for (int i = 0; i < 8; ++i) sum += (int32_t)x[i] * (int32_t)y[i];
  return sum;
}
static int check(unsigned mode, unsigned policy) {
  for (int i = 0; i < 8; ++i) out[i] = 0xa5a5a5a5u;
  int32_t expected = oracle(a, mode == 3 || mode == 4 ? a : b);
  if (mode == 9) {
    uint32_t word = (uint32_t)expected;
    int8_t intermediate[8] = {0};
    for (int i = 0; i < 4; ++i) {
      unsigned byte = (word >> (8 * i)) & 255;
      intermediate[i] = byte < 128 ? byte : (int)byte - 256;
    }
    expected = oracle(intermediate, b);
  }
  uintptr_t csr_before = (passed & 3u) * 2u + (passed & 1u);
  asm volatile("csrw vcsr, %0" : : "r"(csr_before) : "memory");
  vdot_compute(out, a, b, mode, policy);
  uintptr_t vl, vtype, vcsr, start;
  asm volatile("csrr %0, vl\ncsrr %1, vtype\ncsrr %2, vcsr\ncsrr %3, vstart"
               : "=r"(vl), "=r"(vtype), "=r"(vcsr), "=r"(start));
  if (out[0] != (uint32_t)expected || out[1] || out[2] || out[3] ||
      vl != 8 || vtype != policy || vcsr != csr_before || start != 0) {
    printf("vdot FAIL case=%u mode=%u policy=%u actual=%x expected=%x high=%x/%x/%x vl=%lu type=%lx csr=%lu/%lu start=%lu\n",
           passed, mode, policy, out[0], (uint32_t)expected, out[1], out[2], out[3],
           (unsigned long)vl, (unsigned long)vtype, (unsigned long)vcsr,
           (unsigned long)csr_before, (unsigned long)start);
    return 1;
  }
  if (mode == 10) {
    const uint8_t *bytes = (const uint8_t *)(out + 4);
    for (int i = 0; i < 16; ++i) {
      uint8_t expected_byte = i < 8 && (((uint32_t)expected >> i) & 1u)
        ? (uint8_t)((int)a[i] + (int)b[i]) : 0;
      if (bytes[i] != expected_byte) {
        printf("vdot mask FAIL byte=%d actual=%u expected=%u\n", i, bytes[i], expected_byte);
        return 1;
      }
    }
  }
  ++passed;
  return 0;
}

static int ordinary_regression(void) {
  for (int i = 0; i < 16; ++i) { a[i] = i < 8 ? 1 : 99; b[i] = i < 8 ? 2 : -101; }
  for (unsigned mode = 0; mode < 4; ++mode) {
    uintptr_t before = 4u + (mode & 1u); // vxrm=RDN, alternate sticky vxsat
    asm volatile("csrw vcsr, %0" : : "r"(before) : "memory");
    vdot_ordinary(out, a, b, mode);
    unsigned expected = mode == 0 ? 3 : mode == 3 ? 0 : 2;
    const uint8_t *bytes = (const uint8_t *)out;
    for (int i = 0; i < 16; ++i) if (bytes[i] != (i < 8 ? expected : 0)) {
      printf("vdot ordinary FAIL mode=%u byte=%d actual=%u\n", mode, i, bytes[i]);
      return 1;
    }
    uintptr_t csr;
    asm volatile("csrr %0, vcsr" : "=r"(csr));
    if (csr != before) { printf("vdot ordinary CSR FAIL mode=%u\n", mode); return 1; }
  }
  for (int i = 0; i < 8; ++i) a[i] = b[i] = -128;
  asm volatile("csrwi vcsr, 4" : : : "memory");
  vdot_ordinary(out, a, b, 3);
  const uint8_t *bytes = (const uint8_t *)out;
  for (int i = 0; i < 16; ++i) if (bytes[i] != (i < 8 ? 127 : 0)) {
    printf("vdot vsmul saturation FAIL byte=%d actual=%u\n", i, bytes[i]);
    return 1;
  }
  uintptr_t csr;
  asm volatile("csrr %0, vcsr" : "=r"(csr));
  if (csr != 5) { printf("vdot vsmul saturation CSR FAIL\n"); return 1; }
  printf("vdot ordinary regression PASS: vadd/vmul/vmacc/vsmul, sticky and new saturation\n");
  return 0;
}

int main(void) {
  uintptr_t vs_enable = 0x600;
  asm volatile("csrs mstatus, %0\ncsrwi vstart, 0\ncsrwi vcsr, 0"
               : : "r"(vs_enable) : "memory");
  asm volatile("csrw mtvec, %0" : : "r"(vdot_trap_handler) : "memory");
  if (ordinary_regression()) return 1;
  if (VDOT_ORDINARY_ONLY) {
    printf("ordinary-only PASS: no vdot instruction executed\n");
    return 0;
  }
  for (int c = 0; c < 8; ++c) {
    for (int i = 0; i < 16; ++i) {
      a[i] = i < 8 ? (c == 0 || c == 1 ? i + 1 : c == 2 ? -i - 1 : c == 3 || c == 4 ? -128 : c == 5 ? 127 : c == 7 ? (i & 1 ? -127 : 127) : 0) : 99;
      b[i] = i < 8 ? (c == 1 ? 8 - i : c == 3 ? -128 : c == 4 || c == 5 ? 127 : 1) : -101;
    }
    for (unsigned policy = 0; policy < 4; ++policy)
      if (check(0, policy << 6)) return 1;
  }
  printf("vdot directed PASS: 32 cases (positive/negative/extreme/zero/cancellation; all ta/ma)\n");
  for (int i = 0; i < 16; ++i) { a[i] = i + 1; b[i] = i < 8 ? 1 : -128; }
  for (unsigned mode = 1; mode <= 10; ++mode)
    if (check(mode, 0)) return 1;
  printf("vdot integration PASS: overlap/v0/v31/dependency-chain/v0-mask\n");
  for (int c = 0; c < VDOT_RANDOM_CASES; ++c) {
    for (int i = 0; i < 16; ++i) {
      unsigned ua = next_random() & 255u, ub = next_random() & 255u;
      a[i] = ua < 128 ? ua : (int)ua - 256;
      b[i] = ub < 128 ? ub : (int)ub - 256;
    }
    if (check(c % 11, (c % 4) << 6)) return 1;
  }
  printf("vdot random PASS: %u cases seed=0x56444f54\n", (unsigned)VDOT_RANDOM_CASES);
  for (unsigned c = 0; c < 10; ++c) {
    for (int i = 0; i < 4; ++i) out[i] = 0xa5a5a5a5u;
    uintptr_t before = vdot_trap_count;
    uintptr_t fault_pc = vdot_invalid(out, a, b, c);
    uintptr_t expected_tval = c < 4 ? 0 : c == 6 ? 0x0094250bu : 0x0294250bu;
    if (vdot_trap_count != before + 1 || vdot_trap_cause != 2 ||
        vdot_trap_pc != fault_pc || vdot_trap_armed != 0 ||
        vdot_trap_value != expected_tval ||
        vdot_after_vstart != (c == 7 ? 1u : 0u)) {
      printf("vdot exception FAIL case=%u count=%lu cause=%lu pc=%lx/%lx value=%lx vstart=%lu\n",
             c, (unsigned long)vdot_trap_count, (unsigned long)vdot_trap_cause,
             (unsigned long)vdot_trap_pc, (unsigned long)fault_pc,
             (unsigned long)vdot_trap_value, (unsigned long)vdot_after_vstart);
      return 1;
    }
    for (int i = 0; i < 4; ++i) if (out[i] != 0xa5a5a5a5u) {
      printf("vdot exception destination FAIL case=%u word=%d value=%x\n", c, i, out[i]);
      return 1;
    }
    if (check(0, 0)) return 1; // Successful operation immediately after recovery.
  }
  printf("vdot illegal PASS: VL=0/7/9/16, SEW, LMUL, vm, vstart, vill, VS-off\n");
  printf("vdot PASS: valid=%u illegal=10; complete 128-bit results and CSR checks\n", passed);
  return 0;
}
