#!/usr/bin/env python3
"""用当前模型的 ROB 事件验证 v4 CSR 计时边界和点积数据对齐。"""
import argparse
import json
import subprocess
import common as C

def audit(path,diagnostic=False):
    syms=C.symbols();functions={}
    raw=subprocess.check_output(['riscv64-linux-gnu-nm','-S',str(C.ELF)],text=True)
    for row in raw.splitlines():
        p=row.split()
        if len(p)==4 and p[-1] in ('perf_e8_dot','perf_e8_rvv','perf_e16_dot','perf_e16_rvv'):
            functions[p[-1]]=(int(p[0],16),int(p[0],16)+int(p[1],16))
    C.need(len(functions)==4,'missing kernel bounds')
    live={};records=[];seq=0;rows=0;last=-1;dot_outputs=0
    with open(path) as f:
        header=json.loads(next(f))
        expected=dict(type='header',schema=1,phase='settled_low',rob_entries=160,allocation_gate='firstUop')
        if not diagnostic:expected['stop_cycle']=100000
        C.need(header==expected,'wrong bounded event schema')
        footer=None
        for line in f:
            try:r=json.loads(line)
            except json.JSONDecodeError:
                if diagnostic:break
                raise
            if r.get('type')=='footer':footer=r;C.need(not f.read().strip(),'events after footer');break
            rows+=1;c=r['c'];C.need(c>last,'unordered events');last=c
            for t,pc,inst,sew in r.get('d',[]):
                C.need(0<=t<512 and t%256<160,'bad ROB tag')
                old=live.get(t);C.need(old is None or 'commit' in old or 'cancel' in old,'live ROB reused')
                rec=dict(seq=seq,tag=t,pc=pc,instr=inst,dispatch=c);seq+=1;live[t]=rec
                rec['fn']=next((name for name,(lo,hi) in functions.items() if lo<=pc<hi),None)
                if rec['fn']:records.append(rec)
            if 'i' in r:
                v=r['i'];rec=live.get(v['tag'])
                if rec and rec['fn']:
                    C.need(rec['instr']&0xfc00707f==0x200b,'dot input has a non-dot ROB instruction')
                    bits=16 if '_e16_' in rec['fn'] else 8
                    C.need([v[k] for k in ('sew','vl','lmul','vm','start','vill')]==[int(bits==16),8,0,1,0,0],'dot configuration misaligned')
                    C.need('input' not in rec,'duplicate dot acceptance')
                    rec['input']=dict(v,cycle=c,expected=C.oracle(v['a'],v['b'],bits))
            if 'o' in r:
                v=r['o'];rec=live.get(v['tag'])
                if rec and rec['fn'] and 'input' in rec:
                    bits=16 if '_e16_' in rec['fn'] else 8
                    C.need('output' not in rec and c-rec['input']['cycle']==2,'dot latency/alignment mismatch')
                    C.need([v[k] for k in ('sew','vl','lmul','vm','start','vill','illegal')]==[int(bits==16),8,0,1,0,0,0],'output configuration misaligned')
                    C.need(int(v['result'],16)==rec['input']['expected'],'dot result disagrees with independent full128 oracle')
                    rec['output']=dict(v,cycle=c);dot_outputs+=1
            for t in r.get('k',[]):
                rec=live.get(t);C.need(rec is not None and 'commit' not in rec and 'cancel' not in rec,'untracked/duplicate/canceled ROB commit')
                rec['commit']=c
                if rec['fn'] is None:live.pop(t)
            for key in ('f','r'):
                if key not in r:continue
                origin,level=r[key]
                for t,rec in list(live.items()):
                    if 'commit' in rec or 'cancel' in rec:continue
                    delta=(t-origin)%512
                    if 0<delta<256 or (level and delta==0):
                        rec['cancel']=c
                        if rec['fn'] is None:live.pop(t)
        if not diagnostic:
            C.need(footer and footer['rows']==rows and footer['last_cycle']>=last and
                   footer['bounded'] and footer['last_cycle']==header['stop_cycle']+1,'missing/truncated bounded event footer')
    calls=[];counts={}
    for name in functions:
        committed=sorted((r for r in records if r['fn']==name and 'commit' in r),key=lambda r:r['seq'])
        markers={suffix:[r for r in committed if r['pc']==syms[name+'_'+suffix]]
          for suffix in ('pre_guard','start_read','start_guard','end_guard','end_read')}
        n=len(markers['start_read']);C.need(n==42 and all(len(v)==n for v in markers.values()),'incomplete probe call set '+name)
        counts[name]=n
        for i in range(n):
            pre,start,guard,end,read=[markers[k][i] for k in ('pre_guard','start_read','start_guard','end_guard','end_read')]
            C.need(pre['seq']<start['seq']<guard['seq']<end['seq']<read['seq'],'marker order mismatch')
            C.need(pre['commit']<=start['dispatch'],'start read overtook pre-drain')
            C.need(start['commit']<=guard['dispatch'],'start guard overtook start read')
            body=[r for r in committed if guard['seq']<r['seq']<end['seq']]
            C.need(body and guard['commit']<=min(r['dispatch'] for r in body),'kernel dispatched before start marker committed')
            C.need(max(r['commit'] for r in body)<=end['dispatch'],'end marker dispatched before body retired')
            C.need(end['commit']<=read['dispatch'],'end read overtook end marker')
            dots=[r for r in body if r['instr']&0xfc00707f==0x200b]
            if name.endswith('_dot'):
                C.need(dots and all('input' in r and 'output' in r for r in dots),'committed dot body lacks real data events')
                C.need(all(start['commit']<=r['input']['cycle']<=r['output']['cycle']<=end['commit'] for r in dots),'dot outside measured boundaries')
            else:C.need(not dots,'RVV baseline executes custom dot')
            calls.append(dict(function=name,index=i,pre_commit=pre['commit'],start_commit=start['commit'],
              start_guard_commit=guard['commit'],first_body_dispatch=min(r['dispatch'] for r in body),
              last_body_commit=max(r['commit'] for r in body),end_guard_dispatch=end['dispatch'],
              end_guard_commit=end['commit'],end_read_dispatch=read['dispatch'],body_commits=len(body),dots=len(dots)))
    return dict(status='DIAGNOSTIC_ONLY' if diagnostic else 'PASS',calls=counts,boundaries=calls,observed_dot_outputs=dot_outputs,event_rows=rows,
      event_sha256=C.sha(path),elf_sha256=C.sha(C.ELF),phase='settled_low',
      qualification='specific current event model and v4 probe; retirement order and full128 dot alignment; not a general ISA fence or DRAM-persistence proof')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('events');p.add_argument('--out',required=True)
    a=p.parse_args();r=audit(a.events)
    with open(a.out,'x') as f:json.dump(r,f,indent=2)
    print(json.dumps({k:v for k,v in r.items() if k!='boundaries'}))
