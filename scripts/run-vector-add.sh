#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
xs_env_dir="$(cd "${repo_dir}/.." && pwd)"
emu="${xs_env_dir}/XiangShan/build/emu"
ref_so="${xs_env_dir}/XiangShan/ready-to-run/riscv64-nemu-interpreter-so"
image="${repo_dir}/stage1/vector-add/build/cie2026-stage1-vector-add-riscv64-xs.bin"
log_file="${repo_dir}/stage1/logs/vector-add-run.log"
full_log_file="${repo_dir}/stage1/logs/vector-add-run.full.log"

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
  grep -aE "Difftest enabled|vector-add|HIT GOOD TRAP|HIT BAD TRAP|instrCnt|Guest cycle spent|Host time spent" "${full_log_file}" \
    | sed -E $'s/\r$//; s/\x1b\\[[0-9;]*[[:alpha:]]//g'
  echo "[run] exit status: ${emu_status}"
  echo "[run] completed: ${completed_at}"
} | tee "${log_file}"

if ! grep -aFq "vector-add PASS" "${full_log_file}"; then
  echo "vector-add PASS marker not found" >&2
  exit 1
fi

if ! grep -aFq "HIT GOOD TRAP" "${full_log_file}"; then
  echo "HIT GOOD TRAP marker not found" >&2
  exit 1
fi

exit "${emu_status}"
