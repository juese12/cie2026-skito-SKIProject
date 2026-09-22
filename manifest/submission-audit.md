# 作品仓库合规核查

核查日期：2026-09-23

核查依据：

- 大赛 PDF《2026CIE 全国 RISC-V 高水平创新及应用大赛作品提交流程指南》
- `OpenXiangShan/XiangShanLab` 当前 `master` 分支中的 `SUBMISSION_GUIDE.md`

## 作品仓库要求

| 核查项 | 官方要求 | 当前值 | 结论 |
|---|---|---|---|
| 仓库名称 | `cie2026-团队名称-作品名` | `cie2026-skito-SKIProject` | 符合 |
| 所有者 | 参赛者 GitHub 账号 | `juese12` | 符合 |
| 可见性 | Public | `PUBLIC` | 符合 |
| 默认/推送分支 | `main` | `main` | 符合 |
| 项目初始化 | 独立 Git 仓库 | 已执行 `git init -b main` | 符合 |
| 远端地址 | GitHub 作品仓库 | `https://github.com/juese12/cie2026-skito-SKIProject` | 符合 |
| 提交信息 | `2026CIE大赛作品-团队名称-作品名` | `2026CIE大赛作品-skito-SKIProject` | 符合 |

## 目录与内容核查

官方指南没有规定作品仓库内部必须使用某一种目录模板。本仓库采用 `manifest/`、`scripts/`、`stage1/`、`stage2/`、`stage3/` 分阶段组织，属于额外的可复现性设计，不与官方要求冲突。

提交范围仅包含源码、脚本、说明和精简文本日志。以下内容通过 `.gitignore` 排除：

- 编译产物和二进制文件；
- VCD、FST、FSDB 波形；
- 原始大型性能日志；
- `my_submission.txt` 和 `private/` 隐私材料。

## 与 XiangShanLab 提交仓库的边界

本仓库是官方流程第二步要求的“作品公有仓库”，不是 `XiangShanLab` fork。

官方流程第一步已完成：

- GitHub fork：`https://github.com/juese12/XiangShanLab`
- fork 来源：`OpenXiangShan/XiangShanLab`
- 可见性：Public
- 当前默认分支：`master`（与当前上游仓库一致）
- 本地浅层稀疏克隆：`../XiangShanLab`
- 提交目录和 `submit.sh` 已核验存在

官方流程第三至六步尚需：

1. 在 fork 的 `2026-CIE-RISC-V-Contest-Application-Track` 目录创建仅存于本地的隐私文件 `my_submission.txt`。
2. 使用 `submit.sh` 生成加密的 `01_参赛选手提交区/skito/submission.asc`。
3. 只提交加密结果，绝不提交 `my_submission.txt`。
4. 向官方仓库发起 PR。

官方文档第二步明确要求作品仓库为 Public，但第三步示例中的 `repo-url` 文案写成“私有仓库”，两处存在文字矛盾。本项目遵循第二步带“重要”标记的 Public 要求，提交信息中的 `repo-url` 应填写本公有作品仓库地址。
