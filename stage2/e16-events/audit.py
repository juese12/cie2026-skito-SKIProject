#!/usr/bin/env python3
"""严格审核短 e16 运行中的分配、输入、结果、接受取消及提交。"""
import argparse
import hashlib
import json
from pathlib import Path
import re

NAMES=('control_branch_pc','control_branch_dot','control_branch_dot_v0',
       'control_exception_pc','control_younger_dot','control_younger_dot_v0',
       'control_younger_dot_alias','control_exception_resume')
PRINTED=('branch','branch_dot','branch_v0','illegal','young','young_v0','young_alias','resume')

def need(ok,message):
    if not ok:raise ValueError(message)

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def guest_text(text):
    # UART 逐字符输出，宿主跟踪或性能行可能插在字符之间；
    # 仅删除格式完整且已知的宿主记录。
    text=re.sub(r'\[\d{2}\] (?:commit|exception|interrupt) pc [^\n]*\n','',text)
    return re.sub(r'\[(?:PERF|DEBUG|INFO) *\]\[time=[^\n]*\n','',text)

def oracle(a,b):
    def lanes(raw):
        raw=int(raw,16)
        return [(x if x<32768 else x-65536) for x in ((raw>>(16*i))&65535 for i in range(8))]
    return sum(x*y for x,y in zip(lanes(a),lanes(b))) & ((1<<64)-1)

def audit_events(rows,symbols,require_coverage=True):
    live={};records=[];flushes=[];seq=0;last=-1;decisions={};pending=[]
    wrong={symbols[n] for n in NAMES[1:3]};young={symbols[n] for n in NAMES[4:7]}
    targets=wrong|young;wanted=set(symbols.values())
    witness=0;inputs=outputs=allocations=commits=0
    def tag(t):
        need(isinstance(t,int) and 0<=t<512 and t%256<160,'invalid ROB tag')
        return t
    def config(v):
        need([v[k] for k in ('sew','vl','lmul','vm','start','vill')]==[1,8,0,1,0,0],
             'target is not actual legal e16/VL8 execution')
    for row in rows:
        cycle=row['c'];need(cycle>last,'unordered/duplicate event cycle');last=cycle
        for event in list(pending):
            need(cycle==event['cycle']+1,'missing next-cycle precise exception confirmation')
            need(row.get('x')==[0xffffffff,1],'wrong precise illegal exception payload')
            event['exception_confirmed']=cycle;pending.remove(event)
        for t,pc,inst,sew in row.get('d',[]):
            tag(t);old=live.get(t)
            need(old is None or 'commit' in old or 'cancel' in old,'live ROB allocation reused')
            rec=dict(seq=seq,tag=t,pc=pc,instr=inst,sew=sew,dispatch=cycle)
            live[t]=rec;seq+=1;allocations+=1;decisions.pop(t,None)
            if pc in wanted:records.append(rec)
            if pc in targets:
                need(inst&0xfc00707f==0x200b and bool(inst&(1<<25)) and sew==1,
                     'target allocation not unmasked e16 vdot')
        if 'i' in row:
            v=row['i'];rec=live.get(tag(v['tag']))
            if rec is not None and rec['pc'] in targets:
                config(v);need('input' not in rec,'duplicate target FU acceptance')
                need('cancel' not in rec and 'commit' not in rec,'FU acceptance after retirement/cancel')
                need(len(v['a'])==len(v['b'])==32,'input is not full 128-bit')
                rec['input']=dict(v,cycle=cycle,expected=oracle(v['a'],v['b']));inputs+=1
        if 'o' in row:
            v=row['o'];rec=live.get(tag(v['tag']))
            if rec is not None and rec['pc'] in targets:
                config(v);need(v['illegal']==0,'target output carries an illegal exception')
                need('input' in rec and 'output' not in rec,'output lacks unique input')
                need(cycle-rec['input']['cycle']==2,'fixed-two-stage input/output alignment mismatch')
                result=int(v['result'],16)
                need(len(v['result'])==32 and result==rec['input']['expected'],'full 128-bit result disagrees with e16 oracle')
                rec['output']=dict(v,cycle=cycle);outputs+=1
                witness+=result==8589934592
        for t,taken,miss in row.get('b',[]):
            rec=live.get(tag(t))
            if rec is not None and rec['pc']==symbols[NAMES[0]] and taken and miss:
                need(rec['instr']&127==0x63,'mispredict origin not the intended branch')
                decisions[t]=dict(cycle=cycle,seq=rec['seq'])
        for t in row.get('k',[]):
            rec=live.get(tag(t));need(rec is not None,'commit without observed allocation')
            need('cancel' not in rec,'canceled allocation committed')
            need(rec['pc'] not in young,'illegal instruction younger vdot committed')
            need('commit' not in rec,'duplicate architectural commit')
            rec['commit']=cycle;commits+=1
            if rec['pc'] in wrong:need('output' in rec,'legal training commit lacks valid e16 execution')
            if rec['pc']==symbols[NAMES[0]]:
                for event in flushes:
                    if event['kind']=='branch' and event['origin_seq']==rec['seq']:event['settled']=cycle
            if rec['pc']==symbols[NAMES[7]]:
                for event in flushes:
                    if event['kind']=='exception' and 'settled' not in event and event['cycle']<cycle:
                        event['settled']=cycle
            if rec['pc'] not in wanted:live.pop(t)
        for key in ('f','r'):
            if key not in row:continue
            origin,level=row[key];tag(origin)
            rec=live.get(origin);kind='other'
            if key=='f' and rec is not None and rec['pc']==symbols[NAMES[3]]:
                kind='exception';need(rec['instr']==0xffffffff,'unexpected illegal instruction')
            if key=='r' and rec is not None and rec['pc']==symbols[NAMES[0]] and origin in decisions:
                need(decisions[origin]['seq']==rec['seq'],'stale branch decision generation')
                kind='branch'
            event=dict(cycle=cycle,origin=origin,origin_seq=None if rec is None else rec['seq'],kind=kind,victims=[])
            if kind=='branch':
                event['decision']=decisions[origin]['cycle']
                if 'commit' in rec:event['settled']=rec['commit']
            for t,victim in list(live.items()):
                if 'commit' in victim or 'cancel' in victim:continue
                delta=(t-origin)%512
                if 0<delta<256 or (level and delta==0):
                    victim['cancel']=cycle;victim['cancel_kind']=kind
                    if victim['pc'] in targets:event['victims'].append(victim['seq'])
                    if victim['pc'] not in wanted:live.pop(t)
            if kind!='other':
                flushes.append(event)
                if kind=='exception':pending.append(event)
    need(not pending,'truncated exception tail')
    by_seq={r['seq']:r for r in records}
    proof={}
    for kind,pcs in (('branch',wrong),('exception',young)):
        eligible=[]
        for event in flushes:
            seen={by_seq[s]['pc'] for s in event['victims'] if 'input' in by_seq[s] and
                  'output' in by_seq[s] and by_seq[s]['output']['cycle']<=event['cycle']}
            if event['kind']==kind and pcs<=seen and 'settled' in event and (kind!='exception' or 'exception_confirmed' in event):
                eligible.append(event)
        if require_coverage:need(eligible,f'COVERAGE_MISSING: no complete executed e16 {kind} cancellation')
        proof[kind]=eligible
    positive={r['pc'] for r in records if 'commit' in r}
    if require_coverage:
        need(wrong<=positive,'missing legitimate e16 training commits')
        need(witness>0,'missing full-width e16 witness result 8589934592')
    return dict(status='PASS',proof=proof,records=records,flushes=flushes,
        counts=dict(allocations=allocations,commits=commits,inputs=inputs,outputs=outputs,witness_outputs=witness),
        last_event_cycle=last,qualification='actual tagged e16 acceptance/result before accepted cancel; no same-allocation commit; not universal formal verification')

