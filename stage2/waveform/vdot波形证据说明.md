# vdot 波形证据

当前保存方式更新：在先保存实际关键信号及复现实验入口后，已按用户授权精简旧隔离核的正式控制和 e2e 四份大波形，释放约 10.71 GiB；完整结果见[台账](../../manifest/存储清理台账.md)。[控制信号图](../../stage3/reports/figures/isolation-retained/control-signals.png)、[e2e 三档采样图](../../stage3/reports/figures/publication-20261107/e2e-signals.png)、实际信号摘录、原始审计、完整周期 JSON 和日志保留。下文此前“隔离原始大波形未删除”是历史状态；旧核、原镜像、参考库、模块前后波形和当前 e8/e16 产物继续保留。默认运行 `python3 scripts/replay-isolation-evidence.py` 只复核；显式重采命令见[控制报告](../reports/隔离版本整核构建与控制验证报告.md)和[快慢窗口报告](../../stage3/reports/原镜像端到端快慢窗口事件诊断.md)。

执行更新：在先确认优化对比图及文档后，已按用户授权删除 v0.1/P1 五份旧核原始 VCD，释放约 19.54 GiB。下方此前盘点文字是历史状态，完整执行结果见[清理台账](../../manifest/存储清理台账.md)。全部六张前后对比图、基础算术图、信号摘录和审计保留；隔离核及 e8/e16 扩展的文件未删除。原 VCD 解析命令只有原文件可用时才能执行，不带 `--execute` 的 对应原始实验附件 可在清理后只读核查保留证据。

## 文档关键图阅读入口

P1 和隔离优化的前后关键波形分别在 [P1 报告](../../stage3/reports/原始核至P1优化对比报告.md)及[隔离报告](../../stage3/reports/P1至隔离核优化对比报告.md)中说明。三张 P1 图、三张隔离图及对应信号摘录保留，旧原始 VCD 的实际清理状态见上方说明及台账。

### 当前 e8/e16 核的图件

当前核的[e16 整核图文总结](../reports/e16整核仿真与关键信号图解.md)包含两张真实模块 VCD 采样图和两张整核 JSONL 事件图。模块图证明算术和使能行为，事件图说明执行后取消及同代次未提交，不把两者合称全量整核连续波形。第一阶段 Hello 终端截图另见[环境验收](../../stage1/docs/环境与RVV基线验收.md)。

评阅时可直接查看下列图片，无需下载大波形或重新仿真。已有 6 张前后对照图直接复用；5 张事件图来自已有审计记录；另有 8 张基础计算图直接读取原整核 VCD 的信号变化，覆盖从输入到八路乘积、求和及有效输出的通路。没有重新采集或生成 VCD/FST。

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
| mcycle 与串行 CSR 计时边界 | [PNG](../../stage3/reports/figures/evidence/timer-boundaries.png) / [SVG](../../stage3/reports/figures/evidence/timer-boundaries.svg) | [P0 探针](../../stage3/reports/P0完善与验收记录.md)；8 批示例不是正式性能样本 |
| e2e 三档的重复分派气泡/阻塞 | [PNG](../../stage3/reports/figures/evidence/e2e-periods.png) / [SVG](../../stage3/reports/figures/evidence/e2e-periods.svg) | [三档分析](../../stage3/reports/端到端单调用与上下文受控验证报告.md)；不证明上游唯一触发条件 |
| Baseline/vdot 整核执行信号 | [PNG](../../stage3/reports/figures/comparison/baseline-vdot-wave.png) / [SVG](../../stage3/reports/figures/comparison/baseline-vdot-wave.svg) | [图文对照](../../stage3/reports/基线与vdot延迟加速图文分析.md)；原 8 批探针，真实 clock/valid 与 ROB 匹配的有效结果，不是提交轨迹 |
| 正式四进程周期与加速比 | [PNG](../../stage3/reports/figures/publication-20261107/formal-speedup.png) / [SVG](../../stage3/reports/figures/publication-20261107/formal-speedup.svg) | 历史 e8 隔离核四进程周期与加速比 |

