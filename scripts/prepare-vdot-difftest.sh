#!/usr/bin/env bash
# 只应用公开的 Difftest 构建兼容补丁，遇到不匹配的本地修改时停止。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:---check}"
[[ $# -le 1 && ( "$mode" == --check || "$mode" == --apply ) ]] || {
  echo 'usage: bash scripts/prepare-vdot-difftest.sh [--check|--apply]' >&2; exit 2;
}
target="$repo_dir/../XiangShan/difftest"
patch="$repo_dir/stage2/patches/difftest-sync-compat.patch"
if git -C "$target" apply --reverse --check "$patch" 2>/dev/null; then
  echo '[difftest compatibility READY]'
elif git -C "$target" apply --check "$patch"; then
  if [[ "$mode" == --check ]]; then
    echo 'Difftest compatibility patch is required; run prepare-vdot-difftest.sh --apply' >&2
    exit 2
  fi
  git -C "$target" apply "$patch"
  git -C "$target" apply --reverse --check "$patch"
  echo '[difftest compatibility APPLIED]'
else
  echo 'Difftest does not match the compatibility patch; inspect local changes before continuing.' >&2
  exit 1
fi
