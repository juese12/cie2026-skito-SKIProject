#!/usr/bin/env python3
"""Execute the real NEMU helper through its shared-library API.

This test intentionally targets the pinned v0.1 xs-ref ABI (1400 bytes).
It checks the entire architectural vector file and CSR state, not RTL.
"""
import argparse
import ctypes
import random
import struct

parser = argparse.ArgumentParser()
parser.add_argument("reference")
args = parser.parse_args()
lib = ctypes.CDLL(args.reference)
size = ctypes.c_uint.in_dll(lib, "DIFFTEST_REG_SIZE").value
assert size == 1400, f"different ABI: {size}; audit CPU_state before using this test"
State = ctypes.c_uint64 * (size // 8)
lib.difftest_memcpy.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_bool]
lib.difftest_regcpy.argtypes = [ctypes.c_void_p, ctypes.c_bool]
lib.difftest_exec.argtypes = [ctypes.c_uint64]
lib.difftest_init()
initial = State()
lib.difftest_regcpy(ctypes.byref(initial), False)
PC, VECTOR_BASE, VCSR_BASE = 82, 100, 164
# The xs-ref preset resets mnstatus.NMIE=0. This CSR is outside regcpy's
# compact ABI; enable it through a real instruction, as the normal boot ROM does.
initial[PC] = 0x80010000
boot = ctypes.create_string_buffer(struct.pack("<I", 0x74446073))  # csrrsi x0,mnstatus,8
lib.difftest_memcpy(initial[PC], boot, 4, True)
lib.difftest_regcpy(ctypes.byref(initial), True)
lib.difftest_exec(1)
lib.difftest_regcpy(ctypes.byref(initial), False)
random_source = random.Random(0x56444F54)


def signed_byte(x):
    return x if x < 128 else x - 256


def execute(a, b, vd=10, vs1=8, vs2=9, illegal=None, policy=0):
    global count
    state = State(*initial)
    state[65] = (state[65] & ~(1 << 42)) | 0x600  # MDT off, VS dirty
    state[PC] = address = 0x80000000 + count * 4
    state[VCSR_BASE + 4] = 8
    state[VCSR_BASE + 5] = policy
    state[VCSR_BASE + 6] = 16
    state[VCSR_BASE + 1] = count & 1
    state[VCSR_BASE + 2] = count % 4
    state[VCSR_BASE + 3] = 2 * (count % 4) + (count & 1)
    for reg in range(32):
        state[VECTOR_BASE + 2 * reg] = random_source.getrandbits(64)
        state[VECTOR_BASE + 2 * reg + 1] = random_source.getrandbits(64)
    for reg, bytes_ in ((vs1, a), (vs2, b)):
        state[VECTOR_BASE + 2 * reg] = int.from_bytes(bytes(bytes_), "little")
    vm = 1
    if illegal == "vl0": state[VCSR_BASE + 4] = 0
    if illegal == "vl7": state[VCSR_BASE + 4] = 7
    if illegal == "vl9": state[VCSR_BASE + 4] = 9
    if illegal == "vl16": state[VCSR_BASE + 4] = 16
    if illegal == "sew": state[VCSR_BASE + 5] = 8
    if illegal == "lmul": state[VCSR_BASE + 5] = 1
    if illegal == "vill": state[VCSR_BASE + 5] = 1 << 63
    if illegal == "start": state[VCSR_BASE] = 1
    if illegal == "vs": state[65] &= ~0x600
    if illegal == "vm": vm = 0
    before = list(state)
    word = vm << 25 | vs2 << 20 | vs1 << 15 | 2 << 12 | vd << 7 | 0x0B
    instruction = ctypes.create_string_buffer(struct.pack("<I", word))
    lib.difftest_memcpy(address, instruction, 4, True)
    lib.difftest_regcpy(ctypes.byref(state), True)
    lib.difftest_exec(1)
    lib.difftest_regcpy(ctypes.byref(state), False)
    actual = list(state)
    expected_vector = before[VECTOR_BASE:VCSR_BASE]
    if illegal:
        assert actual[73] == 2, (illegal, "cause", actual[73], "pc", hex(actual[PC]), "machine CSRs", actual[64:83], "vcsr", actual[VCSR_BASE:VCSR_BASE + 7])
        assert actual[67] == address, (illegal, "mepc", actual[67], address)
        # Pinned DUT: VL-only execution fault has no captured trap instruction;
        # decode-time illegal configs retain the instruction bits. Both are
        # permitted architectural tval values, and both are checked exactly.
        expected_tval = 0 if illegal in ("vl0", "vl7", "vl9", "vl16") else word
        assert actual[69] == expected_tval, (illegal, "mtval", actual[69], expected_tval)
        assert actual[VCSR_BASE:VCSR_BASE + 7] == before[VCSR_BASE:VCSR_BASE + 7], illegal
    else:
        left = before[VECTOR_BASE + 2 * vs1].to_bytes(8, "little")
        right = before[VECTOR_BASE + 2 * vs2].to_bytes(8, "little")
        total = sum(signed_byte(x) * signed_byte(y) for x, y in zip(left, right))
        expected_vector[2 * vd] = total & 0xFFFFFFFF
        expected_vector[2 * vd + 1] = 0
        assert actual[PC] == address + 4
        assert actual[VCSR_BASE:VCSR_BASE + 7] == before[VCSR_BASE:VCSR_BASE + 7]
    assert actual[VECTOR_BASE:VCSR_BASE] == expected_vector, (count, illegal, vd, vs1, vs2)
    assert actual[:64] == before[:64], "modified scalar or float registers"
    count += 1


