    .text
    .option push
    .option norvc
    .macro wdot vd, vs2, vs1, vm=1
    .4byte ((\vm << 25) | (\vs2 << 20) | (\vs1 << 15) | (2 << 12) | (\vd << 7) | 0x0b)
    .endm
    .globl wide_mixed
wide_mixed:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vsetivli zero, 7, e16, m1, ta, ma
    vsetivli zero, 8, e8, m1, tu, mu
    wdot 10, 9, 8
    vsetivli zero, 0, e8, m1, ta, ma
    vsetivli zero, 8, e16, m1, tu, mu
    vmv.v.i v14, 0
    wdot 11, 9, 8
    vmul.vv v12, v8, v9
    wdot 0, 9, 8
    wdot 13, 9, 0
    vadd.vi v15, v9, 1
    .rept 32
    wdot 13, 15, 13
    .endr
    vmul.vv v14, v8, v9, v0.t
    # 掩码 36 的第 2、5 位为一，在覆盖 v0 之前先检查掩码结果。
    vs1r.v v10, (a0)
    addi t0, a0, 16
    vs1r.v v11, (t0)
    addi t0, a0, 32
    vs1r.v v12, (t0)
    addi t0, a0, 48
    vs1r.v v0, (t0)
    addi t0, a0, 64
    vs1r.v v13, (t0)
    addi t0, a0, 80
    vs1r.v v14, (t0)
    ret

    .globl wide_invalid
wide_invalid:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v10, (a0)
    vsetivli zero, 8, e16, m1, tu, mu
    la t0, vdot_trap_armed
    li t1, 1
    sd t1, 0(t0)
    beqz a3, .Lwidezero
    li t0, 1
    beq a3, t0, .Lwideseven
    li t0, 2
    beq a3, t0, .Lwidemask
    csrwi vstart, 1
    j .Lwidefault
.Lwidezero:
    vsetivli zero, 0, e16, m1, tu, mu
    j .Lwidefault
.Lwideseven:
    vsetivli zero, 7, e16, m1, tu, mu
.Lwidefault:
    wdot 10, 9, 8
    la t2, .Lwidefault
    j .Lwiderecover
.Lwidemask:
    wdot 10, 9, 8, 0
    la t2, .Lwidemask
.Lwiderecover:
    csrwi vstart, 0
    vsetivli zero, 8, e16, m1, tu, mu
    vs1r.v v10, (a0)
    mv a0, t2
    ret
    .option pop
