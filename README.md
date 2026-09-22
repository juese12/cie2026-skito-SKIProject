# SKIProject

2026 CIE 全国大学生集成电路创新创业大赛 RISC-V 赛道作品仓库。

## 队伍信息

- 团队名：`skito`
- TEAM_ID：`skito`
- 项目名：`SKIProject`
- GitHub 用户名：`juese12`
- 开发机 IPv4：`192.168.31.222`
- 目标平台：香山处理器昆明湖 V2（XiangShan Kunminghu V2）
- 目标任务：实现并验证自定义向量点积指令 `vdot.vv`

## 当前进度

- [x] 建立本地独立 Git 作品仓库
- [x] 固化团队、主机和工具链信息
- [x] 固化依赖仓库提交版本
- [x] 构建并通过第一阶段 Hello XiangShan 差分仿真
- [x] 创建 GitHub 公有远端仓库并推送
- [x] 完成 RVV `vadd.vv` 向量加法基线测试
- [x] 完成 `vadd.vv` 波形导出、自动解析与执行/写回定位
- [ ] 进入 `vdot.vv` 指令软硬件协同实现

## 快速开始

本仓库应放在 `xs-env` 根目录下，与 `XiangShan`、`NEMU` 和 `nexus-am` 同级。

```bash
cd cie2026-skito-SKIProject
./scripts/build-hello.sh
./scripts/run-hello.sh
./scripts/verify-stage1-env.sh
./scripts/build-vector-add.sh
./scripts/run-vector-add.sh
./scripts/dump-vector-add-wave.sh
./scripts/analyze-vector-wave.sh
```

运行日志保存在 `stage1/logs/`。构建产物和波形文件不纳入 Git，避免仓库膨胀。

## 目录说明

```text
manifest/                   环境与依赖版本清单
scripts/                    可重复执行脚本
stage1/hello-xiangshan/     最小裸机程序
stage1/docs/                环境部署与操作记录
stage1/logs/                可提交的文本日志
stage2/                     指令功能实现阶段
stage3/                     性能、验证与交付阶段
```

## 安全约定

比赛最终提交用的 `my_submission.txt` 含联系方式等隐私信息，不得提交到本公有仓库；只向官方 XiangShanLab fork 提交脚本生成的加密 `submission.asc`。
