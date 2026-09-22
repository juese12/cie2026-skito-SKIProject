#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xs_env_dir="$(cd "${repo_dir}/.." && pwd)"
log_file="${repo_dir}/stage1/logs/hello-build.log"

source "${xs_env_dir}/env.sh"
mkdir -p "$(dirname "${log_file}")"

{
  echo "[build] started: $(date --iso-8601=seconds)"
  echo "[build] repository: ${repo_dir}"
  echo "[build] AM_HOME: ${AM_HOME}"
  make -C "${repo_dir}/stage1/hello-xiangshan" ARCH=riscv64-xs
  echo "[build] image: ${repo_dir}/stage1/hello-xiangshan/build/cie2026-stage1-hello-riscv64-xs.bin"
  echo "[build] completed: $(date --iso-8601=seconds)"
} 2>&1 | tee "${log_file}"

