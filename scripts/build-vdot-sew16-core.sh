#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --check ) ]] || {
  echo 'usage: bash scripts/build-vdot-sew16-core.sh [--check]' >&2; exit 2;
}
source "$repo_dir/../env.sh"
build_dir="$NOOP_HOME/build/sew16-fixed8"
rtl_dir="$build_dir/rtl"
firtool="${VDOT_FIRTOOL:-${HOME}/.cache/llvm-firtool/1.62.1/bin/firtool}"
for tool in mill make verilator java flock; do command -v "$tool" >/dev/null; done
test -x "$firtool" || { echo "firtool is not executable: $firtool" >&2; exit 2; }
for file in \
  "$NOOP_HOME/src/main/scala/xiangshan/backend/fu/vector/VDot8.scala" \
  "$NOOP_HOME/src/main/scala/xiangshan/backend/fu/wrapper/VIMacU.scala" \
  "$NOOP_HOME/src/main/scala/xiangshan/backend/decode/VecExceptionGen.scala" \
  "$NOOP_HOME/difftest/verilator.mk" "$DRAMSIM3_HOME/build/libdramsim3.a"; do
  test -s "$file" || { echo "missing build input: $file" >&2; exit 2; }
done
bash "$repo_dir/scripts/prepare-vdot-difftest.sh" --check
if [[ "${1:-}" == --check ]]; then
  echo '[sew16 build preflight PASS; no compilation started]'
  exit 0
fi
test ! -e "$build_dir/emu" && test ! -e "$rtl_dir/SimTop.fir" || {
  echo 'sew16 artifacts exist; inspect recorded stage before resuming'; exit 2;
}
mkdir -p "$repo_dir/stage2/logs"
exec 9>"$repo_dir/stage2/logs/sew16-build.lock"
flock -n 9 || exit 2
mkdir -p "$rtl_dir"
cd "$NOOP_HOME"
sha256sum src/main/scala/xiangshan/backend/fu/vector/VDot8.scala \
  src/main/scala/xiangshan/backend/fu/wrapper/VIMacU.scala \
  src/main/scala/xiangshan/backend/decode/VecExceptionGen.scala \
  "$NOOP_HOME/difftest/verilator.mk" \
  "$DRAMSIM3_HOME/build/libdramsim3.a" > "$build_dir/inputs.sha256"
bash "$repo_dir/scripts/vdot-step.sh" sew16-core-chirrtl \
  mill -i -Djvm-xmx=10G -Djvm-xss=16m xiangshan.test.runMain top.SimTop \
  --target-dir "$rtl_dir" --config DefaultConfig --issue E.b --num-cores 1 \
  --with-dramsim3 --dump-fir --target chirrtl --enable-difftest --full-stacktrace
cp -a -- "$NOOP_HOME/build/generated-src" "$build_dir/generated-src"
cp -- "$NOOP_HOME/build/chisel_db.cpp" "$NOOP_HOME/build/chisel_db.h" "$build_dir/"
bash "$repo_dir/scripts/vdot-step.sh" sew16-core-firtool \
  "$firtool" "$rtl_dir/SimTop.fir" -warn-on-unprocessed-annotations \
  -output-annotation-file "$build_dir/circt.anno.json" --repl-seq-mem \
  --repl-seq-mem-file=SimTop.sv.conf -O=release --disable-annotation-unknown \
  --lowering-options=explicitBitcast,disallowLocalVariables,disallowPortDeclSharing,locationInfoStyle=none \
  --split-verilog -o="$rtl_dir"
bash "$repo_dir/scripts/vdot-step.sh" sew16-core-memory \
  ./scripts/gen_sep_mem.sh ./scripts/vlsi_mem_gen "$rtl_dir/SimTop.sv.conf" "$rtl_dir"
bash "$repo_dir/scripts/vdot-step.sh" sew16-core-assert \
  sed -i -e 's/$fatal/xs_assert_v2(`__FILE__, `__LINE__)/g' \
  -e "s/\$error(/\$fwrite(32'h80000002, /g" "$rtl_dir"/*.sv
bash "$repo_dir/scripts/vdot-step.sh" sew16-core-cxx \
  make -C "$NOOP_HOME/difftest" emu BUILD_DIR="$build_dir" RTL_DIR="$rtl_dir" \
  DESIGN_DIR="$NOOP_HOME" NUM_CORES=1 WITH_DRAMSIM3=1 WITH_CONSTANTIN=0 \
  EMU_THREADS=0 EMU_TRACE=0 -j2
sha256sum -c "$build_dir/inputs.sha256"
sha256sum "$build_dir/emu"
echo '[sew16 build COMPLETE]'
