    .text
    .option push
    .option norvc
    # This pinned XS treats a CSR WRITE as waitForward+blockBackward; unlike
    # read-only mcycle, csrwi vstart is not relaxed by Rename. Requires VS on.
    # Pre-start drain is outside the interval. The next two drains are INSIDE.
    # Both implementations pay the same markers; never subtract an empty loop.
    .macro timer_start
    csrwi vstart, 0
    csrr t1, mcycle
    csrwi vstart, 0
    .endm
    .macro timer_end
    csrwi vstart, 0
    csrr t3, mcycle
    .endm
    .macro dot vd, vs1=8
    .4byte ((1 << 25) | (9 << 20) | (\vs1 << 15) | (2 << 12) | (\vd << 7) | 0x0b)
    .endm
    .macro clear_outputs
    vsetivli zero, 4, e32, m1, tu, mu
    vmv.v.i v12, 0
    vmv.v.i v14, 0
    vmv.v.i v18, 0
    vmv.v.i v22, 0
    vmv.v.i v26, 0
    vsetivli zero, 8, e8, m1, tu, mu
    .endm
    .macro rvv_batch
    # Product groups 16:17/20:21/24:25/28:29 do not overlap sources,
    # seed v12, or destinations 14/18/22/26. Each dot sums EXACT i16
    # products into i32; tu preserves the previously cleared upper96.
    vwmul.vv v16, v8, v9
    vwmul.vv v20, v8, v9
    vwmul.vv v24, v8, v9
    vwmul.vv v28, v8, v9
    vsetivli zero, 8, e16, m2, tu, mu
    vwredsum.vs v14, v16, v12
    vwredsum.vs v18, v20, v12
    vwredsum.vs v22, v24, v12
    vwredsum.vs v26, v28, v12
    vsetivli zero, 8, e8, m1, tu, mu
    .endm
    .macro dot_batch
    dot 14
    dot 18
    dot 22
    dot 26
    .endm
    .macro store_outputs
    vs1r.v v14, (a0)
    addi t2, a0, 16
    vs1r.v v18, (t2)
    addi t2, a0, 32
    vs1r.v v22, (t2)
    addi t2, a0, 48
    vs1r.v v26, (t2)
    .endm
    .globl bench_compute
    .type bench_compute, @function
# a0=16-byte output, a1/a2=16-byte sources, a3=baseline, a4=policy.
bench_compute:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vsetivli zero, 4, e32, m1, tu, mu
    vmv.v.i v10, 0
    vmv.v.i v12, 0
    vsetivli zero, 8, e8, m1, tu, mu
    beqz a3, .Lcompute_dot
    vwmul.vv v16, v8, v9
    vsetivli zero, 8, e16, m2, tu, mu
    vwredsum.vs v10, v16, v12
    j .Lcompute_done
.Lcompute_dot:
    # Dot's ta/ma-independence is tested at the actual instruction as well.
    li t0, 8
    vsetvl zero, t0, a4
    .4byte 0x0294250b
.Lcompute_done:
    li t0, 8
    vsetvl zero, t0, a4
    vs1r.v v10, (a0)
    ret
    .size bench_compute, .-bench_compute

    .globl bench_kernel
    .type bench_kernel, @function
# a3=baseline, a4=0 preloaded batch4 / 1 loads+init+stores / 2 feedback chain.
# a5 is a positive batch count. Both impls execute a5 batches of four dots.
# CSR timestamps+scalar loop work
# are identical; baseline configuration changes are intrinsically required.
bench_kernel:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    clear_outputs
    mv t0, a5
    li t4, 2
    beq a4, t4, .Lchain
    beqz a3, .Lkernel_dot
    timer_start
.Lrvv_loop:
    beqz a4, .Lrvv_compute
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    clear_outputs
.Lrvv_compute:
    rvv_batch
    beqz a4, .Lrvv_next
    store_outputs
.Lrvv_next:
    addi t0, t0, -1
    bnez t0, .Lrvv_loop
    j .Lkernel_done
.Lkernel_dot:
    timer_start
.Ldot_loop:
    beqz a4, .Ldot_compute
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    clear_outputs
.Ldot_compute:
    dot_batch
    beqz a4, .Ldot_next
    store_outputs
.Ldot_next:
    addi t0, t0, -1
    bnez t0, .Ldot_loop
    j .Lkernel_done
.Lchain:
    # Zero input is a stable fixed point, but the explicit feedback source
    # creates a real architectural vector dependency on every instruction.
    beqz a3, .Lchain_dot
    timer_start
.Lchain_rvv_loop:
    .rept 4
    vwmul.vv v16, v14, v9
    vsetivli zero, 8, e16, m2, tu, mu
    vwredsum.vs v14, v16, v12
    vsetivli zero, 8, e8, m1, tu, mu
    .endr
    addi t0, t0, -1
    bnez t0, .Lchain_rvv_loop
    j .Lkernel_done
.Lchain_dot:
    timer_start
.Lchain_dot_loop:
    .rept 4
    dot 14, 14
    .endr
    addi t0, t0, -1
    bnez t0, .Lchain_dot_loop
    j .Lkernel_done
.Lkernel_done:
    # Same unconditional jump on both paths.
    timer_end
    sub t3, t3, t1
    store_outputs
    mv a0, t3
    ret
    .size bench_kernel, .-bench_kernel

    .globl bench_empty
    .type bench_empty, @function
bench_empty:
    timer_start
.Lempty:
    addi a0, a0, -1
    bnez a0, .Lempty
    timer_end
    sub a0, t3, t1
    ret
    .size bench_empty, .-bench_empty
    .option pop
