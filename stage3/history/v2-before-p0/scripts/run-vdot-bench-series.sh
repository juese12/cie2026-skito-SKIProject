#!/usr/bin/env bash
# Fresh emulator per run, counterbalanced initial order, no parallel simulation.
set -euo pipefail
repo_dir="${VDOT_BENCH_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
mkdir -p "$repo_dir/stage3/logs"
if [[ "${VDOT_BENCH_SERIES_SNAPSHOT:-0}" != 1 ]]; then
  snapshot_dir="$(mktemp -d "$repo_dir/stage3/logs/series-snapshot.XXXXXX")"
  cp -- "${BASH_SOURCE[0]}" "$snapshot_dir/series.sh"
  exec env VDOT_BENCH_SERIES_SNAPSHOT=1 VDOT_BENCH_REPO_DIR="$repo_dir" \
    bash "$snapshot_dir/series.sh" "$@"
fi
profile=full
runs=""
for arg in "$@"; do
  case "$arg" in
    --smoke) profile=smoke ;;
    --runs=*) runs="${arg#--runs=}" ;;
    --help) echo 'usage: run-vdot-bench-series.sh [--smoke] [--runs=EVEN_NUMBER]'; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done
if [[ -z "$runs" ]]; then
  runs=4
  [[ "$profile" == smoke ]] && runs=2
fi
[[ "$runs" =~ ^[1-9][0-9]?$ ]] || { echo 'invalid run count'; exit 2; }
minimum=4
[[ "$profile" == smoke ]] && minimum=2
(( runs >= minimum && runs % 2 == 0 )) || { echo 'need balanced runs (full>=4, smoke>=2)'; exit 2; }
mkdir -p "$repo_dir/stage3/logs" "$repo_dir/stage2/logs"
exec 9>"$repo_dir/stage3/logs/benchmark-series.lock"
flock -n 9 || { echo 'another benchmark series is active'; exit 2; }
series="$(date +%Y%m%dT%H%M%S)-$$-series-$profile"
manifest="$repo_dir/stage3/logs/$series.paths"
test ! -e "$manifest"
touch "$manifest"
trap 'series_status=$?; printf "[series exit] %s status=%s manifest=%s\n" "$(date --iso-8601=seconds)" "$series_status" "$manifest"' EXIT
for (( run=0; run<runs; run++ )); do
  first=$(( run % 2 ))
  image="$repo_dir/stage3/vdot-bench/build/cie2026-stage3-vdot-bench-v2-$profile-order$first-riscv64-xs.bin"
  test -f "$image" || { echo "build both $profile order images first"; exit 2; }
  echo "[series run] $run/$runs first=$first profile=$profile"
  VDOT_IMAGE="$image" VDOT_BENCH_RUN_ID="$series-run$run" VDOT_BENCH_RESULT_FILE="$manifest" \
    bash "$repo_dir/scripts/run-vdot-bench.sh"
done
mapfile -t summaries < "$manifest"
python3 "$repo_dir/stage3/tests/analyze-bench.py" "${summaries[@]}" \
  --json-out "$repo_dir/stage3/logs/$series.json" | tee "$repo_dir/stage3/logs/$series.log"
printf '%s\tbenchmark-series-%s\t0\t%s\n' "$(date --iso-8601=seconds)" "$profile" "$repo_dir/stage3/logs/$series.log" >> "$repo_dir/stage2/logs/operations.tsv"
echo '[series data PASS] Stability warnings do not constitute a stable-performance claim.'
