#!/usr/bin/env python3
"""比较相同 wrapper 激励并审核隔离，不用于估计功耗。"""
import argparse
import hashlib
import json
from pathlib import Path

TOP = "TOP."
HARNESS = TOP + "VDotIntegrationHarness."
FU = HARNESS + "fu."
DOT = FU + "vdot."
INPUTS = ["io_valid", "io_cancel", "io_op", "io_tag", "io_vs1", "io_vs2",
          "io_oldVd", "io_mask", "io_vxrm", "io_config_vtype_illegal",
          "io_config_vtype_vma", "io_config_vtype_vta", "io_config_vtype_vsew",
          "io_config_vtype_vlmul", "io_config_vl", "io_vm", "io_vstart", "io_v0Dest"]
OUTPUTS = ["io_outTag", "io_result", "io_illegal", "io_saturated", "io_vecWen", "io_v0Wen"]
GROUPS = {
    "dot_products": [DOT + f"products_{i}" for i in range(8)],
    "dot_sum": [DOT + "sum"],
    "mac_wallace_stage1": [FU + f"vimacs_{lane}.wallaceOut_mid_reg_{i}"
                           for lane in range(2) for i in range(6)],
    "mac_result_stage2": [FU + f"vimacs_{lane}.walOut_r" for lane in range(2)],
}
MAC_DATA = [FU + f"vimacs_{lane}.io_{name}"
            for lane in range(2) for name in ("vs1", "vs2", "oldVd")]
MAC_CONTROL = [FU + f"vimacs_{lane}.io_{name}"
               for lane in range(2) for name in
               ("info_vxrm", "highHalf", "isMacc", "isSub", "widen", "isFixP")]


def edges(path, isolated):
    wanted = {TOP + name for name in INPUTS + OUTPUTS + ["clock", "reset", "io_outValid"]}
    wanted.update(MAC_DATA + MAC_CONTROL)
    wanted.update(name for group in GROUPS.values() for name in group)
    wanted.update([HARNESS + "fu_io_in_valid", HARNESS + "ctrlPipe_1_fuOpType",
                   HARNESS + "validPipe_1", FU + "validVecThisFu_1",
                   DOT + "io_enable_0", DOT + "io_enable_1"])
    for lane in range(2):
        wanted.update([FU + f"vimacs_{lane}.io_fire", FU + f"vimacs_{lane}.fireS1_last_r"])
    if isolated:
        wanted.update([DOT + "isolatedVs1", DOT + "isolatedVs2"])
    scope, names, values = [], {}, {}
    result, previous, timestamp = [], None, 0

    def sample():
        nonlocal previous
        if not names:
            return
        missing = wanted - names.keys()
        assert not missing, f"missing VCD signals: {sorted(missing)}"
        now = {name: values.get(code) for name, code in names.items()}
        now["time"] = timestamp
        if previous is not None and previous[TOP + "clock"] == 0 and now[TOP + "clock"] == 1:
            if previous[TOP + "reset"] == 0 and now[TOP + "reset"] == 0:
                assert all(v is not None for v in previous.values()), "unknown/missing pre-edge value"
                assert all(v is not None for v in now.values()), "unknown/missing post-edge value"
                result.append((previous, now))
        previous = now

    with open(path, encoding="ascii") as wave:
        for raw in wave:
            line = raw.strip()
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                fields = line.split()
                name = ".".join(scope + [fields[4]])
                if name in wanted:
                    names[name] = fields[3]
            elif line.startswith("#"):
                sample()
                timestamp = int(line[1:])
            elif line.startswith("b"):
                bits, code = line[1:].split()
                values[code] = None if any(c in bits.lower() for c in "xz") else int(bits, 2)
            elif line and line[0] in "01xzXZ":
                values[line[1:]] = int(line[0]) if line[0] in "01" else None
    sample()
    assert result, "no complete non-reset edges"
    return result


