    .text
    .option push
    .option norvc
    .macro dot vd,vs1
    .4byte (0x0200200b | (8 << 20) | (\vs1 << 15) | (\vd << 7))
    .endm
    # Simple implementation: e32 scalar extraction per eight-element block.
    .globl gemv_dot1
    .type gemv_dot1,@function
gemv_dot1:
    beqz a3,.Lone_return
.Lone_row:
    mv t0,a1
    mv t1,a2
    mv t2,a4
    li t3,0
    beqz t2,.Lone_store
    vsetivli zero,8,e8,m1,tu,mu
.Lone_block:
    vle8.v v8,(t1)
    vle8.v v9,(t0)
    dot 16,9
    vsetivli zero,1,e32,m1,tu,mu
    vmv.x.s t4,v16
    add t3,t3,t4
    addi t0,t0,8
    addi t1,t1,8
    addi t2,t2,-8
    beqz t2,.Lone_store
    vsetivli zero,8,e8,m1,tu,mu
    j .Lone_block
.Lone_store:
    sw t3,0(a0)
    addi a0,a0,4
    add a1,a1,a4
    addi a3,a3,-1
    bnez a3,.Lone_row
.Lone_return:
    vsetivli zero,8,e8,m1,tu,mu
    ret
    .size gemv_dot1,.-gemv_dot1

    # Four independent output rows reuse one eight-byte x load.
    # v16/v18/v20/v22 hold dot results; v24..v27 hold INT32 row sums.
    .macro dot_rows n
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
    beqz t5,.Ldot_store\@
.Ldot_block\@:
    vsetivli zero,8,e8,m1,tu,mu
    vle8.v v8,(t4)
    vle8.v v9,(t0)
    dot 16,9
    .if \n == 4
    vle8.v v10,(t1)
    dot 18,10
    vle8.v v11,(t2)
    dot 20,11
    vle8.v v12,(t3)
    dot 22,12
    .endif
    vsetivli zero,1,e32,m1,tu,mu
    vadd.vv v24,v24,v16
    .if \n == 4
    vadd.vv v25,v25,v18
    vadd.vv v26,v26,v20
    vadd.vv v27,v27,v22
    addi t1,t1,8
    addi t2,t2,8
    addi t3,t3,8
    .endif
    addi t0,t0,8
    addi t4,t4,8
    addi t5,t5,-8
    bnez t5,.Ldot_block\@
.Ldot_store\@:
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
    .globl gemv_dot4
    .type gemv_dot4,@function
gemv_dot4:
    li a6,4
.Lfour_group:
    bltu a3,a6,.Lfour_tail
    dot_rows 4
    j .Lfour_group
.Lfour_tail:
    beqz a3,.Lfour_return
    dot_rows 1
    j .Lfour_tail
.Lfour_return:
    vsetivli zero,8,e8,m1,tu,mu
    ret
    .size gemv_dot4,.-gemv_dot4
    .option pop
