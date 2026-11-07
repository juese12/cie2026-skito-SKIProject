"""人工比较用例用于测试工具，不作为整核或性能证据。"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('oldvd_compare', Path(__file__).with_name('compare-oldvd.py'))
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


class OldVdComparisonTest(unittest.TestCase):
    def run_fixture(self, mutate=None):
        samples = [dict(policy=p, kind=k, rep=r, cycles=100+r)
                   for p in range(4) for k in range(6) for r in range(2)]
        logs = [dict(log_sha256='before', samples=samples),
                dict(log_sha256='after', samples=[dict(s, cycles=s['cycles']//2) for s in samples])]
        before = dict(status='PASS', log_sha256='before', wave_sha256='wave-before',
                      completed_dot=1400, false_wait_dot=632, records=[])
        after = dict(status='PASS', log_sha256='after', wave_sha256='wave-after',
                     completed_dot=1400, false_wait_dot=0, records=[
                         dict(vd=0, vs1=8, vs2=9, wait_phases=0,
                              source_observation=dict(types=[4,4,0,0,4])),
                         dict(vd=0, vs1=0, vs2=9, wait_phases=4,
                              source_observation=dict(types=[8,4,0,8,4]))])
        if mutate:
            mutate(before, after)
        with tempfile.TemporaryDirectory() as tmp:
            files = [Path(tmp)/'before.json', Path(tmp)/'after.json']
            for path, data in zip(files, [before, after]):
                path.write_text(json.dumps(data))
            with patch.object(comparison.audit, 'audit_log', side_effect=logs):
                return comparison.compare('before.log', 'after.log', *files)

    def test_all_groups_and_samples_retained(self):
        result = self.run_fixture()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(len(result['groups']), 24)
        self.assertEqual(sum(len(g['before_raw']) for g in result['groups']), 48)
        self.assertEqual(sum(len(g['after_raw']) for g in result['groups']), 48)
        self.assertEqual(result['groups'][0]['before_raw'], [100, 101])
        self.assertEqual(result['groups'][0]['after_raw'], [50, 50])
        self.assertEqual(result['groups'][0]['ratio'], 2.01)

    def test_matching_successful_log_is_required(self):
        with self.assertRaisesRegex(ValueError, 'match'):
            self.run_fixture(lambda b,a: a.update(log_sha256='another-log'))

    def test_remaining_auxiliary_false_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'auxiliary'):
            self.run_fixture(lambda b,a: a['records'][0]['source_observation']['types'].__setitem__(3,8))

    def test_retained_true_source_evidence_is_required(self):
        with self.assertRaisesRegex(ValueError, 'true-alias'):
            self.run_fixture(lambda b,a: a['records'][1].update(wait_phases=0))
