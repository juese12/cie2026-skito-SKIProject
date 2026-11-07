#!/usr/bin/env python3
"""审核十二组无波形实验，仅比较相同轮次、实现及槽位。"""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('matrix_auditor',ROOT/'scripts/verify-e2e-controlled.py')
matrix=importlib.util.module_from_spec(spec);spec.loader.exec_module(matrix)

def summarize(runs):
    keys=[(r['phase'],r['pressure']) for r in runs]
    matrix.c.need(keys==matrix.MATRIX,'missing/reordered/duplicate matrix arms')
    by_arm={};arms=[]
    for run in runs:
        calls=run['calls']
        expected=[(r,s,(r&1)^s) for r in range(6) for s in range(2)]
        matrix.c.need([(v['round'],v['slot'],v['impl']) for v in calls]==expected,'invalid matched-call labels')
        matrix.c.need(all(v['cycles']>0 for v in calls),'nonpositive sample')
        values={(v['round'],v['impl']):v['cycles'] for v in calls}
        by_arm[run['phase'],run['pressure']]=values
        arm=dict(phase=run['phase'],pressure=run['pressure'],all_calls=calls,groups={})
        for impl in range(2):
            for slot in range(2):
                cycles=[v['cycles'] for v in calls if v['impl']==impl and v['slot']==slot]
                arm['groups'][f'{impl}/{slot}']=dict(raw=cycles,bins=dict(Counter(cycles)),median=statistics.median(cycles))
        arms.append(arm)
    differences=[]
    for kind in ('phase','pressure'):
        comparisons=([((0,p),(s,p)) for p in range(2) for s in range(1,6)] if kind=='phase' else [((s,0),(s,1)) for s in range(6)])
        for a,b in comparisons:
            paired=[]
            for round in range(6):
                for impl in range(2):
                    baseline=by_arm[a][round,impl];changed=by_arm[b][round,impl]
                    paired.append(dict(round=round,impl=impl,slot=(round&1)^impl,baseline=baseline,changed=changed,delta=changed-baseline))
            differences.append(dict(factor=kind,baseline=list(a),changed=list(b),matched_calls=paired))
    return dict(arms=arms,matched_differences=differences,total_calls=sum(len(r['calls']) for r in runs),qualification='deterministic seed=0, 3 calls per position per arm; NO internal wave in matrix; timing sensitivity is not unique decoder/IQ causal proof; all calls retained')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();data=json.loads(args.results.read_text())
    matrix.c.need(data['status']=='PASS','incomplete matrix')
    matrix.c.need(all(matrix.c.sha(p)==h for p,h in data['inputs'].items()),'matrix input changed')
    for run in data['runs']:
        audit=matrix.audit(run['log'],run['phase'],run['pressure'])
        matrix.c.need(audit['calls']==run['calls'] and audit['log_sha256']==run['log_sha256'],'raw matrix record changed')
        image=Path(run['log']).with_suffix('').with_suffix('.bin')
        matrix.c.need(matrix.c.sha(image)==run['variant']['image_sha256'],'variant image changed')
    result=summarize(data['runs']);result.update(status='PASS',results=str(args.results),results_sha256=matrix.c.sha(args.results))
    with args.out.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(dict(status='PASS',arms=len(result['arms']),calls=result['total_calls'],matched_comparisons=len(result['matched_differences']))))

if __name__=='__main__':main()
