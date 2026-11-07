#!/usr/bin/env python3
"""流式读取真实 SimTop VCD，审核 VIMacU/VDot8 执行通路。

此处检查执行单元数据和控制，不代替架构提交验收；
精确异常还需独立成功的完整整核差分结果。
"""
import argparse
import csv
import re
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("wave")
parser.add_argument("--minimum", type=int, default=1)
parser.add_argument("--diagnostic", action="store_true")
parser.add_argument("--commit-log", help="same-window full CPU commit trace")
args = parser.parse_args()
scope, signals, values = [], {}, {}
modules = {}
time = 0
rows = []
top_clock_code, previous_top_clock = None, None


def signed_byte(value):
    return value if value < 128 else value - 256


def dot(left, right):
    return sum(signed_byte((left >> (8 * i)) & 255) *
               signed_byte((right >> (8 * i)) & 255) for i in range(8)) & 0xffffffff


def sample():
    global previous_top_clock
    if not values:
        return
    top_clock = values.get(top_clock_code)
    low_phase = previous_top_clock == 1 and top_clock == 0
    previous_top_clock = top_clock
    for path, state in modules.items():
        def get(name):
            code = signals[path + "." + name]
            if code not in values or values[code] is None:
                raise AssertionError((time, path, "unknown signal", name))
            return values[code]
        clock = get("clock")
        if state["clock"] != clock:
            state["edges"] += 1
        if get("io_out_valid") and get("io_in_bits_ctrlPipe_2_fuOpType") == 0x160:
            state["visible_dot"] += 1
        # 使用 TOP 的稳定低相位：门控时钟可能在新输入到来时仍为低电平，
        # 因而该周期不一定存在模块自身的下降沿。
        # 需要完整波形模式，才能取得上升沿之前的输入使能快照。
        state["clock"] = clock
        if not low_phase or get("reset"):
            continue
        state["falling"] += 1
        # 原版本 VDot8 会随所有 Vimac 运算更新；根据其两级寄存器
        # 独立计算期望结果，避免受 ROB 标签循环复用影响。
        # 采样窗口可能从流水中途开始，乘积和总和已知之前跳过输出核对。
        if (get("io_out_valid") and
                get("io_in_bits_ctrlPipe_2_fuOpType") == 0x160):
            illegal = (get("io_in_bits_dataPipe_2_src_4") != 8 or
                       not get("io_in_bits_ctrlPipe_2_vpu_vm") or
                       get("io_in_bits_ctrlPipe_2_vpu_vstart") != 0)
            assert get("io_out_bits_ctrl_exceptionVec_2") == int(illegal), (time, "exception")
            assert get("io_out_bits_res_vxsat") == 0, (time, "vxsat")
            assert get("io_out_bits_ctrl_vecWen") + get("io_out_bits_ctrl_v0Wen") == 1
            if state["sum"] is not None and not illegal:
                result = get("io_out_bits_res_data")
                assert result == state["sum"], (time, path, hex(result), hex(state["sum"]))
                rows.append((time, path, get("io_out_bits_ctrl_robIdx_flag"),
                             get("io_out_bits_ctrl_robIdx_value"),
                             get("io_out_bits_ctrl_pdest"),
                             get("io_out_bits_ctrl_v0Wen"), hex(result)))
        # 这些寄存器使能作用于下一个上升沿；下一次
        # 低相位快照反映该上升沿更新后的寄存器状态。
        if get("vdot.io_enable_1"):
            state["sum"] = state["products"]
        if get("vdot.io_enable_0"):
            state["products"] = dot(get("vdot.io_vs1"), get("vdot.io_vs2"))


