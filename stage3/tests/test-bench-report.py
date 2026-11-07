#!/usr/bin/env python3
"""报告测试在临时目录中使用人工日志，不代表 RTL 证据。"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


report = module("renderer", "render-bench-report.py")
fixtures = module("fixtures", "test-analyze-bench.py")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "synthetic.paths"
        self.logs = []
        summaries = []
        for n in range(4):
            path = self.root / f"synthetic-run{n}-bench.full.log"
            path.write_text(fixtures.fixture(n % 2, n, "full"))
            self.logs.append(path)
            summaries.append(str(path).replace(".full.log", ".log"))
        self.manifest.write_text("\n".join(summaries)+"\n")
        self.output = self.root / "synthetic.md"

    def test_complete_report_preserves_all_samples_and_synthetic_label(self):
        data = report.gather(self.manifest)
        text = report.render(data, self.manifest, self.output)
        self.assertIn("合成测试报告（不是硬件实测）", text)
        self.assertIn("2.000000", text)
        self.assertEqual(text.count("100, 100, 100, 100, 100, 100, 100, 100"), 12)
        self.assertEqual(text.count("200, 200, 200, 200, 200, 200, 200, 200"), 12)
        self.assertIn("通过启发式门槛", text)

    def test_warnings_are_not_hidden(self):
        self.logs[0].write_text(self.logs[0].read_text().replace("last_cycles=100", "last_cycles=140", 1))
        data = report.gather(self.manifest)
        text = report.render(data, self.manifest, self.output)
        self.assertFalse(data["series"]["stable"])
        self.assertIn("不能宣称整体稳定", text)
        self.assertIn("+40.000%", text)
        self.assertIn("run 0: batch4/vdot", text)

    def test_quarter_cycle_medians_keep_precision(self):
        data = report.gather(self.manifest)
        data["series"]["groups"]["e2e"]["rvv"]["median"] = 10814.25
        data["series"]["groups"]["chain"]["rvv"]["median"] = 29727.25
        text = report.render(data, self.manifest, self.output)
        self.assertIn("| e2e | 10814.25 |", text)
        self.assertIn("| chain | 29727.25 |", text)

    def test_incomplete_corrupt_and_smoke_are_rejected(self):
        original = self.manifest.read_text()
        self.manifest.write_text("\n".join(original.splitlines()[:3])+"\n")
        with self.assertRaises(ValueError):
            report.gather(self.manifest)
        self.manifest.write_text(original)
        original_log = self.logs[0].read_text()
        self.logs[0].write_text(original_log.replace("[process exit] 0", ""))
        with self.assertRaises(ValueError):
            report.gather(self.manifest)
        for n, path in enumerate(self.logs):
            path.write_text(fixtures.fixture(n % 2, n, "smoke"))
        with self.assertRaises(ValueError):
            report.gather(self.manifest)

    def test_cli_writes_json_and_refuses_overwrite(self):
        command = [sys.executable, str(Path(__file__).with_name("render-bench-report.py")),
                   "--manifest", str(self.manifest), "--output", str(self.output),
                   "--json-out", str(self.root / "synthetic.json")]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        content = self.output.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.output.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
