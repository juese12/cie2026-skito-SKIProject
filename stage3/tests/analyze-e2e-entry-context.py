#!/usr/bin/env python3
"""复用已选周期 JSON，关联计时前 redirect 与译码分组。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('entry_events',Path(__file__).with_name('analyze-original-e2e-events.py'))
ev=importlib.util.module_from_spec(spec);spec.loader.exec_module(ev)

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def extract(data,targets):
    columns,rows=data['columns'],data['rows'];index={n:i for i,n in enumerate(columns)}
    def get(row,name):return row[index[name]]
    allocated={};redirects=[]
    for row in rows:
        cycle=get(row,ev.CYCLE)
        if get(row,ev.DIS+'io_enqRob_canAccept'):
            for i in range(6):
                base=ev.DIS+f'io_enqRob_req_{i}_'
                if get(row,base+'valid'):
                    tag=(get(row,base+'bits_robIdx_flag'),get(row,base+'bits_robIdx_value'))
                    allocated[tag]=dict(pc=hex(get(row,base+'bits_pc')),cycle=cycle)
        if get(row,ev.RED+'io_stage2Redirect_valid'):
            tag=(get(row,ev.RED+'io_stage2Redirect_bits_robIdx_flag'),get(row,ev.RED+'io_stage2Redirect_bits_robIdx_value'))
            entry=allocated.get(tag)
            redirects.append(dict(cycle=cycle,pc=entry['pc'] if entry else None,dispatch_cycle=entry['cycle'] if entry else None,ftq_base_pc=hex(get(row,ev.RED+'io_stage2Redirect_bits_cfiUpdate_pc')),mispredict=get(row,ev.RED+'io_stage2Redirect_bits_cfiUpdate_isMisPred'),mem_violation=get(row,ev.RED+'io_stage2Redirect_bits_debugIsMemVio')))
    decoded=ev.CORE+'backend.inner_ctrlBlock.decode.'
    results=[]
    for label,window in targets.items():
        start=window['csr_start']['cycle'];groups=[]
        for row in rows:
            cycle=get(row,ev.CYCLE)
            if not start-128<=cycle<start:continue
            pcs=[hex(get(row,decoded+f'io_in_{i}_bits_pc')) for i in range(6) if get(row,decoded+f'io_in_{i}_valid')]
            if '0x800003d0' in pcs and get(row,decoded+'io_in_0_ready'):
                groups.append(dict(cycle=cycle,offset_from_csr_dispatch=cycle-start,pcs=pcs,marker_slot=pcs.index('0x800003d0')))
        ev.need(groups,'missing pre-timer marker decode group')
        context=[dict(**r,offset_from_csr_dispatch=r['cycle']-start) for r in redirects if start-128<=r['cycle']<start]
        selectors=[r for r in context if r['pc']=='0x80000344' and r['mispredict']]
        group=groups[-1]
        if selectors:ev.need(group['cycle']>selectors[-1]['cycle'],'marker group not after selector recovery')
        results.append(dict(label=label,target=window['target'],csr_dispatch_cycle=start,pre_timer_redirects=context,selector_mispredicts=len(selectors),marker_groups=groups,final_marker_group=group,qualification='decode input snapshot is not committed work; last marker group follows observed selector redirect if present; association is not an intervention on predictor state or IQ assignment'))
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reused',type=Path)
    parser.add_argument('--one',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    paths=[args.reused.with_suffix(s) for s in ('.events.json','.cycles.json')]
    events=json.loads(paths[0].read_text());data=json.loads(paths[1].read_text())
    ev.need(events['status']=='PASS','reused events not finalized')
    results=extract(data,events['windows'])
    if args.one:
        paths += [args.one.with_suffix(s) for s in ('.events.json','.cycles.json')]
        one=json.loads(paths[-2].read_text());cycles=json.loads(paths[-1].read_text())
        ev.need(one['status']=='PASS','single-window events not finalized')
        target=one['comparisons'][0]['windows']['slow']
        results+=extract(cycles,{'intermediate':target})
    with args.out.open('x') as stream:json.dump(dict(status='PASS',contexts=results,inputs={str(p):sha(p) for p in paths},script_sha256=sha(Path(__file__))),stream,indent=2)
    print(json.dumps([dict(label=r['label'],cycles=r['target']['cycles'],selector_mispredicts=r['selector_mispredicts'],marker_slot=r['final_marker_group']['marker_slot']) for r in results]))

if __name__=='__main__':main()
