#!/usr/bin/env python3
"""人工 VCD 输入仅用于验证检查器，不代表整核证据。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("timer",Path(__file__).with_name("check-timer-wave.py"))
timer=importlib.util.module_from_spec(spec); spec.loader.exec_module(timer)


def fixture(directory, bad=None):
    d="TOP.SimTop.l_soc.core_with_l2.core.backend.inner_ctrlBlock.dispatch."
    r="TOP.SimTop.l_soc.core_with_l2.core.backend.inner_ctrlBlock.rob."
    c="TOP.SimTop.l_soc.core_with_l2.core.backend.inner_intExuBlock.exus_7.csr."
    names=["TOP.clock",d+"io_enqRob_canAccept",d+"io_enqRob_isEmpty",r+"hasBlockBackward",c+"io_out_valid",
           c+"io_out_bits_ctrl_robIdx_flag",c+"io_out_bits_ctrl_robIdx_value",c+"io_out_bits_res_data"]
    for i in range(6):
        names += [d+f"io_enqRob_req_{i}_valid"]
        names += [d+f"io_enqRob_req_{i}_bits_"+n for n in ("instr","pc","robIdx_flag","robIdx_value","waitForward","blockBackward")]
    codes={n:f"s{i}" for i,n in enumerate(names)}
    # 完整点分层次名可直接作为引用，不要求嵌套作用域。
    lines=["$timescale 1ns $end"]+[f"$var wire 64 {codes[n]} {n} $end" for n in names]+["$enddefinitions $end"]
    clock=0
    def emit(changes):
        nonlocal clock
        base={n:0 for n in names}; base[d+"io_enqRob_canAccept"]=1; base[d+"io_enqRob_isEmpty"]=1
        base.update(changes)
        for level in (1,0):
            clock+=1; lines.append(f"#{clock}"); base["TOP.clock"]=level
            lines.extend(f"b{v:b} {codes[n]}" for n,v in base.items())
    tag=0
    def op(inst, data):
        nonlocal tag
        tag+=1; p=d+"io_enqRob_req_0_bits_"
        marker=inst==0x00805073
        emit({d+"io_enqRob_req_0_valid":1,p+"instr":inst,p+"pc":0x80000100+tag*4,p+"robIdx_value":tag,
              p+"waitForward":int(marker and bad!="flag"),p+"blockBackward":int(marker)})
        emit({r+"hasBlockBackward":int(marker),d+"io_enqRob_canAccept":int(not marker or bad=="block"),
              c+"io_out_valid":1,c+"io_out_bits_ctrl_robIdx_value":tag,c+"io_out_bits_res_data":data})
    for k in range(3):
        for impl in range(2):
            op(0x00805073,0); op(0xb0002373,1000); op(0x00805073,0)
            op(0x00805073,0); op(0xb0002e73,1100+(bad=="delta"))
    wave,log=Path(directory)/"synthetic.vcd",Path(directory)/"synthetic.log"
    wave.write_text("\n".join(lines)+"\n")
    log.write_text("synthetic fixture, NOT hardware\nDifftest enabled\nHIT GOOD TRAP\ntimer probe PASS: synthetic\n"+
                   "\n".join(f"timer probe kind={k} impl={i} cycles=100" for k in range(3) for i in range(2))+"\n[exit] 0\n")
    return wave,log


class TimerTests(unittest.TestCase):
    def test_complete_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            result=timer.check(*fixture(directory))
            self.assertEqual(len(result["checked_pairs"]),6)
            self.assertEqual(result["checked_markers"],18)
    def test_corruptions_rejected(self):
        for bad in ("flag","block","delta"):
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as directory,self.assertRaises(ValueError):
                timer.check(*fixture(directory,bad))
    def test_interleaved_uart_commit_records(self):
        with tempfile.TemporaryDirectory() as directory:
            wave,log=fixture(directory)
            text=log.read_text().replace("timer probe kind=", "timer [00] commit pc 80000000 inst 13 wen 0 dst 0 data 0 idx 01\nprobe kind=")
            log.write_text(text)
            self.assertEqual(len(timer.check(wave,log)["checked_pairs"]),6)


if __name__=="__main__": unittest.main()
