import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('diag',Path(__file__).resolve().parents[2]/'scripts/diagnose-e2e-context.py')
diag=importlib.util.module_from_spec(spec); spec.loader.exec_module(diag)

class AuditTests(unittest.TestCase):
    def fixture(self,parameter=2):
        lines=['Difftest enabled','e2e diag meta schema=1 mode=%d first=%d batches=32 warmup=8 reps=8 directed=4'%(parameter>>1,parameter&1)]
        for kind in range(2):
            for r in range(16):
                for slot in range(2):
                    impl=(parameter&1)^(r&1)^slot
                    lines.append(f'e2e diag raw kind={kind} round={r} impl={impl} slot={slot} cycles={100+r}')
        return '\n'.join(lines+['e2e diag PASS: synthetic fixture only','HIT GOOD TRAP','[process exit] 0'])+'\n'

    def audit(self,text):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'fixture.log'; p.write_text(text)
            return diag.audit(p,32,2)

    def test_all_calls_retained(self):
        result=self.audit(self.fixture())
        self.assertEqual(result['groups']['1/0']['warm'],list(range(100,108)))
        self.assertEqual(result['groups']['1/0']['measured'],list(range(108,116)))
        self.assertEqual(len(result['raw_rows']),64)

    def test_incomplete_or_duplicate(self):
        text=self.fixture()
        with self.assertRaises(ValueError): self.audit(text.replace('round=15','round=14'))
        with self.assertRaises(ValueError): self.audit(text.replace('e2e diag raw kind=0 round=0','missing kind=0 round=0'))

    def test_exit_and_trap(self):
        text=self.fixture()
        for bad in (text.replace('[process exit] 0','[process exit] 1'),text.replace('HIT GOOD TRAP','HIT BAD TRAP'),text+'bench kernel FAIL\n',text.replace('Difftest enabled','')):
            with self.assertRaises(ValueError): self.audit(bad)

    def test_runtime_labels(self):
        text=self.fixture()
        for bad in (text.replace('mode=1 first=0','mode=0 first=0'),text.replace('slot=0','slot=1'),text.replace('cycles=100','cycles=0')):
            with self.assertRaises(ValueError): self.audit(bad)

if __name__=='__main__': unittest.main()
