# 小型 INT8 矩阵向量乘应用说明

本应用将固定八项 vdot 用于完整的矩阵向量乘，验证加载、分块、累加、尾部和存储组成的实际软件路径。它是比赛第三阶段之外的应用补充；官方要求的指令等价基线及延迟分析仍见原 v4 报告。本轮只增加软件、测试和图文证据，复用当前 e8/e16 核与 NEMU 参考库。

## 1. 计算和接口

```text
y[r] = sum(W[r*K+c] * x[c], c=0..K-1)
```

W 为按行连续存放的有符号 INT8 矩阵，x 为有符号 INT8 向量，y 为 INT32。约定 `0<=M<=32`、`0<=K<=256`，输入输出和打包缓冲区互不重叠；y 按四字节对齐，输入按字节寻址。应用不包括偏置、非零量化零点、缩放、激活或输出重新量化。任一部分和的绝对值不超过 `256*16384=4194304`，INT32 累加不会溢出。

M=0 不写输出，不在计算入口读取输入；K=0 时输出 M 个零，不执行 vdot。向量入口要求 VS 已开启、vstart=0，使用普通调用约定，向量寄存器及 vl/vtype 可被覆盖，vcsr 保持。返回时向量内核统一设为 e8/m1、VL=8。标量路径不改变向量配置。

## 2. 四种实现

| 入口 | 做法 | 用途 |
| --- | --- | --- |
| `gemv_scalar` | INT8 符号扩展，INT32 乘加，关闭编译器自动向量化 | 标量对照 |
| `gemv_rvv` | 最多 16 元素的 e8/m1 加载、`vwmul.vv` 得到 e16/m2、`vwredsum.vs` 归约至 INT32 | 标准向量基线 |
| `gemv_dot1` | 每八项 vdot 后切 e32，用 `vmv.x.s` 提取完整部分和，标量累加 | 清晰的单行实现 |
| `gemv_dot4` | 同一 x 块供四行使用，四条 vdot 后切 e32，四个向量寄存器分别累加 | 应用优化实现 |

标准 RVV 同样采用四行共享 x，归约使用上一块 INT32 和作为 seed，最后不足 16 项时使用实际 VL。这样既保留自然向量长度，也避免人为给基线添加逐块标量搬移。

vdot 要求 SEW=8、LMUL=1、VL=8、vm=1、vstart=0。它只读取源低八字节，目的低 32 位为部分和，高 96 位清零，不累加 oldVd。`vmv.x.s` 按当前 SEW 提取，因此单行实现必须在 e32 下读取结果。四行版本把点积结果和累计值放在不同向量寄存器中，只在 e32、VL=1 下相加和存储，不能用 e8 的逐字节加法代替 INT32 累加。

## 3. 尾部和数据准备

vdot 软件路径使用 `Kp=(K+7)&~7`。每一行的末尾及 x 末尾补零，行跨度变为 Kp。数据加载使用 `vle8.v`、VL=8，每次只读取八字节，不使用会额外读取高八字节的整寄存器加载。

四行版本完成完整四行组后，用单行向量累加路径处理剩余行。打包缓冲区采用静态分配，端到端包装函数不支持并发重入；当前裸机测试为串行调用。

## 4. 测量口径

| 模式 | 计时内 | 计时外 |
| --- | --- | --- |
| 已打包计算 | 四种实现读取相同补零数组；配置、加载、计算、累加、输出存储、调用返回 | 输入生成、打包、独立结果校验 |
| 单次端到端 | 标量/RVV 读取原矩阵；vdot 每次重新打包 W 和 x 后计算 | 输入生成、独立结果校验 |

端到端模式不强迫标准 RVV 打包，也不把 vdot 的打包成本隐藏在计时外。本轮没有单独测量权重复用后的摊销收益。缓存来自同一裸机仿真环境的重复调用，不代表冷启动 DRAM 或完整推理框架。

使用 mcycle 和 vstart 写标记，计时外完成函数选择和参数设置，计时内包含真实调用。新镜像的短探针检查九次调用：先执行一个 4×17 的四行 vdot，再覆盖四种实现、两种模式。通过实际 ROB 分配/提交事件检查计时顺序；这是特定实现的边界验证，不是通用 ISA 屏障或内存持久化证明。

