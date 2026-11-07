#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
emu="$repo_dir/../XiangShan/build/sew16-fixed8/emu"
ref="$repo_dir/../NEMU/build/sew16/riscv64-nemu-interpreter-so"
image="$repo_dir/stage2/sew16/build/cie2026-stage2-vdot-sew16-riscv64-xs.bin"
exec 9>"$repo_dir/stage2/logs/sew16-regression.lock"
flock -n 9 || exit 2
for f in "$emu" "$ref" "$image"; do test -s "$f"; done
stamp="$(date +%Y%m%dT%H%M%S)"
log="$repo_dir/stage2/logs/$stamp-sew16-core.full.log"
sha256sum "$emu" "$ref" "$image" > "$log.inputs.sha256"
set +e
"$emu" --diff="$ref" -i "$image" --max-cycles=3000000 --seed=101 > "$log" 2>&1
status=$?
set -e
printf '\n[process exit] %d\n' "$status" >> "$log"
rg -a 'Difftest enabled|PASS|FAIL|HIT GOOD TRAP|HIT BAD TRAP|ABORT|different at pc|instrCnt|Guest cycle|Host time' "$log" || true
test "$status" -eq 0
rg -aq 'Difftest enabled' "$log"
rg -aq 'HIT GOOD TRAP' "$log"
rg -aq 'sew16 PASS: wide=836 seeds=4 illegal=4 e8-regression=1564 fixed-items=8' "$log"
rg -aq 'sew16 control PASS: branch-training=64 branch-probes=4 younger-exceptions=4' "$log"
test "$(rg -ac 'sew16 random PASS seed=' "$log")" -eq 4
! rg -aq 'FAIL|HIT BAD TRAP|ABORT|different at pc' "$log"
sha256sum -c "$log.inputs.sha256"
echo "[sew16 regression COMPLETE] $log"
