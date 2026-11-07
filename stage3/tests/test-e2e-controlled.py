#!/usr/bin/env python3
import importlib.util
import gzip
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('controlled_bins',ROOT/'scripts/probe-e2e-other-bins.py')
bins=importlib.util.module_from_spec(spec);spec.loader.exec_module(bins)
spec=importlib.util.spec_from_file_location('controlled_matrix',ROOT/'scripts/verify-e2e-controlled.py')
matrix=importlib.util.module_from_spec(spec);spec.loader.exec_module(matrix)
spec=importlib.util.spec_from_file_location('entry_context',Path(__file__).with_name('analyze-e2e-entry-context.py'))
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
spec=importlib.util.spec_from_file_location('matrix_summary',Path(__file__).with_name('analyze-e2e-controlled.py'))
summary=importlib.util.module_from_spec(spec);spec.loader.exec_module(summary)
spec=importlib.util.spec_from_file_location('loop_groups',Path(__file__).with_name('analyze-e2e-loop-groups.py'))
loops=importlib.util.module_from_spec(spec);spec.loader.exec_module(loops)

def wave():
    lines=[]
    for name,code,width in (('TOP.clock','!',1),(bins.ev.MCYCLE,'"',64),(bins.ev.CYCLE,'#',64)):
        parts=name.split('.')
        for part in parts[:-1]:lines.append(f'$scope module {part} $end')
        lines.append(f'$var wire {width} {code} {parts[-1]} $end')
        lines.extend('$upscope $end' for _ in parts[:-1])
    lines.append('$enddefinitions $end')
    for c in range(10):
        lines.extend((f'#{2*c}', '1!', f'b{100+c:b} "', f'b{c:b} #', f'#{2*c+1}', '0!'))
    return '\n'.join(lines)+'\n'

