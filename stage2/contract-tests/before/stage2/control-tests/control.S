    .text
    .option push
    .option norvc
    .macro dot vd, vs2, vs1
    .4byte ((1 << 25) | (\vs2 << 20) | (\vs1 << 15) | (2 << 12) | (\vd << 7) | 0x0b)
    .endm
    .macro slow_value
    li t2, 0x1122334455667788
    li t1, 3
    .rept 6
    divu t2, t2, t1
    .endr
    .endm

    .globl control_branch
control_branch:                   # out,a,b,expected quotient (0 trains fallthrough)
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v20, (a0)
    addi t0, a0, 16
    vl1re8.v v0, (t0)
    vsetivli zero, 8, e8, m1, tu, mu
    slow_value                   # Branch depends on a real six-divide chain.
    .globl control_branch_pc
control_branch_pc:
    beq t2, a3, .Lbranch_skip
    .globl control_branch_dot
control_branch_dot:
    dot 20, 9, 8
    .globl control_branch_dot_v0
control_branch_dot_v0:
    dot 0, 9, 8
.Lbranch_skip:
    vs1r.v v20, (a0)
    addi t0, a0, 16
    vs1r.v v0, (t0)
    ret

    .globl control_exception
control_exception:               # out,a,b: all three destinations pre-poisoned
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v20, (a0)
    addi t0, a0, 16
    vl1re8.v v0, (t0)
    addi t0, a0, 32
    vl1re8.v v21, (t0)
    vsetivli zero, 8, e8, m1, tu, mu
    la t0, control_trap_resume
    la t1, control_exception_resume
    sd t1, 0(t0)
    la t0, control_trap_armed
    li t1, 1
    sd t1, 0(t0)
    slow_value                   # Older divide work delays exception retirement.
    .globl control_exception_pc
control_exception_pc:
    .4byte 0xffffffff
    .globl control_younger_dot
control_younger_dot:
    dot 20, 9, 8
    .globl control_younger_dot_v0
control_younger_dot_v0:
    dot 0, 9, 8
    .globl control_younger_dot_alias
control_younger_dot_alias:
    dot 21, 9, 21
    .globl control_exception_resume
control_exception_resume:
    vs1r.v v20, (a0)
    addi t0, a0, 16
    vs1r.v v0, (t0)
    addi t0, a0, 32
    vs1r.v v21, (t0)
    ret

    .globl control_config
control_config:                  # out,a,b,final vtype policy; no intervening CSR reads
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vsetivli zero, 8, e16, m1, tu, mu
    vsetivli zero, 7, e8, m1, ta, ma
    vsetivli zero, 8, e8, m1, tu, mu
    dot 20, 9, 8
    vsetivli zero, 16, e8, m1, ta, ma
    li t0, 8
    vsetvl zero, t0, a3
    dot 21, 9, 8
    vsetivli zero, 0, e8, m1, tu, mu
    vsetivli zero, 8, e32, m1, ta, ma
    vsetvl zero, t0, a3
    dot 0, 9, 8
    vs1r.v v20, (a0)
    addi t0, a0, 16
    vs1r.v v21, (t0)
    addi t0, a0, 32
    vs1r.v v0, (t0)
    ret

    .globl control_config_fault
control_config_fault:            # out,a,b,policy,a4: 0=last VL7; 1=last SEW16
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v20, (a0)
    la t0, control_trap_resume
    la t1, control_config_fault_resume
    sd t1, 0(t0)
    la t0, control_trap_armed
    li t1, 1
    sd t1, 0(t0)
    vsetivli zero, 0, e32, m1, ta, ma
    vsetivli zero, 8, e8, m1, tu, mu
    li t0, 7
    beqz a4, .Lfault_final
    li t0, 8
    ori a3, a3, 8
.Lfault_final:
    vsetvl zero, t0, a3
    .globl control_config_fault_pc
control_config_fault_pc:
    dot 20, 9, 8
    .globl control_config_fault_resume
control_config_fault_resume:
    csrr t0, vl
    sd t0, 16(a0)
    csrr t0, vtype
    sd t0, 24(a0)
    vsetivli zero, 8, e8, m1, tu, mu
    vs1r.v v20, (a0)
    ret

    .globl control_mixed
control_mixed:                   # out[96],a,b,iterations
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v16, (a0)
    addi t0, a0, 16
    vl1re8.v v17, (t0)
    vsetivli zero, 8, e8, m1, tu, mu
.Lmixed:
    vmul.vv v16, v8, v9
    dot 20, 9, 8
    vmacc.vv v16, v8, v9
    dot 0, 9, 8
    dot 21, 9, 0
    vmul.vv v17, v0, v9
    dot 22, 9, 21
    addi a3, a3, -1
    bnez a3, .Lmixed
    vs1r.v v16, (a0)
    addi t0, a0, 16
    vs1r.v v17, (t0)
    addi t0, a0, 32
    vs1r.v v20, (t0)
    addi t0, a0, 48
    vs1r.v v0, (t0)
    addi t0, a0, 64
    vs1r.v v21, (t0)
    addi t0, a0, 80
    vs1r.v v22, (t0)
    ret

    .globl control_chain
control_chain:                   # out,a,b,iterations: feedback genuinely reads v0
    vl1re8.v v0, (a1)
    vl1re8.v v9, (a2)
    vsetivli zero, 8, e8, m1, tu, mu
.Lchain:
    dot 0, 9, 0
    dot 20, 9, 0
    addi a3, a3, -1
    bnez a3, .Lchain
    vs1r.v v0, (a0)
    ret
    .option pop
