# 本地波形目录

执行以下命令生成和解析 `vadd.vv` 波形：

```bash
./scripts/dump-vector-add-wave.sh
./scripts/analyze-vector-wave.sh
```

默认产物为 `vector-add-vadd.vcd`，覆盖周期 2850–3300。VCD 文件体积较大，受仓库根目录 `.gitignore` 排除，不提交到 GitHub；仓库只保存波形生成脚本、解析脚本和文本分析结果。

当前 XiangShan `emu` 使用 Verilated VCD 后端，因此即使通用参数名为 `--dump-wave`，实际文件格式也是 VCD。打开方式示例：

```bash
gtkwave stage1/waveform/vector-add-vadd.vcd
```