class ControlledToolsTest(unittest.TestCase):
    def parse(self,text,spans):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.vcd';p.write_text(text)
            return bins.filtered_stream(p,spans)
    def test_disjoint_spans_keep_only_requested_rows(self):
        columns,rows=self.parse(wave(),[(102,104),(107,109)])
        self.assertEqual([r[columns.index(bins.ev.MCYCLE)] for r in rows],[102,103,107,108])
    def test_overlapping_spans_do_not_duplicate(self):
        _,rows=self.parse(wave(),[(102,106),(104,108)])
        self.assertEqual(len(rows),6)
    def test_empty_spans_rejected(self):
        with self.assertRaises(ValueError):self.parse(wave(),[(200,210)])
    def test_unknown_selected_signal_rejected(self):
        with self.assertRaises(ValueError):self.parse(wave().replace('b1100100 "','bx "'),[(100,101)])
    def test_compressed_wave_matches_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.vcd.gz'
            with gzip.open(p,'wt') as stream:stream.write(wave())
            self.assertEqual(bins.filtered_stream(p,[(102,104)]),self.parse(wave(),[(102,104)]))
    def test_fifo_compression_does_not_store_plain_wave(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo=Path(tmp)/'wave.fifo';out=Path(tmp)/'wave.vcd.gz';os.mkfifo(fifo)
            worker=multiprocessing.get_context('fork').Process(target=bins.compress_fifo,args=(fifo,out));worker.start()
            try:
                with fifo.open('wb') as stream:stream.write(wave().encode())
                worker.join(5)
                self.assertFalse(worker.is_alive());self.assertEqual(worker.exitcode,0)
                with gzip.open(out,'rt') as stream:self.assertEqual(stream.read(),wave())
            finally:
                if worker.is_alive():worker.terminate();worker.join()

def variant_fixture():
    image=bytearray(256)
    image[16:40]=b'\x13\0\0\0'*6
    image[48:72]=(0x001f8f93).to_bytes(4,'little')*6
    return bytes(image),dict(diag_phase=0x80000010,diag_pressure=0x80000030,diag_parameter=0x80000050,bench_kernel=0x80000080)

def controlled_log():
    rows=['Difftest enabled','controlled meta schema=1 phase=2 pressure=1 batches=256 rounds=6 first=0 directed=4']
    for r in range(6):
        for s in range(2):rows.append(f'controlled raw round={r} slot={s} impl={(r&1)^s} cycles={4400+r+s}')
    rows+=['controlled PASS: complete','HIT GOOD TRAP','[process exit] 0']
    return '\n'.join(rows)+'\n'

class MatrixTest(unittest.TestCase):
    def audit(self,text):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'run.log';p.write_text(text)
            return matrix.audit(p,2,1)
    def test_all_twelve_arms_preserve_layout_and_kernel(self):
        original,symbols=variant_fixture()
        for phase,pressure in matrix.MATRIX:
            image,record=matrix.prepare(original,symbols,phase,pressure)
            self.assertEqual(len(image),len(original));self.assertEqual(image[128:],original[128:])
            self.assertEqual(image[16:16+4*phase],b'\x01\0\x01\0'*phase)
            self.assertEqual(record['extra_nop_instructions'],phase)
    def test_invalid_arm_rejected(self):
        with self.assertRaises(ValueError):matrix.prepare(*variant_fixture(),6,0)
    def test_wrong_base_code_rejected(self):
        original,symbols=variant_fixture()
        with self.assertRaises(ValueError):matrix.prepare(original[:16]+b'\x00'+original[17:],symbols,2,1)
    def test_all_calls_retained(self):
        self.assertEqual(len(self.audit(controlled_log())['calls']),12)
    def test_missing_call_rejected(self):
        with self.assertRaises(ValueError):self.audit(controlled_log().replace('controlled raw round=0 slot=0 impl=0 cycles=4400\n',''))
    def test_wrong_order_rejected(self):
        with self.assertRaises(ValueError):self.audit(controlled_log().replace('round=0 slot=0 impl=0','round=0 slot=0 impl=1'))
    def test_failed_actual_exit_rejected(self):
        with self.assertRaises(ValueError):self.audit(controlled_log().replace('[process exit] 0','[process exit] 1'))
    def test_wrong_metadata_rejected(self):
        with self.assertRaises(ValueError):self.audit(controlled_log().replace('phase=2','phase=3'))

def entry_fixture(pc=0x80000344,ready=1):
    ev=entry.ev;dec=ev.CORE+'backend.inner_ctrlBlock.decode.'
    names=[ev.CYCLE,ev.DIS+'io_enqRob_canAccept',ev.RED+'io_stage2Redirect_valid']
    names += [ev.RED+'io_stage2Redirect_bits_'+n for n in ('robIdx_flag','robIdx_value','cfiUpdate_pc','cfiUpdate_isMisPred','debugIsMemVio')]
    names += [dec+'io_in_0_ready']
    for i in range(6):
        names += [ev.DIS+f'io_enqRob_req_{i}_'+n for n in ('valid','bits_robIdx_flag','bits_robIdx_value','bits_pc')]
        names += [dec+f'io_in_{i}_'+n for n in ('valid','bits_pc')]
    ix={n:i for i,n in enumerate(names)};rows=[]
    for cycle in range(20):
        row=[0]*len(names)
        def put(n,v):row[ix[n]]=v
        put(ev.CYCLE,cycle);put(ev.DIS+'io_enqRob_canAccept',1)
        if cycle==5:
            for n,v in (('valid',1),('bits_pc',pc),('bits_robIdx_value',3)):put(ev.DIS+'io_enqRob_req_0_'+n,v)
        if cycle==10:
            put(ev.RED+'io_stage2Redirect_valid',1)
            for n,v in (('robIdx_value',3),('cfiUpdate_pc',0x80000334),('cfiUpdate_isMisPred',1)):put(ev.RED+'io_stage2Redirect_bits_'+n,v)
        if cycle==15:
            put(dec+'io_in_0_valid',1);put(dec+'io_in_0_bits_pc',0x800003d0);put(dec+'io_in_0_ready',ready)
        rows.append(row)
    return dict(columns=names,rows=rows),{'test':dict(csr_start={'cycle':20},target={'cycles':100})}

class EntryContextTest(unittest.TestCase):
    def test_selector_redirect_precedes_final_group(self):
        result=entry.extract(*entry_fixture())[0]
        self.assertEqual(result['selector_mispredicts'],1)
        self.assertEqual(result['final_marker_group']['marker_slot'],0)
    def test_ftq_base_is_not_branch_instruction_pc(self):
        result=entry.extract(*entry_fixture())[0]
        self.assertEqual(result['pre_timer_redirects'][0]['pc'],'0x80000344')
        self.assertEqual(result['pre_timer_redirects'][0]['ftq_base_pc'],'0x80000334')
    def test_other_redirect_does_not_count_selector(self):
        self.assertEqual(entry.extract(*entry_fixture(pc=0x800009de))[0]['selector_mispredicts'],0)
    def test_unready_group_is_not_accepted(self):
        with self.assertRaises(ValueError):entry.extract(*entry_fixture(ready=0))

class MatrixSummaryTest(unittest.TestCase):
    def fixture(self):
        return [dict(phase=p,pressure=q,calls=[dict(round=r,slot=s,impl=(r&1)^s,cycles=1000+100*r+10*p+20*q+s) for r in range(6) for s in range(2)]) for p,q in matrix.MATRIX]
    def test_all_calls_and_matched_differences(self):
        result=summary.summarize(self.fixture())
        self.assertEqual(result['total_calls'],144)
        self.assertEqual(len(result['matched_differences']),16)
        for comparison in result['matched_differences']:
            expected=10*comparison['changed'][0] if comparison['factor']=='phase' else 20
            self.assertTrue(all(v['delta']==expected for v in comparison['matched_calls']))
    def test_missing_arm_rejected(self):
        with self.assertRaises(ValueError):summary.summarize(self.fixture()[:-1])
    def test_wrong_call_position_rejected(self):
        runs=self.fixture();runs[0]['calls'][0]['slot']=1
        with self.assertRaises(ValueError):summary.summarize(runs)

class LoopGroupTest(unittest.TestCase):
    def fixture(self,block=0,ready=1):
        ev=loops.ev;dec=ev.CORE+'backend.inner_ctrlBlock.decode.'
        values={ev.MCYCLE:150,dec+'decoderComp.state':1,dec+'decoderComp.io_in_valid':0,dec+'io_in_0_ready':ready}
        for i in range(6):
            values[dec+f'io_in_{i}_valid']=int(i==0);values[dec+f'io_in_{i}_bits_pc']=0x80000424
            values[ev.DIS+f'io_fromRename_{i}_valid']=int(i<5)
            for j in range(4):values[ev.DIS+f'uopSelIQ_{i}_{j}']=int(j==((2,16,2,1,0,0)[i]))
        values[ev.DIS+'io_fromRename_0_bits_pc']=0x80000430;values[ev.DIS+'io_fromRename_4_bits_pc']=0x800003dc;values[ev.DIS+'uopBlockByIQ_4']=block
        for j in range(4):values[ev.DIS+f'io_toIssueQueues_{2*j}_ready']=1
        return dict(columns=list(values),rows=[list(values.values())]),{'test':dict(target={'start':100,'end':200})}
    def test_intermediate_scalar_tail_and_queue_selection(self):
        result=loops.extract(*self.fixture())[0]
        self.assertEqual(result['active_without_next_complex_groups'],[{'pcs':['0x80000424'],'count':1}])
        self.assertEqual(result['tail_packets'][0]['iq_slots_0_2_3_4'],[[2],[2],[1],[0]])
    def test_unready_tail_not_counted(self):
        self.assertEqual(loops.extract(*self.fixture(ready=0))[0]['active_without_next_complex_groups'],[])
    def test_block_and_ready_are_separate_observations(self):
        result=loops.extract(*self.fixture(block=1))[0]['tail_packets'][0]
        self.assertEqual(result['slot4_blocked'],1);self.assertEqual(result['int_iq_enqueue_ready'],[1,1,1,1])

if __name__=='__main__':unittest.main()
