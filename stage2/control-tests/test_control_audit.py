#!/usr/bin/env python3
"""人工构造的对抗用例只用于验证审核器，不代表处理器验证结果。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit", Path(__file__).resolve().parents[2]/"scripts/check-vdot-control.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ControlAuditTest(unittest.TestCase):
    def fixture(self, directory, fault=None):
        names = audit.required_signals()
        codes = {name: f"s{i}" for i,name in enumerate(names)}
        symbols = {name: 0x80001000+4*i for i,name in enumerate(audit.SYMBOLS)}
        states = {name:0 for name in names}
        text = []
        for name in names:
            parts = name.split(".")
            for part in parts[:-1]: text.append(f"$scope module {part} $end")
            text.append(f"$var wire 64 {codes[name]} {parts[-1]} $end")
            for _ in parts[:-1]: text.append("$upscope $end")
        text += ["$enddefinitions $end", "#0"]
        for name in names: text.append(f"b0 {codes[name]}")
        tick = 0

        def cycle(changes):
            nonlocal tick
            # 复位所有瞬时有效信号，只断言本用例明确提供的事件。
            for name in names:
                if name.endswith("valid") or "commitValid_" in name or name.endswith("isCommit"):
                    states[name] = 0
            states.update(changes)
            tick += 10
            text.append(f"#{tick}")
            states["TOP.clock"] = 1
            for name,value in states.items():
                text.append(f"b{value:b} {codes[name]}")
            text.extend([f"#{tick+5}", f"b0 {codes['TOP.clock']}"])

        def dispatch(name, tag):
            prefix = audit.DISPATCH+"io_enqRob_req_0_"
            instr = 0x02942a0b if "dot" in name else 0xffffffff if name == "control_exception_pc" else 0x63
            cycle({audit.DISPATCH+"io_enqRob_canAccept":1, prefix+"valid":1,
                   prefix+"bits_pc":symbols[name], prefix+"bits_instr":instr,
                   prefix+"bits_robIdx_flag":tag//256, prefix+"bits_robIdx_value":tag%256})

        def execute(tag):
            cycle({audit.FU+"io_out_valid":1, audit.FU+"io_in_bits_ctrlPipe_2_fuOpType":0x160,
                   audit.FU+"io_out_bits_ctrl_robIdx_flag":tag//256,
                   audit.FU+"io_out_bits_ctrl_robIdx_value":tag%256})

        def commit(tag):
            cycle({audit.ROB+"io_commits_isCommit":1, audit.ROB+"io_commits_commitValid_0":1,
                   audit.ROB+"io_commits_robIdx_0_flag":tag//256, audit.ROB+"io_commits_robIdx_0_value":tag%256})

        for tag,name in ((1,"control_branch_dot"),(2,"control_branch_dot_v0")):
            dispatch(name,tag); execute(tag); commit(tag)
        dispatch("control_branch_pc",158)
        dispatch("control_branch_dot",159); execute(159)
        dispatch("control_branch_dot_v0",256)
        if fault != "no_execution": execute(256)
        prefix = audit.CTRL+"io_fromWB_wbData_1_"
        cycle({prefix+"valid":1, prefix+"bits_redirect_valid":1,
               prefix+"bits_redirect_bits_robIdx_value":157 if fault == "wrong_wb_tag" else 158,
               prefix+"bits_redirect_bits_cfiUpdate_pc":symbols["control_branch_pc"]-(20 if fault == "writeback_pc_shift" else 0),
               prefix+"bits_redirect_bits_cfiUpdate_taken":1,
               prefix+"bits_redirect_bits_cfiUpdate_isMisPred":int(fault != "no_mispredict")})
        cycle({audit.CTRL+"io_redirect_valid":1, audit.CTRL+"io_redirect_bits_robIdx_value":158})
        if fault == "branch_commit": commit(159)
        if fault == "tag_reallocation":
            dispatch("control_branch_dot",159); execute(159); commit(159)
        commit(158)
        dispatch("control_exception_pc",270)
        for i,name in enumerate(("control_younger_dot","control_younger_dot_v0","control_younger_dot_alias")):
            dispatch(name,271+i); execute(271+i)
        cycle({audit.ROB+"io_flushOut_valid":1, audit.ROB+"io_flushOut_bits_robIdx_flag":1,
               audit.ROB+"io_flushOut_bits_robIdx_value":14, audit.ROB+"io_flushOut_bits_level":1})
        cycle({audit.ROB+"io_exception_valid":1,
               audit.ROB+"io_exception_bits_instr":0xffffffff,
               audit.ROB+"io_exception_bits_exceptionVec_2":int(fault != "no_illegal")})
        if fault == "young_commit": commit(271)
        if fault != "truncated":
            dispatch("control_exception_resume",280); commit(280)
        cycle({})
        if fault == "unknown":
            text.append(f"bx {codes[audit.ROB+'io_commits_isCommit']}")
        text.append(f"#{tick+10}")
        path = Path(directory)/"fixture.vcd"
        path.write_text("\n".join(text)+"\n")
        return path,symbols

    def test_positive_and_tag_wrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,symbols = self.fixture(tmp)
            result = audit.audit_wave(path,symbols)
            self.assertEqual(set(result["proof"]), {"branch","exception"})

    def test_new_tag_allocation_not_old_wrong_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,symbols = self.fixture(tmp,"tag_reallocation")
            audit.audit_wave(path,symbols)

    def test_identity_is_rob_allocation_not_transport_pc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path,symbols = self.fixture(tmp,"writeback_pc_shift")
            audit.audit_wave(path,symbols)

    def test_negative_fixtures_fail_closed(self):
        for fault in ("no_execution","no_mispredict","branch_commit","young_commit","no_illegal","truncated","unknown","wrong_wb_tag"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                path,symbols = self.fixture(tmp,fault)
                with self.assertRaises(ValueError): audit.audit_wave(path,symbols)

    def test_log_rejoins_uart_but_preserves_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"run.log"
            passed = ("Difftest enabled\ncontrol PASS: seed=5644"
                      "[00] commit pc 80001000 inst 63 wen 0 dst 0 data 0 idx 1\n"
                      "4f54 random=256 branch_train=64 branch_probe=4 illegal=20 "
                      "configs=24 config_faults=16 mixed=16x32 chains=16x128\n"
                      "control symbols branch=80001000 branch_dot=80001004 branch_v0=80001008 "
                      "illegal=8000100c young=80001010 young_v0=80001014 young_alias=80001018\n"
                      "HIT GOOD TRAP\n[process exit] 0\n")
            path.write_text(passed)
            audit.audit_log(path,"56444f54")
            for suffix in ("ABORT\n", "control FAIL: state\n", "[process exit] 1\n"):
                path.write_text(passed+suffix)
                with self.assertRaises(ValueError): audit.audit_log(path,"56444f54")


if __name__ == "__main__": unittest.main()
