#!/usr/bin/env python3
"""用反例检查原镜像的计时标注和事件边界。"""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value

capture=module('capture_events',ROOT/'scripts/capture-original-e2e-events.py')
events=module('analyze_events',Path(__file__).with_name('analyze-original-e2e-events.py'))

def trace():
    lines=[]; now=0x6c3a000000000000
    for n in range(96):
        kind,pos=divmod(n,32); _,within=divmod(pos,16); rep,slot=divmod(within,2); impl=rep%2^slot
        pc=((0x800003d4,0x8000034c),(0x800003d4,0x8000034c),(0x800004a0,0x80000448))[kind][impl]
        lines.append(f'[00] commit pc {pc:016x} inst b0002373 wen 1 dst 06 data {now:016x} idx 001\n')
        now+=100+n
        lines.append(f'[01] commit pc 00000000800004c8 inst b0002e73 wen 1 dst 28 data {now:016x} idx 002\n')
        now+=10
    return ''.join(lines)

def fixture():
    names={'vcd_time','TOP.clock',events.CYCLE,events.MCYCLE,events.DIS+'io_enqRob_canAccept',events.CSR+'io_out_valid',events.CSR+'io_out_bits_res_data',events.CSR+'io_out_bits_ctrl_robIdx_flag',events.CSR+'io_out_bits_ctrl_robIdx_value',events.RED+'io_stage2Redirect_valid',events.RED+'io_stage2Redirect_bits_cfiUpdate_pc',events.RED+'io_stage2Redirect_bits_cfiUpdate_isMisPred',events.RED+'io_stage2Redirect_bits_debugIsMemVio'}
    names.update(events.MAC+s for s in ('io_in_valid','io_in_ready','io_out_valid','io_out_ready'))
    for i in range(6):
        names.add(events.DIS+f'stallReason_{i}')
        names.add(events.DIS+f'io_enqRob_req_{i}_valid')
        names.update(events.DIS+f'io_enqRob_req_{i}_bits_'+s for s in ('pc','instr','robIdx_flag','robIdx_value','firstUop','lastUop'))
    columns=sorted(names); idx={n:i for i,n in enumerate(columns)}; rows=[]
    for cycle in range(11):
        row=[0]*len(columns)
        def put(name,value): row[idx[name]]=value
        put('vcd_time',101+2*cycle); put(events.CYCLE,cycle); put(events.MCYCLE,100+cycle)
        put(events.DIS+'io_enqRob_canAccept',1)
        for dispatch_cycle,output_cycle,data,tag,start in ((1,2,102,1,True),(4,5,104,2,False),(5,6,106,3,True),(9,10,109,4,False)):
            if cycle==dispatch_cycle:
                base=events.DIS+'io_enqRob_req_0_'
                for s,v in (('valid',1),('bits_pc',0x800003d4 if start else 0x800004c8),('bits_instr',0xb0002373 if start else 0xb0002e73),('bits_robIdx_value',tag),('bits_firstUop',1),('bits_lastUop',1)): put(base+s,v)
            if cycle==output_cycle:
                put(events.CSR+'io_out_valid',1); put(events.CSR+'io_out_bits_res_data',data); put(events.CSR+'io_out_bits_ctrl_robIdx_value',tag)
        rows.append(row)
    windows={'fast':{'start':102,'end':104,'cycles':2},'slow':{'start':106,'end':109,'cycles':3}}
    return columns,rows,windows

def committed_fixture():
    windows={'fast':{'start':102,'end':104},'slow':{'start':106,'end':109}}
    pcs=(0x800003e0,0x800003e4,0x80000404,0x80000408,0x8000040c,0x80000410,0x80000418,0x80000420,0x80000428,0x80000430,0x80000438)
    lines=[]
    def emit(pc,inst,data): return f'[00] commit pc {pc:016x} inst {inst:08x} wen 1 dst 06 data {data:016x} idx 001\n'
    for label in ('fast','slow'):
        lines.append(emit(0x800003d4,0xb0002373,windows[label]['start']))
        for _ in range(256):
            for pc in pcs: lines.append(emit(pc,0x13,0))
        lines.append(emit(0x800004c8,0xb0002e73,windows[label]['end']))
    return ''.join(lines),windows

