#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$repo_dir/scripts/vdot-step.sh" core-wave-audit \
  python3 "$repo_dir/stage2/tests/check-core-wave.py" "$@"

