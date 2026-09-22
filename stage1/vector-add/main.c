#include <am.h>
#include <klib.h>
#include <stdint.h>

#define ELEMENT_COUNT 37

static int32_t source_a[ELEMENT_COUNT] __attribute__((aligned(64)));
static int32_t source_b[ELEMENT_COUNT] __attribute__((aligned(64)));
static int32_t destination[ELEMENT_COUNT] __attribute__((aligned(64)));

extern void rvv_vector_add_i32(int32_t *dst, const int32_t *lhs,
                               const int32_t *rhs, uintptr_t count);

static void enable_vector_state(void) {
  asm volatile(
      "lui a0, 0x2\n"
      "addiw a0, a0, 512\n"
      "csrs mstatus, a0\n"
      "csrwi vcsr, 0\n"
      "csrwi vstart, 0"
      :
      :
      : "a0", "memory");
}

static uintptr_t read_vlmax_e32m1(void) {
  uintptr_t vlmax;
  uintptr_t avl = (uintptr_t)-1;
  asm volatile("vsetvli %0, %1, e32, m1, ta, ma"
               : "=r"(vlmax)
               : "r"(avl));
  return vlmax;
}

int main(void) {
  int64_t checksum = 0;

  enable_vector_state();
  uintptr_t vlmax = read_vlmax_e32m1();

  for (int i = 0; i < ELEMENT_COUNT; i++) {
    source_a[i] = i * 3 - 40;
    source_b[i] = 100 - i * 2;
    destination[i] = 0x55555555;
  }

  rvv_vector_add_i32(destination, source_a, source_b, ELEMENT_COUNT);

  for (int i = 0; i < ELEMENT_COUNT; i++) {
    int32_t expected = source_a[i] + source_b[i];
    if (destination[i] != expected) {
      printf("vector-add FAIL: index=%d actual=%d expected=%d\n",
             i, destination[i], expected);
      return 1;
    }
    checksum += destination[i];
  }

  printf("vector-add configuration: elements=%d sew=32 lmul=1 vlmax=%lu\n",
         ELEMENT_COUNT, (unsigned long)vlmax);
  printf("vector-add result: first=%d last=%d checksum=%ld\n",
         destination[0], destination[ELEMENT_COUNT - 1], (long)checksum);
  printf("vector-add PASS: vadd.vv completed and all elements matched\n");
  return 0;
}
