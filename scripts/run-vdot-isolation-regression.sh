#!/usr/bin/env bash
# 完整整核回归顺序执行，在活动终端会话中通过 vdot-step 启动；
# 不能将沙箱子进程放到后台后假定它会在会话结束后继续运行。
set -euo pipefail
repo_dir="${VDOT_ISOLATION_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
exec 10>"$repo_dir/stage2/logs/isolation-regression.lock"
flock -n 10 || { echo 'isolation regression already active'; exit 2; }
exec 9>"$repo_dir/stage2/logs/isolation-build.lock"
echo '[queue] waiting for isolation build lock; no simulator overlaps RTL generation'
flock 9
build="$repo_dir/../XiangShan/build/operand-isolation"
export VDOT_EMU="$build/emu"
test -x "$VDOT_EMU" || { echo 'build finished without an executable'; exit 2; }
cd "$repo_dir/../XiangShan"
sha256sum -c "$build/source-before.sha256"
cd "$repo_dir"
stamp="$(date +%Y%m%dT%H%M%S)"
manifest="$repo_dir/stage2/logs/$stamp-isolation-regression.sha256"
sha256sum "$VDOT_EMU" "$repo_dir/../NEMU/build/riscv64-nemu-interpreter-so" \
  "$repo_dir"/stage2/control-tests/{main.c,control.S,trap.S,legacy.S,Makefile} \
  "$repo_dir"/stage2/control-tests/build/*-riscv64-xs.{bin,elf} \
  "$repo_dir"/stage2/control-tests/build/*.symbols \
  "$repo_dir/scripts/check-vdot-control.py" "$repo_dir/scripts/run-vdot-control.sh" \
  "$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-riscv64-xs.bin" \
  "$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-smoke-riscv64-xs.bin" | tee "$manifest"
bash scripts/vdot-step.sh isolation-control-auditor-tests python3 stage2/control-tests/test_control_audit.py
VDOT_IMAGE="$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-smoke-riscv64-xs.bin" \
  bash scripts/vdot-step.sh isolation-smoke bash scripts/run-vdot.sh
bash scripts/vdot-step.sh isolation-full-functional bash scripts/run-vdot.sh
init_seed=101
for seed in 56444f54 00000001 9e3779b9 deadbeef; do
  CONTROL_SEED_HEX="$seed" bash scripts/vdot-step.sh "isolation-control-$seed" \
    bash scripts/run-vdot-control.sh --seed="$init_seed"
  init_seed=$((init_seed+101))
done
wave="$repo_dir/stage2/waveform/$stamp-isolation-control.vcd"
CONTROL_SEED_HEX=56444f54 bash scripts/vdot-step.sh isolation-control-wave \
  bash scripts/run-vdot-control.sh --seed=101 --dump-wave --dump-commit-trace \
  --wave-path="$wave" -b 0 -e 26000
# 根据记录的运行命令定位波形，不能简单选最新文件。
mapfile -t logs < <(rg -l -F -- "$wave" "$repo_dir"/stage2/logs/*-control-56444f54.log)
test "${#logs[@]}" -eq 1
full="${logs[0]%.log}.full.log"
bash scripts/vdot-step.sh isolation-control-wave-audit python3 scripts/check-vdot-control.py \
  "$full" --seed 56444f54 --wave "$wave" \
  --symbols stage2/control-tests/build/cie2026-stage2-control-seed56444f54.symbols \
  --json-out "$wave.control.json"
sha256sum -c "$manifest"
printf '[suite PASS] %s\n' "$(date --iso-8601=seconds)"
