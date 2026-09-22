#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
wave_file="${1:-${repo_dir}/stage1/waveform/vector-add-vadd.vcd}"
log_file="${repo_dir}/stage1/logs/vector-add-wave-analysis.log"

if [[ ! -f "${wave_file}" ]]; then
  echo "wave file not found: ${wave_file}" >&2
  exit 1
fi

awk '
function bits_to_uint(bits,  i,result) {
  result = 0
  for (i = 1; i <= length(bits); i++) {
    result = result * 2 + (substr(bits, i, 1) == "1")
  }
  return result
}

function lane0_signed(bits,  lane,value) {
  lane = substr(bits, length(bits) - 31)
  value = bits_to_uint(lane)
  return value >= 2147483648 ? value - 4294967296 : value
}

function flush_cycle(  i,port,valid_name,wb,wb_valid_name) {
  if (time == "") return

  for (i = 1; i <= 5; i++) {
    port = ports[i]
    valid_name = "io_toExus_" port "_valid"
    if (value[id[valid_name]] == "1") {
      execution_count++
      printf "EXEC cycle=%s port=%s ready=%s fuOp=%s vsew=%s vlmul=%s src0_lane0=%d src1_lane0=%d\n", \
          time, port, value[id["io_toExus_" port "_ready"]], \
          value[id["io_toExus_" port "_bits_fuOpType"]], \
          value[id["io_toExus_" port "_bits_vpu_vsew"]], \
          value[id["io_toExus_" port "_bits_vpu_vlmul"]], \
          lane0_signed(value[id["io_toExus_" port "_bits_src_0"]]), \
          lane0_signed(value[id["io_toExus_" port "_bits_src_1"]])
    }
  }

  for (wb = 13; wb <= 17; wb++) {
    wb_valid_name = "io_fromWB_wbData_" wb "_valid"
    if (value[id[wb_valid_name]] == "1") {
      writeback_count++
      printf "WB   cycle=%s channel=%d result_lane0=%d\n", time, wb, \
          lane0_signed(value[id["io_fromWB_wbData_" wb "_bits_data_0"]])
    }
  }
}

BEGIN {
  header = 1
  ports[1] = "vf_2_0"
  ports[2] = "vf_1_1"
  ports[3] = "vf_1_0"
  ports[4] = "vf_0_1"
  ports[5] = "vf_0_0"
}

header && /^ *\$var / {
  id[$5] = $4
  next
}

/^ *\$enddefinitions/ {
  header = 0
  next
}

/^#/ {
  flush_cycle()
  time = substr($0, 2)
  next
}

!header {
  if (substr($0, 1, 1) == "b") {
    split($0, fields, " ")
    value[fields[2]] = substr(fields[1], 2)
  } else if ($0 !~ /^\$/ && length($0) > 1) {
    value[substr($0, 2)] = substr($0, 1, 1)
  }
}

END {
  flush_cycle()
  printf "SUMMARY execution_count=%d writeback_count=%d\n", execution_count, writeback_count
  if (execution_count != 10 || writeback_count != 10) exit 2
}
' "${wave_file}" | tee "${log_file}"
