#!/usr/bin/env python3
"""审核器的人工回归用例不代表真实 RTL 验证证据。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("isolation", Path(__file__).with_name("check-isolation-wave.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture():
    before, after = [], []
    names = [name for group in mod.GROUPS.values() for name in group]
    old_before = dict.fromkeys(names, 0)
    old_after = dict.fromkeys(names, 0)
    previous_dot = False
    previous_mac = False
    for index in range(303):
        dot = index % 3 == 0
        pre = {mod.TOP + name: 0 for name in mod.INPUTS + mod.OUTPUTS}
        pre.update({"time": index * 2, mod.TOP + "io_valid": 1,
                    mod.TOP + "io_op": 0x160 if dot else 0,
                    mod.TOP + "io_vs1": index + 1, mod.TOP + "io_vs2": index + 2,
                    mod.HARNESS + "fu_io_in_valid": 1,
                    mod.HARNESS + "ctrlPipe_1_fuOpType": 0x160 if previous_dot else 0,
                    mod.HARNESS + "validPipe_1": int(index > 0),
                    mod.FU + "validVecThisFu_1": int(index > 0),
                    mod.DOT + "io_enable_0": int(dot),
                    mod.DOT + "io_enable_1": int(previous_dot),
                    mod.DOT + "isolatedVs1": index + 1 if dot else 0,
                    mod.DOT + "isolatedVs2": index + 2 if dot else 0})
        for lane in range(2):
            pre[mod.FU + f"vimacs_{lane}.io_fire"] = int(not dot)
            pre[mod.FU + f"vimacs_{lane}.fireS1_last_r"] = int(previous_mac)
        pre.update({name: 0 if dot else index + 1 for name in mod.MAC_DATA})
        pre.update(dict.fromkeys(mod.MAC_CONTROL, 0))
        bp, ap = dict(pre), dict(pre)
        bp.update(old_before)
        ap.update(old_after)
        bq, aq = dict(bp), dict(ap)
        for group, signals in mod.GROUPS.items():
            enable = {"dot_products": dot, "dot_sum": previous_dot,
                      "mac_wallace_stage1": not dot, "mac_result_stage2": previous_mac}[group]
            for name in signals:
                bq[name] = index + 1
                if enable:
                    aq[name] = index + 1
        for post in (bq, aq):
            post["time"] = index * 2 + 1
            post[mod.TOP + "io_outValid"] = 1
        before.append((bp, bq))
        after.append((ap, aq))
        old_before = {name: bq[name] for name in names}
        old_after = {name: aq[name] for name in names}
        previous_dot, previous_mac = dot, not dot
    return before, after


class IsolationAuditTest(unittest.TestCase):
    def test_accepts_consistent_fixture(self):
        self.assertEqual(mod.audit(*fixture())["status"], "PASS")

    def test_rejects_wrong_stage_two_enable(self):
        before, after = fixture()
        after[1][0][mod.DOT + "io_enable_1"] = 0
        with self.assertRaisesRegex(AssertionError, "dot stage2 enable"):
            mod.audit(before, after)

    def test_rejects_nonisolated_operand(self):
        before, after = fixture()
        after[1][0][mod.DOT + "isolatedVs1"] = 1
        with self.assertRaisesRegex(AssertionError, "dot operand isolation"):
            mod.audit(before, after)

    def test_rejects_disabled_register_update(self):
        before, after = fixture()
        after[1][1][mod.GROUPS["dot_products"][0]] ^= 1
        with self.assertRaisesRegex(AssertionError, "disabled register changed"):
            mod.audit(before, after)

    def test_rejects_output_mismatch(self):
        before, after = fixture()
        after[20][1][mod.TOP + "io_result"] = 1
        with self.assertRaisesRegex(AssertionError, "output differs"):
            mod.audit(before, after)

    def test_rejects_different_stimuli(self):
        before, after = fixture()
        after[20][0][mod.TOP + "io_vs2"] = 99
        with self.assertRaisesRegex(AssertionError, "stimulus differs"):
            mod.audit(before, after)

    def test_rejects_missing_vcd_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            wave = Path(directory) / "missing.vcd"
            wave.write_text("$scope module TOP $end\n$var wire 1 ! clock $end\n$upscope $end\n#0\n0!\n#1\n1!\n", encoding="ascii")
            with self.assertRaisesRegex(AssertionError, "missing VCD signals"):
                mod.edges(wave, True)


if __name__ == "__main__":
    unittest.main()
