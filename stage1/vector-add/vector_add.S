.section .text.rvv_vector_add_i32, "ax", @progbits
.align 2

# void rvv_vector_add_i32(int32_t *dst, const int32_t *lhs,
#                         const int32_t *rhs, size_t count)
.globl rvv_vector_add_i32
.type rvv_vector_add_i32, @function
rvv_vector_add_i32:
  beqz a3, .Ldone

.Lloop:
  vsetvli t0, a3, e32, m1, ta, ma
  vle32.v v8, (a1)
  vle32.v v9, (a2)
  vadd.vv v10, v8, v9
  vse32.v v10, (a0)

  slli t1, t0, 2
  add a0, a0, t1
  add a1, a1, t1
  add a2, a2, t1
  sub a3, a3, t0
  bnez a3, .Lloop

.Ldone:
  ret
.size rvv_vector_add_i32, .-rvv_vector_add_i32
