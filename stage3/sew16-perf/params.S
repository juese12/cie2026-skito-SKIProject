    # 前缀参数字节由全部配置、处理器版本和顺序共用，不修改指令。
    .text
    .balign 8
    .global perf_params
    .type perf_params, @object
perf_params:
    .byte 4, 1, 0, 1           # 版本号、测量配置（探针/烟雾/正式）、起始顺序、e16 开关
    .word 0x56444f54          # 实际输入随机种子
    .size perf_params, 8