def load_events(path,symbols):
    with Path(path).open() as f:
        header=json.loads(next(f))
        need(header==dict(type='header',schema=1,phase='settled_low',rob_entries=160,allocation_gate='firstUop'),
             'wrong event schema/phase/architectural allocation gate')
        footer=None;count=0
        def rows():
            nonlocal footer,count
            for line in f:
                row=json.loads(line)
                if row.get('type')=='footer':
                    footer=row;need(not f.read().strip(),'events after footer');break
                count+=1;yield row
        result=audit_events(rows(),symbols)
        need(footer is not None and footer['rows']==count and footer['last_cycle']>=result['last_event_cycle'],
             'missing/truncated event footer')
        result.update(event_rows=count,event_bytes=Path(path).stat().st_size,event_sha256=sha(path))
        return result

def audit_log(path):
    text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',Path(path).read_text(errors='replace'))
    guest=guest_text(text)
    need('Difftest enabled' in text and text.count('HIT GOOD TRAP')==1,'missing differential GOOD TRAP')
    need(not re.search(r'FAIL|HIT BAD TRAP|ABORT|different at pc',text+'\n'+guest),'CPU architectural failure')
    need(re.findall(r'^\[process exit\] (\d+)$',text,re.M)==['0'],'missing actual process exit zero')
    need(guest.count('short PASS data_seeds=4 train=128 probe=8 exception=8 contract=e16 witness=8589934592')==1,'missing exact short coverage')
    match=re.search('short symbols '+' '.join(k+'=([0-9a-f]+)' for k in PRINTED),guest)
    need(match is not None,'missing runtime symbols')
    symbols={name:int(v,16) for name,v in zip(NAMES,match.groups())}
    inst,cycles=map(int,re.search(r'Core-0 instrCnt = (\d+), cycleCnt = (\d+)',text).groups())
    return dict(status='PASS',instructions=inst,cycles=cycles,symbols=symbols,log_sha256=sha(path))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('log',type=Path);p.add_argument('events',type=Path)
    p.add_argument('--symbols',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();arch=audit_log(args.log)
    elf_symbols={}
    for row in args.symbols.read_text().splitlines():
        parts=row.split()
        if len(parts)==3 and parts[2] in NAMES:elf_symbols[parts[2]]=int(parts[0],16)
    need(elf_symbols==arch['symbols'],'ELF/runtime symbol mismatch')
    result=load_events(args.events,arch['symbols'])
    result.update(architecture=arch,symbols_sha256=sha(args.symbols))
    with args.out.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(status='PASS',counts=result['counts'],proof={k:len(v) for k,v in result['proof'].items()},
                         event_rows=result['event_rows'],event_bytes=result['event_bytes'])))

if __name__=='__main__':main()
