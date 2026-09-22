# 第一阶段：环境与最小闭环

第一阶段目标是先证明“程序编译 → XiangShan 仿真 → NEMU 差分 → 正常退出”的完整链路可用，再开展自定义指令开发。

## 三个步骤

1. 记录参赛身份和开发机地址。
2. 固化工具链、依赖仓库版本及环境验收结果。
3. 建立并运行独立的 Hello XiangShan 最小程序。

Hello 程序的预期关键输出：

```text
hello xiangshan, I am skito, IP address: 192.168.31.222
HIT GOOD TRAP
```

## RVV 向量加法基线

`vector-add/` 使用汇编显式执行：

```text
vsetvli → vle32.v → vadd.vv → vse32.v
```

测试包含 37 个 `int32_t` 元素，可覆盖多个 VLEN 分块，并由 C 程序逐元素比对标量期望值。成功输出包含：

```text
vector-add PASS
HIT GOOD TRAP
```

构建、运行方法及完整操作过程见仓库根目录 `README.md` 和 `docs/向量加法指令执行过程.md`。
