# vdot v0.1 实施进度与操作记录

计划按推荐方案和操作手册实施 v0.1。

P0交付更新：同镜像运行时选序、动态CSR/ROB计时边界证据及e2e数据调查已完成，见 [P0验收与操作](../../stage3/reports/P0完善与验收记录.md) 和 [正式实测v3](../../stage3/reports/原始核正式性能实测报告v3.md)。两个烟雾、四个正式进程均取得功能/数据通过；比值中位数batch4=3.528937、e2e=2.127377、chain=4.129215，不是RTL提升或应用/PPA收益。独立实际边界探针六组时间戳差、19标记/179阻塞相位审计通过，28项工具回归通过；本轮未改RTL/NEMU，也未自动提交/推送。下文按时间保留v0.1/v2历史操作，不以旧“待验证”描述覆盖已取得的后续证据。

v0.1 功能验证与旧数据保留；裸 mcycle 可乱序，旧比值不是严格完整操作延迟。新版微基准周期比 batch4=3.528318、e2e=2.141012、chain=4.128928；最大单组 CV=4.942%，通过项目门槛不等于无波动。本轮没有修改 RTL/NEMU，不覆盖下文历史操作记录，也不据协议变化宣称硬件提升。

## 固定的项目合同

custom-0；低 8 个 signed int8 点积；结果为低 32 位补码、高 96 位零；e8/m1/VL=8/vm=1/vstart=0；其他配置非法；允许源/目的重叠和 v0；保留 vxrm/vxsat/vl/vtype。复用 vimac 的两周期接口，单 uop/单写回。

该合同为本项目 v0.1 的实现范围，赛题图中未定义的细节仍不表示官方确认。

## 完成状态

| 步骤 | 当前状态 | 实际证据 |
| --- | --- | --- |
| G0 基线与版本保护 | 已完成 | `g0-backup`：旧 emu、参考库、NEMU 配置已备份；用户 difftest 修改保留 |
| G1 编码与译码 | 单测通过 | `rtl-all-unit-retest`：编码冲突、译码、单 uop 数与配置合法性 |
| G2 算术单测 | 已通过 | `rtl-all-unit-retest`：定向与 1,000 随机输入、流水使能和高位清零 |
| G3 wrapper 集成 | 已通过 | `rtl-all-unit-retest`：真实 VIMacU，混合 vmul、标签、非法配置和取消；三套测试共 4 项全部通过 |
| G4 整核与回归 | 已通过 | 新核普通向量/饱和回归、32 定向、别名/v0/v31/依赖链/v0-mask、1,000 随机和异常恢复全部通过；真实整核波形 29 次执行与提交关联通过 |
| G5 NEMU 与差分 | 已通过 | 新核/新 ref：1,052 合法 + 10 非法，精确 mtval/cause/PC/目的值检查，GOOD TRAP；API 1,035 + 10 及 tval 隔离通过 |
| G6 等价基线与性能 | 已通过本轮测量 | 新核双方各 1,032 等价性检查；三类各五次周期、GOOD TRAP、退出 0；中位数比值 batch4 2.41× / e2e 1.81× / chain 4.59×，非孤立延迟或 PPA |
| v0.1 补丁与交付 | 本轮交付完成 | 两份补丁干净基线正向/当前树反向检查通过；功能、波形、性能报告和操作日志已整理；未自动提交/推送 |

## 实际修改与原理

- XiangShan：`Instructions.scala` 增加 custom-0 家族；`RiscvInst.scala` 将其纳入向量算术分类；`package.scala` 分配独立 opType / splitType。
- `VecDecoder.scala` 路由到 vimac；`UopInfoGen.scala` 和 `DecodeUnitComp.scala` 固定单 uop 和寄存器索引，避免按普通向量元素展开。
- `VecExceptionGen.scala` 检查 SEW/LMUL/vm；复用公共 vill/vstart/VS 检查。VL 不在该接口中，因此在执行端判断。
- `VDot8.scala`：8 个有符号 8×8 乘法、19 位加法树、两级寄存器；19 位结果先符号扩展到 32 位，再将高 96 位清零。
- `VIMacU.scala`：复用两周期控制通路；vdot 最终选择完整结果，绕过普通 MGU 的逐元素合并；其他 op 保留原数据路径；vdot 不产生 vxsat。
- NEMU：补充指令声明、custom-0 分发和执行 helper；全部源操作数读完再写目的寄存器，支持别名；先检查合法性再修改状态。
- 项目：增加裸机 C/汇编、独立 trap handler、参考库 API 测试、日志执行器、构建/运行/补丁导出脚本。