count = 0
for a, b in ((list(range(1, 9)), [1] * 8), ([255] * 8, [1] * 8),
             ([128] * 8, [128] * 8), ([128] * 8, [127] * 8),
             ([127] * 8, [127] * 8), ([0] * 8, [255] * 8),
             ([127, 129] * 4, [1] * 8)):
    for policy in (0, 64, 128, 192):
        execute(a, b, policy=policy)
for vd, vs1, vs2 in ((8, 8, 9), (9, 8, 9), (8, 8, 8),
                      (10, 0, 9), (10, 8, 0), (0, 8, 9), (31, 8, 9)):
    execute(list(range(1, 9)), [1] * 8, vd, vs1, vs2)
for _ in range(1000):
    execute([random_source.randrange(256) for _ in range(8)],
            [random_source.randrange(256) for _ in range(8)],
            vd=random_source.randrange(32), vs1=random_source.randrange(32),
            vs2=random_source.randrange(32), policy=random_source.choice((0, 64, 128, 192)))
valid_count = count
for illegal in ("vl0", "vl7", "vl9", "vl16", "sew", "lmul", "vill", "start", "vs", "vm"):
    execute(list(range(1, 9)), [1] * 8, illegal=illegal)
print(f"NEMU vdot PASS: valid={valid_count}, illegal={count-valid_count}, ABI={size}, seed=0x56444f54")

# An unsupported custom-0 function is NOT vdot. Preserve standard illegal
# instruction tval behavior even when VL happens to be unsupported for vdot.
standard = State(*initial)
standard[65] = (standard[65] & ~(1 << 42)) | 0x600
standard[PC] = 0x80020000
standard[VCSR_BASE + 4] = 7
standard[VCSR_BASE + 5] = 0
other_word = 0x0200000b
other = ctypes.create_string_buffer(struct.pack("<I", other_word))
lib.difftest_memcpy(standard[PC], other, 4, True)
lib.difftest_regcpy(ctypes.byref(standard), True)
lib.difftest_exec(1)
lib.difftest_regcpy(ctypes.byref(standard), False)
assert standard[73] == 2 and standard[67] == 0x80020000 and standard[69] == other_word
print("NEMU tval isolation PASS: non-vdot custom function retains instruction bits")