def attribution_fixture():
    columns,_,_=fixture()
    columns.append(events.DIS+'io_enqRob_isEmpty')
    columns.extend(events.DIS+'io_fromRename_0_'+s for s in ('valid','ready'))
    index={n:i for i,n in enumerate(columns)}
    rows=[]; result={'windows':{},'delta_cycles':255}; counts={}
    for label,start,period in (('fast',100,4),('slow',5000,5)):
        anchors=[dict(cycle=start+5+i*period,mcycle=start+5+i*period) for i in range(257)]
        last=anchors[255]['cycle']; end=last+12
        target=dict(start=start,end=end,cycles=end-start)
        tail=[dict(pc=hex(pc),cycle=last+offset,mcycle=last+offset) for pc,offset in ((0x80000438,4),(0x8000043c,6),(0x800004c4,9))]
        result['windows'][label]=dict(target=target,loop_anchors=anchors,dispatch_events=tail)
        counts[label]={'0x800003e0':256}
        for cycle in range(start,end):
            row=[0]*len(columns)
            row[index[events.CYCLE]]=cycle; row[index[events.MCYCLE]]=cycle
            row[index[events.DIS+'io_enqRob_isEmpty']]=1
            row[index[events.DIS+'io_fromRename_0_valid']]=1
            row[index[events.DIS+'io_fromRename_0_ready']]=1
            for field in ('io_in_valid','io_in_ready','io_out_valid','io_out_ready'):
                row[index[events.MAC+field]]=int(cycle<start+1024)
            rows.append(row)
    return columns,rows,result,counts

