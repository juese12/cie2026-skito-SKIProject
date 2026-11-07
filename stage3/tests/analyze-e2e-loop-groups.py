#!/usr/bin/env python3
"""利用已有选定信号 JSON 解释三种实测循环档位。"""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('loop_common',Path(__file__).with_name('analyze-e2e-entry-context.py'))
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
ev=entry.ev

def extract(data,targets):
    idx={n:i for i,n in enumerate(data['columns'])};decode=ev.CORE+'backend.inner_ctrlBlock.decode.'
    def get(row,name):return row[idx[name]]
    results=[]
    for label,window in targets.items():
        target=window['target'];tails=Counter();queues=Counter()
        for row in data['rows']:
            if not target['start']<=get(row,ev.MCYCLE)<target['end']:continue
            if get(row,decode+'decoderComp.state')==1 and not get(row,decode+'decoderComp.io_in_valid') and get(row,decode+'io_in_0_ready'):
                pcs=tuple(hex(get(row,decode+f'io_in_{i}_bits_pc')) for i in range(6) if get(row,decode+f'io_in_{i}_valid'))
                if pcs:tails[pcs]+=1
            if all(get(row,ev.DIS+f'io_fromRename_{i}_valid') for i in range(5)) and get(row,ev.DIS+'io_fromRename_0_bits_pc')==0x80000430 and get(row,ev.DIS+'io_fromRename_4_bits_pc')==0x800003dc:
                selections=tuple(tuple(j for j in range(4) if get(row,ev.DIS+f'uopSelIQ_{i}_{j}')) for i in (0,2,3,4))
                blocked=get(row,ev.DIS+'uopBlockByIQ_4')
                ready=tuple(get(row,ev.DIS+f'io_toIssueQueues_{2*j}_ready') for j in range(4))
                queues[selections,blocked,ready]+=1
        results.append(dict(label=label,target=target,active_without_next_complex_groups=[dict(pcs=list(pcs),count=n) for pcs,n in tails.items()],tail_packets=[dict(iq_slots_0_2_3_4=[list(s) for s in selection],slot4_blocked=blocked,int_iq_enqueue_ready=list(ready),count=n) for (selection,blocked,ready),n in queues.items()],qualification='sampled decode inputs and selected dispatch packets, not committed instruction counts; group events not additive total-cycle counters'))
    return results

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reused',type=Path);parser.add_argument('one',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();paths=[];results=[]
    for prefix,is_one in ((args.reused,False),(args.one,True)):
        paths += [prefix.with_suffix(s) for s in ('.events.json','.cycles.json')]
        event=json.loads(paths[-2].read_text());data=json.loads(paths[-1].read_text())
        ev.need(event['status']=='PASS','incomplete source evidence')
        targets={'intermediate':event['comparisons'][0]['windows']['slow']} if is_one else event['windows']
        results+=extract(data,targets)
    result=dict(status='PASS',groups=results,inputs={str(p):entry.sha(p) for p in paths},script_sha256=entry.sha(Path(__file__)))
    with args.out.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(results))

if __name__=='__main__':main()
