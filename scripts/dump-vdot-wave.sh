#!/usr/bin/env bash
# 由调用者选择实测窗口，不能沿用旧向量加法窗口。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
begin="${1:?usage: dump-vdot-wave.sh BEGIN END [WAVE_PATH]}"
end="${2:?usage: dump-vdot-wave.sh BEGIN END [WAVE_PATH]}"
[[ "$begin" =~ ^[0-9]+$ && "$end" =~ ^[0-9]+$ ]] || exit 2
(( end >= begin )) || exit 2
mkdir -p "$repo_dir/stage2/waveform"
wave="${3:-$repo_dir/stage2/waveform/vdot-core-$(date +%Y%m%dT%H%M%S).vcd}"
test ! -e "$wave" || { echo "refusing to overwrite: $wave"; exit 2; }
VDOT_IMAGE="${VDOT_IMAGE:-$repo_dir/stage2/vdot-tests/build/cie2026-stage2-vdot-smoke-riscv64-xs.bin}" \
  bash "$repo_dir/scripts/run-vdot.sh" --dump-wave-full --wave-path="$wave" \
  --dump-commit-trace --log-begin="$begin" --log-end="$end"
test -s "$wave"
sha256sum "$wave"
