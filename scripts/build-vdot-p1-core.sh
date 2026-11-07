#!/usr/bin/env bash
# 独立整核构建按 Java/CHIRRTL、firtool、Verilator/C++ 顺序执行。
# 复用已验证的 COSIM 库，无需升级依赖或重新运行 cmake。
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/../env.sh"
build_dir="$NOOP_HOME/build/p1-oldvd"
rtl_dir="$build_dir/rtl"
firtool="${VDOT_FIRTOOL:-${HOME}/.cache/llvm-firtool/1.62.1/bin/firtool}"
test -x "$firtool"
test ! -e "$build_dir/emu" && test ! -e "$rtl_dir/SimTop.fir" || {
  echo 'P1 build artifacts already exist; inspect/resume the recorded step, do not overwrite'; exit 2;
}
test -s "$DRAMSIM3_HOME/build/libdramsim3.a"
nm -C "$DRAMSIM3_HOME/build/libdramsim3.a" | rg ' T ComplexCoDRAMsim3::ComplexCoDRAMsim3' >/dev/null
exec 9>"$repo_dir/stage3/logs/p1-build.lock"
flock -n 9 || { echo 'another P1 build is active'; exit 2; }
mkdir -p "$rtl_dir"
cd "$NOOP_HOME"
bash "$repo_dir/scripts/vdot-step.sh" p1-core-emit-chirrtl \
  mill -i -Djvm-xmx=10G -Djvm-xss=16m xiangshan.test.runMain top.SimTop \
  --target-dir "$rtl_dir" --config DefaultConfig --issue E.b --num-cores 1 \
  --with-dramsim3 --dump-fir --target chirrtl --enable-difftest --full-stacktrace
# SimTop 的 FileRegisters 将这些生成的接口文件写入 ./build。
# 使用与基线相同的配置；生成后再复制，避免误用生成前的旧文件。
cp -a -- "$NOOP_HOME/build/generated-src" "$build_dir/generated-src"
cp -- "$NOOP_HOME/build/chisel_db.cpp" "$NOOP_HOME/build/chisel_db.h" "$build_dir/"
bash "$repo_dir/scripts/vdot-step.sh" p1-core-firtool \
  "$firtool" "$rtl_dir/SimTop.fir" -warn-on-unprocessed-annotations \
  -output-annotation-file "$build_dir/circt.anno.json" --repl-seq-mem \
  --repl-seq-mem-file=SimTop.sv.conf -O=release --disable-annotation-unknown \
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none \
  --split-verilog -o="$rtl_dir"
bash "$repo_dir/scripts/vdot-step.sh" p1-core-memory-models \
  ./scripts/gen_sep_mem.sh ./scripts/vlsi_mem_gen "$rtl_dir/SimTop.sv.conf" "$rtl_dir"
bash "$repo_dir/scripts/vdot-step.sh" p1-core-assert-bindings \
  sed -i -e 's/$fatal/xs_assert_v2(`__FILE__, `__LINE__)/g' \
  -e "s/\$error(/\$fwrite(32'h80000002, /g" "$rtl_dir"/*.sv
bash "$repo_dir/scripts/vdot-step.sh" p1-core-emu-cxx \
  make -C "$NOOP_HOME/difftest" emu BUILD_DIR="$build_dir" RTL_DIR="$rtl_dir" \
  DESIGN_DIR="$NOOP_HOME" NUM_CORES=1 WITH_DRAMSIM3=1 WITH_CONSTANTIN=0 \
  EMU_THREADS=0 EMU_TRACE=1 -j2
sha256sum "$build_dir/emu"
