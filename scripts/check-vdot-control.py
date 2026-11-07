#!/usr/bin/env python3
"""严格审核整核控制证据，不能从源码存在某条指令推断其已投机执行。"""
import argparse
import hashlib
import json
import re
from pathlib import Path

BASE = "TOP.SimTop.l_soc.core_with_l2.core.backend."
CTRL = BASE + "inner_ctrlBlock."
DISPATCH = CTRL + "dispatch."
ROB = CTRL + "rob."
FU = BASE + "inner_vfExuBlock.exus.Vimac."
SYMBOLS = ("control_branch_pc", "control_branch_dot", "control_branch_dot_v0",
           "control_exception_pc", "control_younger_dot", "control_younger_dot_v0",
           "control_younger_dot_alias", "control_exception_resume")
# 当前 DefaultConfig：160 项 ROB，指针含 8 位索引和 1 位回绕标志。
# 编码指针的比较步长为 256，而不是 160；拒绝未使用的索引值。
# 模 512 的差用于顺序判断，不能当作 uop 数量。
ROB_SIZE = 160
PRINTED_SYMBOLS = dict(branch="control_branch_pc", branch_dot="control_branch_dot",
                       branch_v0="control_branch_dot_v0", illegal="control_exception_pc",
                       young="control_younger_dot", young_v0="control_younger_dot_v0",
                       young_alias="control_younger_dot_alias")


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit_log(path, seed):
    text = Path(path).read_text(errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    # UART 文本可能被完整提交跟踪行打断；删除完整跟踪行
    # 及其换行符后，才能重新连接原 UART 文本。
    text = re.sub(r"\[\d{2}\] commit pc [0-9a-f]+ inst [0-9a-f]+ wen \d+ dst \d+ data [0-9a-f]+ idx [0-9a-f]+[^\n]*\n", "", text)
    expected = (f"control PASS: seed={int(seed,16):x} random=256 branch_train=64 "
                "branch_probe=4 illegal=20 configs=24 config_faults=16 mixed=16x32 chains=16x128")
    need("Difftest enabled" in text and "HIT GOOD TRAP" in text and expected in text,
         "missing exact full-core control PASS/seed/coverage")
    need(not re.search(r"HIT BAD TRAP|ABORT|different at pc|control.*FAIL", text), "core failure")
    need(re.findall(r"^\[process exit\] (\d+)$", text, re.M) == ["0"], "missing actual zero process exit")
    pattern = "control symbols " + " ".join(n+r"=([0-9a-f]+)" for n in PRINTED_SYMBOLS)
    rows = re.findall(pattern, text)
    need(len(rows) == 1, "missing/duplicate runtime symbol report")
    printed = {PRINTED_SYMBOLS[n]:int(v,16) for n,v in zip(PRINTED_SYMBOLS,rows[0])}
    return dict(seed=seed, log_sha256=digest(path), architectural_status="PASS", printed_symbols=printed)


def read_symbols(path):
    # 使用 riscv64-linux-gnu-nm -n 的 ELF 符号，符号表与对应镜像一起留存。
    found = {}
    for row in Path(path).read_text().splitlines():
        fields = row.split()
        if len(fields) == 3 and fields[2] in SYMBOLS:
            found[fields[2]] = int(fields[0], 16)
    need(set(found) == set(SYMBOLS), "missing ELF control symbols")
    need(len(set(found.values())) == len(SYMBOLS), "duplicate control symbol addresses")
    return found


def required_signals():
    names = ["TOP.clock", DISPATCH+"io_enqRob_canAccept",
             CTRL+"io_redirect_valid", CTRL+"io_redirect_bits_level",
             ROB+"io_flushOut_valid", ROB+"io_flushOut_bits_level",
             ROB+"io_exception_valid", ROB+"io_exception_bits_exceptionVec_2",
             ROB+"io_exception_bits_instr",
             ROB+"io_commits_isCommit", FU+"io_out_valid",
             FU+"io_in_bits_ctrlPipe_2_fuOpType", FU+"io_out_bits_res_data"]
    for prefix in (CTRL+"io_redirect_bits_", ROB+"io_flushOut_bits_", FU+"io_out_bits_ctrl_"):
        names += [prefix+"robIdx_"+n for n in ("flag", "value")]
    for i in range(6):
        prefix = DISPATCH+f"io_enqRob_req_{i}_"
        names += [prefix+"valid"] + [prefix+"bits_"+n for n in ("instr", "pc", "robIdx_flag", "robIdx_value")]
    for i in range(8):
        names += [ROB+f"io_commits_commitValid_{i}"]
        names += [ROB+f"io_commits_robIdx_{i}_"+n for n in ("flag", "value")]
    for i in (1, 3, 5, 7):
        prefix = CTRL+f"io_fromWB_wbData_{i}_"
        names += [prefix+"valid", prefix+"bits_redirect_valid"]
        names += [prefix+"bits_redirect_bits_"+n for n in
                  ("robIdx_flag", "robIdx_value", "cfiUpdate_pc", "cfiUpdate_taken", "cfiUpdate_isMisPred")]
    return names


def audit_wave(path, symbols, require_coverage=True):
    scope, signals, values = [], {}, {}
    selected, live, records, flushes, decisions = set(), {}, [], [], {}
    writeback_redirects, accepted_redirects = [], []
    old_clock, time = None, 0
    branch_pc = symbols["control_branch_pc"]
    illegal_pc = symbols["control_exception_pc"]
    wrong_pcs = {symbols[n] for n in ("control_branch_dot", "control_branch_dot_v0")}
    young_pcs = {symbols[n] for n in ("control_younger_dot", "control_younger_dot_v0", "control_younger_dot_alias")}
    wanted_pcs = set(symbols.values())
    serial, phase = 0, 0

    def get(name):
        value = values.get(signals[name])
        need(value is not None, f"unknown {name} at {time}")
        return value

    def tag(prefix):
        flag, value = get(prefix+"robIdx_flag"), get(prefix+"robIdx_value")
        need(flag in (0,1) and 0 <= value < ROB_SIZE, "invalid DefaultConfig ROB pointer")
        return flag * 256 + value

    def flush(origin, kind, level):
        event = dict(time=time, phase=phase, kind=kind, origin=origin, victims=[], settled=False)
        if kind == "branch":
            need(origin in decisions, "branch flush without taken misprediction writeback")
            event["decision_time"] = decisions[origin]
            origin_rec = live.get(origin)
            event["settled"] = origin_rec is not None and "commit_time" in origin_rec
        for robtag, rec in list(live.items()):
            if "squashed_time" in rec or "commit_time" in rec:
                continue
            delta = (robtag-origin) % 512
            if 0 < delta < 256 or (level and delta == 0):
                if rec["pc"] in wrong_pcs | young_pcs:
                    need("commit_time" not in rec, "wrong-path/younger vdot already committed")
                    rec["squashed_time"] = time
                    rec["squash_kind"] = kind
                    event["victims"].append(rec["index"])
                # 保留已取消的相关标签以检查后续误提交，直到
                # 同一标签被新的分派序号明确重新分配。
                if rec["pc"] not in wanted_pcs:
                    live.pop(robtag)
        flushes.append(event)

    def sample():
        nonlocal old_clock, serial, phase
        clock = get("TOP.clock")
        falling = old_clock == 1 and clock == 0
        old_clock = clock
        if not falling:
            return
        phase += 1
        # Rob.scala 在 io.flushOut 后一拍注册 io.exception，
        # 不能将组合取消信号与上一拍异常载荷混为同一事件。
        for event in flushes:
            if event["kind"] == "exception" and "exception_time" not in event:
                need(phase == event["phase"]+1, "missed precise exception confirmation phase")
                need(get(ROB+"io_exception_valid") and get(ROB+"io_exception_bits_exceptionVec_2") and
                     get(ROB+"io_exception_bits_instr") == 0xffffffff,
                     "illegal flush without its next-cycle registered illegal-exception evidence")
                event["exception_time"] = time
        if get(DISPATCH+"io_enqRob_canAccept"):
            for i in range(6):
                prefix = DISPATCH+f"io_enqRob_req_{i}_"
                if not get(prefix+"valid"):
                    continue
                robtag = tag(prefix+"bits_")
                pc = get(prefix+"bits_pc")
                rec = dict(index=len(records), serial=serial, tag=robtag,
                           pc=pc, instr=get(prefix+"bits_instr"), dispatch_time=time)
                serial += 1
                live[robtag] = rec
                decisions.pop(robtag, None)
                if pc in wanted_pcs:
                    if pc in wrong_pcs | young_pcs:
                        need(rec["instr"] & 0xfc00707f == 0x200b and rec["instr"] & (1 << 25),
                             "target control symbol is not an unmasked vdot")
                    records.append(rec)
        if get(FU+"io_out_valid") and get(FU+"io_in_bits_ctrlPipe_2_fuOpType") == 0x160:
            rec = live.get(tag(FU+"io_out_bits_ctrl_"))
            if rec is not None and rec["pc"] in wrong_pcs | young_pcs:
                # 延迟出现的物理结果本身不代表架构提交。
                # 结果记录仍保留，但只有取消之前的执行计入覆盖。
                rec.setdefault("execution_time", time)
                rec["result"] = get(FU+"io_out_bits_res_data")
        for i in (1, 3, 5, 7):
            prefix = CTRL+f"io_fromWB_wbData_{i}_"
            if get(prefix+"valid") and get(prefix+"bits_redirect_valid"):
                redirect = prefix+"bits_redirect_bits_"
                writeback_redirects.append(dict(time=time,port=i,tag=tag(redirect),
                    pc=get(redirect+"cfiUpdate_pc"),taken=get(redirect+"cfiUpdate_taken"),
                    mispredict=get(redirect+"cfiUpdate_isMisPred")))
                origin = tag(redirect)
                branch = live.get(origin)
                # 指令身份来自被接受的 ROB 分配，
                # 不能使用另一传输级的 PC 载荷替代。上方原始 CFI PC
                # 继续保留作为证据，它不一定等于分派时的 PC。
                if (branch is not None and branch["pc"] == branch_pc and
                    branch["instr"] & 0x7f == 0x63 and
                    get(redirect+"cfiUpdate_taken") and get(redirect+"cfiUpdate_isMisPred")):
                    decisions[origin] = time
        if get(ROB+"io_commits_isCommit"):
            for i in range(8):
                if not get(ROB+f"io_commits_commitValid_{i}"):
                    continue
                robtag = get(ROB+f"io_commits_robIdx_{i}_flag")*256 + get(ROB+f"io_commits_robIdx_{i}_value")
                need(robtag % 256 < ROB_SIZE and 0 <= robtag < 512, "invalid commit ROB pointer")
                rec = live.get(robtag)
                if rec is None:
                    continue  # 窗口开始前的指令没有对应分派记录。
                need("squashed_time" not in rec, "squashed allocation committed")
                need(rec["pc"] not in young_pcs, "illegal instruction's younger vdot committed")
                rec["commit_time"] = time
                if rec["pc"] == symbols["control_exception_resume"]:
                    for event in flushes:
                        if event["kind"] == "exception" and event["time"] < time:
                            event["settled"] = True
                if rec["pc"] == branch_pc:
                    for event in flushes:
                        if event["kind"] == "branch" and event["origin"] == robtag and event["time"] <= time:
                            event["settled"] = True
                if rec["pc"] not in wanted_pcs:
                    live.pop(robtag)
        if get(ROB+"io_flushOut_valid"):
            origin = tag(ROB+"io_flushOut_bits_")
            rec = live.get(origin)
            if rec is not None and rec["pc"] == illegal_pc:
                flush(origin, "exception", get(ROB+"io_flushOut_bits_level"))
        if get(CTRL+"io_redirect_valid"):
            origin = tag(CTRL+"io_redirect_bits_")
            rec = live.get(origin)
            accepted_redirects.append(dict(time=time,tag=origin,pc=None if rec is None else rec["pc"],
                                           instr=None if rec is None else rec["instr"],
                                           known_decision=origin in decisions))
            if rec is not None and rec["pc"] == branch_pc and origin in decisions:
                flush(origin, "branch", get(CTRL+"io_redirect_bits_level"))

    with Path(path).open(encoding="ascii") as stream:
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
                    required = required_signals()
                    missing = [n for n in required if n not in signals]
                    need(not missing, f"missing real-core signals: {missing[:8]}")
                    selected = {signals[n] for n in required}
                continue
            if line.startswith("#"):
                if values:
                    sample()
                time = int(line[1:])
            elif line.startswith("b"):
                bits, code = line[1:].split()
                if code in selected:
                    values[code] = None if any(c in bits.lower() for c in "xz") else int(bits, 2)
            elif line and line[0] in "01xz" and line[1:] in selected:
                values[line[1:]] = int(line[0]) if line[0] in "01" else None
    need(not header, "incomplete VCD header")
    sample()
    proven = {}
    for kind, pcs in (("branch", wrong_pcs), ("exception", young_pcs)):
        eligible = []
        for event in flushes:
            victims = [records[i] for i in event["victims"]]
            executed = {r["pc"] for r in victims if "execution_time" in r and r["execution_time"] <= event["time"]}
            if (event["kind"] == kind and pcs <= executed and event["settled"] and
                (kind != "exception" or "exception_time" in event)):
                eligible.append(event)
        if require_coverage:
            need(eligible, f"no settled {kind} flush covering execution of ALL targeted younger vdot PCs")
        proven[kind] = eligible
    if require_coverage:
        need(wrong_pcs <= {r["pc"] for r in records if "commit_time" in r},
             "no legitimate training-dot commits: missing positive commit coverage")
    return dict(wave_sha256=digest(path), symbols={n:hex(v) for n,v in symbols.items()},
                window_last_time=time, proof=proven, observed_flushes=flushes, records=records,
                writeback_redirects=writeback_redirects, accepted_redirects=accepted_redirects,
                coverage_required=require_coverage,
                boundary="Actual tagged dispatch + Vimac execution + accepted flush + no ROB commit; architectural state checked separately by Difftest and full128 sentinels. Not a universal formal proof.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log")
    parser.add_argument("--seed", default="56444f54")
    parser.add_argument("--wave")
    parser.add_argument("--symbols")
    parser.add_argument("--json-out", required=True)
    args = parser.parse_args()
    try:
        need(not Path(args.json_out).exists(), "refusing to overwrite previous evidence")
        result = audit_log(args.log, args.seed)
        need(bool(args.wave) == bool(args.symbols), "wave and symbols must be provided together")
        if args.wave:
            symbols = read_symbols(args.symbols)
            need(all(symbols[n] == v for n,v in result["printed_symbols"].items()),
                 "runtime symbols disagree with frozen ELF: stale/mismatched wave or image")
            result.update(audit_wave(args.wave, symbols))
            result["symbols_sha256"] = digest(args.symbols)
            result["control_status"] = "PASS"
        else:
            result["control_status"] = "NOT_AUDITED"
        with Path(args.json_out).open("x") as stream:
            stream.write(json.dumps(result, indent=2)+"\n")
        compact = {k:v for k,v in result.items()
                   if k not in ("records", "writeback_redirects", "accepted_redirects")}
        if "records" in result:
            compact["record_count"] = len(result["records"])
            compact["writeback_redirect_count"] = len(result["writeback_redirects"])
            compact["accepted_redirect_count"] = len(result["accepted_redirects"])
        print(json.dumps(compact, indent=2))
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(f"control audit FAIL: {error}")
