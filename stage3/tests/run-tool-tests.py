#!/usr/bin/env python3
"""显式加载带连字符的测试模块，不能把零用例发现当作测试通过。"""
import importlib.util
import unittest
from pathlib import Path

suite=unittest.TestSuite()
for path in sorted(Path(__file__).parent.glob("test-*.py")):
    spec=importlib.util.spec_from_file_location(path.stem.replace("-","_"),path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
if suite.countTestCases()<28:
    raise SystemExit("incomplete discovery: expected at least 28 P0/tool tests")
raise SystemExit(0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1)
