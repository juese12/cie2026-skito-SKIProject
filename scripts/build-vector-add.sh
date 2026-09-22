#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xs_env_dir="$(cd "${repo_dir}/.." && pwd)"
log_file="${repo_dir}/stage1/logs/vector-add-build.log"

source "${xs_env_dir}/env.sh"

{
  echo "[build] started: $(date --iso-8601=seconds)"
  echo "[build] MARCH: rv64gcv_zba"
  make -C "${repo_dir}/stage1/vector-add" ARCH=riscv64-xs
  echo "[build] image: ${repo_dir}/stage1/vector-add/build/cie2026-stage1-vector-add-riscv64-xs.bin"
  echo "[build] completed: $(date --iso-8601=seconds)"
} 2>&1 | tee "${log_file}"
