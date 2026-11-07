# vdot 补丁选择：当前 e8/e16 与历史版本

当前功能验收选择 `sew16-fixed8`，合同和整组 emu/ref/image 见[版本选择](../../docs/核与参考库版本选择.md)，主设计见[当前设计](../docs/vdot指令设计说明.md)。补丁均为相对指定基线的完整整合补丁，同一仓库只选择一个版本。

## 当前配套补丁

| 仓库 | 适用基线 | 当前补丁 |
| --- | --- | --- |
| XiangShan | 项目配套的香山基线 | [xiangshan-vdot-sew16-fixed8.patch](xiangshan-vdot-sew16-fixed8.patch) |
| NEMU | 项目配套的 NEMU 基线 | [nemu-vdot-sew16-fixed8.patch](nemu-vdot-sew16-fixed8.patch) |
| XiangShan/difftest | 项目配套的 Difftest 子模块基线 | [difftest-sync-compat.patch](difftest-sync-compat.patch) |

XS 补丁包含既有指令集成、oldVd 去依赖、操作数隔离/更新使能、e8/e16 共享算术及 Scala 测试。NEMU 补丁包含精确匹配、参考 helper、既有 ROM/差分兼容代码及配置。项目内 `stage2/sew16/` 测试程序和脚本由作品仓库提供，不包含在这两个子仓库补丁中。

精确源码版本见[依赖版本清单](../../manifest/submodule-commits.txt)。应用补丁前应确认对应仓库版本，不在其他版本上直接叠加。

本轮完整 24 项依赖以 `manifest/release-dependencies.json` 为准，包含 Difftest 和 NEMU 隐式仓库。`prepare-clean-workspace.py` 成功后已经应用下列三份补丁，此时只检查状态，不再次执行 `git apply`。

以下是匹配干净基线的应用步骤示例。先保留本地修改，确认基线；当前已经包含补丁的工作区只做反向检查，不重复应用：

```bash
# 从 xs-env 执行；仅用于匹配的干净基线。
git -C XiangShan apply --check ../cie2026-skito-SKIProject/stage2/patches/xiangshan-vdot-sew16-fixed8.patch
git -C NEMU apply --check ../cie2026-skito-SKIProject/stage2/patches/nemu-vdot-sew16-fixed8.patch
git -C XiangShan apply ../cie2026-skito-SKIProject/stage2/patches/xiangshan-vdot-sew16-fixed8.patch
git -C NEMU apply ../cie2026-skito-SKIProject/stage2/patches/nemu-vdot-sew16-fixed8.patch
# 从作品目录应用独立 Difftest 兼容补丁；重复执行只检查，不重复修改。
cd cie2026-skito-SKIProject
bash scripts/prepare-vdot-difftest.sh --apply
```

应用检查只证明补丁能否应用。本轮已另在同主机独立目录检出指定依赖、应用三份补丁，完成真实整核构建和差分回归，见[独立目录复现报告](../reports/公开包独立目录复现报告.md)。原当前核的成功记录仍见[扩展验收](../reports/固定八项e8e16实施与验收报告.md)，两轮日志分开保存。

已确认当前两侧仓库与配套基线一致，两份补丁的 `git apply --reverse --check` 均通过。该操作只检查补丁能否反向应用，没有改变工作区。

参考模型继续使用经本工程验证的 `vdot-v0.1_defconfig` 配置；名称是历史命名，实际执行语义由已应用的 NEMU 补丁决定。当前新库独立构建到 `NEMU/build/sew16/`，构建命令使用 `git_commit=` 禁用教学自动提交钩子；完整步骤见[扩展手册](../sew16/固定八项e8e16扩展操作手册.md)。旧参考库保留在 `NEMU/build/riscv64-nemu-interpreter-so`。

## 历史补丁与导出边界

旧 `xiangshan-vdot-v0.1.patch` / P1 / `xiangshan-vdot-operand-isolation.patch` 和 `nemu-vdot-v0.1.patch` 保留对应 e8 版本。旧隔离核的正式性能和实际取消证据见[历史验收](../reports/vdot功能与整核控制验收报告.md)；这些证据不代替新核性能/PPA。

`scripts/export-vdot-patches.sh --xiangshan-only LABEL` 导出指定新名称的 XS 补丁并拒绝覆盖已有同名文件；该选项不导出 NEMU。脚本无参数时写旧 `v0.1` 命名产物，不能作为当前 e8/e16 的默认导出入口。本轮已有新补丁，无需再次导出。

`XiangShan/difftest/verilator.mk` 的七处 `sync` 参数修正已单独导出为第三份补丁，未改变现有 Difftest 工作区。它将重复的 `-d` 选项合并为一个，仍对两个目录执行同步；不改动 RTL 或差分语义。应用脚本会先检查是否已应用，再检查能否应用，不匹配时停止。构建预检要求该补丁已就绪。

工具链与子模块依赖见[仓库清单](../../manifest/仓库关系.md)，三份补丁后的完整步骤见[公开交付与干净复现手册](../../docs/公开交付与干净复现操作手册.md)。同主机独立目录复现通过；官方验收、全新系统环境和物理 PPA 不在本轮结论内。
