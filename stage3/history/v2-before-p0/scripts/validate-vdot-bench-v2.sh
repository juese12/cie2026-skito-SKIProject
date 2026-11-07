#!/usr/bin/env bash
# Wait for an explicitly selected smoke series, audit it, then run full series.
set -euo pipefail
repo_dir="${VDOT_BENCH_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
mkdir -p "$repo_dir/stage3/logs"
if [[ "${VDOT_BENCH_VALIDATION_SNAPSHOT:-0}" != 1 ]]; then
  snapshot_dir="$(mktemp -d "$repo_dir/stage3/logs/validation-snapshot.XXXXXX")"
  cp -- "${BASH_SOURCE[0]}" "$snapshot_dir/validate.sh"
  exec env VDOT_BENCH_VALIDATION_SNAPSHOT=1 VDOT_BENCH_REPO_DIR="$repo_dir" \
    bash "$snapshot_dir/validate.sh" "$@"
fi
manifest="${1:?usage: validate-vdot-bench-v2.sh COMPLETED_OR_RUNNING_SMOKE.paths}"
test "$#" -eq 1
test -f "$manifest"
echo "[validation wait] explicit smoke manifest=$manifest"
while ! flock -n "$repo_dir/stage3/logs/benchmark-series.lock" true; do
  sleep 10
done
mapfile -t logs < "$manifest"
test "${#logs[@]}" -eq 2 || { echo 'expected exactly two completed smoke processes'; exit 2; }
python3 "$repo_dir/stage3/tests/analyze-bench.py" "${logs[@]}"
for log in "${logs[@]}"; do
  rg -aq 'bench meta schema=2 profile=smoke ' "$log"
done
echo '[validation] smoke data verified; starting four fresh full-profile processes'
bash "$repo_dir/scripts/run-vdot-bench-series.sh"
echo '[validation data PASS] inspect all stability warnings before performance claims'
