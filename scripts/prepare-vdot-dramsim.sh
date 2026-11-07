#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cmake="${VDOT_CMAKE:-cmake}"
command -v "$cmake" >/dev/null || { echo 'cmake missing: set VDOT_CMAKE to an installed/local executable'; exit 2; }
bash "$repo_dir/scripts/vdot-step.sh" dramsim3-prepare-configure \
  "$cmake" -S "$repo_dir/../DRAMsim3" -B "$repo_dir/../DRAMsim3/build" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCOSIM=ON
bash "$repo_dir/scripts/vdot-step.sh" dramsim3-prepare-build \
  "$cmake" --build "$repo_dir/../DRAMsim3/build" --target dramsim3 -j2
nm -C "$repo_dir/../DRAMsim3/build/libdramsim3.a" | rg ' T ComplexCoDRAMsim3::ComplexCoDRAMsim3' >/dev/null
