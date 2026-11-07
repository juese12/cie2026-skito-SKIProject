#!/usr/bin/env bash
set -euo pipefail
repo_dir="${VDOT_BENCH_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
mkdir -p "$repo_dir/stage3/logs" "$repo_dir/stage2/logs"
if [[ "${VDOT_BENCH_RUNNER_SNAPSHOT:-0}" != 1 ]]; then
  snapshot_dir="$(mktemp -d "$repo_dir/stage3/logs/runner-snapshot.XXXXXX")"
  cp -- "${BASH_SOURCE[0]}" "$snapshot_dir/run.sh"
  exec env VDOT_BENCH_RUNNER_SNAPSHOT=1 VDOT_BENCH_REPO_DIR="$repo_dir" \
    bash "$snapshot_dir/run.sh" "$@"
fi
emu="${VDOT_EMU:-$repo_dir/../XiangShan/build/emu}"
ref="${VDOT_REF_SO:-$repo_dir/../NEMU/build/riscv64-nemu-interpreter-so}"
image="${VDOT_IMAGE:-$repo_dir/stage3/vdot-bench/build/cie2026-stage3-vdot-bench-v2-full-order0-riscv64-xs.bin}"
stamp="$(date +%Y%m%dT%H%M%S)"
mkdir -p "$repo_dir/stage3/logs" "$repo_dir/stage2/logs"
exec 8>"$repo_dir/stage3/logs/benchmark.lock"
flock -n 8 || { echo 'another benchmark runner is active'; exit 2; }
run_id="${VDOT_BENCH_RUN_ID:-$stamp-$$}"
[[ "$run_id" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo 'invalid run id'; exit 2; }
log="$repo_dir/stage3/logs/$run_id-bench.full.log"
summary="$repo_dir/stage3/logs/$run_id-bench.log"
[[ ! -e "$log" && ! -e "$summary" ]] || { echo 'refusing to overwrite an existing run'; exit 2; }
cmd=("$emu" "--diff=$ref" -i "$image" --max-cycles=10000000 -b 0 -e 0 "$@")
runtime_record=""
if [[ -n "${VDOT_RUNTIME_FIRST:-}" ]]; then
  [[ "$VDOT_RUNTIME_FIRST" == 0 || "$VDOT_RUNTIME_FIRST" == 1 ]] || exit 2
  [[ -f "${VDOT_RUNTIME_ELF:-}" ]] || { echo 'runtime ELF missing'; exit 2; }
  overlay_dir="$(mktemp -d "$repo_dir/stage3/logs/runtime-overlay.XXXXXX")"
  overlay="$overlay_dir/parameter.bin"
  runtime_record="$(python3 "$repo_dir/stage3/tests/prepare-runtime-order.py" "$VDOT_RUNTIME_ELF" "$image" "$VDOT_RUNTIME_FIRST" "$overlay")"
  overwrite_nbytes="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["overwrite_nbytes"])' "$runtime_record")"
  cmd+=("--gcpt-restore=$overlay" "--overwrite-nbytes=$overwrite_nbytes")
fi
{
  printf '[started] %s\n[run id] %s\n[command] ' "$(date --iso-8601=seconds)" "$run_id"
  printf '%q ' "${cmd[@]}"
  printf '\n'
  printf '[runner snapshot] %s\n' "$(sha256sum "${BASH_SOURCE[0]}")"
  if [[ -n "$runtime_record" ]]; then printf '[runtime parameter] %s\n' "$runtime_record"; fi
  for role in emu ref image; do
    case "$role" in emu) artifact="$emu" ;; ref) artifact="$ref" ;; image) artifact="$image" ;; esac
    hash="$(sha256sum "$artifact")"
    printf '[artifact %s] %s\n' "$role" "${hash%% *}"
    printf '[path %s] %s\n' "$role" "$artifact"
  done
} | tee "$summary" "$log"
set +e
stdbuf -oL -eL "${cmd[@]}" >> "$log" 2>&1
status=$?
set -e
printf '\n[process exit] %s\n' "$status" >> "$log"
rg -a 'Difftest enabled|bench |benchmark PASS|HIT GOOD TRAP|HIT BAD TRAP|ABORT|different at pc|instrCnt|Guest cycle|Host time' "$log" \
  | sed -E 's/\x1b\[[0-9;]*[[:alpha:]]//g' | tee -a "$summary" || true
printf '[process exit] %s\n' "$status" >> "$summary"
if (( status == 0 )); then
  python3 "$repo_dir/stage3/tests/analyze-bench.py" "$log" \
    --json-out "$repo_dir/stage3/logs/$run_id-bench.json" | tee -a "$summary" || status=$?
fi
printf '[completed] %s\n[exit] %d\n[full log] %s\n' "$(date --iso-8601=seconds)" "$status" "$log" | tee -a "$summary"
printf '%s\tvdot-benchmark\t%s\t%s\n' "$(date --iso-8601=seconds)" "$status" "$log" >> "$repo_dir/stage2/logs/operations.tsv"
if [[ -n "${VDOT_BENCH_RESULT_FILE:-}" ]]; then
  printf '%s\n' "$summary" >> "$VDOT_BENCH_RESULT_FILE"
fi
exit "$status"