正式测量为 16×64、17×65，各模式预热 2 次、正式采样 6 次，四独立初始化进程。每轮按 `(first+rep+slot)%4` 轮转实现，四个进程 first 分别为 0/1/2/3。全部预热和正式值保留；先求每进程中位数及比值，再汇总四进程，不将同一进程样本当作独立实验。不删除样本，不扣除空循环。

## 5. 验证与运行

独立 `oracle.c` 用 INT64 累加并检查 INT32 范围；它不调用任何待测实现。功能检查覆盖正负极值、零、抵消、超过 16 位的累加、M/K 尾部、空规模、四个实际数据种子及输入输出保护区。每次调用逐行比对输出。NEMU 快速入口还检查输入未被修改，整核入口始终开启差分。

以下命令从作品目录执行，输出目录必须为不存在的新路径：

```bash
bash scripts/build-int8-gemv.sh
python3 stage3/int8-gemv/check-nemu.py
python3 stage3/int8-gemv/test-tools.py
bash scripts/run-int8-gemv.sh --suite probe --out stage3/logs/NEW-gemv-probe
python3 stage3/int8-gemv/audit-timer.py stage3/logs/NEW-gemv-probe/probe.events.jsonl --out stage3/logs/NEW-gemv-probe/timer-audit.json
bash scripts/run-int8-gemv.sh --suite smoke --out stage3/logs/NEW-gemv-smoke
python3 stage3/int8-gemv/build-wave-observer.py
python3 stage3/int8-gemv/wave.py --probe stage3/logs/NEW-gemv-probe --out stage3/logs/NEW-gemv-wave
python3 stage3/int8-gemv/render-evidence.py --wave stage3/logs/NEW-gemv-wave --probe stage3/logs/NEW-gemv-probe --out stage3/reports/figures/NEW-gemv
bash scripts/run-int8-gemv.sh --suite full --out stage3/logs/NEW-gemv-full
python3 stage3/int8-gemv/analyze.py stage3/logs/NEW-gemv-full --out stage3/logs/NEW-gemv.analysis.json
```

推荐核为 `../XiangShan/build/sew16-fixed8/emu`，参考库为 `../NEMU/build/sew16/riscv64-nemu-interpreter-so`。短探针使用同设计的只读事件观察器 `sew16-perf-events/emu`，普通测量使用推荐核。构建出的独立镜像为 `build/cie2026-int8-gemv-riscv64-xs.bin`，不覆盖 v4 镜像。

当前推荐整核编译时关闭了完整 VCD。波形命令使用 `int8-gemv-wave/emu`：`build-wave-observer.py` 仅重新编译和链接只读 C++ 观察包装，复用 `sew16-events/emu-compile/` 的原模型归档，不重新生成 RTL，不改原 emu。观察器每周期高/低相位求值后分别记录实际信号，时间戳为 `2*cycle+phase`，图中按周期解释，不推导物理频率。只有第一条四行 GEMV 调用的窄窗口会写 VCD，并保存压缩副本；同时记录 ROB 事件，审核观察开关前后九次调用的周期、执行数据和提交记录一致。普通应用运行不依赖该观察器；重建波形观察器需保留上述编译模型和事件包装源码。目标目录已存在时构建脚本拒绝覆盖，直接复用已验收观察器。

## 6. 源码组成

| 文件 | 实现内容 |
| --- | --- |
| `main.c`、`oracle.c` | 定向与随机输入、INT64 独立参考、保护区与逐行校验 |
| `gemv_scalar.c`、`gemv_rvv.S` | 标量对照和四行复用的标准 RVV 基线 |
| `gemv_vdot.S`、`pack.c` | 单行/四行点积、跨块 INT32 累加、补零及端到端包装 |
| `measure.S`、`protocol.json` | 共用计时边界、尺寸、种子、先后顺序和统计规则 |
| `check-nemu.py`、`audit-timer.py` | 独立参考执行与真实计时事件检查 |
| `run.py`、`analyze.py` | 差分运行、完整采样解析和逐进程统计 |
| `wave.py`、`signals.py`、`render-evidence.py` | 单调用实际信号读取、逐项核算及图件生成 |

实际结果见[应用测试与性能报告](../reports/INT8矩阵向量乘应用测试与性能报告.md)。
