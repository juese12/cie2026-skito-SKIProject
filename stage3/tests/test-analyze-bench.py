#!/usr/bin/env python3
"""仅使用人工解析器输入验证工具，不作为硬件证据。"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("analyze_bench", Path(__file__).with_name("analyze-bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def fixture(first=0, run=0, profile="smoke"):
    reps, warmup, batches, random = (4, 2, 8, 0) if profile == "smoke" else (8, 8, 256, 1000)
    lines = [f"synthetic parser fixture run={run}", "Difftest enabled", "HIT GOOD TRAP",
             f"bench equivalence PASS: vectors={8+random} checks={32+random} policies=4 baseline=vwmul+vwredsum vdot=1",
             f"bench meta schema=2 profile={profile} reps={reps} warmup={warmup} batches={batches} random={random} first={first} deferred=1 seed=56444f54 timing=mcycle_vstart_serialized"]
    for role, value in (("emu", "a"), ("ref", "b"), ("image", "c" if first == 0 else "d")):
        lines.append(f"[artifact {role}] {value * 64}")
    for kind in bench.KINDS:
        for impl in bench.IMPLS:
            value = 100 if impl == "vdot" else 200
            lines.append(f"bench warm kind={kind} impl={impl} count={warmup} first_cycles={value} last_cycles={value}")
        for rep in range(reps):
            for slot in range(2):
                impl = bench.IMPLS[first ^ (rep & 1) ^ slot]
                cycles = 100 if impl == "vdot" else 200
                lines.append(f"bench raw kind={kind} impl={impl} rep={rep} slot={slot} dots={4*batches} cycles={cycles}")
    for rep in range(reps):
        lines.append(f"bench raw kind=empty impl=control rep={rep} loops={batches} cycles=50")
    lines += ["vdot benchmark PASS: synthetic", "[process exit] 0"]
    return "\n".join(lines) + "\n"


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.counter = 0

    def parse(self, text):
        self.counter += 1
        path = Path(self.tmp.name) / f"fixture-{self.counter}.log"
        path.write_text(text)
        return bench.audit(path)

    def test_valid_orders_and_statistics(self):
        for first in (0, 1):
            result = self.parse(fixture(first))
            self.assertTrue(result["stable"])
            self.assertEqual(result["groups"]["chain"]["raw_speedup"], 2)
            self.assertEqual(result["groups"]["batch4"]["vdot"]["slot_effect"], 0)

    def test_corruption_is_rejected(self):
        original = fixture()
        corrupt = [
            original.replace("vdot=1", "vdot=0"),
            original.replace("HIT GOOD TRAP", "HIT BAD TRAP"),
            original.replace("[process exit] 0", "[process exit] 1"),
            original.replace("[process exit] 0", ""),
            original + "[process exit] 0\n",
            original.replace("rep=0 slot=0", "rep=99 slot=0", 1),
            original.replace("slot=0", "slot=1", 1),
            original.replace("dots=32", "dots=128", 1),
            original.replace("cycles=100", "cycles=0", 1),
            original.replace("reps=4", "reps=3"),
            original.replace("checks=32", "checks=33"),
            original.replace("profile=smoke", "profile=full"),
            original.replace("deferred=1", "deferred=0"),
            original.replace("loops=8", "loops=9", 1),
            original.replace("control rep=1", "control rep=0"),
            original.replace("bench warm kind=batch4 impl=vdot", "bench warm kind=batch4 impl=rvv"),
            original + "bench raw kind=unknown impl=vdot rep=0 dots=32 cycles=100\n",
            original + "bench raw kind=batch4 impl=vdot rep=0 slot=0 dots=32 cycles=100\n",
        ]
        for text in corrupt:
            with self.subTest(text=text[-80:]), self.assertRaises(ValueError):
                self.parse(text)

    def test_missing_record(self):
        lines = fixture().splitlines()
        self.parse("\n".join(lines))
        with self.assertRaises(ValueError):
            self.parse("\n".join(l for l in lines if "kind=chain impl=rvv rep=3" not in l))

    def test_variation_warning(self):
        result = self.parse(fixture().replace("slot=0 dots=32 cycles=100", "slot=0 dots=32 cycles=500", 1))
        self.assertFalse(result["stable"])
        self.assertTrue(result["warnings"])
        result = self.parse(fixture().replace("last_cycles=100", "last_cycles=150", 1))
        self.assertFalse(result["stable"])
        self.assertEqual(result["groups"]["batch4"]["vdot"]["warm_tail_drift"], 0.5)

    def test_balanced_series(self):
        runs = [self.parse(fixture(i % 2, i)) for i in range(2)]
        result = bench.aggregate(runs)
        self.assertTrue(result["stable"])
        self.assertEqual(result["groups"]["batch4"]["speedup"]["n"], 2)
        self.assertEqual(result["groups"]["batch4"]["speedup"]["median"], 2)
        with self.assertRaises(ValueError):
            bench.aggregate([runs[0], runs[0]])
        with self.assertRaises(ValueError):
            bench.aggregate([runs[0], self.parse(fixture(0, 2))])
        with self.assertRaises(ValueError):
            bench.aggregate([runs[0], self.parse(fixture(1, 2).replace("b" * 64, "e" * 64))])

    def test_full_needs_four_runs(self):
        runs = [self.parse(fixture(i % 2, i, "full")) for i in range(4)]
        self.assertTrue(bench.aggregate(runs)["stable"])
        with self.assertRaises(ValueError):
            bench.aggregate(runs[:2])
        with self.assertRaises(ValueError):
            self.parse(fixture(profile="full").replace("mcycle_vstart_serialized", "mcycle_raw"))

    def test_cli_strict_and_optimized_python(self):
        import subprocess
        path = Path(self.tmp.name) / "unstable.log"
        path.write_text(fixture().replace("slot=0 dots=32 cycles=100", "slot=0 dots=32 cycles=500", 1))
        tool = str(Path(__file__).with_name("analyze-bench.py"))
        result = subprocess.run(["python3", "-O", tool, str(path), "--strict-stability"], capture_output=True)
        self.assertEqual(result.returncode, 3)
        path.write_text(fixture().replace("HIT GOOD TRAP", "HIT BAD TRAP"))
        result = subprocess.run(["python3", "-O", tool, str(path)], capture_output=True)
        self.assertEqual(result.returncode, 1)

    def test_legacy_real_evidence(self):
        path = Path(__file__).parents[1] / "logs/20261002T115511-bench.log"
        result = bench.audit(path)
        self.assertEqual(result["meta"]["schema"], 1)
        self.assertEqual(result["groups"]["batch4"]["vdot"]["median"], 477)
        self.assertFalse(result["stable"])


if __name__ == "__main__":
    unittest.main()
