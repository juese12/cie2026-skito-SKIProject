# 波形与信号图索引

当前核的计算与边界见[基础功能报告](../reports/当前vdot基础功能测试报告.md)和[扩展验收](../reports/固定八项e8e16实施与验收报告.md)；完整整核事件见[图文总结](../reports/e16整核仿真与关键信号图解.md)。

以下图片、SVG、精确采样和相应审计随工程提供。模块波形用于验证算术与流水，整核事件按 ROB 分配代次关联执行、取消和提交；二者分别标明来源。历史 e8 图只作为对应优化或方法的证据。

| 要证明的结论 | 图件 | 来源与主要限制 |
| --- | --- | --- |
| 标准 vadd 执行与写回 | [PNG](../../stage3/reports/figures/evidence/stage1-vadd-events.png) / [SVG](../../stage3/reports/figures/evidence/stage1-vadd-events.svg) | [第一阶段解析](../../stage1/docs/向量加法波形分析.md)；十次事件、最低元素，不是点积基线 |
| vdot 正数的计算正确性 | [PNG](../../stage3/reports/figures/functional/positive-asymmetric.png) / [SVG](../../stage3/reports/figures/functional/positive-asymmetric.svg) | 实际输入、八路乘积、sum=120、有效完整输出；[详细判读](../reports/vdot基础功能测试与验收报告v0.1.md) |
| vdot 负数的符号与输出打包 | [PNG](../../stage3/reports/figures/functional/negative.png) / [SVG](../../stage3/reports/figures/functional/negative.svg) | 八路负乘积、sum=−36、低 32 位补码、高 96 位零 |
| 最大值的 19 位求和 | [PNG](../../stage3/reports/figures/functional/maximum.png) / [SVG](../../stage3/reports/figures/functional/maximum.svg) | 实际八个 16384 相加为 131072，不能用 18 位有符号表示 |
| 最小值与非零相消 | [最小值](../../stage3/reports/figures/functional/minimum.png) / [相消](../../stage3/reports/figures/functional/cancellation.png) | 实际负乘积/正负乘积，结果分别为 −130048/0；其他三组见基础报告 |
| vdot 结果事件概览 | [PNG](../../stage3/reports/figures/evidence/vdot-result-events.png) / [SVG](../../stage3/reports/figures/evidence/vdot-result-events.svg) | 仅作事件索引；不能替代上述真实计算信号波形 |
| 独立目的 oldVd 误依赖去除 | [原 PNG](../../stage3/reports/figures/review-edition-20261101/p1/p1-oldvd.png) / [原 SVG](../../stage3/reports/figures/review-edition-20261101/p1/p1-oldvd.svg) | [P1 报告](../../stage3/reports/原始核至P1优化对比报告.md)；同一记录分派对齐，13→7 周期不是纯 FU latency |
| 目的 v0 的无用辅助源去除 | [原 PNG](../../stage3/reports/figures/review-edition-20261101/p1/p1-v0.png) / [原 SVG](../../stage3/reports/figures/review-edition-20261101/p1/p1-v0.svg) | 实际 vs1/vs2 不是 v0，不代表所有 v0 源可忽略 |
| 真实 vs1 依赖保留 | [原 PNG](../../stage3/reports/figures/review-edition-20261101/p1/p1-true.png) / [原 SVG](../../stage3/reports/figures/review-edition-20261101/p1/p1-true.svg) | 真源等待仍在；不是性能收益样例 |
| 普通乘法时 dot 分支保持 | [原 PNG](../../stage3/reports/figures/isolation/isolation-dot-hold.png) / [原 SVG](../../stage3/reports/figures/isolation/isolation-dot-hold.svg) | [隔离报告](../../stage3/reports/P1至隔离核优化对比报告.md)；真实 wrapper 模块，不是整核提交 |
| dot 时普通 MAC 分支保持 | [原 PNG](../../stage3/reports/figures/isolation/isolation-mac-hold.png) / [原 SVG](../../stage3/reports/figures/isolation/isolation-mac-hold.svg) | 当前输出无效时不比较数据；不能据此声称全单元停机 |
| 普通 MAC 与旧 dot 按级混发 | [原 PNG](../../stage3/reports/figures/isolation/isolation-overlap.png) / [原 SVG](../../stage3/reports/figures/isolation/isolation-overlap.svg) | 旧 dot S2 与当前 MAC S1 同时推进；不能用当前类型关掉旧结果 |
| 错误路径及非法后的年轻 dot 取消 | [PNG](../../stage3/reports/figures/evidence/control-cancellation.png) / [SVG](../../stage3/reports/figures/evidence/control-cancellation.svg) | [隔离整核控制](../reports/隔离版本整核构建与控制验证报告.md)；同一 ROB 分配跟踪及架构检查共同证明不提交 |
| mcycle 与串行 CSR 计时边界 | [PNG](../../stage3/reports/figures/evidence/timer-boundaries.png) / [SVG](../../stage3/reports/figures/evidence/timer-boundaries.svg) | [计时边界](../../stage3/docs/历史隔离核性能测量与复核手册v3.md)；8 批示例不是正式性能样本 |
| e2e 三档的重复分派气泡/阻塞 | [PNG](../../stage3/reports/figures/evidence/e2e-periods.png) / [SVG](../../stage3/reports/figures/evidence/e2e-periods.svg) | [三档分析](../../stage3/reports/端到端单调用与上下文受控验证报告.md)；不证明上游唯一触发条件 |
| Baseline/vdot 整核执行信号 | [PNG](../../stage3/reports/figures/comparison/baseline-vdot-wave.png) / [SVG](../../stage3/reports/figures/comparison/baseline-vdot-wave.svg) | [图文对照](../../stage3/reports/基线与vdot延迟加速图文分析.md)；原 8 批探针，真实 clock/valid 与 ROB 匹配的有效结果，不是提交轨迹 |
| 正式四进程周期与加速比 | [PNG](../../stage3/reports/figures/publication-20261107/formal-speedup.png) / [SVG](../../stage3/reports/figures/publication-20261107/formal-speedup.svg) | 历史 e8 隔离核四进程周期与加速比 |

基础计算图保留原 VCD 的信号变化，并标出低相位检查点；寄存器在其间的实际时钟上升沿更新，只有有效输出才参与结果判断。事件图则只绘制记录包含的时刻，不恢复连续电平。各图的时间单位、硬件版本和范围以图注为准；六张原优化图的灰色或空白区域也按原报告定义解释。

## 附件范围

信号图直接使用已保存的 VCD 跳变或整核事件，不补造未观测电平。图中的时标、采样相位、有效条件及版本以各报告图注为准。公开包包含图件、精确摘录和选定原始日志；完整历史 VCD 及仿真二进制不包含在源码包中。

当前核另有[独立目录模块波形](../reports/公开包独立目录复现报告.md)和[INT8 应用信号图](../../stage3/reports/INT8矩阵向量乘应用测试与性能报告.md)。
