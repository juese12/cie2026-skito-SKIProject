#!/usr/bin/env bash
# 导出补丁时不暂存文件，也不包含无关子模块修改。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xs_env_dir="$(cd "$repo_dir/.." && pwd)"
variant="v0.1"
xiangshan_only=0
if [[ $# != 0 ]]; then
  [[ $# == 2 && "$1" == --xiangshan-only && "$2" =~ ^[a-zA-Z0-9_-]+$ ]] || {
    echo 'usage: export-vdot-patches.sh [--xiangshan-only LABEL]'; exit 2;
  }
  variant="$2"
  xiangshan_only=1
  test ! -e "$repo_dir/stage2/patches/xiangshan-vdot-$variant.patch" || {
    echo 'refusing to overwrite a named patch'; exit 2;
  }
fi
mkdir -p "$repo_dir/stage2/patches"
emit_new() {
  local status=0
  git diff --no-index -- /dev/null "$1" || status=$?
  [[ "$status" -le 1 ]]
}
(
  cd "$xs_env_dir/XiangShan"
  git diff -- src/main/scala/xiangshan
  emit_new src/main/scala/xiangshan/backend/fu/vector/VDot8.scala
  emit_new src/test/scala/xiangshan/VDotDecodeTest.scala
  emit_new src/test/scala/xiangshan/backend/fu/vector/VDot8Test.scala
  emit_new src/test/scala/xiangshan/backend/fu/vector/VDotIntegrationTest.scala
) > "$repo_dir/stage2/patches/xiangshan-vdot-$variant.patch"
if (( xiangshan_only )); then
  sha256sum "$repo_dir/stage2/patches/xiangshan-vdot-$variant.patch"
  exit 0
fi
(
  cd "$xs_env_dir/NEMU"
  git diff -- src
  emit_new configs/vdot-v0.1_defconfig
) > "$repo_dir/stage2/patches/nemu-vdot-v0.1.patch"
sha256sum "$repo_dir/stage2/patches/"*.patch
