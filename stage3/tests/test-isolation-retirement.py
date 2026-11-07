#!/usr/bin/env python3
"""清理前后的真实摘录与重放安全边界；不执行整核仿真。"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


F=load('test_retained_signals','stage3/tests/render-isolation-retained-signals.py')
R=load('test_retained_replay','scripts/replay-isolation-evidence.py')
D=load('test_retire_wave','scripts/retire-isolation-waves.py')


class IsolationRetirementTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((F.OUT/'signal-excerpts.json').read_text())
        self.plan=json.loads(R.PLAN.read_text())

    def test_actual_control_samples(self):
        self.assertTrue(F.validate_control(self.data['control']))
        self.assertEqual([c['period'] for c in self.data['e2e']],[17,19,20])

    def mutate(self,name,value,kind='branch',moment=None):
        data=copy.deepcopy(self.data['control']);case=next(c for c in data['cases'] if c['kind']==kind)
        time=moment(case) if moment else case['victims'][0]['execution_time']
        row=next(r for r in data['windows'][kind] if r[0]==time)
        row[data['columns'].index(name)]=value
        return data

    def test_wrong_result_rejected(self):
        with self.assertRaises(ValueError):F.validate_control(self.mutate(F.CTRL.FU+'io_out_bits_res_data',999))

    def test_missing_target_execution_rejected(self):
        with self.assertRaises(ValueError):F.validate_control(self.mutate(F.CTRL.FU+'io_out_valid',0))

    def test_missing_precise_exception_rejected(self):
        bad=self.mutate(F.CTRL.ROB+'io_exception_bits_instr',0,'exception',lambda c:c['event']['exception_time'])
        with self.assertRaises(ValueError):F.validate_control(bad)

    def test_commands_use_old_core_and_fixed_parameters(self):
        for kind,seed,window in [('control',101,(0,26000)),('e2e',0,(828182,838423)),('middle',0,(892399,897515))]:
            args=R.command(self.plan,kind,Path('/tmp/NEW.vcd'))
            self.assertIn('operand-isolation/emu',args[0]);self.assertIn('--seed='+str(seed),args)
            self.assertEqual((args[args.index('-b')+1],args[args.index('-e')+1]),tuple(map(str,window)))
            self.assertIn('--dump-wave-full',args)
            if kind!='control':self.assertIn('--overwrite-nbytes=1305',args)

    def test_default_does_not_start_cpu(self):
        with patch('sys.argv',['replay']),patch.object(R,'check',return_value={'status':'PASS'}), \
             patch.object(R,'run') as run,contextlib.redirect_stdout(io.StringIO()):
            R.main();run.assert_not_called()

    def test_output_without_run_rejected(self):
        with patch('sys.argv',['replay','--out-dir','/tmp/NEW']), \
             patch.object(R,'check',return_value={'status':'PASS'}),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):R.main()

    def test_exact_four_vcd_targets_only(self):
        self.assertEqual(len(D.TARGETS),4)
        self.assertTrue(all(n.endswith(('.vcd','.vcd.gz')) for n in D.TARGETS))
        self.assertFalse(any('sew16' in n or n.endswith('.json') for n in D.TARGETS))


if __name__=='__main__':unittest.main()
