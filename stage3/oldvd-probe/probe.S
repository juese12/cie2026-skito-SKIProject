    .text
    .balign 4
    .global oldvd_probe
    .type oldvd_probe, @function
# 参数：a0 为输出，a1 为场景，a2 为策略（位 0 为 ta，位 1 为 ma）。
# RTL 修改前后使用同一份程序镜像。
# 初始化和配置放在计时外，串行标记沿用 P0 协议。
oldvd_probe:
    vsetivli zero,16,e8,m1,tu,mu
    vmv.v.i v0,0
    vmv.v.i v6,0
    vmv.v.i v7,3
    vmv.v.i v8,1
    vmv.v.i v9,2
    vmv.v.i v10,0
    vmv.v.i v11,0
    li t0,8
    slli t1,a2,6
    vsetvl zero,t0,t1
    beqz a1,.Lwaw
    li t0,1
    beq a1,t0,.Lold_div
    li t0,2
    beq a1,t0,.Lunrelated_div
    li t0,3
    beq a1,t0,.Ltrue_alias
    li t0,4
    beq a1,t0,.Lv0_false
    j .Lv0_true

    .macro start_timer
    csrwi vstart,0
    csrr t1,mcycle
    csrwi vstart,0
    .endm
    .macro stop_timer
    csrwi vstart,0
    csrr t2,mcycle
    sub a3,t2,t1
    .endm
    .macro dot dst,src1,src2
    .word (0x0200200b | (\src2 << 20) | (\src1 << 15) | (\dst << 7))
    .endm
    .macro independent32
    .rept 32
    dot 10,8,9
    .endr
    .endm
.Lwaw:
    start_timer
    independent32
    j .Lend_v10
.Lold_div:
    start_timer
    vdiv.vv v10,v6,v7
    independent32
    j .Lend_v10
.Lunrelated_div:
    start_timer
    vdiv.vv v11,v6,v7
    independent32
    j .Lend_v10
.Ltrue_alias:
    start_timer
    vdiv.vv v10,v6,v7
    .rept 32
    dot 10,10,9
    .endr
.Lend_v10:
    stop_timer
    vs1r.v v10,(a0)
    mv a0,a3
    ret
.Lv0_false:
    start_timer
    vdiv.vv v0,v6,v7
    .rept 32
    dot 0,8,9
    .endr
    j .Lend_v0
.Lv0_true:
    start_timer
    vdiv.vv v0,v6,v7
    .rept 32
    dot 0,0,9
    .endr
.Lend_v0:
    stop_timer
    vs1r.v v0,(a0)
    mv a0,a3
    ret
    .size oldvd_probe,.-oldvd_probe