## 可复现入口

在 xs-env 根目录执行（全量构建耗时较长）：

```bash
source env.sh
make -C NEMU vdot-v0.1_defconfig
make -C NEMU -j2
bash cie2026-skito-SKIProject/scripts/build-vdot.sh
bash cie2026-skito-SKIProject/scripts/run-vdot.sh
bash cie2026-skito-SKIProject/scripts/export-vdot-patches.sh
```

完整核构建配置：`make -C XiangShan emu CONFIG=DefaultConfig NUM_CORES=1 JVM_XMX=10G JVM_XSS=16m WITH_DRAMSIM3=1 WITH_CONSTANTIN=0 EMU_THREADS=2 EMU_TRACE=1 -j2`。

该初次全量构建在 8.7 GiB RAM / 16 GiB swap 的机器上几乎耗尽资源，主动终止本次 firtool（退出 143），没有删除源码/用户数据。随后重试功能验证配置：同样的 DefaultConfig 与差分/断言，`JVM_XMX=6G DISABLE_PERF=1 DISABLE_ALWAYSDB=1`；该尝试仅关闭性能统计与 AlwaysDB 电路，不作为正式性能计数基线。

更新：上述 6G 重试在 `PrintModuleName` 转换阶段触发 Java heap space，退出 2。随后复用首次完整构建已成功生成的 `SimTop.fir`，独立调用同版本 firtool 1.62.1 和相同参数（`rtl-firtool-standalone`），使 Java 与 firtool 不再同时保留大量内存。此路径使用**原始完整 DefaultConfig，性能统计未关闭**；待其成功后，`finish-vdot-rtl.sh` 执行 Makefile 的 SRAM 模型生成、断言绑定及 C++ 编译步骤。

记录：独立 firtool 成功退出 0，完整 Verilog 已生成；开始 SRAM / 断言后处理与 Verilator/C++ 构建。当前 vdot 的整核差分仍未执行。

记录：双线程 Verilator 模型转换持续计算约 35 分钟，尚未生成新 C++。旧 emu 的构建记录未启用 `--threads`，因此主动终止本次转换（signal 15 / 子进程 143 / make 2），以 `EMU_THREADS=0` 重试；完整 RTL、性能统计、断言、trace 和差分均不变。长耗时是否由多线程划分导致尚未证实，不能把主动终止写成 RTL 编译错误。`finish-vdot-rtl.sh` 现默认单线程，可以通过 `VDOT_EMU_THREADS` 覆盖。

## wrapper 波形证据

### 最终队列结论

对应原始实验附件：新核双方等价性通过，每个实现 1,032 检查；batch4/e2e/chain 各五次原始周期和全部完整输出检查通过，benchmark PASS、GOOD TRAP、分析器 PASS、退出 0。验证队列 对应原始实验附件 最终 `[queue PASS]`、`status=0`，已无残留验证进程。RVV/vdot 中位数分别为 1149/477、1688/931、3772/822，原始比值 2.408805× / 1.813104× / 4.588808×；空循环中位数 187 不相减。完整口径、波动及限制见 [性能报告](../../stage3/reports/vdot原始版本等价基线与性能实测.md)。本轮功能交付摘要见 [验收摘要](vdot基础功能测试与验收报告v0.1.md)。

源码、脚本语法及整合补丁检查均通过。旧 FIR 复用与干净快照全流程构建属于不同验收范围；完整公开包复现单独列明。

### 模块级补充证据

`stage2/waveform/vdot-wrapper.vcd`（284,515 字节，忽略提交）来自真实 VIMacU 的单测夹具。

`wrapper-wave-audit` 独立解析波形并复核 24 次输出，包括 7 条非法运行配置的异常标志；混发普通 vmul，校验完整 128 位结果、v0/vec 写使能、标签、vxsat，以及取消的 tag=42 没有输出。**非法输出中的数据只是执行单元数据线，不代表架构写回；夹具验证异常标志，整核还需验证异常提交与目的寄存器不变。该波形不代表完整 CPU 执行。**

复查命令：`python3 stage2/tests/check-wrapper-wave.py stage2/waveform/vdot-wrapper.vcd`（在作品仓库中运行）。

另保存 `stage2/waveform/vdot-arithmetic.vcd`，来自最终统一重跑的 `VDot8Test`，包含定向/随机、流水使能、气泡和高位毒化测试。同样是模块级证据，不是整核证据。
