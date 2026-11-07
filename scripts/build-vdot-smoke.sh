#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
# 对象文件独立保存；修改用例数量后不能复用完整测试的 main.o。
bash "$repo_dir/scripts/vdot-step.sh" software-smoke-build \
  make -C "$repo_dir/stage2/vdot-tests" ARCH=riscv64-xs \
  NAME=cie2026-stage2-vdot-smoke VDOT_RANDOM_CASES=0 \
  DST_DIR="$repo_dir/stage2/vdot-tests/build/smoke-objects/"
