    # 只读启动参数不作为指令执行；前缀覆盖只修改该字节，时点位于
    # 处理器 RAM 装载之后、首条程序指令执行之前，
    # 并且早于参考模型和黄金内存初始化。
    .text
    .balign 8
    .global bench_runtime_order
    .type bench_runtime_order, @object
bench_runtime_order:
    .byte 0
    .size bench_runtime_order, 1
