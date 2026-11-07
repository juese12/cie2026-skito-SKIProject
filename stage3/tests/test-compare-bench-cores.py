"""用人工数据检查处理器对比约定，不使用实测整核结果。"""
import copy
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cores', Path(__file__).with_name('compare-bench-cores.py'))
cores = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cores)


class CoreComparisonTest(unittest.TestCase):
    def fixture(self, mutate=None):
        before = dict(runs=[dict(meta=dict(first=first, schema=3, profile='full'),
                                artifacts=dict(emu='before', ref='same-ref', image='same-image'),
                                runtime_parameter=dict(first=first, overlay_sha256=str(first)),
                                groups={k: dict(vdot=dict(median=100, raw=[100]*8),
                                                rvv=dict(median=200, raw=[200]*8)) for k in cores.bench.KINDS})
                            for first in (0,1,0,1)],
                      series=dict(stable=False, warnings=['retained synthetic warning']))
        after = copy.deepcopy(before)
        for run in after['runs']:
            run['artifacts']['emu'] = 'after'
            for group in run['groups'].values():
                group['vdot'] = dict(median=50, raw=[50]*8)
        if mutate:
            mutate(before, after)
        with patch.object(cores, 'gather', side_effect=[before,after]):
            return cores.compare('old.paths', 'new.paths')

    def test_run_units_control_and_warnings_are_retained(self):
        result = self.fixture()
        self.assertEqual(len(result['groups']), 3)
        self.assertEqual(result['groups']['batch4']['vdot_gain']['median'], 2)
        self.assertEqual(result['groups']['batch4']['rvv_control']['median'], 1)
        self.assertEqual(result['groups']['batch4']['vdot_gain']['n'], 4)
        self.assertEqual(len(result['after']['runs'][0]['groups']['batch4']['vdot']['raw']), 8)
        self.assertFalse(result['before']['series']['stable'])
        self.assertEqual(result['before']['series']['warnings'], ['retained synthetic warning'])

    def test_changed_image_and_overlay_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'image'):
            self.fixture(lambda b,a: a['runs'][0]['artifacts'].update(image='changed'))
        with self.assertRaisesRegex(ValueError, 'overlay'):
            self.fixture(lambda b,a: a['runs'][0]['runtime_parameter'].update(overlay_sha256='changed'))

    def test_configuration_and_identical_core_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'configuration'):
            self.fixture(lambda b,a: a['runs'][0]['meta'].update(first=1))
        with self.assertRaisesRegex(ValueError, 'identical'):
            self.fixture(lambda b,a: [r['artifacts'].update(emu='before') for r in a['runs']])
