#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
exec 9>"$repo_dir/stage2/logs/control-software-build.lock"
flock -n 9 || { echo 'control software build is active'; exit 2; }
for seed in 56444f54 00000001 9e3779b9 deadbeef; do
  # 对象文件和最终镜像均按种子独立生成，避免沿用旧 CFLAGS。
  bash "$repo_dir/scripts/vdot-step.sh" "control-build-$seed" \
    make -C "$repo_dir/stage2/control-tests" ARCH=riscv64-xs \
    "NAME=cie2026-stage2-control-seed$seed" "CONTROL_SEED=0x$seed" \
    "DST_DIR=$repo_dir/stage2/control-tests/build/seed$seed/"
  riscv64-linux-gnu-nm -n "$repo_dir/stage2/control-tests/build/cie2026-stage2-control-seed$seed-riscv64-xs.elf" \
    > "$repo_dir/stage2/control-tests/build/cie2026-stage2-control-seed$seed.symbols"
done
sha256sum "$repo_dir"/stage2/control-tests/build/*-riscv64-xs.bin
