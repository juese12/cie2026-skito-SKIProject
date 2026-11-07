#!/usr/bin/env python3
"""检查实际预处理与汇编输出，包括历史指令文本的一致性。"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
CC='riscv64-linux-gnu-gcc'
OBJCOPY='riscv64-linux-gnu-objcopy'

def preprocess(source,contract):
    return subprocess.check_output([CC,'-E','-P','-x','assembler-with-cpp',
        f'-DVDOT_TEST_E16={contract}',str(source)],text=True,stderr=subprocess.STDOUT)

class ContractSelectionTests(unittest.TestCase):
    def test_functional_bad_sew_is_versioned(self):
        path=ROOT/'stage2/vdot-tests/vdot.S'
        self.assertIn('vsetivli zero, 8, e16, m1',preprocess(path,0).split('.Lbadsew:')[1].split('.Lbadlmul:')[0])
        self.assertIn('vsetivli zero, 8, e32, m1',preprocess(path,1).split('.Lbadsew:')[1].split('.Lbadlmul:')[0])

    def test_control_bad_vtype_has_current_e32_e64(self):
        path=ROOT/'stage2/control-tests/control.S'
        legacy=preprocess(path,0).split('control_config_fault:')[1].split('control_mixed:')[0]
        current=preprocess(path,1).split('control_config_fault:')[1].split('control_mixed:')[0]
        self.assertIn('ori a3, a3, 8',legacy)
        self.assertNotIn('.Lfault_sew64:',legacy)
        self.assertIn('ori a3, a3, 16',current)
        self.assertIn('ori a3, a3, 24',current)

    def test_invalid_contract_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            preprocess(ROOT/'stage2/vdot-tests/vdot.S',2)

    def test_legacy_assembly_text_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory)
            for group in ('vdot-tests','control-tests'):
                name='vdot.S' if group=='vdot-tests' else 'control.S'
                source=Path('stage2')/group/name
                before=ROOT/'stage2/contract-tests/before'/source
                after=ROOT/source
                results=[]
                for index,path in enumerate((before,after)):
                    obj=temp/f'{group}-{index}.o'; binary=obj.with_suffix('.text')
                    subprocess.run([CC,'-c','-march=rv64gcv_zba','-mabi=lp64d',
                        '-DVDOT_TEST_E16=0',str(path),'-o',str(obj)],check=True)
                    subprocess.run([OBJCOPY,'-O','binary','--only-section=.text',str(obj),str(binary)],check=True)
                    results.append(binary.read_bytes())
                self.assertEqual(results[0],results[1],group)

if __name__=='__main__':unittest.main()
