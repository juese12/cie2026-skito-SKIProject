    .text
    .option push
    .option norvc
    .macro dot vd, vs2, vs1, vm=1
    .4byte ((\vm << 25) | (\vs2 << 20) | (\vs1 << 15) | (2 << 12) | (\vd << 7) | 0x0b)
    .endm

    .globl vdot_compute
    .type vdot_compute, @function
# a0=32-byte output, a1/a2=16-byte inputs, a3=mode, a4=vtype (ta/ma).
# Clobbers v0/v8/v9/v10/v11/v31 and VL/vtype; called only from scalar C.
vdot_compute:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v10, (a0)           # Poison the old destination.
    li t0, 8
    vsetvl zero, t0, a4
    beqz a3, .Lnormal
    li t0, 1
    beq a3, t0, .Lalias1
    li t0, 2
    beq a3, t0, .Lalias2
    li t0, 3
    beq a3, t0, .Lsamesrc
    li t0, 4
    beq a3, t0, .Lallalias
    li t0, 5
    beq a3, t0, .Lsrc0a
    li t0, 6
    beq a3, t0, .Lsrc0b
    li t0, 7
    beq a3, t0, .Ldest0
    li t0, 8
    beq a3, t0, .Ldest31
    li t0, 9
    beq a3, t0, .Lchain
    li t0, 10
    beq a3, t0, .Lmask
.Lnormal:
    dot 10, 9, 8
    vs1r.v v10, (a0)
    ret
.Lalias1:
    dot 8, 9, 8
    vs1r.v v8, (a0)
    ret
.Lalias2:
    dot 9, 9, 8
    vs1r.v v9, (a0)
    ret
.Lsamesrc:
    dot 10, 8, 8
    vs1r.v v10, (a0)
    ret
.Lallalias:
    dot 8, 8, 8
    vs1r.v v8, (a0)
    ret
.Lsrc0a:
    vl1re8.v v0, (a1)
    dot 10, 9, 0
    vs1r.v v10, (a0)
    ret
.Lsrc0b:
    vl1re8.v v0, (a2)
    dot 10, 0, 8
    vs1r.v v10, (a0)
    ret
.Ldest0:
    dot 0, 9, 8
    vs1r.v v0, (a0)
    ret
.Ldest31:
    dot 31, 9, 8
    vs1r.v v31, (a0)
    ret
.Lchain:
    dot 10, 9, 8
    dot 11, 9, 10
    vs1r.v v11, (a0)
    ret
.Lmask:
    vsetivli zero, 16, e8, m1, ta, ma
    vmv.v.i v11, 0
    vsetivli zero, 8, e8, m1, tu, mu
    dot 0, 9, 8
    vs1r.v v0, (a0)
    vadd.vv v11, v8, v9, v0.t
    addi t0, a0, 16
    vs1r.v v11, (t0)
    # Restore the caller-selected policy and VL=8.
    li t0, 8
    vsetvl zero, t0, a4
    ret
    .size vdot_compute, .-vdot_compute

    .globl vdot_ordinary
    .type vdot_ordinary, @function
# Same source/output layout, a3=0:add,1:mul,2:macc,3:smul.
vdot_ordinary:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vsetivli zero, 16, e8, m1, ta, ma
    vmv.v.i v10, 0
    vsetivli zero, 8, e8, m1, tu, mu
    beqz a3, .Lregadd
    li t0, 1
    beq a3, t0, .Lregmul
    li t0, 2
    beq a3, t0, .Lregmacc
    vsmul.vv v10, v8, v9
    j .Lregstore
.Lregadd:
    vadd.vv v10, v8, v9
    j .Lregstore
.Lregmul:
    vmul.vv v10, v8, v9
    j .Lregstore
.Lregmacc:
    vmacc.vv v10, v8, v9
.Lregstore:
    vs1r.v v10, (a0)
    ret
    .size vdot_ordinary, .-vdot_ordinary

    .globl vdot_invalid
    .type vdot_invalid, @function
# a0=old destination/result (16 bytes), a1/a2=16-byte source, a3=case.
# Returns the PC of the expected fault, with VS enabled and vstart reset for
# subsequent test code. The handler records pre-recovery exception state.
vdot_invalid:
    vl1re8.v v8, (a1)
    vl1re8.v v9, (a2)
    vl1re8.v v10, (a0)
    vsetivli zero, 8, e8, m1, tu, mu
    la t0, vdot_trap_armed
    li t1, 1
    sd t1, 0(t0)
    beqz a3, .Lbadvl0
    li t0, 1
    beq a3, t0, .Lbadvl7
    li t0, 2
    beq a3, t0, .Lbadvl9
    li t0, 3
    beq a3, t0, .Lbadvl16
    li t0, 4
    beq a3, t0, .Lbadsew
    li t0, 5
    beq a3, t0, .Lbadlmul
    li t0, 6
    beq a3, t0, .Lbadvm
    li t0, 7
    beq a3, t0, .Lbadvstart
    li t0, 8
    beq a3, t0, .Lbadvill
    # case 9: turn off vector context after preparing source/destination.
    li t0, 0x600
    csrc mstatus, t0
    j .Lfault
.Lbadvl0:
    vsetivli zero, 0, e8, m1, tu, mu
    j .Lfault
.Lbadvl7:
    vsetivli zero, 7, e8, m1, tu, mu
    j .Lfault
.Lbadvl9:
    vsetivli zero, 9, e8, m1, tu, mu
    j .Lfault
.Lbadvl16:
    vsetivli zero, 16, e8, m1, tu, mu
    j .Lfault
.Lbadsew:
    vsetivli zero, 8, e16, m1, tu, mu
    j .Lfault
.Lbadlmul:
    vsetivli zero, 8, e8, m2, tu, mu
    j .Lfault
.Lbadvstart:
    csrwi vstart, 1
    j .Lfault
.Lbadvill:
    li t0, 8
    li t1, -1
    vsetvl zero, t0, t1
    j .Lfault
.Lbadvm:
.Lvmfault:
    dot 10, 9, 8, 0
    la t2, .Lvmfault
    j .Lrecover
.Lfault:
    dot 10, 9, 8
    la t2, .Lfault
.Lrecover:
    # Record vstart before resetting it. VS must be enabled for CSR access.
    li t0, 0x600
    csrs mstatus, t0
    csrr t0, vstart
    la t1, vdot_after_vstart
    sd t0, 0(t1)
    csrwi vstart, 0
    vsetivli zero, 8, e8, m1, tu, mu
    vs1r.v v10, (a0)
    mv a0, t2
    ret
    .size vdot_invalid, .-vdot_invalid
    .option pop
