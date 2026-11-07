#!/usr/bin/env python3
"""保留全部 48 个配对定向样本，并联合已审核的 IQ 证据，不筛选样本。"""
import argparse
import importlib.util
import json
import statistics
from pathlib import Path

spec=importlib.util.spec_from_file_location("oldvd",Path(__file__).with_name("check-oldvd-wave.py"))
audit=importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def compare(before_log,after_log,before_wave_audit,after_wave_audit):
    before,after=audit.audit_log(before_log),audit.audit_log(after_log)
    waves=[json.loads(Path(p).read_text()) for p in (before_wave_audit,after_wave_audit)]
    for log,wave in zip((before,after),waves):
        audit.need(wave['status']=='PASS' and wave['log_sha256']==log['log_sha256'],
                   'wave audit must match the successful actual CPU log')
        audit.need(wave['completed_dot']>=1400,'insufficient dynamic coverage')
    audit.need(waves[0]['false_wait_dot']>0 and waves[1]['false_wait_dot']==0,
               'old-destination obstruction not proven eliminated')
    observations=[r for r in waves[1]['records'] if 'source_observation' in r]
    audit.need(observations,'no after-source observations')
    for r in observations:
        types=r['source_observation']['types']
        audit.need(types[2]==0,'after dot still reads old destination')
        if r['vd']==0 and r['vs1']!=0 and r['vs2']!=0:
            audit.need(types[3]==0,'after independent v0 destination still has auxiliary v0 source')
    true_alias=[r for r in observations if r['vd'] in (r['vs1'],r['vs2']) and r['wait_phases']]
    audit.need(true_alias,'no retained actual true-alias readiness waits')
    audit.need(any(r['vd']==0 and r['source_observation']['types'][3]==8 for r in true_alias),
               'missing retained real v0 source')
    groups=[]
    for policy in range(4):
        for kind in range(6):
            raw=[[s['cycles'] for s in run['samples'] if s['policy']==policy and s['kind']==kind]
                 for run in (before,after)]
            med=[statistics.median(r) for r in raw]
            groups.append(dict(policy=policy,kind=kind,before_raw=raw[0],after_raw=raw[1],
                               before_median=med[0],after_median=med[1],
                               ratio=med[0]/med[1],cycles_saved=med[0]-med[1]))
    return dict(status='PASS',before=before,after=after,groups=groups,
                before_wave_sha256=waves[0]['wave_sha256'],after_wave_sha256=waves[1]['wave_sha256'],
                before_false_wait_dot=waves[0]['false_wait_dot'],after_false_wait_dot=waves[1]['false_wait_dot'],
                after_true_alias_wait_dot=len(true_alias),
                caveat='Directed 32-dot whole intervals, two samples/group in one process. NOT application/PPA, isolated latency, peak II or statistical confidence. All 48 samples per core retained.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('before_log'); p.add_argument('after_log')
    p.add_argument('before_wave_audit'); p.add_argument('after_wave_audit')
    p.add_argument('--json-out',required=True); args=p.parse_args()
    audit.need(not Path(args.json_out).exists(),'refusing to overwrite comparison')
    result=compare(args.before_log,args.after_log,args.before_wave_audit,args.after_wave_audit)
    with Path(args.json_out).open('x') as f: f.write(json.dumps(result,indent=2)+'\n')
    print('policy,kind,before_raw,after_raw,before_median,after_median,ratio,cycles_saved')
    for g in result['groups']:
        print(','.join(str(g[k]) for k in ('policy','kind','before_raw','after_raw','before_median','after_median','ratio','cycles_saved')))
    print(result['caveat'])
