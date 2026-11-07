#!/usr/bin/env bash
# 为限制内存峰值，先完成 Java，再启动独立的 firtool 进程。
# 此处提供仅生成 CHIRRTL 的重建路径；首次留存的构建
# 使用中断的集成构建已经生成的完整 FIR 文件。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
firtool="${VDOT_FIRTOOL:-${HOME}/.cache/llvm-firtool/1.62.1/bin/firtool}"
test -x "$firtool" || { echo "set VDOT_FIRTOOL to firtool 1.62.1"; exit 2; }
bash "$repo_dir/scripts/prepare-vdot-dramsim.sh"
cd "$NOOP_HOME"
bash "$repo_dir/scripts/vdot-step.sh" rtl-emit-chirrtl \
  mill -i -Djvm-xmx=10G -Djvm-xss=16m xiangshan.test.runMain top.SimTop \
  --target-dir build/rtl --config DefaultConfig --issue E.b --num-cores 1 \
  --with-dramsim3 --dump-fir --target chirrtl --enable-difftest --full-stacktrace
bash "$repo_dir/scripts/vdot-step.sh" rtl-firtool-separated \
  "$firtool" build/rtl/SimTop.fir -warn-on-unprocessed-annotations \
  -output-annotation-file circt.anno.json --repl-seq-mem \
  --repl-seq-mem-file=SimTop.sv.conf -O=release --disable-annotation-unknown \
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none \
  --split-verilog -o=build/rtl
bash "$repo_dir/scripts/finish-vdot-rtl.sh"
