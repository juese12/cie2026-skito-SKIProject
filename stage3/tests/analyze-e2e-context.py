#!/usr/bin/env python3
"""描述全部诊断调用和同位置历史，不将相关性直接归为根因。"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('diagnostic',ROOT/'scripts/diagnose-e2e-context.py')
diag=importlib.util.module_from_spec(spec); spec.loader.exec_module(diag)

def describe(warm,measured,first,impl):
    need=diag.need
    need(len(warm)==len(measured)==8 and first in (0,1) and impl in (0,1),'wrong sample contract')
    need(all(v>0 for v in warm+measured),'nonpositive cycles')
    positions={str(slot):[v for r,v in enumerate(measured) if (first^(r&1)^impl)==slot] for slot in (0,1)}
    medians={slot:statistics.median(vals) for slot,vals in positions.items()}
    median=statistics.median(measured)
    warm_slot=first^1^impl  # 最后预热轮编号为 7，与正式第 7 轮的奇偶性相同。
    return dict(warm=warm,measured=measured,median=median,positions=positions,
                position_medians=medians,warm_last_slot=warm_slot,
                warm_tail_drift=warm[-1]/median-1,
                same_position_warm_tail_drift=warm[-1]/medians[str(warm_slot)]-1,
                cv=statistics.pstdev(measured)/statistics.mean(measured),
                slot_effect=medians['0']/medians['1']-1,
                half_drift=statistics.median(measured[4:])/statistics.median(measured[:4])-1)

def gather(manifests):
    runs=[]
    for path in manifests:
        matrix=json.loads(Path(path).read_text())
        diag.need([(r['mode'],r['first']) for r in matrix['runs']]==[(0,0),(0,1),(1,0),(1,1)],'incomplete/unbalanced matrix')
        diag.need(all(diag.sha(p)==h for p,h in matrix['frozen'].items()),'matrix input changed')
        for old in matrix['runs']:
            diag.need(diag.sha(old['log'])==old['log_sha256'],'recorded log changed')
            parameter=(old['mode']<<1)|old['first']
            fresh=diag.audit(old['log'],old['batches'],parameter)
            diag.need(fresh['groups']==old['groups'],'stored groups changed')
            groups={}
            warnings=[]
            for key,g in fresh['groups'].items():
                info=describe(g['warm'],g['measured'],old['first'],int(key.split('/')[1]))
                groups[key]=info
                for metric,limit in (('cv',.05),('warm_tail_drift',.10),('slot_effect',.10),('half_drift',.10)):
                    if abs(info[metric])>limit: warnings.append(f'{key}: {metric} exceeds {limit}')
            fresh['groups']=groups; fresh['warnings']=warnings
            runs.append(fresh)
    # 同位置诊断不替代原顺序样本，
    # 也不改变原稳定性门槛或正式报告。
    spec=importlib.util.spec_from_file_location('bench',ROOT/'stage3/tests/analyze-bench.py')
    bench=importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
    prefix=ROOT/'stage3/logs/20261006T060358-16-isolation-perf'
    state=json.loads(prefix.with_suffix('.state.json').read_text())
    original=[]
    for slot in state['slots']:
        if slot['profile']!='full': continue
        r=bench.audit(slot['log']); g=r['groups']['e2e']['vdot']
        warm=next(w for w in r['warmup_summaries'] if w[:2]==('e2e','vdot'))
        first=r['meta']['first']; vals=g['raw']
        warm_slot=first^1
        matched=statistics.median([v for rep,v in enumerate(vals) if (first^(rep&1))==warm_slot])
        original.append(dict(log=slot['log'],log_sha256=r['log_sha256'],first=first,
             warm_last=int(warm[4]),median=g['median'],warm_last_slot=warm_slot,
             measured_raw=vals,same_position_median=matched,
             same_position_warm_tail_drift=int(warm[4])/matched-1,
             original_warnings=r['warnings']))
    return dict(runs=runs,original=original,
        caveat='All samples retained. Matched-position comparison is descriptive only; original 5%/10% gates and warning results unchanged. No cache/branch/LSQ root cause proven.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifests',nargs='+')
    parser.add_argument('--json-out',type=Path,required=True)
    args=parser.parse_args()
    data=gather(args.manifests)
    with args.json_out.open('x') as stream: json.dump(data,stream,indent=2); stream.write('\n')
    for r in data['runs']:
        g=r['groups']['1/0']
        print(f"batches={r['batches']} mode={r['mode']} first={r['first']} warm_gap={g['warm_tail_drift']:.6%} cv={g['cv']:.6%} slot={g['slot_effect']:.6%} same_slot_gap={g['same_position_warm_tail_drift']:.6%}")
    for r in data['original']:
        print(f"ORIGINAL first={r['first']} same_slot_gap={r['same_position_warm_tail_drift']:.6%}; warnings unchanged")
