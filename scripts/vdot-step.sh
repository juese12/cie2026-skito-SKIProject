#!/usr/bin/env bash
# 记录实际命令和退出结果，保留先前运行记录。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
step="${1:?usage: bash scripts/vdot-step.sh STEP COMMAND [ARG ...]}"
shift
[[ "$step" =~ ^[a-zA-Z0-9_-]+$ ]] || exit 2
mkdir -p "$repo_dir/stage2/logs"
stamp="$(date +%Y%m%dT%H%M%S)"
log="$repo_dir/stage2/logs/${stamp}-${step}.full.log"
{
  printf '[started] %s\n[cwd] %s\n[command] ' "$(date --iso-8601=seconds)" "$PWD"
  printf '%q ' "$@"
  printf '\n'
} | tee "$log"
set +e
"$@" 2>&1 | tee -a "$log" | sed -u '/^\[PERF \]/d'
status=${PIPESTATUS[0]}
set -e
printf '[completed] %s\n[exit] %s\n' "$(date --iso-8601=seconds)" "$status" | tee -a "$log"
printf '%s\t%s\t%s\t%s\n' "$(date --iso-8601=seconds)" "$step" "$status" "$(basename "$log")" >> "$repo_dir/stage2/logs/operations.tsv"
exit "$status"
