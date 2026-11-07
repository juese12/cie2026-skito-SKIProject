#!/usr/bin/env bash
# 按既定顺序继续：已知烟雾测试、动态计时边界、正式测试、报告。
set -euo pipefail
repo_dir="${VDOT_BENCH_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [[ "${VDOT_P0_SNAPSHOT:-0}" != 1 ]]; then
  snapshot_dir="$(mktemp -d "$repo_dir/stage3/logs/validation-snapshot.XXXXXX")"
  cp -- "${BASH_SOURCE[0]}" "$snapshot_dir/p0.sh"
  exec env VDOT_P0_SNAPSHOT=1 VDOT_BENCH_REPO_DIR="$repo_dir" bash "$snapshot_dir/p0.sh" "$@"
fi
test "$#" -eq 3 || { echo 'usage: complete-vdot-p0.sh SMOKE.paths TIMER.vcd TIMER.full.log'; exit 2; }
cd "$repo_dir"
smoke_manifest="$1"; wave="$2"; wave_log="$3"
test -f "$smoke_manifest" && test -f "$wave" && test -f "$wave_log"
report="${VDOT_P0_REPORT:-stage3/reports/原始核正式性能实测报告v3.md}"
test ! -e "$report" || { echo "report already exists; set VDOT_P0_REPORT to a fresh output path: $report"; exit 2; }
test -d "$(dirname "$report")" || { echo "report parent directory does not exist: $report"; exit 2; }
while ! flock -n stage3/logs/benchmark-series.lock true; do sleep 10; done
mapfile -t smoke_logs < "$smoke_manifest"
test "${#smoke_logs[@]}" -eq 2
for log in "${smoke_logs[@]}"; do rg -aq 'bench meta schema=3 profile=smoke ' "$log"; done
python3 stage3/tests/analyze-bench.py "${smoke_logs[@]}"
stamp="$(date +%Y%m%dT%H%M%S)-$$"
python3 stage3/tests/check-timer-wave.py "$wave" "$wave_log" \
  --json-out "stage3/logs/$stamp-timer-final-audit.json" > "stage3/logs/$stamp-timer-final-audit.log"
echo '[P0] runtime smoke and dynamic boundary passed; starting four formal processes'
series_console="stage3/logs/$stamp-p0-full-series-console.log"
bash scripts/run-vdot-bench-series.sh --runtime-order | tee "$series_console"
manifest="$(sed -n 's/.*\[series exit\].*status=0 manifest=//p' "$series_console")"
test -f "$manifest"
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
printf '%s\tP0-full-report-strict-audit\t%s\t%s\n' "$(date --iso-8601=seconds)" "$strict_status" "$manifest" >> stage2/logs/operations.tsv
echo "[P0 data/report completed] strict_stability_exit=$strict_status manifest=$manifest"
(( strict_status == 0 || strict_status == 3 ))
