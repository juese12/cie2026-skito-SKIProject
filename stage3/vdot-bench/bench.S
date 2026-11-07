    .text
    .option push
    .option norvc
    # 当前香山将 CSR 写视为 waitForward 与 blockBackward 操作；
    # 与只读 mcycle 不同，Rename 不会放宽 csrwi vstart，且执行时需启用 VS。
    # 起始前排空在计时外，后两个排空位于计时区间内部。
    # 两种实现承担相同标记成本，不扣除空循环时间。
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
    # 乘积寄存器组 16:17、20:21、24:25、28:29 不与源、
    # 零种子 v12 或目的 14/18/22/26 重叠；每次点积将精确 i16
    # 乘积归约到 i32，tu 保留预先清零的高 96 位。
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
# 参数：a0 为 16 字节输出，a1/a2 为 16 字节源，a3 选基线，a4 选策略。
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
    # 同时在实际点积指令处检查结果不依赖 ta/ma。
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
# a3 选择基线；a4=0 预加载批处理、1 加载/初始化/存储、2 反馈链。
# a5 为正批次数；两种实现均执行 a5 批，每批四次点积。
# 两种实现使用相同的 CSR 时间戳与标量循环开销；
# 基线额外配置切换属于其算法本身所需的成本。
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
    # 零输入虽然是稳定不动点，但显式反馈源
    # 仍在每条指令间建立真实的架构向量依赖。
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
    # 两条路径执行相同的无条件跳转。
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
