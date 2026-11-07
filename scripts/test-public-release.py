#!/usr/bin/env python3
"""验证发布筛选和附件处理，防止误带原核、波形及私人材料。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('public_export', Path(__file__).with_name('export-public-release.py'))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
check_spec = importlib.util.spec_from_file_location('public_check', Path(__file__).with_name('check-public-release.py'))
C = importlib.util.module_from_spec(check_spec)
check_spec.loader.exec_module(C)
run_spec = importlib.util.spec_from_file_location('clean_runner', Path(__file__).with_name('run-clean-regressions.py'))
R = importlib.util.module_from_spec(run_spec)
run_spec.loader.exec_module(R)


class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_root = E.ROOT
        self.addCleanup(setattr, E, 'ROOT', self.old_root)
        E.ROOT = Path(self.tmp.name) / 'source'
        E.ROOT.mkdir()
        self.out = Path(self.tmp.name) / 'public'
        self.write('stage3/sew16-perf/review-public-data.py', 'print("manifest/protocol.json")\n')
        self.write('manifest/protocol.json', '{}\n')

    def write(self, name, content):
        path = E.ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_excludes_executable_wave_build_and_private(self):
        self.write('README.md', '# Public\n')
        self.write('src/main.c', 'int main(void) { return 0; }\n')
        self.write('build/old.py', 'generated = True\n')
        self.write('private/info.txt', 'private material\n')
        self.write('my_submission.txt', 'private submission\n')
        self.write('stage2/old.vcd', 'wave\n')
        self.write('stage2/old.vcd.gz', 'wave\n')
        self.write('stage2/logs/old-backup', '\x7fELFbinary\n')
        E.export(self.out)
        paths={r['path'] for r in json.loads((self.out/'manifest/public-release-files.json').read_text())['files']}
        self.assertIn('src/main.c', paths)
        self.assertIn('manifest/protocol.json', paths)
        for name in ('build/old.py', 'private/info.txt', 'my_submission.txt', 'stage2/old.vcd',
                     'stage2/old.vcd.gz', 'stage2/logs/old-backup'):
            self.assertNotIn(name, paths)

    def test_omitted_binary_link_points_to_archive_explanation(self):
        source=self.write('README.md', '[Old emulator](stage2/logs/emu-before)\n')
        original=source.read_bytes()
        self.write('stage2/logs/emu-before', '\x7fELFbinary\n')
        E.export(self.out)
        self.assertEqual(source.read_bytes(), original)
        self.assertIn('manifest/开发归档说明.md', (self.out/'README.md').read_text())
        self.assertIn('stage2/logs/emu-before', (self.out/'manifest/开发归档说明.md').read_text())
        self.assertFalse((self.out/'stage2/logs/emu-before').exists())

    def test_missing_document_evidence_is_rejected(self):
        self.write('README.md', '[Missing](missing.png)\n')
        with self.assertRaisesRegex(ValueError, '链接缺失'):
            E.export(self.out)
        self.assertFalse(self.out.exists())

    def test_external_local_link_is_rejected(self):
        self.write('README.md', '[Outside](../outside.txt)\n')
        with self.assertRaisesRegex(ValueError, '包外'):
            E.export(self.out)

    def test_recording_dependency_source_link_uses_public_patch(self):
        dependency=E.ROOT.parent/'NEMU/src/isa/riscv64/instr/rvv/vcompute.h'
        dependency.parent.mkdir(parents=True)
        dependency.write_text('void helper(void);\n')
        self.write('README.md', '[NEMU source](../NEMU/src/isa/riscv64/instr/rvv/vcompute.h)\n')
        self.write('stage2/patches/nemu-vdot-sew16-fixed8.patch', 'reference changes\n')
        E.export(self.out)
        self.assertIn('stage2/patches/nemu-vdot-sew16-fixed8.patch', (self.out/'README.md').read_text())
        self.assertFalse((self.out/'NEMU').exists())
        self.assertEqual(C.check(self.out)['status'], 'PASS')

    def test_existing_target_is_not_overwritten(self):
        self.out.mkdir()
        marker=self.out/'keep'
        marker.write_text('keep\n')
        with self.assertRaises(ValueError):
            E.export(self.out)
        self.assertEqual(marker.read_text(), 'keep\n')

    def test_exported_file_list_and_links_pass_public_check(self):
        self.write('README.md', '# Public\n')
        E.export(self.out)
        self.assertEqual(C.check(self.out)['status'], 'PASS')

    def test_unlisted_file_is_rejected_before_packaging(self):
        self.write('README.md', '# Public\n')
        E.export(self.out)
        (self.out/'my_submission.txt').write_text('unlisted private material\n')
        with self.assertRaisesRegex(AssertionError, '未登记'):
            C.check(self.out)

    def test_changed_file_size_is_rejected(self):
        self.write('README.md', '# Public\n')
        E.export(self.out)
        (self.out/'README.md').write_text('# Modified after export\n')
        with self.assertRaisesRegex(AssertionError, '大小'):
            C.check(self.out)


class ModuleWaveDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def wave(self, parent):
        p = self.root / parent / 'mixed/VDotIntegrationHarness.vcd'
        p.parent.mkdir(parents=True)
        p.write_text('$enddefinitions $end\n')
        return p.resolve()

    def test_direct_test_directory(self):
        wave = self.wave('test_run_dir')
        self.assertEqual(R.find_module_wave(self.root), wave)

    def test_mill_sandbox_directory(self):
        wave = self.wave('out/xiangshan/test/testOnly.dest/sandbox/test_run_dir')
        self.assertEqual(R.find_module_wave(self.root), wave)

    def test_ambiguous_wave_is_not_silently_selected(self):
        self.wave('test_run_dir')
        self.wave('out/xiangshan/test/testOnly.dest/sandbox/test_run_dir')
        with self.assertRaisesRegex(RuntimeError, '唯一'):
            R.find_module_wave(self.root)

    def test_missing_wave_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '唯一'):
            R.find_module_wave(self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
