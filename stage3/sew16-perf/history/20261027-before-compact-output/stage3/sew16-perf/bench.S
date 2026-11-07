    .text
    .option push
    .option norvc
    .macro dot vd, vs1=8
    .4byte ((1 << 25) | (9 << 20) | (\vs1 << 15) | (2 << 12) | (\vd << 7) | 0x0b)
    .endm
    .macro input_config bits
    .if \bits == 8
    vsetivli zero, 8, e8, m1, tu, mu
    .else
    vsetivli zero, 8, e16, m1, tu, mu
    .endif
    .endm
    .macro reduction_config bits
    .if \bits == 8
    vsetivli zero, 8, e16, m2, tu, mu
    .else
    vsetivli zero, 8, e32, m2, tu, mu
    .endif
    .endm
    .macro clear_outputs bits
    vsetivli zero, 4, e32, m1, tu, mu
    vmv.v.i v12, 0
    vmv.v.i v14, 0
    vmv.v.i v18, 0
    vmv.v.i v22, 0
    vmv.v.i v26, 0
    input_config \bits
    .endm
    .macro stores chain=0
    vs1r.v v14, (a0)
    addi t2, a0, 16
    .if \chain
    vs1r.v v14, (t2)
    .else
    vs1r.v v18, (t2)
    .endif
    addi t2, a0, 32
    .if \chain
    vs1r.v v14, (t2)
    .else
    vs1r.v v22, (t2)
    .endif
    addi t2, a0, 48
    .if \chain
    vs1r.v v14, (t2)
    .else
    vs1r.v v26, (t2)
    .endif
    .endm

    # out,a,b,kind(0=batch4,1=e2e,2=chain),positive iterations.
    # All four variants share the exact timing-marker and scalar-loop pattern.
    .macro kernel name, bits, baseline
    .globl \name
    .type \name, @function
\name:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    clear_outputs \bits
    mv t0, a4
    li t4, 2
    bne a3, t4, .Lprepared_\name
    vmv.v.v v14, v8
.Lprepared_\name:
    .globl \name\()_pre_guard
\name\()_pre_guard:
    csrwi vstart, 0
    .globl \name\()_start_read
\name\()_start_read:
    csrr t1, mcycle
    .globl \name\()_start_guard
\name\()_start_guard:
    csrwi vstart, 0
    .globl \name\()_body
\name\()_body:
    beq a3, t4, .Lchain_\name
.Lloop_\name:
    beqz a3, .Lcompute_\name
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    clear_outputs \bits
.Lcompute_\name:
    .if \baseline
    vwmul.vv v16, v8, v9
    vwmul.vv v20, v8, v9
    vwmul.vv v24, v8, v9
    vwmul.vv v28, v8, v9
    reduction_config \bits
    vwredsum.vs v14, v16, v12
    vwredsum.vs v18, v20, v12
    vwredsum.vs v22, v24, v12
    vwredsum.vs v26, v28, v12
    input_config \bits
    .else
    dot 14
    dot 18
    dot 22
    dot 26
    .endif
    beqz a3, .Lnext_\name
    stores 0
.Lnext_\name:
    addi t0, t0, -1
    bnez t0, .Lloop_\name
    j .Lfinish_\name
.Lchain_\name:
    .rept 4
    .if \baseline
    vwmul.vv v16, v14, v9
    reduction_config \bits
    vwredsum.vs v14, v16, v12
    input_config \bits
    .else
    dot 14, 14
    .endif
    .endr
    addi t0, t0, -1
    bnez t0, .Lchain_\name
    j .Lfinish_\name
.Lfinish_\name:
    .globl \name\()_end_guard
\name\()_end_guard:
    csrwi vstart, 0
    .globl \name\()_end_read
\name\()_end_read:
    csrr t3, mcycle
    beq a3, t4, .Lchainstore_\name
    stores 0
    j .Lreturn_\name
.Lchainstore_\name:
    stores 1
.Lreturn_\name:
    sub a0, t3, t1
    ret
    .size \name, .-\name
    .endm
    kernel perf_e8_dot, 8, 0
    kernel perf_e8_rvv, 8, 1
    kernel perf_e16_dot, 16, 0
    kernel perf_e16_rvv, 16, 1
    .option pop
