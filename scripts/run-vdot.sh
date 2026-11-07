#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xs_env_dir="$(cd "$repo_dir/.." && pwd)"
emu="${VDOT_EMU:-$xs_env_dir/XiangShan/build/emu}"
ref="${VDOT_REF_SO:-$xs_env_dir/NEMU/build/riscv64-nemu-interpreter-so}"
image="${VDOT_IMAGE:-$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-riscv64-xs.bin}"
stamp="$(date +%Y%m%dT%H%M%S)"
mkdir -p "$repo_dir/stage2/logs"
full="$repo_dir/stage2/logs/$stamp-vdot-run.full.log"
summary="$repo_dir/stage2/logs/$stamp-vdot-run.log"
for f in "$emu" "$ref" "$image"; do test -f "$f" || { echo "missing: $f"; exit 2; }; done
{
  printf '[started] %s\n' "$(date --iso-8601=seconds)"
  printf '[command] %q --diff=%q -i %q --max-cycles=10000000\n' "$emu" "$ref" "$image"
  sha256sum "$emu" "$ref" "$image"
} | tee "$summary"
set +e
"$emu" --diff="$ref" -i "$image" --max-cycles=10000000 "$@" > "$full" 2>&1
status=$?
set -e
rg -a 'Difftest enabled|vdot |HIT GOOD TRAP|HIT BAD TRAP|ABORT|different at pc|instrCnt|Guest cycle|Host time' "$full" \
  | sed -E 's/\x1b\[[0-9;]*[[:alpha:]]//g' | tee -a "$summary" || true
process_status="$status"
if ! rg -aq 'Difftest enabled' "$full" ||
   ! rg -aq 'vdot PASS:' "$full" ||
   ! rg -aq 'HIT GOOD TRAP' "$full" ||
   rg -aq 'HIT BAD TRAP|ABORT|vdot.*FAIL|different at pc' "$full"; then
  status=1
fi
printf '[process exit] %d\n[verification exit] %d\n' "$process_status" "$status" | tee -a "$summary"
printf '[completed] %s\n[exit] %d\n[full log] %s\n' "$(date --iso-8601=seconds)" "$status" "$full" | tee -a "$summary"
printf '%s\tvdot-run\t%s\t%s\n' "$(date --iso-8601=seconds)" "$status" "$(basename "$full")" >> "$repo_dir/stage2/logs/operations.tsv"
exit "$status"
