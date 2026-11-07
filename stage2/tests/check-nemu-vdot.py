#!/usr/bin/env python3
"""通过共享库接口执行真实 NEMU helper。

使用项目配套的 1400 字节 xs-ref 接口，并显式选择指令约定。
检查完整架构向量寄存器组及 CSR 状态，不代表 RTL 仿真。
"""
import argparse
import ctypes
import random
import struct

parser = argparse.ArgumentParser()
parser.add_argument("reference")
parser.add_argument("--contract", choices=("e8-only", "e8-e16"), required=True,
                    help="select actual reference ISA; never infer support from its filename")
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
# xs-ref 预设将 mnstatus.NMIE 复位为零，该 CSR 不在 regcpy
# 的紧凑接口中，需像正常启动 ROM 一样通过实际指令开启。
initial[PC] = 0x80010000
boot = ctypes.create_string_buffer(struct.pack("<I", 0x74446073))  # 用 csrrsi x0,mnstatus,8 开启相应状态位。
lib.difftest_memcpy(initial[PC], boot, 4, True)
lib.difftest_regcpy(ctypes.byref(initial), True)
lib.difftest_exec(1)
lib.difftest_regcpy(ctypes.byref(initial), False)
random_source = random.Random(0x56444F54)


def signed_byte(x):
    return x if x < 128 else x - 256


def execute(a, b, vd=10, vs1=8, vs2=9, illegal=None, policy=0, bits=8):
    global count
    state = State(*initial)
    state[65] = (state[65] & ~(1 << 42)) | 0x600  # 关闭 MDT，并将 VS 置为脏状态。
    state[PC] = address = 0x80000000 + count * 4
    state[VCSR_BASE + 4] = 8
    state[VCSR_BASE + 5] = policy | (8 if bits == 16 else 0)
    state[VCSR_BASE + 6] = 16
    state[VCSR_BASE + 1] = count & 1
    state[VCSR_BASE + 2] = count % 4
    state[VCSR_BASE + 3] = 2 * (count % 4) + (count & 1)
    for reg in range(32):
        state[VECTOR_BASE + 2 * reg] = random_source.getrandbits(64)
        state[VECTOR_BASE + 2 * reg + 1] = random_source.getrandbits(64)
    for reg, elements in ((vs1, a), (vs2, b)):
        packed = sum((x & ((1 << bits) - 1)) << (bits * i) for i, x in enumerate(elements))
        state[VECTOR_BASE + 2 * reg] = packed & ((1 << 64) - 1)
        if bits == 16:
            state[VECTOR_BASE + 2 * reg + 1] = packed >> 64
    vm = 1
    if illegal == "vl0": state[VCSR_BASE + 4] = 0
    if illegal == "vl7": state[VCSR_BASE + 4] = 7
    if illegal == "vl9": state[VCSR_BASE + 4] = 9
    if illegal == "vl16": state[VCSR_BASE + 4] = 16
    if illegal == "sew": state[VCSR_BASE + 5] = 8 if args.contract == "e8-only" else 16
    if illegal == "sew64": state[VCSR_BASE + 5] = 24
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
        # 当前处理器仅 VL 非法的执行异常未捕获陷入指令；
        # 译码阶段的非法配置则保留指令位。这两种 tval 值
        # 均符合架构允许范围，并且都必须精确核对。
        expected_tval = 0 if illegal in ("vl0", "vl7", "vl9", "vl16") else word
        assert actual[69] == expected_tval, (illegal, "mtval", actual[69], expected_tval)
        assert actual[VCSR_BASE:VCSR_BASE + 7] == before[VCSR_BASE:VCSR_BASE + 7], illegal
    else:
        def lanes(reg):
            raw = before[VECTOR_BASE + 2 * reg] | (before[VECTOR_BASE + 2 * reg + 1] << 64)
            values = [(raw >> (bits*i)) & ((1 << bits)-1) for i in range(8)]
            return [v if v < (1 << (bits-1)) else v-(1 << bits) for v in values]
        total = sum(x*y for x,y in zip(lanes(vs1), lanes(vs2)))
        expected_vector[2 * vd] = total & ((1 << (32 if bits == 8 else 64))-1)
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
if args.contract == "e8-e16":
    for x,y in ((-32768,-32768),(-32768,32767),(32767,32767),(0,-32768)):
        for policy in (0,64,128,192):
            for regs in ((10,8,9),(8,8,9),(9,8,9),(8,8,8),(10,0,9),(10,8,0),(0,8,9)):
                execute([x]*8,[y]*8,*regs,policy=policy,bits=16)
    for _ in range(256):
        execute([random_source.randrange(-32768,32768) for _ in range(8)],
                [random_source.randrange(-32768,32768) for _ in range(8)],
                vd=random_source.randrange(32),vs1=random_source.randrange(32),
                vs2=random_source.randrange(32),bits=16)
valid_count = count
faults=("vl0", "vl7", "vl9", "vl16", "sew", "lmul", "vill", "start", "vs", "vm")
for illegal in faults + (("sew64",) if args.contract == "e8-e16" else ()):
    execute(list(range(1, 9)), [1] * 8, illegal=illegal)
print(f"NEMU vdot PASS: contract={args.contract} valid={valid_count}, illegal={count-valid_count}, ABI={size}, seed=0x56444f54")

# 未支持的 custom-0 功能不是 vdot；即使当前 VL 对 vdot 不合法，
# 仍需保留普通非法指令的 tval 行为。
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
