#include "../vdot-bench/bench.S"
    .text
    .option push
    .option norvc
    .balign 4
    .globl diag_wrapper
    .type diag_wrapper,@function
diag_wrapper:
    li t6,3
    .globl diag_pressure
diag_pressure:
    .rept 6
    addi t6,t6,1
    .endr
    .globl diag_phase
diag_phase:
    # 每个固定 4 字节槽放一条 addi x0,x0,0，或两条 c.nop。
    # 各组不改变分支、目标以及调用者、内核或数据的地址布局。
    .rept 6
    .4byte 0x00000013
    .endr
    j bench_kernel
    .size diag_wrapper,.-diag_wrapper
    .option pop
