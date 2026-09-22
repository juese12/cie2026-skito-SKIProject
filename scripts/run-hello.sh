#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xs_env_dir="$(cd "${repo_dir}/.." && pwd)"
emu="${xs_env_dir}/XiangShan/build/emu"
ref_so="${xs_env_dir}/XiangShan/ready-to-run/riscv64-nemu-interpreter-so"
image="${repo_dir}/stage1/hello-xiangshan/build/cie2026-stage1-hello-riscv64-xs.bin"
log_file="${repo_dir}/stage1/logs/hello-run.log"
full_log_file="${repo_dir}/stage1/logs/hello-run.full.log"

for required_file in "${emu}" "${ref_so}" "${image}"; do
  if [[ ! -f "${required_file}" ]]; then
    echo "missing required file: ${required_file}" >&2
    exit 1
  fi
done

started_at="$(date --iso-8601=seconds)"
if "${emu}" --diff="${ref_so}" -i "${image}" >"${full_log_file}" 2>&1; then
  emu_status=0
else
  emu_status=$?
fi
completed_at="$(date --iso-8601=seconds)"

{
  echo "[run] started: ${started_at}"
  echo "[run] emulator: ${emu}"
  echo "[run] reference: ${ref_so}"
  echo "[run] image: ${image}"
  echo "[run] key output:"
  grep -aE "Difftest enabled|hello xiangshan|HIT GOOD TRAP|instrCnt|Guest cycle spent|Host time spent" "${full_log_file}" \
    | sed -E $'s/\x1b\\[[0-9;]*[[:alpha:]]//g'
  echo "[run] exit status: ${emu_status}"
  echo "[run] completed: ${completed_at}"
} | tee "${log_file}"

exit "${emu_status}"
