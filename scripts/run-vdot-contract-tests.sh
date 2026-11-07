#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --check ) ]] || {
  echo 'usage: bash scripts/run-vdot-contract-tests.sh [--check]' >&2; exit 2;
}
emu="$repo_dir/../XiangShan/build/sew16-fixed8/emu"
ref="$repo_dir/../NEMU/build/sew16/riscv64-nemu-interpreter-so"
# 两个镜像全部检查完才启动第一个进程；不回退到历史平铺镜像。
declare -A images
for kind in functional control; do
  images[$kind]="$(make --no-print-directory -s -C "$repo_dir/stage2/contract-tests" \
    ARCH=riscv64-xs KIND="$kind" RANDOM_CASES=0 CONTROL_SEED=0x56444f54 print-image)"
  for file in "$emu" "$ref" "${images[$kind]}"; do
    test -s "$file" || {
      echo "missing regression input: $file" >&2
      echo "build images with: make -C stage2/contract-tests ARCH=riscv64-xs KIND=$kind RANDOM_CASES=0 CONTROL_SEED=0x56444f54" >&2
      exit 2
    }
  done
done
test -x "$emu"
if [[ "${1:-}" == --check ]]; then
  printf '[contract input READY] %s\n' "${images[functional]}" "${images[control]}"
  exit 0
fi
mkdir -p "$repo_dir/stage2/logs"
exec 9>"$repo_dir/stage2/logs/contract-regression.lock"
flock -n 9 || exit 2
cd "$repo_dir"
stamp="$(date +%Y%m%dT%H%M%S)"
for kind in functional control; do
  image="${images[$kind]}"
  log="$repo_dir/stage2/logs/$stamp-contract-$kind.full.log"
  sha256sum "$emu" "$ref" "$image" > "$log.inputs.sha256"
  printf '[contract running] %s %s\n' "$kind" "$log"
  set +e
  "$emu" --diff="$ref" -i "$image" --max-cycles=2000000 --seed=101 > "$log" 2>&1
  status=$?
  set -e
  printf '\n[process exit] %d\n' "$status" >> "$log"
  test "$status" -eq 0
  rg -aq 'Difftest enabled' "$log"
  rg -aq 'HIT GOOD TRAP' "$log"
  ! rg -aq 'FAIL|HIT BAD TRAP|ABORT|different at pc' "$log"
  if [[ "$kind" == functional ]]; then
    rg -aq 'vdot contract=e8-e16 unsupported=e32' "$log"
    rg -aq 'vdot e16 legal PASS: cases=32 exact64=1 upper64=0' "$log"
    rg -aq 'vdot PASS: valid=52 illegal=10;' "$log"
  else
    rg -aq 'control contract=e8-e16 unsupported=e32/e64' "$log"
    python3 scripts/check-vdot-control.py "$log" --seed 56444f54 --json-out "$log.architectural.json"
  fi
  sha256sum -c "$log.inputs.sha256"
  printf '[contract PASS] %s\n' "$kind"
done
echo '[contract regression COMPLETE]'
