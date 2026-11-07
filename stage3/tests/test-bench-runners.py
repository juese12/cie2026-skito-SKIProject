#!/usr/bin/env python3
"""使用明确的模拟替身检查运行编排，不作为 RTL 验证证据。"""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("parser_fixtures", Path(__file__).with_name("test-analyze-bench.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "synthetic-repo"
        for directory in ("scripts", "stage3/tests", "stage3/vdot-bench/build"):
            (self.repo / directory).mkdir(parents=True)
        for script in ("run-vdot-bench.sh", "run-vdot-bench-series.sh", "validate-vdot-bench-v2.sh"):
            shutil.copyfile(ROOT / "scripts" / script, self.repo / "scripts" / script)
        shutil.copyfile(ROOT / "stage3/tests/analyze-bench.py", self.repo / "stage3/tests/analyze-bench.py")
        texts = {profile: ["\n".join(line for line in fixtures.fixture(first, profile=profile).splitlines()
                                     if not line.startswith(("[artifact", "[process exit]"))) for first in (0, 1)]
                 for profile in ("smoke", "full")}
        self.emu = self.repo / "fake-emu"
        self.emu.write_text("#!/usr/bin/env python3\nimport os,sys,time\nfrom pathlib import Path\n"
                            "image=Path(sys.argv[sys.argv.index('-i')+1])\nfirst=int(image.read_text())\n"
                            "with open(os.environ['FAKE_COUNTER'],'a') as f:f.write(str(first)+'\\n')\n"
                            "time.sleep(float(os.environ.get('FAKE_DELAY','0')))\n"
                            "if os.environ.get('FAKE_FAIL'):print('HIT BAD TRAP');sys.exit(17)\n"
                            f"print({texts!r}['full' if '-full-' in image.name else 'smoke'][first])\n")
        self.emu.chmod(0o700)
        self.ref = self.repo / "fake-ref"
        self.ref.write_text("not a real reference model\n")
        self.images = []
        for first in (0, 1):
            image = self.repo / f"stage3/vdot-bench/build/cie2026-stage3-vdot-bench-v2-smoke-order{first}-riscv64-xs.bin"
            image.write_text(str(first))
            self.images.append(image)
            full_image = self.repo / f"stage3/vdot-bench/build/cie2026-stage3-vdot-bench-v2-full-order{first}-riscv64-xs.bin"
            full_image.write_text(str(first))
        self.counter = self.repo / "fake-counter"
        self.env = dict(os.environ, VDOT_EMU=str(self.emu), VDOT_REF_SO=str(self.ref), FAKE_COUNTER=str(self.counter))

    def run_script(self, script, *args, env=None):
        return subprocess.run(["bash", str(self.repo / "scripts" / script), *args],
                              env=env or self.env, capture_output=True, text=True, timeout=20)

    def test_two_fresh_runs_and_aggregation(self):
        result = self.run_script("run-vdot-bench-series.sh", "--smoke")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.counter.read_text(), "0\n1\n")
        self.assertIn("[series data PASS]", result.stdout)
        self.assertEqual(len(list((self.repo / "stage3/logs").glob("*-series-smoke.json"))), 1)

    def test_failure_stops_before_second_run(self):
        result = self.run_script("run-vdot-bench-series.sh", "--smoke", env=dict(self.env, FAKE_FAIL="1"))
        self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
        self.assertEqual(self.counter.read_text(), "0\n")
        self.assertNotIn("[series data PASS]", result.stdout)

    def test_no_overwrite_and_invalid_run_count(self):
        env = dict(self.env, VDOT_IMAGE=str(self.images[0]), VDOT_BENCH_RUN_ID="synthetic-fixed-id")
        result = self.run_script("run-vdot-bench.sh", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.run_script("run-vdot-bench.sh", env=env).returncode, 2)
        self.assertEqual(self.counter.read_text(), "0\n")
        self.assertEqual(self.run_script("run-vdot-bench-series.sh", "--runs=3").returncode, 2)

    def test_snapshot_survives_source_edit(self):
        env = dict(self.env, VDOT_IMAGE=str(self.images[0]), VDOT_BENCH_RUN_ID="synthetic-snapshot", FAKE_DELAY="0.5")
        script = self.repo / "scripts/run-vdot-bench.sh"
        process = subprocess.Popen(["bash", str(script)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not self.counter.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(self.counter.exists(), "fake emulator did not start")
            script.write_text("this is deliberately invalid BASH source ' \n")
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)

    def test_run_option_order_is_independent(self):
        for args in (("--runs=4", "--smoke"), ("--smoke", "--runs=4")):
            result = self.run_script("run-vdot-bench-series.sh", *args)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.counter.read_text(), "0\n1\n0\n1\n" * 2)

    def test_validation_continues_verified_smoke_with_four_full_runs(self):
        result = self.run_script("run-vdot-bench-series.sh", "--smoke")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = next((self.repo / "stage3/logs").glob("*-series-smoke.paths"))
        result = self.run_script("validate-vdot-bench-v2.sh", str(manifest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.counter.read_text(), "0\n1\n0\n1\n0\n1\n")
        self.assertIn("[validation data PASS]", result.stdout)

    def test_validation_rejects_incomplete_or_corrupt_smoke(self):
        result = self.run_script("run-vdot-bench-series.sh", "--smoke")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = next((self.repo / "stage3/logs").glob("*-series-smoke.paths"))
        original = manifest.read_text()
        manifest.write_text(original.splitlines()[0] + "\n")
        self.assertEqual(self.run_script("validate-vdot-bench-v2.sh", str(manifest)).returncode, 2)
        manifest.write_text(original)
        summary = Path(original.splitlines()[0])
        summary.write_text(summary.read_text().replace("[process exit] 0", "[process exit] 17"))
        self.assertEqual(self.run_script("validate-vdot-bench-v2.sh", str(manifest)).returncode, 1)
        self.assertEqual(self.counter.read_text(), "0\n1\n")


if __name__ == "__main__":
    unittest.main()
