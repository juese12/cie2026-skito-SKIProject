#!/usr/bin/env python3
"""生成经过检查的启动参数覆盖文件，无需重新编译或修改指令。"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def prepare(elf, image, first, output):
    if first not in (0, 1):
        raise ValueError("order must be 0 or 1")
    symbols = subprocess.check_output(["riscv64-linux-gnu-nm", str(elf)], text=True)
    found = [int(line.split()[0], 16) for line in symbols.splitlines()
             if line.split()[-1] == "bench_runtime_order"]
    if len(found) != 1:
        raise ValueError("need exactly one runtime parameter symbol")
    offset = found[0] - 0x80000000
    original = Path(image).read_bytes()
    if not 0 <= offset < min(len(original), 0xf00) or original[offset] != 0:
        raise ValueError("parameter must be initialized zero in supported boot prefix")
    overlay = bytearray(original[:offset + 1])
    overlay[offset] = first
    reconstructed = overlay + original[len(overlay):]
    changes = [i for i, (a, b) in enumerate(zip(original, reconstructed)) if a != b]
    if changes != ([offset] if first else []):
        raise ValueError("unexpected executable/layout change")
    record = dict(first=first, parameter_address=hex(found[0]), offset=offset,
                  overwrite_nbytes=len(overlay), changed_offsets=changes,
                  image_sha256=hashlib.sha256(original).hexdigest(),
                  overlay_sha256=hashlib.sha256(overlay).hexdigest())
    with Path(output).open("xb") as stream:
        stream.write(overlay)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf")
    parser.add_argument("image")
    parser.add_argument("first", type=int)
    parser.add_argument("output")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.elf, args.image, args.first, args.output), sort_keys=True))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"runtime parameter FAIL: {error}\n")
