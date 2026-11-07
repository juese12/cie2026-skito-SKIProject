#!/usr/bin/env python3
"""Strictly reconstruct inputs, parse every sample, and report per-process ratios."""
import argparse
import csv
import json
from pathlib import Path
import re
import statistics as S
import run as R

NAMES=('Scalar','RVV 四行','vdot 单行','vdot 四行')
def need(ok,msg):
    if not ok:raise ValueError(msg)
def values(seed,m,k):
    def nxt():
        nonlocal seed
        seed=(seed^(seed<<13))&0xffffffff;seed=(seed^(seed>>17))&0xffffffff;seed=(seed^(seed<<5))&0xffffffff
        a=seed&255;return a-256 if a>=128 else a
    x=[nxt() for _ in range(k)];w=[[nxt() for _ in range(k)] for _ in range(m)]
    return [sum(a*b for a,b in zip(row,x)) for row in w]
def parse(result):
    raw=R.clean(Path(result['log']));profile=result['profile']
    need(result['status']=='PASS' and result['returncode']==0,'failed process')
    need(raw.count('HIT GOOD TRAP')==1 and 'Difftest enabled' in raw and '[process exit] 0' in raw,'missing success evidence')
    need(not re.search(r'gemv FAIL|HIT BAD TRAP|ABORT|different at pc',raw),'architectural failure')
    matches=re.findall(r'^gemv meta schema=1 profile=(\d+) first=(\d+) seed=([0-9a-f]+) warm=(\d+) reps=(\d+) cases=(\d+)$',raw,re.M)
    need(len(matches)==1,'metadata missing/duplicate')
    p,first,seed,warms,reps,cases=matches[0];warms,reps,cases=map(int,(warms,reps,cases))
    need((int(p),int(first),int(seed,16))==(profile,result['first'],result['data']),'parameters differ')
    need((warms,reps,cases)==((2,6,30) if profile==2 else (1,2,12)),'coverage count differs')
    need(f'gemv PASS profile={profile} checked_each_row=1 guards=1 signed=1 data_seeds=4' in raw,'incomplete final checks')
    checks=re.findall(r'^gemv checks impl=(\d+) calls=(\d+)$',raw,re.M)
    need(sorted((int(a),int(b)) for a,b in checks)==[(i,2*cases+4*(warms+reps)) for i in range(4)],'missing kernel checks')
    shapes=((16,64),(17,65)) if profile==2 else ((4,16),(5,17));case_rows={}
    for c,m,k,kp,data,y in re.findall(r'^gemv case id=(\d+) m=(\d+) k=(\d+) kp=(\d+) data=([0-9a-f]+) y=([\d,\-]+)$',raw,re.M):
        c,m,k,kp,data=map(int,(c,m,k,kp,int(data,16)))
        need(c in (0,1) and c not in case_rows and (m,k)==shapes[c] and kp==(k+7)//8*8,'wrong shape')
        expected_seed=(result['data']^(0x13579bdf*(c+1)))&0xffffffff
        need(data==(expected_seed or 1),'data seed differs')
        answer=list(map(int,y.split(',')));need(answer==values(data,m,k),'independent matrix oracle differs')
        case_rows[c]=dict(m=m,k=k,kp=kp,data=data,y=answer)
    need(set(case_rows)=={0,1},'missing cases')
    seen=set();rows=[]
    for case,mode,impl,array in re.findall(r'^gemv seq case=(\d+) mode=(\d+) impl=(\d+) cycles=([\d,]+)$',raw,re.M):
        key=tuple(map(int,(case,mode,impl)));case,mode,impl=key
        need(case in (0,1) and mode in (0,1) and impl in range(4) and key not in seen,'duplicate/invalid samples')
        seen.add(key);array=list(map(int,array.split(',')))
        need(len(array)==warms+reps and min(array)>0,'missing/zero cycles')
        for rep,cycles in enumerate(array):rows.append(dict(process_seed=result['seed'],data_seed=result['data'],
            case=case,mode=mode,impl=impl,phase='warm' if rep<warms else 'sample',rep=rep if rep<warms else rep-warms,
            slot=(impl-result['first']-rep)%4,cycles=cycles))
    need(len(seen)==16,'incomplete sample groups')
    return dict(status='PASS',seed=result['seed'],cases=case_rows,checks=checks,rows=rows)
def analyze(directory):
    completed=json.loads((directory/'results.json').read_text());need(completed['status']=='PASS','queue incomplete')
    runs=completed['runs'];need(len(runs)==4,'need four independent processes')
    need([(r['seed'],r['first'],r['data']) for r in runs]==list(zip((101,202,303,404),range(4),(0x56444f54,1,0x9e3779b9,0xdeadbeef))),'wrong process/seed set')
    # Relocation uses only the supplied directory, never the old workspace.
    local_runs=[]
    for r in runs:
        local=dict(r);local['log']=str(directory/Path(r['log']).name)
        need(Path(local['log']).is_file(),'raw log missing from supplied directory')
        local_runs.append(local)
    parsed=[parse(r) for r in local_runs];rows=[row for p in parsed for row in p['rows']];groups=[];warnings=[]
    for case in range(2):
        for mode in range(2):
            proc=[]
            for run in parsed:
                med=[]
                for impl in range(4):
                    select=[r for r in run['rows'] if (r['case'],r['mode'],r['impl'])==(case,mode,impl)]
                    vals=[r['cycles'] for r in select if r['phase']=='sample'];median=S.median(vals);med.append(median)
                    spread=(max(vals)-min(vals))/median
                    if spread>.10:warnings.append(dict(seed=run['seed'],case=case,mode=mode,impl=impl,reason='sample range exceeds 10% median',spread=spread))
                proc.append(dict(seed=run['seed'],cycles=med,rvv_over_dot4=med[1]/med[3],scalar_over_dot4=med[0]/med[3],dot1_over_dot4=med[2]/med[3]))
            groups.append(dict(case=case,mode=mode,processes=proc,cycles=[S.median(p['cycles'][i] for p in proc) for i in range(4)],
                rvv_over_dot4=S.median(p['rvv_over_dot4'] for p in proc),scalar_over_dot4=S.median(p['scalar_over_dot4'] for p in proc),
                dot1_over_dot4=S.median(p['dot1_over_dot4'] for p in proc),rvv_ratio_range=[min(p['rvv_over_dot4'] for p in proc),max(p['rvv_over_dot4'] for p in proc)]))
    return dict(status='PASS',processes=4,total_samples=len(rows),warnings=warnings,groups=groups,runs=parsed)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=analyze(a.directory);R.write(a.out,r)
    with a.out.with_suffix('.csv').open('x',newline='') as f:
        rows=[row for run in r['runs'] for row in run['rows']];w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print('GEMV formal analysis PASS processes=4 samples='+str(r['total_samples'])+' warnings='+str(len(r['warnings'])))
if __name__=='__main__':main()
