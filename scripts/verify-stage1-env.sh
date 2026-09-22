#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xs_env_dir="$(cd "${repo_dir}/.." && pwd)"
log_file="${repo_dir}/stage1/logs/environment-check.log"
failed=0

check_command() {
  local command_name="$1"
  if command -v "${command_name}" >/dev/null 2>&1; then
    echo "PASS command ${command_name}: $(command -v "${command_name}")"
  else
    echo "FAIL command ${command_name}: not found"
    failed=1
  fi
}

check_file() {
  local file_path="$1"
  if [[ -f "${file_path}" ]]; then
    echo "PASS file: ${file_path}"
  else
    echo "FAIL file: ${file_path}"
    failed=1
  fi
}

{
  echo "[environment] checked: $(date --iso-8601=seconds)"
  echo "[environment] host IPv4: $(hostname -I | xargs)"
  check_command git
  check_command gcc
  check_command clang
  check_command java
  check_command verilator
  check_command riscv64-linux-gnu-gcc
  check_file "${xs_env_dir}/env.sh"
  check_file "${xs_env_dir}/XiangShan/build/emu"
  check_file "${xs_env_dir}/XiangShan/ready-to-run/riscv64-nemu-interpreter-so"
  check_file "${xs_env_dir}/nexus-am/Makefile.app"
  echo "xs-env commit: $(git -C "${xs_env_dir}" rev-parse HEAD)"
  echo "XiangShan commit: $(git -C "${xs_env_dir}/XiangShan" rev-parse HEAD)"
  echo "NEMU commit: $(git -C "${xs_env_dir}/NEMU" rev-parse HEAD)"
  echo "nexus-am commit: $(git -C "${xs_env_dir}/nexus-am" rev-parse HEAD)"
  if [[ "${failed}" -eq 0 ]]; then
    echo "ENVIRONMENT CHECK PASS"
  else
    echo "ENVIRONMENT CHECK FAIL"
  fi
} 2>&1 | tee "${log_file}"

exit "${failed}"
