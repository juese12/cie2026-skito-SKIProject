#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
bash "$repo_dir/scripts/vdot-step.sh" software-ordinary-build \
  make -C "$repo_dir/stage2/vdot-tests" ARCH=riscv64-xs \
  NAME=cie2026-stage2-vdot-ordinary VDOT_ORDINARY_ONLY=1 \
  DST_DIR="$repo_dir/stage2/vdot-tests/build/ordinary-objects/"
