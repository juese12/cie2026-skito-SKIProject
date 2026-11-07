#ifndef INT8_GEMV_H
#define INT8_GEMV_H
#include <stdint.h>
#include <stddef.h>

/* Row-major signed inputs; no alias between output, inputs and pack buffers.
 * 0 <= M <= 32, 0 <= K <= 256. All sums fit int32. No bias or requantization.
 * Vector registers and vl/vtype are caller-clobbered. vstart must be zero. */
#define GEMV_MAX_M 32u
#define GEMV_MAX_K 256u
typedef void (*GemvKernel)(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
void gemv_scalar(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
void gemv_rvv(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
/* dot kernels require K divisible by 8, including K=0. */
void gemv_dot1(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
void gemv_dot4(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
int gemv_oracle(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
size_t gemv_pack(int8_t *, int8_t *, const int8_t *, const int8_t *, size_t, size_t);
uintptr_t gemv_measure(GemvKernel, int32_t *, const int8_t *, const int8_t *, size_t, size_t);
void gemv_dot1_e2e(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
void gemv_dot4_e2e(int32_t *, const int8_t *, const int8_t *, size_t, size_t);
#endif
