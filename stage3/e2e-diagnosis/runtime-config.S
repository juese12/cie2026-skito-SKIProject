    .text
    .balign 8
    .global bench_runtime_order
    .type bench_runtime_order, @object
bench_runtime_order:
    # 仅用于诊断：位 0 选择初始顺序，位 1 选择统一调用者；各组使用同一二进制。
    .byte 0
    .size bench_runtime_order, 1
