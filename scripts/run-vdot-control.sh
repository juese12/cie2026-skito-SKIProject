#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
emu="${VDOT_EMU:-$repo_dir/../XiangShan/build/operand-isolation/emu}"
ref="${VDOT_REF_SO:-$repo_dir/../NEMU/build/riscv64-nemu-interpreter-so}"
seed="${CONTROL_SEED_HEX:-56444f54}"
[[ "$seed" =~ ^[0-9a-f]{8}$ ]] || { echo 'CONTROL_SEED_HEX must be eight lowercase hex digits'; exit 2; }
image="${VDOT_IMAGE:-$repo_dir/stage2/control-tests/build/cie2026-stage2-control-seed$seed-riscv64-xs.bin}"
# 控制审核读取稳定低相位；模拟器 --dump-wave 只记录上升沿，
# 因此必须在记录命令和运行之前将波形选项规范化。
control_args=()
for control_arg in "$@"; do
  if [[ "$control_arg" == --dump-wave ]]; then control_args+=(--dump-wave-full)
  else control_args+=("$control_arg"); fi
done
set -- "${control_args[@]}"
for f in "$emu" "$ref" "$image"; do test -s "$f" || { echo "missing: $f"; exit 2; }; done
mkdir -p "$repo_dir/stage2/logs"
stamp="$(date +%Y%m%dT%H%M%S)-$$"
full="$repo_dir/stage2/logs/$stamp-control-$seed.full.log"
summary="$repo_dir/stage2/logs/$stamp-control-$seed.log"
{
  printf '[started] %s\n' "$(date --iso-8601=seconds)"
  printf '[command] %q --diff=%q -i %q --max-cycles=10000000 ' "$emu" "$ref" "$image"
  printf '%q ' "$@"; printf '\n'
  sha256sum "$emu" "$ref" "$image"
} | tee "$summary"
set +e
"$emu" --diff="$ref" -i "$image" --max-cycles=10000000 "$@" > "$full" 2>&1
process_status=$?
set -e
printf '\n[process exit] %d\n' "$process_status" >> "$full"
rg -a 'Difftest enabled|control |HIT GOOD TRAP|HIT BAD TRAP|ABORT|different at pc|instrCnt|Guest cycle|Host time' "$full" | sed -E 's/\x1b\[[0-9;]*[[:alpha:]]//g' | tee -a "$summary" || true
status="$process_status"
if ! python3 "$repo_dir/scripts/check-vdot-control.py" "$full" --seed "$seed" --json-out "$full.architectural.json" | tee -a "$summary"; then status=1; fi
printf '[process exit] %d\n[verification exit] %d\n[completed] %s\n[full log] %s\n' \
  "$process_status" "$status" "$(date --iso-8601=seconds)" "$full" | tee -a "$summary"
printf '%s\tcontrol-%s\t%s\t%s\n' "$(date --iso-8601=seconds)" "$seed" "$status" "$(basename "$full")" >> "$repo_dir/stage2/logs/operations.tsv"
exit "$status"
