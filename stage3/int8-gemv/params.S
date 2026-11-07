    .text
    .balign 8
    .global gemv_params
    .type gemv_params,@object
gemv_params:
    .byte 1, 1, 0, 0  # schema, profile (probe/smoke/full), first implementation, reserved
    .word 0x56444f54
    .size gemv_params,8
