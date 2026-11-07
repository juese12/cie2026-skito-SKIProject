#!/usr/bin/env python3
"""执行真实 NEMU 指令，以独立 Python 整数参考值检查完整向量及 CSR 接口。"""
import argparse
import ctypes as ct
import random
import struct

p = argparse.ArgumentParser()
p.add_argument('reference')
args = p.parse_args()
lib = ct.CDLL(args.reference)
size = ct.c_uint.in_dll(lib, 'DIFFTEST_REG_SIZE').value
assert size == 1400, size
State = ct.c_uint64 * (size // 8)
lib.difftest_memcpy.argtypes = [ct.c_uint64, ct.c_void_p, ct.c_size_t, ct.c_bool]
lib.difftest_regcpy.argtypes = [ct.c_void_p, ct.c_bool]
lib.difftest_exec.argtypes = [ct.c_uint64]
lib.difftest_init()
initial = State()
lib.difftest_regcpy(ct.byref(initial), False)
initial[82] = 0x80010000
boot = ct.create_string_buffer(struct.pack('<I', 0x74446073))
lib.difftest_memcpy(initial[82], boot, 4, True)
lib.difftest_regcpy(ct.byref(initial), True)
lib.difftest_exec(1)
lib.difftest_regcpy(ct.byref(initial), False)
valid = illegal = 0

def execute(rng, bits, a, b, regs=(10, 8, 9), fault=None):
    global valid, illegal
    vd, vs1, vs2 = regs
    state = State(*initial)
    state[65] = (state[65] & ~(1 << 42)) | 0x600
    # 每例使用不同 PC，避免通过 API 替换客体指令后
    # NEMU 仍复用该地址原先的译码缓存。
    state[82] = 0x80000000 + 4 * (valid + illegal)
    state[164] = 0
    state[165] = rng.randrange(2)
    state[166] = rng.randrange(4)
    state[167] = 2 * state[166] + state[165]
    state[168] = 8
    state[169] = (8 if bits == 16 else 0) | (rng.randrange(4) << 6)
    state[170] = 16
    for i in range(100, 164): state[i] = rng.getrandbits(64)
    for reg, values in ((vs1, a), (vs2, b)):
        packed = sum((x & ((1 << bits) - 1)) << (bits*i) for i, x in enumerate(values))
        state[100+2*reg] = packed & ((1 << 64)-1)
        if bits == 16: state[101+2*reg] = packed >> 64
    vm = fault != 'mask'
    if fault in (0, 1, 7, 9, 16): state[168] = fault
    if fault == 'e32': state[169] = 16
    if fault == 'e64': state[169] = 24
    if fault == 'lmul': state[169] |= 1
    if fault == 'vill': state[169] = 1 << 63
    if fault == 'start': state[164] = 1
    if fault == 'off': state[65] &= ~0x600
    word = int(vm) << 25 | vs2 << 20 | vs1 << 15 | 2 << 12 | vd << 7 | 0xb
    before = list(state)
    insn = ct.create_string_buffer(struct.pack('<I', word))
    lib.difftest_memcpy(state[82], insn, 4, True)
    lib.difftest_regcpy(ct.byref(state), True)
    lib.difftest_exec(1)
    lib.difftest_regcpy(ct.byref(state), False)
    actual = list(state)
    expected = before[100:164]
    if fault is not None:
        assert actual[73] == 2 and actual[67] == before[82], (bits, fault, 'trap')
        assert actual[69] == (0 if isinstance(fault, int) else word), (bits, fault, 'tval', actual[69])
        illegal += 1
    else:
        def lanes(reg):
            raw = before[100+2*reg] | (before[101+2*reg] << 64)
            xs = [(raw >> (bits*i)) & ((1 << bits)-1) for i in range(8)]
            return [x if x < (1 << (bits-1)) else x-(1 << bits) for x in xs]
        total = sum(x*y for x,y in zip(lanes(vs1), lanes(vs2)))
        expected[2*vd] = total & ((1 << (32 if bits == 8 else 64))-1)
        expected[2*vd+1] = 0
        assert actual[82] == before[82]+4
        valid += 1
    assert actual[100:164] == expected, (bits, fault, regs, 'vector')
    assert actual[164:171] == before[164:171], (bits, fault, 'CSR')
    assert actual[:64] == before[:64], 'scalar/floating registers changed'

for seed in (1, 0x56444f54, 0x9e3779b9, 0xdeadbeef):
    rng = random.Random(seed)
    for bits in (8, 16):
        lo = -(1 << (bits-1)); hi = -lo-1
        aliases = ((10,8,9), (8,8,9), (9,8,9), (8,8,8), (10,0,9), (10,8,0), (0,8,9), (31,8,9))
        for x,y in ((lo,lo), (lo,hi), (hi,hi), (0,hi)):
            for regs in aliases: execute(rng,bits,[x]*8,[y]*8,regs)
        for _ in range(256):
            execute(rng,bits,[rng.randint(lo,hi) for _ in range(8)],
                    [rng.randint(lo,hi) for _ in range(8)],tuple(rng.randrange(32) for _ in range(3)))
        for fault in (0,1,7,9,16,'e32','e64','lmul','vill','start','off','mask'):
            execute(rng,bits,[lo]*8,[hi]*8,fault=fault)
print(f'sew16 reference PASS valid={valid} illegal={illegal} seeds=4 ABI={size}')
