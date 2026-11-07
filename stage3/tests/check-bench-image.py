#!/usr/bin/env python3
"""静态二进制检查，不代替执行时波形证明。"""
import argparse
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("elf")
args = parser.parse_args()
text = subprocess.check_output(["riscv64-linux-gnu-objdump", "-d", args.elf], text=True)


def body(name):
    match = re.search(rf"^[0-9a-f]+ <{name}>:\n(.*?)(?=^[0-9a-f]+ <|\Z)", text, re.M | re.S)
    if not match:
        raise ValueError(f"missing {name}")
    return match[1]


kernel, empty = body("bench_kernel"), body("bench_empty")
start = r"csrwi\s+vstart,0\n[^\n]*csrr\s+t1,mcycle\n[^\n]*csrwi\s+vstart,0"
end = r"csrwi\s+vstart,0\n[^\n]*csrr\s+t3,mcycle"
if len(re.findall(start, kernel)) != 4 or len(re.findall(end, kernel)) != 1:
    raise ValueError("kernel timer markers missing/misordered")
if len(re.findall(start, empty)) != 1 or len(re.findall(end, empty)) != 1:
    raise ValueError("empty control timer markers missing/misordered")
if not re.search(r"mv\s+t0,a5", kernel):
    raise ValueError("batch count is not passed through a5")
if re.search(r"\b(?:jal|jalr)\b", kernel + empty):
    raise ValueError("unexpected function call in timed kernels")
print("benchmark binary audit PASS: runtime batches, symmetric CSR-write timer markers, no function calls")
print("Static evidence only; no isolated FU latency or dynamic ROB-order proof")
