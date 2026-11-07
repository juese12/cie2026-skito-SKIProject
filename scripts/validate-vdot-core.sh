#!/usr/bin/env bash
# 顺序验收；flock 防止会话中断后误启动第二个队列。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir/.."
mkdir -p "$repo_dir/stage2/logs"
exec 9>"$repo_dir/stage2/logs/core-validation.lock"
flock -n 9 || { echo 'another core validation queue is active'; exit 2; }
trap 'queue_status=$?; printf "[queue exit] %s status=%s\n" "$(date --iso-8601=seconds)" "$queue_status"' EXIT
echo "[queue start] $(date --iso-8601=seconds)"
sha256sum XiangShan/build/emu NEMU/build/riscv64-nemu-interpreter-so
bash "$repo_dir/scripts/vdot-step.sh" new-core-vadd-resume \
  stdbuf -oL XiangShan/build/emu --diff=NEMU/build/riscv64-nemu-interpreter-so \
  -i "$repo_dir/stage1/vector-add/build/cie2026-stage1-vector-add-riscv64-xs.bin" --max-cycles=100000
vadd_log="$(ls -t "$repo_dir"/stage2/logs/*-new-core-vadd-resume.full.log | head -n 1)"
rg -aq 'vector-add PASS' "$vadd_log"
rg -aq 'HIT GOOD TRAP' "$vadd_log"
! rg -aq 'HIT BAD TRAP|ABORT|different at pc' "$vadd_log"
echo "[queue] new-core vadd verified"
VDOT_IMAGE="$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-smoke-riscv64-xs.bin" \
  bash "$repo_dir/scripts/run-vdot.sh"
echo "[queue] smoke verified"
bash "$repo_dir/scripts/run-vdot.sh"
echo "[queue] full vdot verified"
bash "$repo_dir/scripts/run-vdot-bench.sh"
echo "[queue] benchmark verified"
echo "[queue PASS] $(date --iso-8601=seconds)"
