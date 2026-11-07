#!/usr/bin/env bash
# 已授权的 P1 后续步骤：定向证明、功能回归、v3 测量队列。
# 使用已有构建和测量参数，保留旧报告。
set -euo pipefail
repo_dir="${VDOT_P1_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$repo_dir"
if [[ "${VDOT_P1_SNAPSHOT:-0}" != 1 ]]; then
  snapshot_dir="$(mktemp -d "$repo_dir/stage3/logs/p1-continuation.XXXXXX")"
  cp -- "${BASH_SOURCE[0]}" "$snapshot_dir/continue.sh"
  exec env VDOT_P1_SNAPSHOT=1 VDOT_P1_REPO_DIR="$repo_dir" bash "$snapshot_dir/continue.sh" "$@"
fi
[[ $# == 0 ]] || { echo 'usage: complete-vdot-p1.sh'; exit 2; }
exec 8>stage3/logs/p1-validation.lock
flock -n 8 || { echo 'another P1 validation is active'; exit 2; }
export VDOT_EMU="$repo_dir/../XiangShan/build/p1-oldvd/emu"
export VDOT_REF_SO="$repo_dir/../NEMU/build/riscv64-nemu-interpreter-so"
probe=stage3/oldvd-probe/build/cie2026-stage3-oldvd-probe-riscv64-xs.bin
before_log=stage2/logs/20261004T212622-p1-before-directed-wave.full.log
before_audit=stage3/logs/p1-before-wave-source-audit.json
before_manifest=stage3/logs/20261003T155604-301-series-full-runtime.paths
report=stage3/reports/P1核正式性能实测报告.md
test -f "$VDOT_EMU" && test -f "$before_log" && test -f "$before_audit" && test -f "$before_manifest"
test ! -e "$report" || { echo "refusing to overwrite $report"; exit 2; }
check_sha() {
  local expected="$1" path="$2" actual
  actual="$(sha256sum "$path")"; actual="${actual%% *}"
  [[ "$actual" == "$expected" ]] || { echo "frozen artifact changed: $path"; exit 2; }
}
check_sha 97ef3eef1700270941519d5acfc91e3632c7a33b24ab54076550f646e6a43f66 stage3/logs/p1-artifacts-20261004/emu-before
check_sha 2ad56dc58975ed98748a7c76e014d8ac2a4576b327adbb6324f7f7082b25cb74 "$VDOT_REF_SO"
check_sha 17ca8abfb560f1e0fe4b9bf605d55d5c2b1b376a6855c213b58d0ca335a7a216 "$probe"
check_sha 2adc73bbe4a0e01d183b93fc7a38613438b979af955ef8d2201904db6e0e1c24 stage3/vdot-bench-p0/build/cie2026-stage3-vdot-bench-v3-full-riscv64-xs.bin
check_sha f351c87fe9f29cc1aafaca00c2f8f6c770288a894bfa92eed512985934a52ba5 stage3/vdot-bench-p0/build/cie2026-stage3-vdot-bench-v3-smoke-riscv64-xs.bin
stamp="$(date +%Y%m%dT%H%M%S)-$$"
prefix="stage3/logs/$stamp-p1"
sha256sum "$VDOT_EMU" "$VDOT_REF_SO" "$probe" stage2/vdot-tests/build/*-riscv64-xs.bin \
  stage3/tests/check-oldvd-wave.py stage3/tests/compare-oldvd.py \
  stage3/tests/compare-bench-cores.py stage3/tests/prepare-runtime-order.py \
  stage3/tests/analyze-bench.py stage3/tests/render-bench-report.py \
  stage3/tests/analyze-e2e-variation.py stage3/vdot-bench-p0/build/*-riscv64-xs.bin \
  stage3/vdot-bench-p0/build/*-riscv64-xs.elf \
  scripts/run-vdot-bench.sh scripts/run-vdot-bench-series.sh > "$prefix-frozen.sha256"
step="p1-after-directed-$stamp"
bash scripts/vdot-step.sh "$step" "$VDOT_EMU" --diff="$VDOT_REF_SO" -i "$probe" \
  --max-cycles=2000000 --dump-wave-full --wave-path="$prefix-after.vcd" \
  --dump-commit-trace --log-begin=0 --log-end=26000 > "$prefix-directed-console.log" 2>&1
after_logs=(stage2/logs/*-"$step".full.log)
[[ ${#after_logs[@]} == 1 ]] && test -f "${after_logs[0]}"
python3 stage3/tests/check-oldvd-wave.py "$prefix-after.vcd" "${after_logs[0]}" \
  --minimum-completed-dot=1400 --minimum-false-wait=0 --require-no-false-wait \
  --json-out "$prefix-after-wave-audit.json" > "$prefix-after-wave-audit.log"
python3 stage3/tests/compare-oldvd.py "$before_log" "${after_logs[0]}" \
  "$before_audit" "$prefix-after-wave-audit.json" \
  --json-out "$prefix-directed-comparison.json" > "$prefix-directed-comparison.log"
echo "[P1 directed PASS] prefix=$prefix"
VDOT_IMAGE="$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-smoke-riscv64-xs.bin" bash scripts/run-vdot.sh
VDOT_IMAGE="$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-riscv64-xs.bin" bash scripts/run-vdot.sh
echo '[P1 functional PASS] starting two v3 smoke processes'
bash scripts/run-vdot-bench-series.sh --runtime-order --smoke | tee "$prefix-smoke-series-console.log"
sha256sum -c "$prefix-frozen.sha256"
echo '[P1 smoke PASS] starting four authorized v3 formal processes'
bash scripts/run-vdot-bench-series.sh --runtime-order | tee "$prefix-full-series-console.log"
manifest="$(sed -n 's/.*\[series exit\].*status=0 manifest=//p' "$prefix-full-series-console.log")"
test -f "$manifest"
sha256sum -c "$prefix-frozen.sha256"
python3 stage3/tests/render-bench-report.py --manifest "$manifest" \
  --output "$report" --json-out "${manifest%.paths}-report.json"
mapfile -t summaries < "$manifest"
full_logs=()
for log in "${summaries[@]}"; do full_logs+=("${log%.log}.full.log"); done
python3 stage3/tests/analyze-e2e-variation.py "${full_logs[@]}" > "${manifest%.paths}-e2e-diagnosis.json"
set +e
python3 stage3/tests/analyze-bench.py "${full_logs[@]}" --strict-stability \
  --json-out "${manifest%.paths}-strict-audit.json" > "${manifest%.paths}-strict-audit.log"
strict_status=$?
set -e
printf '%s\tP1-full-report-strict-audit\t%s\t%s\n' "$(date --iso-8601=seconds)" "$strict_status" "$manifest" >> stage2/logs/operations.tsv
echo "[P1 data/report completed] strict_stability_exit=$strict_status manifest=$manifest prefix=$prefix"
(( strict_status == 0 || strict_status == 3 ))
python3 stage3/tests/compare-bench-cores.py "$before_manifest" "$manifest" \
  --json-out "$prefix-formal-core-comparison.json" > "$prefix-formal-core-comparison.log"
echo "[P1 formal core comparison PASS] prefix=$prefix"
