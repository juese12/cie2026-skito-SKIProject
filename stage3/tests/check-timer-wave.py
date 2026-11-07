#!/usr/bin/env python3
"""流式审核真实整核 VCD 中 CSR 写的排空、阻塞及 mcycle 读取顺序。"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def need(value, message):
    if not value: raise ValueError(message)


def check(wave, log):
    scope, signals, values = [], {}, {}
    dispatch = "TOP.SimTop.l_soc.core_with_l2.core.backend.inner_ctrlBlock.dispatch."
    rob = "TOP.SimTop.l_soc.core_with_l2.core.backend.inner_ctrlBlock.rob."
    csr = "TOP.SimTop.l_soc.core_with_l2.core.backend.inner_intExuBlock.exus_7.csr."
    selected, pending, events = set(), {}, []
    time, old_clock, blocked_cycles, markers = 0, None, 0, 0

    def get(name):
        value = values.get(signals[name])
        need(value is not None, f"unknown signal: {name} at {time}")
        return value

    def sample():
        nonlocal old_clock, blocked_cycles, markers
        clock = get("TOP.clock")
        falling = old_clock == 1 and clock == 0
        old_clock = clock
        if not falling: return
        accept = get(dispatch+"io_enqRob_canAccept")
        if get(rob+"hasBlockBackward"):
            blocked_cycles += 1
            need(not accept, f"younger enqueue allowed while blocked at {time}")
        active = [i for i in range(6) if accept and get(dispatch+f"io_enqRob_req_{i}_valid")]
        for i in active:
            prefix = dispatch+f"io_enqRob_req_{i}_bits_"
            inst = get(prefix+"instr")
            if inst & 0x7f != 0x73: continue
            tag = (get(prefix+"robIdx_flag"), get(prefix+"robIdx_value"))
            entry = dict(dispatch_time=time, pc=hex(get(prefix+"pc")), inst=hex(inst), tag=list(tag))
            pending[tag] = entry
            if inst == 0x00805073:
                markers += 1
                need(get(prefix+"waitForward") and get(prefix+"blockBackward"), "marker lost serial flags")
                need(get(dispatch+"io_enqRob_isEmpty"), f"marker entered nonempty ROB at {time}")
                need(active == [i], f"marker admitted with older/younger instructions at {time}")
                entry["rob_empty_at_dispatch"] = True
                events.append(entry)
        if get(csr+"io_out_valid"):
            tag = (get(csr+"io_out_bits_ctrl_robIdx_flag"), get(csr+"io_out_bits_ctrl_robIdx_value"))
            entry = pending.pop(tag, None)
            if entry is not None:
                entry["output_time"] = time
                entry["data"] = get(csr+"io_out_bits_res_data")
                if entry["inst"] in (hex(0xb0002373), hex(0xb0002e73)): events.append(entry)

    with Path(wave).open(encoding="ascii") as stream:
        header = True
        for raw in stream:
            line = raw.strip()
            if header:
                fields = line.split()
                if line.startswith("$scope"): scope.append(fields[2])
                elif line.startswith("$upscope"): scope.pop()
                elif line.startswith("$var"): signals[".".join(scope+[fields[4]])] = fields[3]
                elif line.startswith("$enddefinitions"):
                    header = False
                    required = ["TOP.clock", dispatch+"io_enqRob_canAccept", dispatch+"io_enqRob_isEmpty", rob+"hasBlockBackward",
                                csr+"io_out_valid", csr+"io_out_bits_ctrl_robIdx_flag", csr+"io_out_bits_ctrl_robIdx_value", csr+"io_out_bits_res_data"]
                    for i in range(6):
                        required += [dispatch+f"io_enqRob_req_{i}_valid"]
                        required += [dispatch+f"io_enqRob_req_{i}_bits_"+name for name in ("instr","pc","robIdx_flag","robIdx_value","waitForward","blockBackward")]
                    need(all(name in signals for name in required), "missing actual CPU timer/ROB hierarchy")
                    selected = {signals[name] for name in required}
                continue
            if line.startswith("#"):
                if values: sample()
                time = int(line[1:])
            elif line.startswith("b"):
                bits, code = line[1:].split()
                if code in selected: values[code] = None if any(c in bits.lower() for c in "xz") else int(bits,2)
            elif line and line[0] in "01xz":
                if line[1:] in selected: values[line[1:]] = int(line[0]) if line[0] in "01" else None
    sample()
    text = Path(log).read_text(errors="replace")
    # UART 字符与逐指令提交行共用标准输出；只删除
    # 格式完整的提交记录及宿主换行符，
    # 重新连接 UART 文本，同时保留原日志、校验记录和失败信息。
    text = re.sub(r"\[\d{2}\] commit pc [0-9a-f]+ inst [0-9a-f]+ wen \d+ dst \d+ data [0-9a-f]+ idx [0-9a-f]+[^\n]*\n", "", text)
    need("Difftest enabled" in text and "HIT GOOD TRAP" in text and "timer probe PASS:" in text, "probe did not pass full-core test")
    need(re.findall(r"^\[exit\] (\d+)$", text, re.M) == ["0"], "missing recorded zero exit")
    need(not re.search(r"HIT BAD TRAP|ABORT|different at pc", text), "difftest failure")
    samples = re.findall(r"timer probe kind=(\d+) impl=(\d+) cycles=(\d+)", text)
    need([(k,i) for k,i,c in samples] == [(str(k),str(i)) for k in range(3) for i in range(2)], "need all six probe outputs")
    starts = [e for e in events if e["inst"] == hex(0xb0002373)]
    ends = [e for e in events if e["inst"] == hex(0xb0002e73)]
    need(len(starts) == len(ends) == 6, f"window must cover six complete timed calls: starts={len(starts)} ends={len(ends)} markers={markers}; observed={events}")
    pairs=[]
    for start,end,(kind,impl,cycles) in zip(starts,ends,samples):
        inside = [e for e in events if e["inst"] == hex(0x00805073) and start["dispatch_time"] < e["dispatch_time"] < end["dispatch_time"]]
        need(len(inside)==2, "need start/end CSR-write markers within each pair")
        need(start["output_time"] < inside[0]["dispatch_time"], "start marker preceded timestamp completion")
        need("output_time" in inside[1] and inside[1]["output_time"] < end["dispatch_time"], "end read preceded marker completion")
        delta=(end["data"]-start["data"]) & ((1<<64)-1)
        need(delta==int(cycles), "waveform timestamp delta differs from program")
        pairs.append(dict(kind=int(kind),impl=int(impl),cycles=delta,start=start,end=end,markers=inside))
    need(blocked_cycles>0 and markers>=18, "no complete serial boundary evidence")
    with Path(wave).open("rb") as stream: wave_hash=hashlib.file_digest(stream,"sha256").hexdigest()
    return dict(status="PASS", wave_sha256=wave_hash, log_sha256=hashlib.sha256(Path(log).read_bytes()).hexdigest(),
                checked_pairs=pairs, checked_markers=markers, blocked_low_phases=blocked_cycles,
                boundary="CSR dispatch drain/block and timestamp output order; NOT DRAM store durability, wrong-path proof or PPA")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wave"); parser.add_argument("log"); parser.add_argument("--json-out")
    args=parser.parse_args()
    try:
        result=check(args.wave,args.log)
        if args.json_out:
            with Path(args.json_out).open("x") as stream: stream.write(json.dumps(result,indent=2)+"\n")
        print(json.dumps(result,indent=2))
    except (ValueError,OSError,KeyError) as error: parser.exit(1,f"timer waveform FAIL: {error}\n")