with open(args.wave, encoding="ascii") as wave:
    in_header = True
    for raw in wave:
        line = raw.strip()
        if in_header:
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                fields = line.split()
                signals[".".join(scope + [fields[4]])] = fields[3]
            elif line.startswith("$enddefinitions"):
                in_header = False
                for name in signals:
                    if name.endswith(".vdot.io_enable_0"):
                        path = name.removesuffix(".vdot.io_enable_0")
                        modules[path] = {"clock": None, "products": None, "sum": None,
                                         "edges": 0, "falling": 0, "visible_dot": 0}
                assert modules, "no real VIMacU/VDot8 hierarchy found"
                top_clock_code = signals.get("TOP.clock") or signals.get("TOP.SimTop.clock")
                assert top_clock_code is not None, "no top-level clock found"
                required = ("clock", "reset", "io_out_valid", "io_in_bits_ctrlPipe_2_fuOpType",
                            "io_in_bits_dataPipe_2_src_4", "io_in_bits_ctrlPipe_2_vpu_vm",
                            "io_in_bits_ctrlPipe_2_vpu_vstart", "io_out_bits_ctrl_exceptionVec_2",
                            "io_out_bits_res_vxsat", "io_out_bits_ctrl_vecWen", "io_out_bits_ctrl_v0Wen",
                            "io_out_bits_res_data", "io_out_bits_ctrl_robIdx_flag",
                            "io_out_bits_ctrl_robIdx_value", "io_out_bits_ctrl_pdest",
                            "vdot.io_enable_0", "vdot.io_enable_1", "vdot.io_vs1", "vdot.io_vs2")
                for path in modules:
                    for name in required:
                        assert path + "." + name in signals, (path, "missing", name)
                # 即使波形达到数 GiB，也只保留相关信号标识。
                selected = {signals[path + "." + name] for path in modules for name in required}
                selected.add(top_clock_code)
            continue
        if line.startswith("#"):
            sample()
            time = int(line[1:])
        elif line.startswith("b"):
            bits, code = line[1:].split()
            if code in selected:
                values[code] = None if "x" in bits.lower() or "z" in bits.lower() else int(bits, 2)
        elif line and line[0] in "01xz":
            code = line[1:]
            if code in selected:
                values[code] = int(line[0]) if line[0] in "01" else None
sample()
if args.diagnostic:
    for path, state in modules.items():
        print("diagnostic", path, state, file=sys.stderr)
assert len(rows) >= args.minimum, f"only {len(rows)} checked outputs; need {args.minimum}"
if args.commit_log:
    with open(args.commit_log, encoding="utf-8", errors="replace") as log:
        trace = log.read()
    assert "Difftest enabled" in trace and "HIT GOOD TRAP" in trace and "vdot PASS:" in trace
    assert not re.search(r"HIT BAD TRAP|ABORT|different at pc|vdot.*FAIL", trace)
    commits = []
    for match in re.finditer(r"commit pc ([0-9a-f]+) inst ([0-9a-f]+) wen (\d+) dst (\d+) data ([0-9a-f]+) idx ([0-9a-f]+)", trace):
        pc, inst, wen, dest, data, tag = match.groups()
        inst = int(inst, 16)
        if inst & 0xfe00707f == 0x0200200b:
            assert int(wen) == 1 and int(dest) == (inst >> 7) & 31
            commits.append((int(tag, 16), int(data, 16), int(pc, 16)))
    # 仅将窗口内实际观察到的执行结果与同窗口真实提交配对。
    # 采集边界允许存在未完整覆盖的前后缀，不能假定
    # 每次投机执行都会成为架构写入。
    cursor = 0
    for row in rows:
        wanted = (row[3], int(row[6], 16))
        while cursor < len(commits) and commits[cursor][:2] != wanted:
            cursor += 1
        assert cursor < len(commits), (row, "no ordered matching commit")
        cursor += 1
    print(f"commit correlation PASS: execution_observations={len(rows)} vdot_commits={len(commits)}",
          file=sys.stderr)
writer = csv.writer(sys.stdout)
writer.writerow(("time", "hierarchy", "rob_flag", "rob_index", "pdest", "v0_wen", "result_128"))
writer.writerows(rows)
print(f"core waveform execution-path PASS: checked={len(rows)}; retirement requires difftest")
