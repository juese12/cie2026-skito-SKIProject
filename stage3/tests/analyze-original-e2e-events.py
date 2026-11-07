#!/usr/bin/env python3
"""将原镜像 VCD 流式解析为周期对齐的可见事件，不用于 PPA 分析。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

CORE='TOP.SimTop.l_soc.core_with_l2.core.'
DIS=CORE+'backend.inner_ctrlBlock.dispatch.'
CSR=CORE+'backend.inner_intExuBlock.exus_7.csr.'
RED=CORE+'backend.inner_ctrlBlock.redirectGen.'
MAC=CORE+'backend.inner_vfExuBlock.exus.Vimac.'
CYCLE=CORE+'backend.inner_ctrlBlock.rob.difftest_module_8.io_bits_cycleCnt'
MCYCLE=CSR+'csrMod.mcycle.reg_ALL'

def need(ok,message):
    if not ok: raise ValueError(message)

def selected(name):
    if name in ('TOP.clock',CYCLE,MCYCLE): return True
    short=name.rsplit('.',1)[-1]
    if name.startswith(DIS):
        return bool(re.fullmatch(r'io_enqRob_(canAccept|isEmpty|req_[0-5]_(valid|bits_(pc|instr|robIdx_flag|robIdx_value|firstUop|lastUop)))|io_fromRename_[0-5]_(valid|ready|bits_(pc|instr))|stallReason_[0-5]|io_(robFull|lqCanAccept|sqCanAccept|robHeadNotReady|toRenameAllFire)|uopBlockByIQ_[0-5]|allowDispatch_[0-5]|thisCanActualOut_[0-5]|lsqCanAccept|io_toIssueQueues_[0-9]+_(valid|ready)|uopBlockMatrix_[0-5]_[0-9]+|uopSelIQ_[0-5]_[0-9]+|io_debugTopDown_.*',short))
    if name.startswith(CORE+'backend.inner_ctrlBlock.') and name.rsplit('.',2)[-2] in ('decode','rename','renamePipeDispatch'):
        return bool(re.fullmatch(r'io_(in|out)_[0-5]_(valid|ready|bits_(pc|instr))|complexNum|io_outAllFire',short))
    if name.startswith(CORE+'backend.inner_ctrlBlock.decode.decoderComp.') and name.rsplit('.',2)[-2]=='decoderComp':
        return bool(re.fullmatch(r'io_in_(valid|ready)|io_out_complexDecodedInsts_[0-5]_(valid|ready)|state',short))
    if name.startswith(CORE+'frontend.inner_ibuffer.') and name.rsplit('.',2)[-2]=='inner_ibuffer':
        return bool(re.fullmatch(r'io_out(_[0-5])?_(valid|ready|bits_(pc|instr))|validEntryCount|validEntries|numValid|allowEnq',short))
    if name.startswith(CSR) and '.csrMod.' not in name:
        return short in ('io_out_valid','io_out_bits_ctrl_robIdx_flag','io_out_bits_ctrl_robIdx_value','io_out_bits_res_data')
    if name.startswith(RED):
        return short in ('io_stage2Redirect_valid','io_loadReplay_valid','io_oldestExuRedirect_valid','io_stage2Redirect_bits_cfiUpdate_pc','io_stage2Redirect_bits_cfiUpdate_isMisPred','io_stage2Redirect_bits_debugIsMemVio','io_stage2Redirect_bits_debugIsCtrl','io_stage2Redirect_bits_robIdx_flag','io_stage2Redirect_bits_robIdx_value','io_stage2Redirect_bits_ftqOffset')
    if name.startswith(MAC) and name[:-len(short)]==MAC:
        return short in ('io_in_valid','io_in_ready','io_in_bits_ctrl_fuOpType','io_out_valid','io_out_ready','io_out_bits_ctrl_robIdx_flag','io_out_bits_ctrl_robIdx_value')
    if re.search(r'\.inner_LoadUnit_[0-2]\.',name) and name.rsplit('.',2)[-2].startswith('inner_LoadUnit_'):
        return short in ('s2_fire_probe','s2_dcache_miss','io_dcache_resp_bits_miss','s1_tlb_miss','io_replay_valid','io_replay_ready','s2_full_fwd','s3_replayqueue_rep_cause_0','s2_bank_conflict','s2_wpu_pred_fail','s2_dcache_fast_rep','s2_mq_nack','s2_troublem')
    if name.startswith(CORE+'memBlock.inner_sbuffer.') and name.rsplit('.',2)[-2]=='inner_sbuffer':
        return bool(re.fullmatch(r'io_in_[01]_(valid|ready)|io_dcache_req_(valid|ready)|io_(sqempty|sbempty|flush_valid|flush_empty)|empty|sbuffer_state',short))
    if '.IssueQueue' in name and name.rsplit('.',2)[-2].startswith('IssueQueue'):
        return bool(re.fullmatch(r'io_deqDelay_[0-9]+_(valid|ready|bits_common_(robIdx_flag|robIdx_value|fuType|fuOpType|isFirstIssue))',short))
    return False

def stream(wave):
    scope,signals,values,columns,codes=[],{}, {},[],set()
    rows=[]
    time,old_clock=0,None
    def sample():
        nonlocal old_clock
        clock=values.get(signals['TOP.clock'])
        falling=old_clock==1 and clock==0
        old_clock=clock
        if not falling: return
        row=[values.get(signals[n]) for n in columns]
        need(all(x is not None for x in row),'unknown selected signal at time '+str(time))
        rows.append([time]+row)
    with Path(wave).open(encoding='ascii') as source:
        header=True
        for raw in source:
            line=raw.strip()
            if header:
                f=line.split()
                if line.startswith('$scope'): scope.append(f[2])
                elif line.startswith('$upscope'): scope.pop()
                elif line.startswith('$var'):
                    name='.'.join(scope+[f[4]])
                    if selected(name): signals[name]=f[3]
                elif line.startswith('$enddefinitions'):
                    required=['TOP.clock',CYCLE,MCYCLE,DIS+'io_enqRob_canAccept',CSR+'io_out_valid',CSR+'io_out_bits_res_data',RED+'io_stage2Redirect_valid',MAC+'io_in_valid',MAC+'io_out_valid']
                    for i in range(6):
                        required+=[DIS+f'io_enqRob_req_{i}_valid']
                        required+=[DIS+f'io_enqRob_req_{i}_bits_'+s for s in ('pc','instr','robIdx_flag','robIdx_value','firstUop','lastUop')]
                    need(all(n in signals for n in required),'missing required original CPU hierarchy')
                    columns=sorted(signals); codes=set(signals.values()); header=False
                continue
            if line.startswith('#'):
                if values: sample()
                time=int(line[1:])
            elif line.startswith('b'):
                bits,code=line[1:].split()
                if code in codes: values[code]=int(bits,2) if not re.search('[xz]',bits) else None
            elif line[:1] in ('0','1','x','z') and line[1:] in codes:
                values[line[1:]]=int(line[0]) if line[0] in '01' else None
    sample()
    need(rows and all(b[0]>a[0] for a,b in zip(rows,rows[1:])),'bad waveform timeline')
    return ['vcd_time']+columns, rows

def analyze(columns,rows,windows):
    idx={n:i for i,n in enumerate(columns)}
    def get(row,name): return row[idx[name]]
    def optional(row,name): return row[idx[name]] if name in idx else None
    allocated={}
    csr_events=[]
    dispatch=[]
    redirects=[]
    issues=[]
    mac_outputs=[]
    issue_ports=[n[:-len('valid')] for n in columns if re.search(r'\.IssueQueue[^.]+\.io_deqDelay_\d+_valid$',n)]
    for row in rows:
        cycle=get(row,CYCLE); mcycle=get(row,MCYCLE)
        if get(row,DIS+'io_enqRob_canAccept'):
            for i in range(6):
                base=DIS+f'io_enqRob_req_{i}_'
                if not get(row,base+'valid'): continue
                pc=get(row,base+'bits_pc'); inst=get(row,base+'bits_instr')
                tag=(get(row,base+'bits_robIdx_flag'),get(row,base+'bits_robIdx_value'))
                entry=dict(cycle=cycle,mcycle=mcycle,time=row[0],pc=hex(pc),inst=hex(inst),tag=list(tag),first=get(row,base+'bits_firstUop'),last=get(row,base+'bits_lastUop'))
                allocated[tag]=entry
                dispatch.append(entry)
        if get(row,CSR+'io_out_valid'):
            tag=(get(row,CSR+'io_out_bits_ctrl_robIdx_flag'),get(row,CSR+'io_out_bits_ctrl_robIdx_value'))
            entry=allocated.get(tag)
            if entry and entry['inst'] in ('0xb0002373','0xb0002e73'):
                csr_events.append(dict(**entry,output_cycle=cycle,output_mcycle=mcycle,data=get(row,CSR+'io_out_bits_res_data')))
        if get(row,RED+'io_stage2Redirect_valid'):
            tag=(optional(row,RED+'io_stage2Redirect_bits_robIdx_flag'),optional(row,RED+'io_stage2Redirect_bits_robIdx_value'))
            entry=allocated.get(tag)
            redirects.append(dict(cycle=cycle,mcycle=mcycle,ftq_base_pc=hex(get(row,RED+'io_stage2Redirect_bits_cfiUpdate_pc')),dispatch_pc=entry['pc'] if entry else None,tag=list(tag),mispredict=get(row,RED+'io_stage2Redirect_bits_cfiUpdate_isMisPred'),mem_violation=get(row,RED+'io_stage2Redirect_bits_debugIsMemVio')))
        for port in issue_ports:
            if not get(row,port+'valid') or not get(row,port+'ready'): continue
            tag=(get(row,port+'bits_common_robIdx_flag'),get(row,port+'bits_common_robIdx_value'))
            entry=allocated.get(tag)
            issues.append(dict(port=port,cycle=cycle,mcycle=mcycle,tag=list(tag),pc=entry['pc'] if entry else None,dispatch_cycle=entry['cycle'] if entry else None))
        if get(row,MAC+'io_out_valid') and get(row,MAC+'io_out_ready'):
            tag=(get(row,MAC+'io_out_bits_ctrl_robIdx_flag'),get(row,MAC+'io_out_bits_ctrl_robIdx_value'))
            entry=allocated.get(tag)
            mac_outputs.append(dict(cycle=cycle,mcycle=mcycle,tag=list(tag),pc=entry['pc'] if entry else None,dispatch_cycle=entry['cycle'] if entry else None))
    result={}
    for label in ('fast','slow'):
        target=windows[label]; start,end=target['start'],target['end']
        body=[r for r in rows if start<=get(r,MCYCLE)<end]
        need(len(body)==target['cycles'],'timestamp integration length differs from benchmark')
        starts=[e for e in csr_events if e['data']==start and e['inst']=='0xb0002373']
        ends=[e for e in csr_events if e['data']==end and e['inst']=='0xb0002e73']
        need(len(starts)==len(ends)==1,'missing/duplicate actual timestamp CSR output')
        events=[e for e in dispatch if start<=e['mcycle']<end and e['first']]
        counts=Counter(e['pc'] for e in events)
        anchors=[e for e in events if e['pc']=='0x800003e0']
        intervals=[b['cycle']-a['cycle'] for a,b in zip(anchors,anchors[1:])]
        issue_events=[e for e in issues if start<=e['mcycle']<end]
        outputs=[e for e in mac_outputs if start<=e['mcycle']<end]
        issue_latency={}
        for pc in sorted({e['pc'] for e in issue_events if e['pc']}):
            issue_latency[pc]=dict(Counter(e['cycle']-e['dispatch_cycle'] for e in issue_events if e['pc']==pc))
        wb_latency={}
        for pc in sorted({e['pc'] for e in outputs if e['pc']}):
            wb_latency[pc]=dict(Counter(e['cycle']-e['dispatch_cycle'] for e in outputs if e['pc']==pc))
        boolean_counts={n:sum(bool(get(r,n)) for r in body) for n in columns if n.endswith(('_valid','_ready','_probe','_miss','_full_fwd','_fast_rep','_bank_conflict','_wpu_pred_fail','_mq_nack','_troublem'))}
        # 此处计数仅统计采样周期中被断言的信号；解释未命中或重放条件前，
        # 必须结合该级的 valid/fire 判断其是否构成实际事件。
        stalls=Counter()
        for r in body:
            for i in range(6):
                stalls[str(get(r,DIS+f'stallReason_{i}'))]+=1
        load={}
        for unit in range(3):
            base=CORE+f'memBlock.inner_LoadUnit_{unit}.'
            load[str(unit)]={
                's2_fire':sum(bool(optional(r,base+'s2_fire_probe')) for r in body),
                's2_fire_dcache_response_miss':sum(bool(optional(r,base+'s2_fire_probe')) and bool(optional(r,base+'io_dcache_resp_bits_miss')) for r in body),
                's2_fire_effective_miss':sum(bool(optional(r,base+'s2_fire_probe')) and bool(optional(r,base+'s2_dcache_miss')) for r in body),
                's2_fire_bank_conflict':sum(bool(optional(r,base+'s2_fire_probe')) and bool(optional(r,base+'s2_bank_conflict')) for r in body),
                'replay_handshakes':sum(bool(optional(r,base+'io_replay_valid')) and bool(optional(r,base+'io_replay_ready')) for r in body),
            }
        result[label]=dict(target=target,csr_start=starts[0],csr_end=ends[0],sampled_cycles=len(body),dispatch_first_uop_by_pc=dict(counts),dispatch_events=events,loop_anchor_intervals=dict(Counter(intervals)),loop_anchors=anchors,redirect_events=[e for e in redirects if start<=e['mcycle']<end],asserted_cycle_counts=boolean_counts,stall_reason_slots=dict(stalls),loads=load,issue_events=issue_events,dispatch_to_issue_latency=issue_latency,mac_outputs=outputs,dispatch_to_mac_output_latency=wb_latency,mac_input_handshakes=sum(get(r,MAC+'io_in_valid') and get(r,MAC+'io_in_ready') for r in body),mac_output_handshakes=sum(get(r,MAC+'io_out_valid') and get(r,MAC+'io_out_ready') for r in body))
    return dict(status='PASS',windows=result,delta_cycles=result['slow']['sampled_cycles']-result['fast']['sampled_cycles'],qualification='direct internal observations; overlap counts are NOT additive cycle attribution; wrong-path dispatches are not commits')

def committed(text,windows):
    pattern=re.compile(r'\[\d{2}\] commit pc ([0-9a-f]+) inst ([0-9a-f]+) wen \d+ dst \d+ data ([0-9a-f]+) idx [0-9a-f]+[^\n]*\n')
    pending=None; counts=Counter(); result={}
    starts={windows[label]['start']:label for label in ('fast','slow')}
    for match in pattern.finditer(text):
        pc,inst,data=(int(x,16) for x in match.groups())
        if pc==0x800003d4 and inst==0xb0002373 and data in starts:
            need(pending is None,'overlapping committed windows')
            pending=starts[data]; counts=Counter()
        elif pending is not None and pc==0x800004c8 and inst==0xb0002e73:
            need(data==windows[pending]['end'],'committed end differs from waveform target')
            need(pending not in result,'duplicate committed window')
            for p in (0x800003e0,0x800003e4,0x80000404,0x80000408,0x8000040c,0x80000410,0x80000418,0x80000420,0x80000428,0x80000430,0x80000438):
                need(counts[p]==256,'need 256 committed original iterations at '+hex(p))
            result[pending]={hex(p):n for p,n in counts.items()}
            pending=None
        elif pending is not None: counts[pc]+=1
    need(pending is None and set(result)=={'fast','slow'},'missing committed fast/slow windows')
    return result

def attribution(columns,rows,result,counts):
    index={n:i for i,n in enumerate(columns)}
    def get(row,name,default=0): return row[index[name]] if name in index else default
    final={}
    for label,w in result['windows'].items():
        target=w['target']; body=[r for r in rows if target['start']<=get(r,MCYCLE)<target['end']]
        need(counts[label]['0x800003e0']==256,'bad committed loop count')
        anchors=w['loop_anchors']
        need(len(anchors)==257,'expected 256 iterations plus one squashed loop-start dispatch')
        real=anchors[:256]
        intervals=[b['mcycle']-a['mcycle'] for a,b in zip(real,real[1:])]
        prefix=real[0]['mcycle']-target['start']; span=real[-1]['mcycle']-real[0]['mcycle']; suffix=target['end']-real[-1]['mcycle']
        need(prefix+span+suffix==target['cycles'],'non-additive interval decomposition')
        counters={
            'dispatch_no_valid_cycles':sum(not any(get(r,DIS+f'io_fromRename_{i}_valid') for i in range(6)) for r in body),
            'dispatch_any_valid_unready_cycles':sum(any(get(r,DIS+f'io_fromRename_{i}_valid') and not get(r,DIS+f'io_fromRename_{i}_ready') for i in range(6)) for r in body),
            'dispatch_iq2_third_enqueue_block_cycles':sum(get(r,DIS+'io_fromRename_4_valid') and get(r,DIS+'uopBlockByIQ_4') and get(r,DIS+'uopSelIQ_4_2') for r in body),
        }
        decode=CORE+'backend.inner_ctrlBlock.decode.'
        for pc in (0x80000414,0x8000042c):
            counters['decode_solo_simple_'+hex(pc)]=sum(get(r,decode+'io_in_0_valid') and get(r,decode+'io_in_0_ready') and get(r,decode+'io_in_0_bits_pc')==pc and not any(get(r,decode+f'io_in_{i}_valid') for i in range(1,6)) for r in body)
        row_by_cycle={get(r,CYCLE):r for r in rows}
        patterns=Counter()
        for a,b in zip(real,real[1:]):
            period=[row_by_cycle[c] for c in range(a['cycle'],b['cycle'])]
            empty=tuple(i for i,r in enumerate(period) if not any(get(r,DIS+f'io_fromRename_{j}_valid') for j in range(6)))
            iq=tuple(i for i,r in enumerate(period) if get(r,DIS+'io_fromRename_4_valid') and get(r,DIS+'uopBlockByIQ_4') and get(r,DIS+'uopSelIQ_4_2'))
            patterns[(len(period),empty,iq)]+=1
        mac=MAC
        inputs=[get(r,CYCLE) for r in body if get(r,mac+'io_in_valid') and get(r,mac+'io_in_ready')]
        outputs=[get(r,CYCLE) for r in body if get(r,mac+'io_out_valid') and get(r,mac+'io_out_ready')]
        need(len(inputs)==len(outputs)==1024,'incomplete VDOT port observations')
        def tail_event(pc):
            matches=[e for e in w['dispatch_events'] if e['pc']==hex(pc) and e['cycle']>=real[-1]['cycle']]
            need(len(matches)==1,'missing/duplicate tail event at '+hex(pc))
            return matches[0]
        branch,jump,marker=[tail_event(pc) for pc in (0x80000438,0x8000043c,0x800004c4)]
        marker_row=row_by_cycle[marker['cycle']]
        need(get(marker_row,DIS+'io_enqRob_isEmpty')==1,'end marker did not dispatch into empty ROB')
        tail_parts=dict(last_head_to_branch=branch['mcycle']-real[-1]['mcycle'],branch_to_fallthrough_jump=jump['mcycle']-branch['mcycle'],jump_to_empty_rob_marker=marker['mcycle']-jump['mcycle'],marker_to_timestamp=target['end']-marker['mcycle'])
        need(sum(tail_parts.values())==suffix,'tail interval decomposition failed')
        final[label]=dict(real_iterations=256,extra_dispatched_not_committed_loop_starts=1,real_interval_histogram=dict(Counter(intervals)),prefix_cycles=prefix,first_to_last_real_start_cycles=span,suffix_cycles=suffix,suffix_parts=tail_parts,observations=counters,steady_patterns=[dict(period=p,dispatch_empty_offsets=list(e),iq2_block_offsets=list(i),count=n) for (p,e,i),n in patterns.items()],mac_low_phase_input_to_output_cycles=dict(Counter(b-a for a,b in zip(inputs,outputs))))
    final['exact_delta']={k:final['slow'][k]-final['fast'][k] for k in ('prefix_cycles','first_to_last_real_start_cycles','suffix_cycles')}
    need(sum(final['exact_delta'].values())==result['delta_cycles'],'delta decomposition failed')
    return final

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix',type=Path)
    parser.add_argument('--preliminary',action='store_true',help='separate provisional outputs while full replay is pending')
    parser.add_argument('--output-tag',default='',help='optional non-overwriting analysis revision tag')
    args=parser.parse_args(); prefix=args.prefix
    wave=prefix.with_suffix('.vcd')
    windows=json.loads(prefix.with_suffix('.windows.json').read_text())
    before=wave.stat()
    columns,rows=stream(wave)
    result=analyze(columns,rows,windows)
    result['committed_pc_counts']=committed(prefix.with_name(prefix.name+'-wave.full.log').read_text(errors='replace'),windows)
    result['interval_attribution']=attribution(columns,rows,result,result['committed_pc_counts'])
    with wave.open('rb') as source: result['wave_sha256']=hashlib.file_digest(source,'sha256').hexdigest()
    after=wave.stat()
    need((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'wave still changing during analysis')
    need(not args.output_tag or re.fullmatch('[a-z][a-z0-9_-]*',args.output_tag),'invalid output tag')
    marker=('.'+args.output_tag if args.output_tag else '')+('.preliminary' if args.preliminary else '')
    result['analysis_script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.preliminary:
        result['status']='WINDOW_CHECKS_PASS_FULL_REPLAY_PENDING'
    else:
        need(result['wave_sha256']==json.loads(prefix.with_suffix('.capture.json').read_text())['wave_sha256'],'capture wave changed')
    for suffix,value in ((marker+'.events.json',result),(marker+'.cycles.json',dict(columns=columns,rows=rows))):
        with prefix.with_suffix(suffix).open('x') as target: json.dump(value,target)
    print(json.dumps(dict(status=result['status'],delta_cycles=result['delta_cycles'],selected_signals=len(columns)-1,cycles=len(rows))))

if __name__=='__main__': main()
