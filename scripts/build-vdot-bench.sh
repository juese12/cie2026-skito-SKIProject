#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
profile=full
baseline=0
orders=(0 1)
for arg in "$@"; do
  case "$arg" in
    --smoke) profile=smoke ;;
    --baseline-only) baseline=1; orders=(0) ;;
    --first=0) orders=(0) ;;
    --first=1) orders=(1) ;;
    --help) echo 'usage: build-vdot-bench.sh [--smoke] [--first=0|1] [--baseline-only]'; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
reps=8; warmup=8; batches=256; random=1000; smoke=0
if [[ "$profile" == smoke ]]; then
  reps=4; warmup=2; batches=8; random=0; smoke=1
fi
for first in "${orders[@]}"; do
  name="cie2026-stage3-vdot-bench-v2-$profile-order$first"
  if (( baseline )); then name="cie2026-stage3-vdot-baseline-v2-$profile"; fi
  bash "$repo_dir/scripts/vdot-step.sh" "bench-v2-$profile-order$first-build" \
    make -C "$repo_dir/stage3/vdot-bench" ARCH=riscv64-xs NAME="$name" \
    VDOT_BASELINE_ONLY="$baseline" VDOT_BENCH_FIRST="$first" VDOT_BENCH_SMOKE="$smoke" \
    VDOT_BENCH_REPS="$reps" VDOT_BENCH_WARMUP="$warmup" \
    VDOT_BENCH_BATCHES="$batches" VDOT_BENCH_RANDOM="$random" \
    DST_DIR="$repo_dir/stage3/vdot-bench/build/$name-objects/"
done