基础计算图保留原 VCD 的信号变化，并标出低相位检查点；寄存器在其间的实际时钟上升沿更新，只有有效输出才参与结果判断。事件图则只绘制记录包含的时刻，不恢复连续电平。各图的时间单位、硬件版本和范围以图注为准；六张原优化图的灰色或空白区域也按原报告定义解释。

## 已有波形及解析说明

新增 `isolation/before.vcd` 与 `isolation/after.vcd`，同一固定随机 seed 的真实 wrapper 模块仿真。301 个有效输出前后匹配、37 次混合级重叠、4,140 项禁用寄存器保持通过，所选活动计数见[隔离优化记录](../reports/操作数隔离与寄存器更新门控报告.md)。不是整核波形或功耗证据；旧波形不覆盖新隔离 RTL。复核入口为 `stage2/tests/check-isolation-wave.py`，它要求两个波形及一个尚不存在的 `--json-out` 路径。

当前保存 `vdot-wrapper.vcd`（真实 VIMacU + 固定两周期控制夹具）和 `vdot-arithmetic.vcd`（VDot8 算术单元）。实际 CPU 的 原版本波形文件 已按范围精简，保留真实采样、图及执行/提交审计。前两个不是完整 CPU 波形。

源单测：`xiangshan.backend.fu.vector.VDotIntegrationTest`。大小 284,515 字节。

在作品仓库中复查：

```bash
python3 stage2/tests/check-wrapper-wave.py stage2/waveform/vdot-wrapper.vcd
```

实测通过：24 个输出，7 个非法配置异常标志，取消的 tag=42 没有输出；完整结果、高位、标签、v0/vec 写使能与 vxsat 均匹配。波形时标来自测试夹具，并非实际芯片频率。VCD 由 `.gitignore` 排除，单测可以重新生成它。

非法运算在异常标志置位时仍可能在数据线上出现点积值；能否阻止架构写回由整核的异常提交/恢复机制决定，不能根据数据线值判定目的寄存器已修改。

完整 CPU 波形已采集并检查 29 次完整执行输出、与 29 条实际提交 trace 对应，见 [整核波形报告](../reports/vdot原始核执行与提交波形.md)。该窗口覆盖定向点积，不覆盖全部非法/v0/冲刷场景；其余场景的证据类型在报告中分别披露。

`vdot-arithmetic.vcd` 来自统一重跑的 `VDot8Test`，含 1,000 随机输入与定向边界、气泡/使能及高位毒化检查。

## 当前核边界信号图

[当前功能与边界验收报告](../reports/固定八项e8e16实施与验收报告.md)集中展示 e8 最大正和、零、最小负和乘积与禁用保持，以及 e16 最大正和整核提交、负数宽位打包和 VL=0 非法配置。图中区分实际完整输出、部分级证据和稀疏整核事件。

五张新提取图均复用已有 VCD/整核记录，PNG、SVG 与[精确采样](../reports/figures/current-boundary/boundary-evidence-excerpts.json)一并保留；e16 负结果图复用原图件。

## 中文图注与复核

当前文档使用的 39 组说明图，其图题、图例、坐标说明和解读注释均已中文化，PNG 与 SVG 同步更新。RTL 信号标识符、指令名、公式及原始终端日志保留原文。图件沿用原路径，原有数值、事件位置、波形轨迹和实验范围保持；12 组未被文档引用的重复或早期图件已清理，相关信号摘录和原始审计继续保留。

以下命令只检查图件，或从已保存的 SVG 信息导出中文版本，不启动仿真、不生成 VCD。导出时需本机中文字体，可通过 `--font` 或环境变量 `VDOT_CJK_FONT` 指定字体文件；字体文件不随作品分发。

```bash
python3 stage3/tests/chinese-figure-edition.py --check
python3 stage3/tests/chinese-figure-edition.py --export /tmp/vdot-chinese-figures-NEW
```
