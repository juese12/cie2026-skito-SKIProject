#!/usr/bin/env python3
"""审核已有 e8/e16 模块波形的隔离与保持，不据此宣称功耗收益。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('wave', type=Path)
p.add_argument('--out', type=Path, required=True)
args = p.parse_args()
spec = importlib.util.spec_from_file_location('iso', Path(__file__).parents[1]/'tests/check-isolation-wave.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
counts = dict(edges=0, e8=0, e16=0, disabled_holds=0, mixed_overlap=0)
for pre, post in m.edges(args.wave, True):
    counts['edges'] += 1
    dot0 = bool(pre[m.HARNESS+'fu_io_in_valid'] and pre[m.TOP+'io_op'] == 0x160)
    dot1 = bool(pre[m.HARNESS+'validPipe_1'] and pre[m.FU+'validVecThisFu_1'] and pre[m.HARNESS+'ctrlPipe_1_fuOpType'] == 0x160)
    mac0 = bool(pre[m.HARNESS+'fu_io_in_valid'] and not dot0)
    assert pre[m.DOT+'io_enable_0'] == dot0
    assert pre[m.DOT+'io_enable_1'] == dot1
    if dot0: counts['e16' if pre[m.TOP+'io_config_vtype_vsew'] == 1 else 'e8'] += 1
    counts['mixed_overlap'] += int(mac0 and dot1)
    for name in ('vs1','vs2'):
        assert pre[m.DOT+'isolatedV'+name[1:]] == (pre[m.TOP+'io_'+name] if dot0 else 0)
    if not mac0: assert all(pre[n] == 0 for n in m.MAC_DATA+m.MAC_CONTROL)
    for group, names in m.GROUPS.items():
        for name in names:
            enable = dot0 if group == 'dot_products' else dot1 if group == 'dot_sum' else mac0
            if group == 'mac_result_stage2':
                lane = int(name.split('vimacs_')[1][0])
                enable = pre[m.FU+f'vimacs_{lane}.fireS1_last_r']
            if not enable:
                assert pre[name] == post[name], (name, pre['time'])
                counts['disabled_holds'] += 1
assert counts['e8'] > 50 and counts['e16'] > 50 and counts['mixed_overlap'] > 0, counts
result = dict(status='PASS', counts=counts, wave=str(args.wave),
              sha256=hashlib.sha256(args.wave.read_bytes()).hexdigest(),
              scope='module settled-edge isolation and hold checks; not PPA or CPU commit proof')
with args.out.open('x') as f: json.dump(result, f, indent=2)
print(json.dumps(result))
