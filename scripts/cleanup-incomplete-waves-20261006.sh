#!/usr/bin/env bash
# 按用户授权仅清理两个已被替代的不完整 VCD，且只执行一次。
set -euo pipefail
repo_dir=/home/saintrikashy/riscv/xs-env/cie2026-skito-SKIProject
cd "$repo_dir"
targets=(
  stage2/waveform/20261006T021301-isolation-control.vcd
  stage3/logs/timer-probe-20261003.vcd
)
sizes=(5982650919 1955423664)
for i in 0 1; do
  path="$repo_dir/${targets[$i]}"
  [[ -f "$path" && ! -L "$path" ]]
  [[ "$(realpath -e -- "$path")" == "$path" ]]
  [[ "$(stat -c %s -- "$path")" == "${sizes[$i]}" ]]
done

# 核验替代波形确实成功，不能仅检查文件存在。
python3 -c 'import json,pathlib; a=json.loads(pathlib.Path("stage2/waveform/20261006T033620-isolation-control-resumed.vcd.control.json").read_text()); b=json.loads(pathlib.Path("stage3/logs/timer-probe-20261003-window2-audit.json").read_text()); assert a["architectural_status"]==a["control_status"]==b["status"]=="PASS"'
printf '%s\n' \
  '4f1109892278b5a5461d364a4e8b20fe82707395e15811a33d5a0ee5867ba8c4  stage2/waveform/20261006T033620-isolation-control-resumed.vcd' \
  '5098053cc076c28055da35110821ff766d4e53f9d3dd3f2e6616a040c8caf06d  stage3/logs/timer-probe-20261003-window2.vcd' \
  | sha256sum -c -

stamp="$(date +%Y%m%dT%H%M%S)"
manifest="stage2/logs/${stamp}-incomplete-wave-protected.sha256"
[[ ! -e "$manifest" ]]
sha256sum \
  stage2/waveform/20261006T033620-isolation-control-resumed.vcd \
  stage3/logs/timer-probe-20261003-window2.vcd \
  stage2/waveform/20261006T033620-isolation-control-resumed.vcd.control.json \
  stage3/logs/timer-probe-20261003-window2-audit.json \
  stage2/logs/20261006T033620-32-control-56444f54.full.log \
  stage2/logs/20261006T032902-383-control-56444f54.full.log \
  stage2/logs/20261003T152953-timer-probe-wave-window2.full.log \
  | tee "$manifest"
printf '[deleted-source fingerprints]\n'
sha256sum -- "${targets[@]}"
printf '[allocated bytes before]\n'
du -B1 -- "${targets[@]}"

rm -- \
  /home/saintrikashy/riscv/xs-env/cie2026-skito-SKIProject/stage2/waveform/20261006T021301-isolation-control.vcd \
  /home/saintrikashy/riscv/xs-env/cie2026-skito-SKIProject/stage3/logs/timer-probe-20261003.vcd
[[ ! -e "${targets[0]}" && ! -e "${targets[1]}" ]]
sha256sum -c "$manifest"
printf '[cleanup PASS] deleted only two incomplete VCDs; logical bytes=7938074583; protected=%s\n' "$manifest"
