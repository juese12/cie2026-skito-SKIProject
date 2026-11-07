#!/usr/bin/env python3
"""Check actual ROB events for all nine calls in the new GEMV probe image."""
import argparse
import json
from pathlib import Path
import run as R

def need(ok,msg):
    if not ok:raise ValueError(msg)
def oracle(a,b):
    def lanes(raw):
        v=int(raw,16);return [(x-256 if x>=128 else x) for x in ((v>>(8*i))&255 for i in range(8))]
    return sum(x*y for x,y in zip(lanes(a),lanes(b)))&0xffffffff
def audit(path):
    syms=R.symbols();live={};records=[];seq=0;rows=0;last=-1;dot_outputs=0;footer=None
    with Path(path).open() as f:
        header=json.loads(next(f));need(header.get('phase')=='settled_low' and header.get('allocation_gate')=='firstUop','wrong observer schema')
        for line in f:
            r=json.loads(line)
            if r.get('type')=='footer':footer=r;need(not f.read().strip(),'data after footer');break
            rows+=1;c=r['c'];need(c>last,'unordered events');last=c
            for t,pc,inst,sew in r.get('d',[]):
                old=live.get(t);need(old is None or 'commit' in old or 'cancel' in old,'live ROB tag reuse')
                rec=dict(seq=seq,tag=t,pc=pc,instr=inst,dispatch=c);seq+=1
                live[t]=rec;records.append(rec)
            if 'i' in r:
                v=r['i'];rec=live.get(v['tag']);need(rec is not None,'untracked dot input')
                need(rec['instr']&0xfc00707f==0x200b,'input not a custom dot')
                need([v[k] for k in ('sew','vl','lmul','vm','start','vill')]==[0,8,0,1,0,0],'illegal dot config')
                need('input' not in rec,'duplicate acceptance');rec['input']=dict(v,cycle=c,expected=oracle(v['a'],v['b']))
            if 'o' in r:
                v=r['o'];rec=live.get(v['tag']);need(rec and 'input' in rec,'untracked output')
                need(c-rec['input']['cycle']==2,'dot interface latency differs')
                need([v[k] for k in ('sew','vl','lmul','vm','start','vill','illegal')]==[0,8,0,1,0,0,0],'output config differs')
                need(int(v['result'],16)==rec['input']['expected'],'full128 signed dot oracle differs')
                rec['output']=dict(v,cycle=c);dot_outputs+=1
            for t in r.get('k',[]):
                rec=live.get(t);need(rec and 'commit' not in rec and 'cancel' not in rec,'invalid commit');rec['commit']=c
            for key in ('f','r'):
                if key not in r:continue
                origin,level=r[key]
                for t,rec in live.items():
                    if 'commit' not in rec and 'cancel' not in rec:
                        delta=(t-origin)%512
                        if 0<delta<256 or (level and delta==0):rec['cancel']=c
    need(footer and footer['rows']==rows and footer['last_cycle']>=last,'incomplete events')
    committed=sorted((r for r in records if 'commit' in r),key=lambda r:r['seq'])
    suffixes=('pre_guard','start_read','start_guard','end_guard','end_read')
    markers={k:[r for r in committed if r['pc']==syms['gemv_timer_'+k]] for k in suffixes}
    need(all(len(v)==9 for v in markers.values()),'need all nine complete timer calls')
    for key,records_at_pc in markers.items():
        instruction=0xb0002473 if key=='start_read' else 0xb00022f3 if key=='end_read' else 0x00805073
        need(all(r['instr']==instruction for r in records_at_pc),'marker symbol has unexpected actual instruction: '+key)
    counts=(12,0,0,12,12,0,0,12,12);calls=[]
    labels=('vdot4-first','scalar-compute','rvv-compute','vdot1-compute','vdot4-compute',
            'scalar-e2e','rvv-e2e','vdot1-e2e','vdot4-e2e')
    for i in range(9):
        pre,start,guard,end,read=[markers[k][i] for k in suffixes]
        need(pre['seq']<start['seq']<guard['seq']<end['seq']<read['seq'],'marker order')
        body=[r for r in committed if guard['seq']<r['seq']<end['seq']]
        need(body,'empty body')
        need(pre['commit']<=start['dispatch'] and start['commit']<=guard['dispatch'],'start read/guard overtook older work')
        need(guard['commit']<=min(r['dispatch'] for r in body),'body entered before start guard retired')
        need(max(r['commit'] for r in body)<=end['dispatch'] and end['commit']<=read['dispatch'],'end read/guard overtook body')
        dots=[r for r in body if r['instr']&0xfc00707f==0x200b]
        adds=[r for r in body if r['instr']&0xfc00707f==0x57 and (r['instr']>>7)&31 in (24,25,26,27)]
        need(len(dots)==counts[i] and all('input' in r and 'output' in r for r in dots),'missing committed dot data')
        need(all(r['output']['cycle']<=r['commit'] for r in dots),'dot output after commit')
        calls.append(dict(label=labels[i],pre_commit=pre['commit'],start_commit=start['commit'],
            start_guard_commit=guard['commit'],end_guard_dispatch=end['dispatch'],end_guard_commit=end['commit'],
            end_read_commit=read['commit'],body_commits=len(body),dots=dots,adds=adds))
    need(dot_outputs>=60,'incomplete probe dot coverage')
    return dict(status='PASS',calls=calls,dot_outputs=dot_outputs,event_rows=rows,
        qualification='new GEMV image; actual ROB dispatch/retirement and full128 dot oracle; not a universal fence or DRAM persistence proof')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('events',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();data=audit(a.events);R.write(a.out,data);print('GEMV timer PASS calls=9 dot_outputs=60')
