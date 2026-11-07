    .text
    .balign 4
    .option push
    .option norvc
    .globl control_trap_handler
control_trap_handler:
    addi sp, sp, -32
    sd t0, 0(sp)
    sd t1, 8(sp)
    sd t2, 16(sp)
    sd t3, 24(sp)
    la t0, control_trap_armed
    ld t1, 0(t0)
    beqz t1, .Lunexpected
    sd zero, 0(t0)
    la t0, control_trap_count
    ld t1, 0(t0)
    addi t1, t1, 1
    sd t1, 0(t0)
    csrr t1, mcause
    la t0, control_trap_cause
    sd t1, 0(t0)
    csrr t1, mepc
    la t0, control_trap_pc
    sd t1, 0(t0)
    csrr t1, mtval
    la t0, control_trap_value
    sd t1, 0(t0)
    la t0, control_trap_resume
    ld t1, 0(t0)
    csrw mepc, t1                 # 跳过全部年轻指令区域，异常恢复后不重新执行该区域。
    ld t0, 0(sp)
    ld t1, 8(sp)
    ld t2, 16(sp)
    ld t3, 24(sp)
    addi sp, sp, 32
    mret
.Lunexpected:
    li a0, 1
    .4byte 0x0000006b
    j .Lunexpected
    .option pop
