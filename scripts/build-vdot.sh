#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
bash "$repo_dir/scripts/vdot-step.sh" software-build make -C "$repo_dir/stage2/vdot-tests" ARCH=riscv64-xs
