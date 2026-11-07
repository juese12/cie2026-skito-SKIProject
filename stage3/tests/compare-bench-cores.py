#!/usr/bin/env python3
"""比较分别审核的四进程 v3 队列，保留全部样本及警告。"""
import argparse
import importlib.util
import json
import statistics
from pathlib import Path

spec = importlib.util.spec_from_file_location('bench', Path(__file__).with_name('analyze-bench.py'))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def gather(manifest):
    paths = [Path(line) for line in Path(manifest).read_text().splitlines() if line]
    bench.need(len(paths) == 4, 'need exactly four independent processes per core')
    bench.need(all(p.name.endswith('-bench.log') for p in paths), 'invalid summary manifest')
    runs = [bench.audit(p.with_name(p.stem + '.full.log')) for p in paths]
    summary = bench.aggregate(runs)
    bench.need(all(r['meta']['schema'] == 3 and r['meta']['profile'] == 'full' for r in runs),
               'core comparison requires original v3 full protocol')
    bench.need([r['meta']['first'] for r in runs] == [0,1,0,1], 'unexpected counterbalanced order')
    return dict(runs=runs, series=summary)


def compare(before_manifest, after_manifest):
    before, after = gather(before_manifest), gather(after_manifest)
    for old, new in zip(before['runs'], after['runs']):
        bench.need(old['meta'] == new['meta'], 'measurement configuration changed')
        bench.need(all(old['artifacts'][r] == new['artifacts'][r] for r in ('ref','image')),
                   'reference model or v3 image changed')
        bench.need(old['runtime_parameter'] == new['runtime_parameter'], 'runtime overlay changed')
    bench.need(before['runs'][0]['artifacts']['emu'] != after['runs'][0]['artifacts']['emu'],
               'old/new cores have identical artifact identity')
    groups = {}
    for kind in bench.KINDS:
        pairs = []
        for index, (old, new) in enumerate(zip(before['runs'], after['runs'])):
            med = {f'{side}_{impl}': r['groups'][kind][impl]['median']
                   for side,r in [('before',old),('after',new)] for impl in bench.IMPLS}
            pairs.append(dict(run=index, first=old['meta']['first'], **med,
                              vdot_old_over_new=med['before_vdot']/med['after_vdot'],
                              rvv_control_old_over_new=med['before_rvv']/med['after_rvv']))
        groups[kind] = dict(pairs=pairs,
                           vdot_gain=bench.distribution([p['vdot_old_over_new'] for p in pairs]),
                           rvv_control=bench.distribution([p['rvv_control_old_over_new'] for p in pairs]),
                           by_order={str(first): statistics.median(p['vdot_old_over_new'] for p in pairs
                                                                   if p['first']==first) for first in (0,1)})
    return dict(status='PASS', before=before, after=after, groups=groups,
                thresholds=dict(cv=0.05, drift=0.10),
                caveat='Chronological same-order run-median comparisons, not simultaneous randomized core trials. All raw samples and both stability warnings retained; RVV is an unadjusted control. Whole guest intervals, NOT isolated FU latency, PPA or application speedup.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before_manifest'); parser.add_argument('after_manifest')
    parser.add_argument('--json-out', required=True)
    args = parser.parse_args()
    bench.need(not Path(args.json_out).exists(), 'refusing to overwrite comparison')
    result = compare(args.before_manifest, args.after_manifest)
    with Path(args.json_out).open('x') as f:
        f.write(json.dumps(result, indent=2)+'\n')
    for kind,g in result['groups'].items():
        print(f"{kind}: vdot old/new median={g['vdot_gain']['median']:.6f}, RVV control old/new={g['rvv_control']['median']:.6f}, by_order={g['by_order']}")
    print(result['caveat'])
