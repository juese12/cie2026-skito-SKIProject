"""仅使用人工解析器输入，不作为整核或 RTL 性能证据。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("oldvd_audit",Path(__file__).with_name("check-oldvd-wave.py"))
audit=importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def fixture(path,alias=False,psrc=13):
    d=audit.DISPATCH; f=audit.FU; e=audit.IQ+"othersEntriesComp_0."
    v={"TOP.clock":0,d+"io_enqRob_canAccept":1,f+"io_out_valid":0,
       f+"io_in_bits_ctrlPipe_2_fuOpType":0x160,f+"io_out_bits_ctrl_robIdx_flag":0,
       f+"io_out_bits_ctrl_robIdx_value":2,f+"io_out_bits_res_data":16}
    for i in range(6):
        v[d+f"io_enqRob_req_{i}_valid"]=0
        for n in ("instr","pc","robIdx_flag","robIdx_value","vecWen","v0Wen","pdest"):
            v[d+f"io_enqRob_req_{i}_bits_"+n]=0
    for n,value in (("io_commonOut_valid",0),("io_commonOut_canIssue",0),
                    ("entryReg_payload_fuOpType",0x160),("entryReg_payload_vpu_vta",0)):
        v[e+n]=value
    for n,value in (("robIdx_flag",0),("robIdx_value",2),("issued",0),("blocked",0)):
        v[e+"entryReg_status_"+n]=value
    for j in range(5):
        for n,value in (("srcState",1),("srcType",4),("psrc",psrc if j==2 else 20+j)):
            v[e+f"entryReg_status_srcStatus_{j}_"+n]=value
    ids={name:f"s{i}" for i,name in enumerate(v)}
    lines=[]
    # 完整层次名由普通 VCD 作用域逐级拼接。
    for name,code in ids.items():
        scopes=name.split('.')[:-1]
        lines += [f"$scope module {s} $end" for s in scopes]
        lines += [f"$var wire 64 {code} {name.split('.')[-1]} $end"]
        lines += ["$upscope $end"]*len(scopes)
    lines += ["$enddefinitions $end","#0"]+[f"b{value:b} {ids[name]}" for name,value in v.items()]
    def at(t,changes):
        lines.append(f"#{t}")
        lines.extend(f"b{value:b} {ids[name]}" for name,value in changes.items())
    pre=d+"io_enqRob_req_0_bits_"
    at(1,{"TOP.clock":1,d+"io_enqRob_req_0_valid":1,pre+"instr":0xb0002373})
    at(2,{"TOP.clock":0})
    at(3,{"TOP.clock":1,pre+"instr":0x02000557,pre+"robIdx_value":1,pre+"vecWen":1,pre+"pdest":13})
    at(4,{"TOP.clock":0})
    word=0x0200200b|(9<<20)|((10 if alias else 8)<<15)|(10<<7)
    at(5,{"TOP.clock":1,pre+"instr":word,pre+"robIdx_value":2,pre+"pdest":14})
    at(6,{"TOP.clock":0})
    at(7,{"TOP.clock":1,d+"io_enqRob_req_0_valid":0,e+"io_commonOut_valid":1,
          e+"entryReg_status_srcStatus_2_srcState":0})
    at(8,{"TOP.clock":0})
    at(9,{"TOP.clock":1,e+"io_commonOut_valid":0,f+"io_out_valid":1})
    at(10,{"TOP.clock":0})
    path.write_text('\n'.join(lines)+'\n')


class OldVdWaveTest(unittest.TestCase):
    def test_actual_source_slot_and_producer_match_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            wave=Path(tmp)/'synthetic.vcd'; fixture(wave)
            result=audit.check(wave,None)
            self.assertEqual(result['status'],'DIAGNOSTIC_ONLY')
            self.assertEqual(result['false_wait_dot'],1)
            self.assertEqual(result['records'][0]['example']['states'],[1,1,0,1,1])
            fixture(wave,psrc=99)
            with self.assertRaisesRegex(ValueError,'physical source'): audit.check(wave,None)

    def test_true_alias_is_not_counted_as_false_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            wave=Path(tmp)/'synthetic.vcd'; fixture(wave,alias=True)
            result=audit.check(wave,None,0)
            self.assertEqual(result['false_wait_dot'],0)
            with self.assertRaisesRegex(ValueError,'false-wait'): audit.check(wave,None,1)

    def test_complete_log_contract_and_no_zero_exit_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=Path(tmp)/'synthetic.log'
            text='synthetic parser fixture\nDifftest enabled\nHIT GOOD TRAP\noldvd probe PASS: 48 calls\n'
            text+=''.join(f'oldvd sample policy={p} kind={k} rep={r} dots=32 cycles=70\n'
                          for p in range(4) for k in range(6) for r in range(2))
            log.write_text(text+'[exit] 0\n'); self.assertEqual(len(audit.audit_log(log)['samples']),48)
            log.write_text(text+'[exit] 1\n')
            with self.assertRaisesRegex(ValueError,'zero exit'): audit.audit_log(log)