def audit(before, after):
    assert len(before) == len(after), "different edge counts"
    counts = {"edges": len(after), "outputs": 0, "dot_requests": 0, "mac_requests": 0,
              "dot_stage2_transfers": 0, "mixed_overlap_edges": 0, "disabled_hold_checks": 0}
    flips = {version: dict.fromkeys(GROUPS, 0) for version in ("before", "after")}
    input_flips = {version: {"dot_multiplier_inputs": 0, "mac_inputs": 0}
                   for version in ("before", "after")}
    last_inputs = {}
    for index, ((bp, bq), (ap, aq)) in enumerate(zip(before, after)):
        assert bp["time"] == ap["time"] and bq["time"] == aq["time"], (index, "time mismatch")
        for name in INPUTS:
            assert bp[TOP + name] == ap[TOP + name], (index, "stimulus differs", name)
        assert bq[TOP + "io_outValid"] == aq[TOP + "io_outValid"], (index, "valid differs")
        if aq[TOP + "io_outValid"]:
            for name in OUTPUTS:
                assert bq[TOP + name] == aq[TOP + name], (index, "output differs", name)
            counts["outputs"] += 1
        valid = ap[HARNESS + "fu_io_in_valid"]
        is_dot = ap[TOP + "io_op"] == 0x160
        dot0 = int(valid and is_dot)
        mac0 = int(valid and not is_dot)
        dot1 = int(ap[HARNESS + "validPipe_1"] and ap[FU + "validVecThisFu_1"]
                   and ap[HARNESS + "ctrlPipe_1_fuOpType"] == 0x160)
        assert ap[DOT + "io_enable_0"] == dot0, (index, "dot stage1 enable")
        assert ap[DOT + "io_enable_1"] == dot1, (index, "dot stage2 enable")
        counts["dot_requests"] += dot0
        counts["mac_requests"] += mac0
        counts["dot_stage2_transfers"] += dot1
        counts["mixed_overlap_edges"] += int(mac0 and dot1)
        for name, source in (("isolatedVs1", "io_vs1"), ("isolatedVs2", "io_vs2")):
            expected = ap[TOP + source] & ((1 << 64) - 1) if dot0 else 0
            assert ap[DOT + name] == expected, (index, "dot operand isolation", name)
        for lane in range(2):
            assert ap[FU + f"vimacs_{lane}.io_fire"] == mac0, (index, "mac fire")
        if not mac0:
            assert all(ap[name] == 0 for name in MAC_DATA + MAC_CONTROL), (index, "mac input isolation")
        enables = {"dot_products": dot0, "dot_sum": dot1, "mac_wallace_stage1": mac0}
        for group, signals in GROUPS.items():
            for name in signals:
                enable = enables.get(group)
                if group == "mac_result_stage2":
                    lane = int(name.split("vimacs_")[1][0])
                    enable = ap[FU + f"vimacs_{lane}.fireS1_last_r"]
                if not enable:
                    assert ap[name] == aq[name], (index, "disabled register changed", name)
                    counts["disabled_hold_checks"] += 1
                flips["before"][group] += (bp[name] ^ bq[name]).bit_count()
                flips["after"][group] += (ap[name] ^ aq[name]).bit_count()
        for version, pre in (("before", bp), ("after", ap)):
            dot_inputs = [pre[DOT + name] for name in ("isolatedVs1", "isolatedVs2")] if version == "after" else [pre[TOP + name] & ((1 << 64) - 1) for name in ("io_vs1", "io_vs2")]
            groups = {"dot_multiplier_inputs": dot_inputs,
                      "mac_inputs": [pre[name] for name in MAC_DATA]}
            for group, data in groups.items():
                key = (version, group)
                if key in last_inputs:
                    input_flips[version][group] += sum((x ^ y).bit_count() for x, y in zip(last_inputs[key], data))
                last_inputs[key] = data
    assert counts["outputs"] >= 300 and counts["dot_requests"] >= 70 and counts["mac_requests"] >= 200, counts
    assert counts["mixed_overlap_edges"] > 0, "missing mixed-stage overlap"
    assert sum(flips["after"].values()) < sum(flips["before"].values()), "no selected register activity reduction"
    return {"status": "PASS", "scope": "fixed-ready wrapper RTL, NOT CPU/PPA/power",
            "counts": counts, "register_sampled_bit_flips": flips,
            "operand_cycle_sampled_bit_flips": input_flips,
            "limitations": "Selected signals at settled cycle/edge samples; excludes glitches, clocks, MGU, shared pipeline, cell capacitance and physical power."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--json-out", required=True)
    args = parser.parse_args()
    result = audit(edges(args.before, False), edges(args.after, True))
    result["wave_sha256"] = {key: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                             for key, path in (("before", args.before), ("after", args.after))}
    with open(args.json_out, "x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
