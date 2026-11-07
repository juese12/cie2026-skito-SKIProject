    # Prefix parameter bytes, shared by every profile/core/order. No code edits.
    .text
    .balign 8
    .global perf_params
    .type perf_params, @object
perf_params:
    .byte 4, 1, 0, 1           # schema, profile(probe/smoke/full), first, e16
    .word 0x56444f54          # actual input RNG seed
    .size perf_params, 8
