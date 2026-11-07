#!/usr/bin/env python3
"""审核 VDotIntegrationTest 的 VCD，不将其视作整核运行证据。"""
import argparse
import csv
import sys

parser = argparse.ArgumentParser()
parser.add_argument("wave")
args = parser.parse_args()
names, values, scope = {}, {}, []
previous_clock, rows = 0, []
expected, observed = {}, set()
time = 0


def sample():
    global previous_clock
    def get(name):
        return values.get(names[name], 0)
    clock = get("clock")
    if clock and not previous_clock and not get("reset"):
        if get("io_cancel"):
            expected.clear()
        if get("io_valid") and not get("io_cancel"):
            tag = get("io_tag")
            left = get("io_vs1").to_bytes(16, "little")
            right = get("io_vs2").to_bytes(16, "little")
            signed = lambda byte: byte if byte < 128 else byte - 256
            op = get("io_op")
            if op == 0x160:
                result = sum(signed(a) * signed(b) for a, b in zip(left[:8], right[:8])) & 0xffffffff
            else:
                result = int.from_bytes(bytes((a * b) & 255 for a, b in zip(left[:8], right[:8])), "little")
            illegal = op == 0x160 and (get("io_config_vl") != 8 or not get("io_vm") or get("io_vstart") != 0)
            expected[tag] = (op, result, int(illegal), get("io_v0Dest"))
        if get("io_outValid"):
            tag = get("io_outTag")
            assert tag in expected, (time, "unexpected/canceled tag", tag)
            assert tag not in observed, (time, "duplicate output", tag)
            op, result, illegal, v0 = expected[tag]
            assert get("io_illegal") == illegal
            assert get("io_saturated") == 0
            assert get("io_v0Wen") == v0 and get("io_vecWen") == 1 - v0
            if not illegal:
                assert get("io_result") == result, (tag, hex(get("io_result")), hex(result))
            observed.add(tag)
            rows.append((time, tag, hex(op), illegal, hex(get("io_result"))))
    previous_clock = clock


with open(args.wave, encoding="ascii") as wave:
    for raw in wave:
        line = raw.strip()
        if line.startswith("$scope"):
            scope.append(line.split()[2])
        elif line.startswith("$upscope"):
            scope.pop()
        elif line.startswith("$var") and scope == ["TOP"]:
            fields = line.split()
            names[fields[4]] = fields[3]
        elif line.startswith("#"):
            sample()
            time = int(line[1:])
        elif line.startswith("b"):
            bits, code = line[1:].split()
            if "x" not in bits.lower() and "z" not in bits.lower():
                values[code] = int(bits, 2)
        elif line and line[0] in "01":
            values[line[1:]] = int(line[0])
sample()
assert len(rows) == 24, f"expected 24 checked outputs, got {len(rows)}"
assert 42 not in observed, "flushed operation wrote back"
assert sum(row[3] for row in rows) == 7
writer = csv.writer(sys.stdout)
writer.writerow(("time_ps", "tag", "op", "illegal", "full_128bit_result"))
writer.writerows(rows)
print("wrapper waveform PASS: outputs=24 illegal=7 canceled_tag=42; NOT full-CPU evidence")
