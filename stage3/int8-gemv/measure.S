    .text
    .option push
    .option norvc
    .globl gemv_measure
    .type gemv_measure,@function
gemv_measure:
    addi sp,sp,-32
    sd ra,0(sp)
    sd s0,8(sp)
    mv t0,a0
    mv a0,a1
    mv a1,a2
    mv a2,a3
    mv a3,a4
    mv a4,a5
    .globl gemv_timer_pre_guard
gemv_timer_pre_guard:
    csrwi vstart,0
    .globl gemv_timer_start_read
gemv_timer_start_read:
    csrr s0,mcycle
    .globl gemv_timer_start_guard
gemv_timer_start_guard:
    csrwi vstart,0
    .globl gemv_timer_call
gemv_timer_call:
    jalr t0
    .globl gemv_timer_end_guard
gemv_timer_end_guard:
    csrwi vstart,0
    .globl gemv_timer_end_read
gemv_timer_end_read:
    csrr t0,mcycle
    sub a0,t0,s0
    ld s0,8(sp)
    ld ra,0(sp)
    addi sp,sp,32
    ret
    .size gemv_measure,.-gemv_measure
    .option pop