class OriginalEvents(unittest.TestCase):
    def test_complete_original_labels(self):
        pairs=capture.windows(trace())
        self.assertEqual(len(pairs),96)
        self.assertEqual((pairs[47]['kind'],pairs[47]['phase'],pairs[47]['rep'],pairs[47]['slot'],pairs[47]['impl']),('e2e','warm',7,1,'vdot'))
        self.assertEqual((pairs[48]['phase'],pairs[48]['rep'],pairs[48]['slot'],pairs[48]['impl']),('measured',0,0,'vdot'))
    def test_missing_pair_rejected(self):
        with self.assertRaises(ValueError): capture.windows(trace().rsplit('[00]',1)[0])
    def test_wrong_pc_rejected(self):
        with self.assertRaises(ValueError): capture.windows(trace().replace('00000000800003d4','000000008000034c',1))
    def test_wrong_timestamp_destination_rejected(self):
        with self.assertRaises(ValueError): capture.windows(trace().replace('dst 06','dst 07',1))
    def test_start_without_end_rejected(self):
        with self.assertRaises(ValueError): capture.windows(trace().replace('00000000800004c8','000000008000050c',1))
    def test_uart_only_complete_records_removed(self):
        record=trace().splitlines(keepends=True)[0]
        self.assertEqual(capture.COMMIT.sub('','bench '+record+'PASS\n'),'bench PASS\n')
        self.assertEqual(capture.COMMIT.sub('','[00] commit pc BAD\n'),'[00] commit pc BAD\n')
    def test_exact_epoch_integration(self):
        result=events.analyze(*fixture())
        self.assertEqual(result['delta_cycles'],1)
        self.assertEqual(result['windows']['fast']['sampled_cycles'],2)
    def test_missing_cycle_rejected(self):
        columns,rows,windows=fixture()
        with self.assertRaises(ValueError): events.analyze(columns,rows[:3]+rows[4:],windows)
    def test_missing_timestamp_output_rejected(self):
        columns,rows,windows=fixture()
        rows[2][columns.index(events.CSR+'io_out_valid')]=0
        with self.assertRaises(ValueError): events.analyze(columns,rows,windows)
    def test_wrong_duration_rejected(self):
        columns,rows,windows=fixture(); windows=copy.deepcopy(windows); windows['slow']['cycles']=4
        with self.assertRaises(ValueError): events.analyze(columns,rows,windows)
    def test_signal_routing(self):
        self.assertTrue(events.selected(events.MAC+'io_in_valid'))
        self.assertTrue(events.selected(events.CORE+'memBlock.inner_LoadUnit_0.s2_bank_conflict'))
        self.assertFalse(events.selected(events.MAC+'vimacs_0.io_in_valid'))
        self.assertFalse(events.selected(events.CORE+'fake.inner_LoadUnit_0.bits_data'))
    def test_committed_loops(self):
        counts=events.committed(*committed_fixture())
        self.assertEqual(counts['fast']['0x800003e0'],256)
        self.assertEqual(counts['slow']['0x80000438'],256)
    def test_committed_wrong_end_rejected(self):
        text,windows=committed_fixture(); windows['fast']['end']=105
        with self.assertRaises(ValueError): events.committed(text,windows)
    def test_committed_missing_call_rejected(self):
        text,windows=committed_fixture(); text=text[:text.index('data 000000000000006a')]
        with self.assertRaises(ValueError): events.committed(text,windows)
    def test_committed_missing_iteration_rejected(self):
        text,windows=committed_fixture()
        text=text.replace('00000000800003e0','00000000800003e1',1)
        with self.assertRaises(ValueError): events.committed(text,windows)
    def test_committed_duplicate_rejected(self):
        text,windows=committed_fixture()
        with self.assertRaises(ValueError): events.committed(text+text,windows)
    def test_deep_signal_routes(self):
        self.assertTrue(events.selected(events.DIS+'uopSelIQ_4_2'))
        self.assertTrue(events.selected(events.CORE+'backend.inner_ctrlBlock.decode.decoderComp.state'))
        self.assertTrue(events.selected(events.CORE+'backend.inner_ctrlBlock.decode.io_in_0_bits_pc'))
    def test_redirect_pc_comes_from_dispatch_tag(self):
        columns,rows,windows=fixture()
        for name in ('io_stage2Redirect_bits_robIdx_flag','io_stage2Redirect_bits_robIdx_value'):
            columns.append(events.RED+name)
            for row in rows: row.append(0)
        rows[3][columns.index(events.RED+'io_stage2Redirect_valid')]=1
        rows[3][columns.index(events.RED+'io_stage2Redirect_bits_cfiUpdate_pc')]=0x800003c0
        rows[3][columns.index(events.RED+'io_stage2Redirect_bits_robIdx_value')]=1
        redirect=events.analyze(columns,rows,windows)['windows']['fast']['redirect_events'][0]
        self.assertEqual(redirect['ftq_base_pc'],'0x800003c0')
        self.assertEqual(redirect['dispatch_pc'],'0x800003d4')
    def test_interval_attribution(self):
        answer=events.attribution(*attribution_fixture())
        self.assertEqual(answer['exact_delta'],dict(prefix_cycles=0,first_to_last_real_start_cycles=255,suffix_cycles=0))
        self.assertEqual(answer['fast']['suffix_parts']['marker_to_timestamp'],3)
    def test_interval_wrong_duration_rejected(self):
        columns,rows,result,counts=attribution_fixture()
        result['windows']['fast']['target']['cycles']+=1
        with self.assertRaises(ValueError): events.attribution(columns,rows,result,counts)
    def test_nonempty_rob_end_marker_rejected(self):
        columns,rows,result,counts=attribution_fixture()
        marker=result['windows']['fast']['dispatch_events'][-1]['cycle']
        next(r for r in rows if r[columns.index(events.CYCLE)]==marker)[columns.index(events.DIS+'io_enqRob_isEmpty')]=0
        with self.assertRaises(ValueError): events.attribution(columns,rows,result,counts)

if __name__=='__main__': unittest.main()
