#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_dir/../env.sh"
make -C "$project_dir/stage3/int8-gemv" ARCH=riscv64-xs "$@"
