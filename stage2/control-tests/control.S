#include "../test-contract.h"
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
control_branch:                   # 参数为输出、输入 a/b、预期商；零用于训练不跳转路径。
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v20, (a0)
    addi t0, a0, 16
    vl1re8.v v0, (t0)
    vsetivli zero, 8, e8, m1, tu, mu
    slow_value                   # 分支依赖六级真实除法链的结果。
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
control_exception:               # 参数为输出、输入 a/b；三个目的均预先填入检查值。
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
    slow_value                   # 较老除法链延后异常提交，为年轻点积创造执行窗口。
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
control_config:                  # 参数为输出、输入 a/b、最终 vtype 策略；配置之间不插入 CSR 读取。
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
control_config_fault:            # a4=0 检查 VL=7，1 检查不支持的 SEW，2 检查 e64（当前约定）。
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
#if VDOT_TEST_E16
    li t1, 2
    beq a4, t1, .Lfault_sew64
#endif
    ori a3, a3, VDOT_BAD_VTYPE
#if VDOT_TEST_E16
    j .Lfault_final
.Lfault_sew64:
    ori a3, a3, 24
#endif
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
control_mixed:                   # 参数为 96 字节输出、输入 a/b、迭代次数。
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
control_chain:                   # 参数为输出、输入 a/b、迭代次数；反馈链真实读取 v0。
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
