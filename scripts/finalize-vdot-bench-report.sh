#!/usr/bin/env bash
# 等待明确指定的完整测量队列结束，汇总前审核全部原始日志。
set -euo pipefail
repo_dir="${VDOT_BENCH_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
mkdir -p "$repo_dir/stage3/logs"
if [[ "${VDOT_BENCH_REPORT_SNAPSHOT:-0}" != 1 ]]; then
  snapshot_dir="$(mktemp -d "$repo_dir/stage3/logs/report-snapshot.XXXXXX")"
  cp -- "${BASH_SOURCE[0]}" "$snapshot_dir/finalize.sh"
  exec env VDOT_BENCH_REPORT_SNAPSHOT=1 VDOT_BENCH_REPO_DIR="$repo_dir" \
    bash "$snapshot_dir/finalize.sh" "$@"
fi
manifest="${1:?usage: finalize-vdot-bench-report.sh FULL_SERIES.paths}"
test "$#" -eq 1
test -f "$manifest"
echo "[report wait] explicit full manifest=$manifest"
while ! flock -n "$repo_dir/stage3/logs/benchmark-series.lock" true; do
  sleep 10
done
python3 "$repo_dir/stage3/tests/render-bench-report.py" --manifest "$manifest" \
  --output "$repo_dir/stage3/reports/vdot正式性能实测报告v2.md" \
  --json-out "${manifest%.paths}-report.json"
