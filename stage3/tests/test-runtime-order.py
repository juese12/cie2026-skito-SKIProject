#!/usr/bin/env python3
"""人工工具测试，不作为硬件证据。"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = module("runtime", "prepare-runtime-order.py")
fixtures = module("fixtures", "test-analyze-bench.py")
bench = fixtures.bench


class RuntimeTests(unittest.TestCase):
    def test_overlay_is_one_byte_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            image, output = Path(directory)/"image", Path(directory)/"overlay"
            image.write_bytes(bytes(64))
            with patch.object(runtime.subprocess, "check_output", return_value="80000010 T bench_runtime_order\n"):
                record = runtime.prepare("fixture.elf", image, 1, output)
                self.assertEqual(record["changed_offsets"], [16])
                self.assertEqual(output.read_bytes(), bytes(16)+b"\x01")
                self.assertEqual(image.read_bytes(), bytes(64))
                with self.assertRaises(FileExistsError): runtime.prepare("fixture.elf", image, 0, output)
                with self.assertRaises(ValueError): runtime.prepare("fixture.elf", image, 2, output)

    def test_invalid_layout_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory)/"image"
            image.write_bytes(bytes(64))
            for symbols in ("", "80001000 T bench_runtime_order\n", "80000040 T bench_runtime_order\n"):
                with patch.object(runtime.subprocess, "check_output", return_value=symbols), self.assertRaises(ValueError):
                    runtime.prepare("fixture.elf", image, 1, Path(directory)/"out")

    def parse(self, directory, first, run, image="c", profile="smoke"):
        record = dict(first=first, image_sha256=image*64, offset=16,
                      overwrite_nbytes=17, changed_offsets=[16] if first else [],
                      parameter_address="0x80000010", overlay_sha256=("e" if first else "f")*64)
        text = fixtures.fixture(first, run, profile).replace("schema=2", "schema=3")
        text = text.replace(("c" if first == 0 else "d")*64, image*64)
        text += "[runtime parameter] " + json.dumps(record) + "\n"
        path = Path(directory)/f"run{run}.log"
        path.write_text(text)
        return bench.audit(path)

    def test_single_image_aggregation(self):
        with tempfile.TemporaryDirectory() as directory:
            runs = [self.parse(directory, i%2, i) for i in range(2)]
            self.assertTrue(bench.aggregate(runs)["stable"])
            runs[1] = self.parse(directory, 1, 1, "d")
            with self.assertRaises(ValueError): bench.aggregate(runs)

    def test_missing_parameter_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"bad.log"
            path.write_text(fixtures.fixture().replace("schema=2", "schema=3"))
            with self.assertRaises(ValueError): bench.audit(path)

    def test_v3_report_is_qualified_and_tracks_runtime_sources(self):
        renderer=module("renderer", "render-bench-report.py")
        with tempfile.TemporaryDirectory() as directory:
            runs=[self.parse(directory,i%2,i,profile="full") for i in range(4)]
            text=renderer.render(dict(runs=runs,series=bench.aggregate(runs)),
                                 Path(directory)/"synthetic.paths",Path(directory)/"synthetic.md")
            self.assertIn("合成测试报告（不是硬件实测）",text)
            self.assertIn("全部进程加载同一个镜像",text)
            self.assertIn("启动参数审计",text)
            self.assertIn("stage3/vdot-bench-p0/runtime-config.S",text)
            self.assertNotIn("专门动态时间戳/ROB 边界波形尚未取得",text)


if __name__ == "__main__": unittest.main()
