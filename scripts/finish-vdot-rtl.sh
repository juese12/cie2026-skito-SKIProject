#!/usr/bin/env bash
# 独立 firtool 完成后，继续执行原 Makefile 的 RTL 后处理。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
bash "$repo_dir/scripts/prepare-vdot-dramsim.sh"
cd "$NOOP_HOME"
test -s build/rtl/VDot8.sv
test -s build/rtl/SimTop.sv
test -s build/rtl/SimTop.sv.conf
bash "$repo_dir/scripts/vdot-step.sh" rtl-memory-models \
  ./scripts/gen_sep_mem.sh ./scripts/vlsi_mem_gen build/rtl/SimTop.sv.conf build/rtl
# 这些机械变换与 Makefile 中非 PLDM、
# 非 XPROP 的仿真路径一致；断言保留并接到 xs_assert_v2。
bash "$repo_dir/scripts/vdot-step.sh" rtl-assert-bindings \
  sed -i -e 's/$fatal/xs_assert_v2(`__FILE__, `__LINE__)/g' \
  -e "s/\$error(/\$fwrite(32'h80000002, /g" build/rtl/*.sv
bash "$repo_dir/scripts/vdot-step.sh" rtl-emu-cxx \
  make emu CONFIG=DefaultConfig NUM_CORES=1 WITH_DRAMSIM3=1 \
  WITH_CONSTANTIN=0 EMU_THREADS="${VDOT_EMU_THREADS:-0}" EMU_TRACE=1 -j2
