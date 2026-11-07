#!/usr/bin/env python3
"""按 ROB 标签将真实整核 IQ 就绪状态与分派、结果关联。

此处证明源未就绪导致的阻塞，不证明其他全部发射资源
必然会选择该 uop，也不构成完整错误路径或功耗证明。
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

BASE = "TOP.SimTop.l_soc.core_with_l2.core.backend."
DISPATCH = BASE + "inner_ctrlBlock.dispatch."
IQ = BASE + "inner_vfScheduler.IssueQueueVfmaVialuFixVimacVppuVfaluVfcvtVipuVsetrvfwvf.entries."
FU = BASE + "inner_vfExuBlock.exus.Vimac."


def need(ok, message):
    if not ok:
        raise ValueError(message)


def audit_log(path):
    raw = Path(path).read_bytes()
    text = raw.decode(errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\[\d{2}\] commit pc [0-9a-f]+ inst [0-9a-f]+ wen \d+ dst \d+ data [0-9a-f]+ idx [0-9a-f]+[^\n]*\n", "", text)
    need("Difftest enabled" in text and "HIT GOOD TRAP" in text and
         "oldvd probe PASS: 48 calls" in text, "missing full-core PASS")
    need(not re.search(r"HIT BAD TRAP|ABORT|different at pc|oldvd probe FAIL", text), "core failure")
    need(re.findall(r"^\[exit\] (\d+)$", text, re.M) == ["0"], "missing actual zero exit")
    rows = re.findall(r"oldvd sample policy=(\d+) kind=(\d+) rep=(\d+) dots=32 cycles=(\d+)", text)
    expected = [(p,k,r) for p in range(4) for k in range(6) for r in range(2)]
    need([tuple(map(int,row[:3])) for row in rows] == expected, "incomplete/duplicate samples")
    return dict(log_sha256=hashlib.sha256(raw).hexdigest(),
                samples=[dict(policy=int(p),kind=int(k),rep=int(r),cycles=int(c)) for p,k,r,c in rows])


def check(wave, log, minimum_false_wait=1):
    result = audit_log(log) if log is not None else dict(diagnostic=True)
    scope, signals, values = [], {}, {}
    selected, entries = set(), []
    records, current, writers = [], {}, {}
    time, old_clock, call = 0, None, -1

    def get(name):
        value = values.get(signals[name])
        need(value is not None, f"unknown {name} at {time}")
        return value

    def sample():
        nonlocal old_clock, call
        clock = get("TOP.clock")
        falling = old_clock == 1 and clock == 0
        old_clock = clock
        if not falling:
            return
        if get(DISPATCH+"io_enqRob_canAccept"):
            for i in range(6):
                pre = DISPATCH+f"io_enqRob_req_{i}_bits_"
                if not get(DISPATCH+f"io_enqRob_req_{i}_valid"):
                    continue
                inst = get(pre+"instr")
                tag = (get(pre+"robIdx_flag"),get(pre+"robIdx_value"))
                if inst == 0xb0002373:  # 每次调用执行一次 csrr t1,mcycle。
                    call += 1
                vd, vs1, vs2 = (inst >> 7) & 31, (inst >> 15) & 31, (inst >> 20) & 31
                producer = writers.get(vd)
                if inst & 0xfc00707f == 0x0000200b:
                    rec = dict(index=len(records),tag=list(tag),call=call,pc=hex(get(pre+"pc")),
                               vd=vd,vs1=vs1,vs2=vs2,dispatch_time=time,
                               producer=producer,wait_phases=[],false_wait_phases=[],example=None)
                    records.append(rec)
                    current[tag] = rec
                else:
                    current.pop(tag,None)
                if get(pre+"vecWen") or get(pre+"v0Wen"):
                    writers[vd] = dict(tag=list(tag),pc=hex(get(pre+"pc")),pdest=get(pre+"pdest"))
        for entry in entries:
            if not get(entry+"io_commonOut_valid") or get(entry+"entryReg_payload_fuOpType") != 0x160:
                continue
            pre = entry+"entryReg_status_"
            tag = (get(pre+"robIdx_flag"),get(pre+"robIdx_value"))
            rec = current.get(tag)
            if rec is None or "output_time" in rec:
                continue
            states = [get(pre+f"srcStatus_{j}_srcState") for j in range(5)]
            types = [get(pre+f"srcStatus_{j}_srcType") for j in range(5)]
            regs = [get(pre+f"srcStatus_{j}_psrc") for j in range(5)]
            if "source_observation" not in rec:
                rec["source_observation"] = dict(time=time,entry=entry,states=states,
                                                  types=types,psrc=regs)
            blocked = [j for j,s in enumerate(states) if not s]
            # 尚未发射或重试；使用实际 IQ 发射资格，
            # 不能根据指令名或总耗时猜测。
            if blocked and not get(pre+"issued") and not get(pre+"blocked"):
                need(not get(entry+"io_commonOut_canIssue"), "not-ready source but eligible")
                if time not in rec["wait_phases"]:
                    rec["wait_phases"].append(time)
                independent = rec["vd"] not in (rec["vs1"],rec["vs2"])
                only_old = set(blocked) <= ({2,3} if rec["vd"] == 0 else {2})
                if independent and only_old:
                    need(rec["producer"] is not None, "old-source wait without known producer")
                    need(rec["producer"]["pdest"] in [regs[j] for j in blocked],
                         "blocking physical source does not match old destination producer")
                    if time not in rec["false_wait_phases"]:
                        rec["false_wait_phases"].append(time)
                    if rec["example"] is None:
                        rec["example"] = dict(time=time,entry=entry,states=states,types=types,
                                              psrc=regs,blocked_sources=blocked,
                                              vta=get(entry+"entryReg_payload_vpu_vta"))
        if get(FU+"io_out_valid") and get(FU+"io_in_bits_ctrlPipe_2_fuOpType") == 0x160:
            tag = (get(FU+"io_out_bits_ctrl_robIdx_flag"),get(FU+"io_out_bits_ctrl_robIdx_value"))
            rec = current.get(tag)
            if rec is not None:
                need("output_time" not in rec, "duplicate execution output")
                rec["output_time"] = time
                rec["result"] = get(FU+"io_out_bits_res_data")

    with Path(wave).open(encoding="ascii") as stream:
        header = True
        for raw in stream:
            line = raw.strip()
            if header:
                fields = line.split()
                if line.startswith("$scope"):
                    scope.append(fields[2])
                elif line.startswith("$upscope"):
                    scope.pop()
                elif line.startswith("$var"):
                    signals[".".join(scope+[fields[4]])] = fields[3]
                elif line.startswith("$enddefinitions"):
                    header = False
                    entries = sorted({n.removesuffix("io_commonOut_valid") for n in signals
                                      if n.startswith(IQ) and ".othersEntries" in n
                                      and n.endswith(".io_commonOut_valid")})
                    need(entries, "missing actual Vimac issue queue")
                    required = ["TOP.clock",DISPATCH+"io_enqRob_canAccept",FU+"io_out_valid",
                                FU+"io_in_bits_ctrlPipe_2_fuOpType",FU+"io_out_bits_ctrl_robIdx_flag",
                                FU+"io_out_bits_ctrl_robIdx_value",FU+"io_out_bits_res_data"]
                    for i in range(6):
                        required += [DISPATCH+f"io_enqRob_req_{i}_valid"]
                        required += [DISPATCH+f"io_enqRob_req_{i}_bits_"+n
                                     for n in ("instr","pc","robIdx_flag","robIdx_value","vecWen","v0Wen","pdest")]
                    for entry in entries:
                        required += [entry+n for n in ("io_commonOut_valid","io_commonOut_canIssue",
                                     "entryReg_payload_fuOpType","entryReg_payload_vpu_vta")]
                        required += [entry+"entryReg_status_"+n for n in ("robIdx_flag","robIdx_value","issued","blocked")]
                        required += [entry+f"entryReg_status_srcStatus_{j}_"+n for j in range(5)
                                     for n in ("srcState","srcType","psrc")]
                    missing = [n for n in required if n not in signals]
                    need(not missing, f"missing IQ/dispatch/FU signals: {missing[:5]}")
                    selected = {signals[n] for n in required}
                continue
            if line.startswith("#"):
                if values:
                    sample()
                time = int(line[1:])
            elif line.startswith("b"):
                bits,code = line[1:].split()
                if code in selected:
                    values[code] = None if any(c in bits.lower() for c in "xz") else int(bits,2)
            elif line and line[0] in "01xz" and line[1:] in selected:
                values[line[1:]] = int(line[0]) if line[0] in "01" else None
    sample()
    completed = [r for r in records if "output_time" in r]
    for rec in completed:
        need(0 <= rec["call"] < 48, "execution outside known probe calls")
        kind = (rec["call"] % 12) // 2
        need(rec["result"] == (0 if kind in (3,5) else 16), "incorrect full128 execution result")
    false = [r for r in completed if r["false_wait_phases"]]
    need(len(false) >= minimum_false_wait, f"only {len(false)} proven false-wait uops")
    need(completed, "no correlated vdot outputs")
    with Path(wave).open("rb") as stream:
        wave_hash = hashlib.file_digest(stream,"sha256").hexdigest()
    result.update(status="PASS" if log is not None else "DIAGNOSTIC_ONLY",wave_sha256=wave_hash,window_last_time=time,
                  dispatched_dot=len(records),completed_dot=len(completed),
                  false_wait_dot=len(false),records=records,
                  boundary="Actual IQ source-readiness obstruction. NOT exclusive resource-stall attribution, wrong-path or PPA proof.")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wave")
    parser.add_argument("log",nargs="?",help="omit only for diagnostic waveform inspection, never full-core PASS")
    parser.add_argument("--minimum-false-wait",type=int,default=1)
    parser.add_argument("--require-no-false-wait",action="store_true")
    parser.add_argument("--minimum-completed-dot",type=int,default=1)
    parser.add_argument("--json-out",required=True)
    args = parser.parse_args()
    try:
        need(not Path(args.json_out).exists(), "refusing to overwrite audit JSON")
        result = check(args.wave,args.log,args.minimum_false_wait)
        need(result["completed_dot"] >= args.minimum_completed_dot, "insufficient execution coverage")
        if args.require_no_false_wait:
            need(result["false_wait_dot"] == 0, "residual false source-readiness obstruction")
        with Path(args.json_out).open("x") as stream:
            stream.write(json.dumps(result,indent=2)+"\n")
        print(json.dumps({k:v for k,v in result.items() if k not in ("records","samples")},indent=2))
    except (ValueError,OSError,KeyError) as error:
        raise SystemExit(f"oldvd wave audit FAIL: {error}")
