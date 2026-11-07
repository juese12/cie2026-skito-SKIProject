#!/usr/bin/env python3
"""在临时目录验证公开构建入口和搬迁数据复算，不启动实际硬件仿真。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path('stage3/logs/20261027T190338-sew16-perf4-full.results.json')
PUBLIC = Path('stage3/sew16-perf/review-public-data.py')


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def invoke(args, cwd, code=0, env=None):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, env=env)
    if result.returncode != code:
        raise AssertionError(f'{args}: exit {result.returncode}, expected {code}\n'
                             f'{result.stdout}\n{result.stderr}')
    return result


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vdot-release-entry-')
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.repo = self.workspace / ROOT.name
        for name in ('scripts/build-vdot-sew16-core.sh', 'scripts/vdot-step.sh',
                     'scripts/prepare-vdot-difftest.sh', 'scripts/run-vdot-contract-tests.sh',
                     'stage2/contract-tests/Makefile', 'stage2/patches/difftest-sync-compat.patch'):
            write(self.repo / name, (ROOT / name).read_text())
        write(self.workspace / 'env.sh', (ROOT.parent / 'env.sh').read_text())
        self.diff = self.workspace / 'XiangShan/difftest'
        self.diff.mkdir(parents=True)
        invoke(['git', 'init', '-q'], self.diff)
        base = invoke(['git', 'show', 'HEAD:verilator.mk'], ROOT.parent / 'XiangShan/difftest')
        write(self.diff / 'verilator.mk', base.stdout)

    def prepare(self, mode, code=0):
        return invoke(['bash', 'scripts/prepare-vdot-difftest.sh', mode], self.repo, code)

    def test_compatibility_apply_twice_preserves_other_edits(self):
        self.prepare('--check', 2)
        with (self.diff / 'verilator.mk').open('a') as stream:
            stream.write('\n# unrelated local setting\n')
        self.prepare('--apply')
        first = (self.diff / 'verilator.mk').read_bytes()
        self.prepare('--apply')
        self.prepare('--check')
        self.assertEqual(first, (self.diff / 'verilator.mk').read_bytes())
        self.assertTrue(first.endswith(b'# unrelated local setting\n'))

    def test_compatibility_conflict_does_not_write(self):
        p = self.diff / 'verilator.mk'
        write(p, p.read_text().replace('@sync -d $(BUILD_DIR) -d $(EMU_DIR)', '@custom_sync'))
        before = p.read_bytes()
        self.prepare('--apply', 1)
        self.assertEqual(before, p.read_bytes())

    def test_core_build_reaches_cpp_without_any_nemu_or_old_emu(self):
        self.prepare('--apply')
        xs = self.workspace / 'XiangShan'
        for name in ('vector/VDot8.scala', 'wrapper/VIMacU.scala'):
            write(xs / 'src/main/scala/xiangshan/backend/fu' / name, '// fixture RTL\n')
        write(xs / 'src/main/scala/xiangshan/backend/decode/VecExceptionGen.scala', '// fixture RTL\n')
        write(self.workspace / 'DRAMsim3/build/libdramsim3.a', 'fixture library\n')
        write(xs / 'scripts/gen_sep_mem.sh', '#!/usr/bin/env bash\nexit 0\n', True)
        fake = self.workspace / 'tools'
        driver = '''#!/usr/bin/env python3
import json, os, pathlib, sys
name=pathlib.Path(sys.argv[0]).name
with open(os.environ['VDOT_TEST_CALLS'],'a') as f: f.write(json.dumps([name,*sys.argv[1:]])+'\\n')
xs=pathlib.Path(os.environ['NOOP_HOME'])
if name=='mill':
    rtl=pathlib.Path(sys.argv[sys.argv.index('--target-dir')+1])
    (rtl/'SimTop.fir').write_text('fixture firrtl')
    (xs/'build/generated-src').mkdir()
    for n in ('chisel_db.cpp','chisel_db.h'): (xs/'build'/n).write_text('fixture')
elif name=='firtool':
    rtl=pathlib.Path(next(a[3:] for a in sys.argv if a.startswith('-o=')))
    (rtl/'SimTop.sv').write_text('module SimTop; endmodule\\n')
    (rtl/'SimTop.sv.conf').write_text('fixture')
elif name=='make':
    build=pathlib.Path(next(a.split('=',1)[1] for a in sys.argv if a.startswith('BUILD_DIR=')))
    (build/'emu').write_text('fixture emulator')
'''
        for name in ('mill', 'make', 'firtool', 'verilator', 'java'):
            write(fake / name, driver, True)
        calls = self.workspace / 'calls.jsonl'
        env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ['PATH'],
                   VDOT_FIRTOOL=str(fake / 'firtool'), VDOT_TEST_CALLS=str(calls))
        invoke(['bash', 'scripts/build-vdot-sew16-core.sh', '--check'], self.repo, env=env)
        self.assertFalse(calls.exists())
        invoke(['bash', 'scripts/build-vdot-sew16-core.sh'], self.repo, env=env)
        self.assertFalse((self.workspace / 'NEMU').exists())
        self.assertFalse((xs / 'build/operand-isolation').exists())
        self.assertEqual([json.loads(x)[0] for x in calls.read_text().splitlines()],
                         ['mill', 'firtool', 'make'])
        before = calls.read_bytes()
        invoke(['bash', 'scripts/build-vdot-sew16-core.sh'], self.repo, 2, env)
        self.assertEqual(before, calls.read_bytes())

    def image(self, kind):
        return Path(invoke(['make', '--no-print-directory', '-s', '-C', 'stage2/contract-tests',
                            'KIND=' + kind, 'print-image'], self.repo).stdout.strip())

    def test_contract_build_and_runner_share_path_and_reject_stale_image(self):
        functional, control = self.image('functional'), self.image('control')
        self.assertNotEqual(functional.parent, control.parent)
        self.assertFalse((self.repo / 'stage2/contract-tests/build').exists())
        # 用轻量 AM 替身检验最终 BINARY 绑定，不运行交叉编译器。
        am = self.workspace / 'fake-am'
        write(am / 'Makefile.app', 'default:\n\t@mkdir -p "$(DST_DIR)"\n'
              '\t@printf "fixture image\\n" > "$(BINARY).bin"\n')
        for kind, expected in (('functional', functional), ('control', control)):
            invoke(['make', '--no-print-directory', '-s', '-C', 'stage2/contract-tests',
                    'KIND=' + kind, 'AM_HOME=' + str(am)], self.repo)
            self.assertTrue(expected.is_file())
        emu = self.workspace / 'XiangShan/build/sew16-fixed8/emu'
        write(emu, '#!/usr/bin/env bash\necho emulator-must-not-start >&2\nexit 99\n', True)
        write(self.workspace / 'NEMU/build/sew16/riscv64-nemu-interpreter-so', 'fixture ref')
        invoke(['bash', 'scripts/run-vdot-contract-tests.sh', '--check'], self.repo)
        # 即使历史平铺镜像存在，缺少当前 control 镜像也必须先失败。
        control.rename(control.with_suffix('.saved'))
        stale = self.repo / 'stage2/contract-tests/build' / control.name
        write(stale, 'stale image')
        failed = invoke(['bash', 'scripts/run-vdot-contract-tests.sh'], self.repo, 2)
        self.assertIn(str(control), failed.stderr)
        self.assertNotIn('emulator-must-not-start', failed.stderr)
        self.assertFalse((self.repo / 'stage2/logs').exists())


class PublicDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='vdot-public-data-')
        cls.repo = Path(cls.temp.name) / 'renamed-public-project'
        cls.names = invoke([sys.executable, str(PUBLIC), str(RESULTS), '--list-files'], ROOT).stdout.splitlines()
        for name in cls.names:
            dest = cls.repo / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_review(self, name, code=1, strict=False):
        out = self.repo / (name + '.json')
        cmd = [sys.executable, str(PUBLIC), str(RESULTS), '--out', str(out)]
        if strict:
            cmd.append('--strict')
        result = invoke(cmd, self.repo, code)
        if code == 1:
            self.assertFalse(out.exists())
        return result, out

    def test_renamed_package_without_binaries_replays_all_data(self):
        self.assertFalse((self.repo / 'stage3/sew16-perf/build').exists())
        self.assertFalse((self.repo.parent / 'XiangShan').exists())
        _, out = self.run_review('review-pass', 0)
        result = json.loads(out.read_text())
        self.assertEqual((result['formal_processes'], result['raw_sample_rows']), (8, 1920))
        self.assertEqual(len(result['warnings']), 12)
        self.assertFalse(result['stable'])
        self.assertEqual(result['artifact_identity'], 'NOT_AUDITED')
        self.run_review('review-strict', 3, True)

    def changed(self, relative, replacement, name):
        path = self.repo / relative
        before = path.read_bytes()
        try:
            path.write_bytes(replacement(before))
            self.run_review(name)
        finally:
            path.write_bytes(before)

    def test_corrupted_log_rejected(self):
        name = next(n for n in self.names if n.endswith('-new0.full.log'))
        self.changed(name, lambda b: b + b'\nFAIL injected corruption\n', 'bad-log')

    def test_corrupted_csv_rejected(self):
        name = next(n for n in self.names if n.endswith('.samples.csv'))
        self.changed(name, lambda b: b.replace(b'cycles', b'changed', 1), 'bad-csv')

    def test_corrupted_statistics_rejected(self):
        name = next(n for n in self.names if n.endswith('.analysis.json'))
        def corrupt(b):
            d = json.loads(b)
            d['summary'][0]['speedup_median'] += 1
            return json.dumps(d).encode()
        self.changed(name, corrupt, 'bad-stats')

    def test_changed_threshold_rejected(self):
        self.changed('stage3/sew16-perf/protocol.json',
                     lambda b: b.replace(b'0.05', b'0.95'), 'bad-threshold')

    def test_changed_invocation_parameters_rejected(self):
        def corrupt(b):
            d = json.loads(b)
            d['runs'][0]['params']['first'] ^= 1
            return json.dumps(d).encode()
        self.changed(RESULTS, corrupt, 'bad-params')

    def test_missing_log_does_not_fall_back_to_original_workspace(self):
        path = self.repo / next(n for n in self.names if n.endswith('-old0.full.log'))
        renamed = path.with_suffix('.saved')
        path.rename(renamed)
        try:
            self.run_review('missing-log')
        finally:
            renamed.rename(path)

    def test_escape_from_package_rejected(self):
        def corrupt(b):
            d = json.loads(b)
            d['runs'][0]['log'] = str(Path(d['prefix']).parents[2] / '../outside.full.log')
            return json.dumps(d).encode()
        self.changed(RESULTS, corrupt, 'bad-path')


if __name__ == '__main__':
    unittest.main(verbosity=2)
