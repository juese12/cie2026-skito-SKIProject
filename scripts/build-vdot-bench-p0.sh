#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
profile="${1:---smoke}"
case "$profile" in
  --smoke) name=smoke; reps=4; warmup=2; batches=8; random=0; smoke=1 ;;
  --full) name=full; reps=8; warmup=8; batches=256; random=1000; smoke=0 ;;
  *) echo 'usage: build-vdot-bench-p0.sh [--smoke|--full]'; exit 2 ;;
esac
bash "$repo_dir/scripts/vdot-step.sh" "bench-v3-$name-build" \
  make -C "$repo_dir/stage3/vdot-bench-p0" ARCH=riscv64-xs \
  NAME="cie2026-stage3-vdot-bench-v3-$name" VDOT_BENCH_REPS="$reps" \
  DST_DIR="$repo_dir/stage3/vdot-bench-p0/build/$name-objects/" \
  VDOT_BENCH_WARMUP="$warmup" VDOT_BENCH_BATCHES="$batches" \
  VDOT_BENCH_RANDOM="$random" VDOT_BENCH_SMOKE="$smoke"
