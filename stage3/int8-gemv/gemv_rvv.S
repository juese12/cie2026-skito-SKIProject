    .text
    .option push
    .option norvc
    # Same four-row reuse as optimized dot, with natural e8/m1 VL up to 16.
    # e8 multiply -> e16/m2 product -> e32 widening reduction, seeded by sum.
    .macro rvv_rows n
    mv t0,a1
    .if \n == 4
    add t1,t0,a4
    add t2,t1,a4
    add t3,t2,a4
    .endif
    mv t4,a2
    mv t5,a4
    vsetivli zero,1,e32,m1,tu,mu
    vmv.v.i v24,0
    .if \n == 4
    vmv.v.i v25,0
    vmv.v.i v26,0
    vmv.v.i v27,0
    .endif
    beqz t5,.Lrvv_store\@
.Lrvv_block\@:
    vsetvli t6,t5,e8,m1,tu,mu
    vle8.v v8,(t4)
    vle8.v v9,(t0)
    vwmul.vv v16,v9,v8
    .if \n == 4
    vle8.v v10,(t1)
    vwmul.vv v18,v10,v8
    vle8.v v11,(t2)
    vwmul.vv v20,v11,v8
    vle8.v v12,(t3)
    vwmul.vv v22,v12,v8
    .endif
    vsetvli zero,t6,e16,m2,tu,mu
    vwredsum.vs v24,v16,v24
    .if \n == 4
    vwredsum.vs v25,v18,v25
    vwredsum.vs v26,v20,v26
    vwredsum.vs v27,v22,v27
    add t1,t1,t6
    add t2,t2,t6
    add t3,t3,t6
    .endif
    add t0,t0,t6
    add t4,t4,t6
    sub t5,t5,t6
    bnez t5,.Lrvv_block\@
    vsetivli zero,1,e32,m1,tu,mu
.Lrvv_store\@:
    vse32.v v24,(a0)
    .if \n == 4
    addi a5,a0,4
    vse32.v v25,(a5)
    addi a5,a0,8
    vse32.v v26,(a5)
    addi a5,a0,12
    vse32.v v27,(a5)
    .endif
    addi a0,a0,4*\n
    li a5,\n
    mul a5,a5,a4
    add a1,a1,a5
    addi a3,a3,-\n
    .endm
    .globl gemv_rvv
    .type gemv_rvv,@function
gemv_rvv:
    li a6,4
.Lrvv_group:
    bltu a3,a6,.Lrvv_tail
    rvv_rows 4
    j .Lrvv_group
.Lrvv_tail:
    beqz a3,.Lrvv_return
    rvv_rows 1
    j .Lrvv_tail
.Lrvv_return:
    vsetivli zero,8,e8,m1,tu,mu
    ret
    .size gemv_rvv,.-gemv_rvv
    .option pop
